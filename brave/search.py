"""Brave Search module using BeautifulSoup and curl_cffi."""

from __future__ import annotations

import concurrent.futures
import copy
import datetime
import logging
import os
import random
import re
import sys
import time
from typing import Any, Literal, TypedDict

import trafilatura
from bs4 import BeautifulSoup, Tag
from curl_cffi import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

DEFAULT_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]


def get_random_user_agent() -> str:
    """Return a random User-Agent string."""
    try:
        from fake_useragent import UserAgent

        ua = UserAgent(["Firefox"])
        return ua.random
    except Exception:
        return random.choice(DEFAULT_USER_AGENTS)


def get_str_attr(tag: Tag | None, attr: str) -> str:
    """Safely get a string attribute from a BeautifulSoup Tag."""
    if tag is None:
        return ""
    val = tag.get(attr)
    if isinstance(val, list):
        return " ".join(x for x in val).strip()
    if isinstance(val, str):
        return val.strip()
    return ""


def get_clean_image_url(img_el: Tag | None) -> str | None:
    """Extract real image URL from img element, skipping lazy-loading data URIs."""
    if img_el is None:
        return None
    for attr in ("data-src-hq", "data-src", "data-src-web", "src"):
        val = get_str_attr(img_el, attr)
        if val and not val.startswith("data:"):
            if val.startswith("//"):
                val = f"https:{val}"
            return val
    return None


def parse_dt_to_utc(raw_dt: str | None) -> str | None:
    """Convert Brave search result date/relative time string into UTC ISO-8601 string.

    Supports formats like 'Aug 23, 2025', '12 hours ago', '3m', '43m', '3 days ago', 'just now', etc.
    """
    if not raw_dt:
        return None

    text = raw_dt.strip()
    if not text:
        return None

    # Clean leading/trailing separators and whitespace
    text = re.sub(
        r"^[\s·\u00a0\-\|\:\,]+|[\s·\u00a0\-\|\:\,]+$", "", text
    ).strip()
    text = re.sub(
        r"^(?:Published|Updated|Date)\s*:\s*", "", text, flags=re.IGNORECASE
    ).strip()
    if not text:
        return None

    # If text contains a relative time followed by other text (e.g. '3 hours ago - ...'), isolate time
    time_part_match = re.match(
        r"^(\d+\s*(?:s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|wk|wks|week|weeks|mo|mon|mons|month|months|y|yr|yrs|year|years)\b(?:\s*ago)?)",
        text,
        flags=re.IGNORECASE,
    )
    if time_part_match:
        text = time_part_match.group(1).strip()

    now_utc = datetime.datetime.now(datetime.UTC)
    lower = text.lower()

    if lower in ("just now", "moments ago", "seconds ago", "second ago"):
        return now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    if lower == "yesterday":
        dt = now_utc - datetime.timedelta(days=1)
        return dt.strftime("%Y-%m-%dT00:00:00Z")

    rel_match = re.match(
        r"^(\d+)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|wk|wks|week|weeks|mo|mon|mons|month|months|y|yr|yrs|year|years)\b(?:\s*ago)?",
        lower,
    )
    if rel_match:
        val = int(rel_match.group(1))
        unit = rel_match.group(2)

        if unit in ("s", "sec", "secs", "second", "seconds"):
            dt = now_utc - datetime.timedelta(seconds=val)
        elif unit in ("m", "min", "mins", "minute", "minutes"):
            dt = now_utc - datetime.timedelta(minutes=val)
        elif unit in ("h", "hr", "hrs", "hour", "hours"):
            dt = now_utc - datetime.timedelta(hours=val)
        elif unit in ("d", "day", "days"):
            dt = now_utc - datetime.timedelta(days=val)
        elif unit in ("w", "wk", "wks", "week", "weeks"):
            dt = now_utc - datetime.timedelta(weeks=val)
        elif unit in ("mo", "mon", "mons", "month", "months"):
            dt = now_utc - datetime.timedelta(days=val * 30)
        elif unit in ("y", "yr", "yrs", "year", "years"):
            dt = now_utc - datetime.timedelta(days=val * 365)
        else:
            return text
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        fmt = "%B %d, %Y"
        parsed = datetime.datetime.strptime(text, fmt).astimezone()
        parsed = parsed.replace(year=now_utc.year)
        parsed_utc = parsed.replace(tzinfo=datetime.UTC)
        return parsed_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        pass

    return text


class BraveSearchResult(TypedDict, total=False):
    url: str
    title: str
    description: str
    thumbnail_url: str | None
    favicon_url: str | None
    page_age: str | None
    content: str | None


class BraveNewsResult(TypedDict, total=False):
    url: str
    title: str
    description: str
    source: str
    thumbnail_url: str | None
    favicon_url: str | None
    page_age: str | None
    content: str | None


TIMELIMIT_MAP: dict[str, str] = {
    "d": "pd",
    "w": "pw",
    "m": "pm",
    "y": "py",
}


def extract_web_results(soup: BeautifulSoup) -> list[BraveSearchResult]:
    """Extract organic web results from Brave search HTML."""
    results: list[BraveSearchResult] = []
    seen_cards = soup.select(
        "div[data-type='search-result'], div.snippet, div[data-pos]"
    )

    for el in seen_cards:
        if el.get("data-type") not in ["web", "news"]:
            continue
        # Extract title:
        title_el = el.select_one(".title, .search-snippet-title")
        title = title_el.get_text().strip() if title_el else ""
        if not title:
            title_candidates = el.select(
                "div.title, div[class*='title'], div.sitename-container"
            )
            if title_candidates:
                title = title_candidates[-1].get_text().strip()
        title = re.sub(r"\s+", " ", title).strip()

        # Extract href:
        link_el = el.select_one(
            "a.l1, a:has(div.title), a:has(.title), a[class*='title'], a[href]"
        )
        url = ""
        if link_el:
            url = get_str_attr(link_el, "href")

        # Favicon URL:
        fav_el = el.select_one(
            "img.favicon, .favicon-wrapper img, .site-name-wrapper img"
        )
        favicon_url = get_clean_image_url(fav_el)

        # Thumbnail URL:
        thumb_el = el.select_one(
            ".thumbnail-wrapper img, .thumbnail img, img.thumbnail, .video-snippet img"
        )
        thumbnail_url = get_clean_image_url(thumb_el)

        # Page age & description:
        raw_age = None
        attr_el = el.select_one(
            ".item-attributes .attr, .video-snippet .attr, .content .t-secondary, .age-header .t-tertiary"
        )
        if attr_el:
            raw_age = attr_el.get_text().strip()

        body_el = el.select_one(
            ".generic-snippet .content, .video-snippet .content .desktop-default-regular, .video-snippet .content, .generic-snippet"
        )
        if not body_el:
            body_el = el.select_one(
                ".snippet-description, .content .description, .inline-qa-answer"
            )

        description = ""
        if body_el:
            body_copy = copy.copy(body_el)
            date_span = body_copy.select_one("span.t-secondary, .age-snippet")
            if date_span:
                if not raw_age:
                    raw_age = date_span.get_text().strip()
                date_span.decompose()
            for item_attr in body_copy.select(".item-attributes, .attr"):
                item_attr.decompose()
            description = body_copy.get_text().strip()

        page_age = parse_dt_to_utc(raw_age)
        description = re.sub(r"\s+", " ", description).strip()
        description = re.sub(r"^[\s\-\·\u00a0]+", "", description).strip()

        if title or url or description:
            results.append(
                {
                    "title": title or "Untitled",
                    "url": url or "",
                    "description": description or "",
                    "thumbnail_url": thumbnail_url,
                    "favicon_url": favicon_url,
                    "page_age": page_age,
                }
            )
    return results


def get_page_content(
    url: str, proxy: str | None = None, timeout: int = 3
) -> str:
    """Fetch raw HTML content for a URL using curl_cffi."""
    user_agent = get_random_user_agent()
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            proxy=proxy,
            timeout=timeout,
            impersonate="firefox133",
            verify=False,
        )
        response.raise_for_status()
        return response.text
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"Error fetching {url}: {e}")


def search_brave(
    query: str,
    max_results: int = 10,
    region: str = "us-en",
    safesearch: Literal["on", "moderate", "off"] | str = "moderate",
    timelimit: Literal["d", "w", "m", "y"] | str | None = None,
    page: int = 1,
    timeout: int = 15,
    max_attempts: int = 3,
    extraction: bool = False,
    proxy: str | None = None,
    news: bool = False,
    format: Literal["html", "markdown"] = "html",
    **kwargs: Any,
) -> list[Any]:
    """Searches Brave Search engine and returns extracted results.

    :param query: The search query string.
    :param max_results: Maximum number of results to return (default: 10).
    :param region: Region code (e.g. 'us-en', default: 'us-en').
    :param safesearch: SafeSearch filter ('on' | 'moderate' | 'off', default: 'moderate').
    :param timelimit: Time limit filter ('d' | 'w' | 'm' | 'y' | None).
    :param page: Page number for pagination (default: 1).
    :param timeout: Request timeout in seconds (default: 15).
    :param max_attempts: Maximum retry attempts (default: 3).
    :param extraction: Whether to fetch page contents via ThreadPoolExecutor.
    :param proxy: Proxy URL (defaults to PROXY_URL from environment).
    :param news: Whether to perform a news search.
    :return: List of parsed search result dicts.
    """
    trimmed_query = query.strip()
    if not trimmed_query:
        raise ValueError("Query must be a non-empty string")

    if max_results <= 0:
        return []

    if max_results:
        max_results = min(max_results, 100)

    # Read PROXY_URL from environment if not explicitly provided
    if proxy is None:
        proxy = os.environ.get("PROXY_URL")

    # Build query params
    params: dict[str, str] = {
        "q": trimmed_query,
        "source": "web",
    }

    if timelimit and timelimit in TIMELIMIT_MAP:
        params["tf"] = TIMELIMIT_MAP[timelimit]

    # Build cookies
    country = region.lower().split("-")[0] if region else "us"
    if not country:
        country = "us"
    cookie_list = [f"{country}={country}", "useLocation=0"]
    if safesearch != "moderate":
        cookie_list.append(
            f"safesearch={'strict' if safesearch == 'on' else 'off'}"
        )
    cookie_header = "; ".join(cookie_list)

    if news:
        url = "https://search.brave.com/news"
    else:
        url = "https://search.brave.com/search"

    last_error: Exception | None = None
    results: list[Any] = []
    seen_web_urls: set[str] = set()
    current_offset = max(0, page - 1)
    added_count: int = 0

    while len(results) < max_results:
        page_params = dict(params)
        if current_offset > 0:
            page_params["offset"] = str(current_offset)

        page_success = False
        for attempt in range(1, max_attempts + 1):
            try:
                user_agent = get_random_user_agent()
                session = requests.Session(
                    proxy=proxy,
                    verify=False,
                    impersonate="firefox133",
                    headers={
                        "Cookie": cookie_header,
                        "User-Agent": user_agent,
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                )
                response = session.get(
                    url,
                    params=page_params,
                    timeout=timeout,
                )

                if response.status_code < 200 or response.status_code >= 400:
                    raise RuntimeError(
                        f"Brave Search returned HTTP {response.status_code}"
                    )

                html = response.text

                if not html or not html.strip():
                    raise RuntimeError(
                        "Empty response received from Brave Search"
                    )

                soup = BeautifulSoup(html, "html.parser")
                new_items = extract_web_results(soup)

                added_count = 0
                for item in new_items:
                    item_key = item.get("url") or item.get("title")
                    if item_key and item_key not in seen_web_urls:
                        seen_web_urls.add(item_key)
                        results.append(item)
                        added_count += 1

                page_success = True
                break

            except Exception as err:
                last_error = err
                if attempt < max_attempts:
                    time.sleep(1.5 * attempt)

        if not page_success:
            if not results:
                raise RuntimeError(
                    f"Brave search failed after {max_attempts} attempts: {last_error}"
                )
            break

        # Stop if no new items were found on this page
        if added_count == 0:
            break

        if len(results) >= max_results:
            break

        current_offset += 1

    results = results[:max_results]

    if extraction and results:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(results), 10)
        ) as executor:
            futures = {
                executor.submit(
                    get_page_content,
                    item.get("url", ""),
                    proxy,
                    timeout,
                ): item
                for item in results
                if item.get("url")
            }
            for future in concurrent.futures.as_completed(futures):
                item = futures[future]
                try:
                    result = future.result()
                    if format == "markdown":
                        markdown_text = (
                            trafilatura.extract(
                                result,
                                include_tables=True,
                                include_links=False,
                                output_format="markdown",
                            )
                            or ""
                        )
                        item["content"] = markdown_text
                    else:
                        clean_text = re.sub(r"\n+", " ", result)
                        clean_text = BeautifulSoup(
                            clean_text, "html.parser"
                        ).get_text()
                        item["content"] = re.sub(
                            r"\s+", " ", clean_text
                        ).strip()
                except Exception:
                    item["content"] = None

    return results


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore
        except Exception:
            pass

    query_arg = sys.argv[1] if len(sys.argv) > 1 else "latest world news"
    proxy_override = sys.argv[2] if len(sys.argv) > 2 else None
    print(f"Searching Brave for: {query_arg!r}")
    items = search_brave(query_arg, proxy=proxy_override, news=True)
    import json

    print(json.dumps(items, indent=2))
