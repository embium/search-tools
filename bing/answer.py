"""Bing Answer module."""

from __future__ import annotations

import copy
import json
import os
import random
import re
import sys
import time
from typing import Any, TypedDict
from urllib.parse import quote_plus

from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString
from curl_cffi import requests

DEFAULT_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def get_random_user_agent() -> str:
    """Return a random User-Agent string."""
    try:
        from fake_useragent import UserAgent

        ua = UserAgent(["Firefox"])
        return ua.random
    except Exception:
        return random.choice(DEFAULT_USER_AGENTS)


def generateConvid(length: int = 21) -> str:
    """Generate a random Base58 conversation ID matching Bing's 21-char pattern."""
    return "".join(random.choice(BASE58_ALPHABET) for _ in range(length))


# Snake_case alias
generate_convid = generateConvid


class BingCitation(TypedDict):
    number: int
    title: str
    url: str


class BingAnswer(TypedDict):
    text: str
    citations: list[BingCitation]


def parse_bing_answers_raw(raw_text: str) -> BingAnswer | None:
    """Parse the raw chunked streaming response from Bing /cmc/fetch (delimited by ::csbreak::)

    extracting formatted answer text with inline [1], [2] citation markers and citations metadata.
    """
    chunks = [s.strip() for s in raw_text.split("::csbreak::") if s.strip()]

    soup = BeautifulSoup(
        '<div class="cht_text" inslvl=""></div>', "html.parser"
    )
    cht_text = soup.select_one(".cht_text")
    if cht_text is None:
        return None

    citations_map: dict[int, BingCitation] = {}
    has_content = False

    for chunk in chunks:
        try:
            data = json.loads(chunk)
            if data.get("type") != "htmlFragment" or not data.get(
                "value", {}
            ).get("levelFragments"):
                continue

            val = data["value"]
            insertion_id = (val.get("insertionId") or "").strip()

            # Citation references
            if "cht_cit_root" in insertion_id or "cht_ans" in insertion_id:
                for _, html_str in val["levelFragments"]:
                    card_soup = BeautifulSoup(html_str, "html.parser")
                    for el in card_soup.select(".cht_cit"):
                        num_str = el.get("data-citation-num")
                        num_str = str(num_str) if num_str else ""
                        num = (
                            int(num_str)
                            if num_str and num_str.isdigit()
                            else len(citations_map) + 1
                        )
                        title_el = el.select_one(
                            ".cht_cit_title_text, .cht_cit_site"
                        )
                        title = title_el.get_text().strip() if title_el else ""
                        siteurl_el = el.select_one(".cht_cit_siteurl")
                        href = ""
                        if siteurl_el and siteurl_el.get_text().strip():
                            href = siteurl_el.get_text().strip()
                        else:
                            a_tag = el.select_one("a")
                            if a_tag and a_tag.get("href"):
                                href_attr = a_tag.get("href")
                                href = str(href_attr) if href_attr else ""

                        if num and num not in citations_map:
                            citations_map[num] = {
                                "number": num,
                                "title": title,
                                "url": href,
                            }
                continue

            # HTML content fragments
            for level, html_str in val["levelFragments"]:
                if html_str.startswith("<style") or html_str.startswith(
                    "<script"
                ):
                    continue
                has_content = True
                frag = BeautifulSoup(html_str, "html.parser")
                frag_elements = list(frag.contents)

                if insertion_id == ".cht_text" or insertion_id == "":
                    for item in frag_elements:
                        cht_text.append(item)
                else:
                    target_selector = re.sub(
                        r"^\.cht_text\s*", "", insertion_id
                    ).strip()
                    target = (
                        cht_text.select_one(target_selector)
                        if target_selector
                        else None
                    )
                    if target:
                        current = target
                        inslvl_count = 0
                        while inslvl_count < level:
                            parent = current.parent
                            if not parent or parent.name in (
                                "[document]",
                                "html",
                                "body",
                            ):
                                break
                            current = parent
                            classes_attr = current.get("class")
                            if not classes_attr:
                                classes = []
                            elif isinstance(classes_attr, str):
                                classes = classes_attr.split()
                            else:
                                classes = [str(c) for c in classes_attr]
                            if (
                                current.has_attr("inslvl")
                                or "cht_text" in classes
                                or "cht_mdroot" in classes
                            ):
                                inslvl_count += 1
                        for item in frag_elements:
                            current.append(item)
                    else:
                        mdroot = cht_text.select_one(".cht_mdroot")
                        target_container = mdroot if mdroot else cht_text
                        for item in frag_elements:
                            target_container.append(item)

        except Exception:
            # Ignore unparseable chunks
            continue

    if not has_content:
        return None

    # 1. Remove style, script, UI buttons
    for el in cht_text.select(
        "style, script, .cht_codblk_clip, .cht_codblk_sr_announce, noscript"
    ):
        el.decompose()

    # 2. Select citation root elements (.md_citlink can be <a> or <span>, or have data-sups)
    cit_selector = ".md_citlink, [data-sups]"

    # Fallback: If no citation cards in .cht_cit_root, extract from inline links
    if not citations_map:
        for el in cht_text.select(cit_selector):
            href_attr = el.get("href")
            href = str(href_attr) if href_attr else ""
            site_title_el = el.select_one(".md_citlink__site")
            site_title = (
                site_title_el.get_text().strip() if site_title_el else ""
            )
            aria_label = str(el.get("aria-label") or "")
            aria_label = re.sub(
                r"^Sources:\s*", "", aria_label, flags=re.I
            ).strip()
            title = site_title or aria_label or ""
            sups_attr = el.get("data-sups")
            sups = str(sups_attr) if sups_attr else ""
            if sups:
                for s_part in sups.split(","):
                    s_part = s_part.strip()
                    if s_part.isdigit():
                        n = int(s_part)
                        if n not in citations_map:
                            citations_map[n] = {
                                "number": n,
                                "title": title,
                                "url": href,
                            }
            elif href:
                n = len(citations_map) + 1
                citations_map[n] = {"number": n, "title": title, "url": href}

    # 3. Replace inline citation elements with formatted citation markers e.g. [1], [1][2]
    for el in list(cht_text.select(cit_selector)):
        href_attr = el.get("href")
        href = str(href_attr) if href_attr else ""
        sups_attr = el.get("data-sups")
        sups = str(sups_attr) if sups_attr else ""
        marker = ""

        if sups:
            nums = [s.strip() for s in sups.split(",") if s.strip()]
            marker = "".join(f"[{n}]" for n in nums)
        else:
            found_num = None
            for n, cit in citations_map.items():
                if cit.get("url") and href and cit["url"] == href:
                    found_num = n
                    break
            if not found_num:
                site_title_el = el.select_one(".md_citlink__site")
                site_title = (
                    site_title_el.get_text().strip() if site_title_el else ""
                )
                aria_label = str(el.get("aria-label") or "")
                aria_label = re.sub(
                    r"^Sources:\s*", "", aria_label, flags=re.I
                ).strip()
                title = site_title or aria_label or ""
                if title or href:
                    found_num = len(citations_map) + 1
                    citations_map[found_num] = {
                        "number": found_num,
                        "title": title,
                        "url": href,
                    }
            if found_num:
                marker = f"[{found_num}]"

        el.replace_with(f" {marker}")

    # 4. Extract structured text preserving headings, paragraphs, lists, and code blocks
    lines: list[str] = []

    def traverse(node: Tag | NavigableString) -> None:
        if isinstance(node, NavigableString):
            t = str(node).strip()
            if t:
                lines.append(t)
            return

        if not isinstance(node, Tag):
            return

        tag = node.name.lower()
        if re.match(r"^h[1-6]$", tag):
            text_str = re.sub(r"\s+", " ", node.get_text()).strip()
            if text_str:
                lines.append(text_str)
            return

        if tag == "pre":
            lang_el = node.select_one(".cht_codblk_lang")
            lang = lang_el.get_text().strip().lower() if lang_el else ""
            for hdr in node.select(".cht_codblk_hdr"):
                hdr.decompose()
            for br in node.select("br"):
                br.replace_with("\n")
            code = node.get_text().strip()
            if code:
                lines.append(f"```{lang}\n{code}\n```")
            return

        if tag == "p":
            p_copy = copy.copy(node)
            for child in p_copy.select("ul, ol, pre"):
                child.decompose()
            for br in p_copy.select("br"):
                br.replace_with("\n")
            t = re.sub(r"[ \t]+", " ", p_copy.get_text())
            t = re.sub(r"\n\s*\n+", "\n", t).strip()
            if t:
                lines.append(t)
            for child in node.find_all(["ul", "ol", "pre"], recursive=False):
                traverse(child)
            return

        if tag == "li":
            li_copy = copy.copy(node)
            for child in li_copy.select("ul, ol, pre"):
                child.decompose()
            for br in li_copy.select("br"):
                br.replace_with("\n")
            t = re.sub(r"[ \t]+", " ", li_copy.get_text())
            t = re.sub(r"\n\s*\n+", "\n", t).strip()
            if t:
                lines.append(f"- {t}")
            for child in node.find_all(["ul", "ol", "pre"], recursive=False):
                traverse(child)
            return

        if tag in ("ul", "ol", "div", "section", "article") or not tag:
            for child in node.children:
                if isinstance(child, Tag):
                    traverse(child)
            return

        t = re.sub(r"[ \t]+", " ", node.get_text()).strip()
        if t:
            lines.append(t)

    for child in cht_text.children:
        if isinstance(child, Tag):
            traverse(child)

    text_output = (
        "\n\n".join(lines)
        if lines
        else re.sub(
            r"\n\s*\n+",
            "\n\n",
            re.sub(r"[ \t]+", " ", cht_text.get_text()),
        ).strip()
    )
    text_output = text_output.replace("\r", "")

    citations = [
        cit
        for cit in sorted(citations_map.values(), key=lambda c: c["number"])
        if cit["title"] or cit["url"]
    ]

    return {
        "text": text_output,
        "citations": citations,
    }


def get_bing_answer(
    query: str,
    timeout: int = 15,
    max_attempts: int = 3,
    proxy: str | None = None,
) -> BingAnswer | None:
    """Fetch AI generated answer directly from Bing with citations.

    :param query: The search query string.
    :param timeout: Request timeout in seconds (default: 15).
    :param max_attempts: Maximum retry attempts (default: 3).
    :param proxy: Proxy URL (defaults to PROXY_URL from environment).
    :return: Dict containing 'text' and 'citations', or None if no answer found.
    """
    trimmed_query = query.strip()
    if not trimmed_query:
        raise ValueError("Query must be a non-empty string")

    if proxy is None:
        proxy = os.environ.get("PROXY_URL")

    url = "https://www.bing.com/cmc/fetch"
    convid = generateConvid()
    params = {
        "q": trimmed_query,
        "convid": convid,
        "ajaxreq": "1",
    }

    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            user_agent = get_random_user_agent()
            session = requests.Session(
                impersonate="firefox133",
                proxy=proxy if proxy else None,
                verify=False,
                timeout=timeout,
            )

            response = session.get(
                url,
                params=params,
                headers={
                    "User-Agent": user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": f"https://www.bing.com/search?q={quote_plus(trimmed_query)}",
                },
            )

            if response.status_code < 200 or response.status_code >= 400:
                raise RuntimeError(
                    f"HTTP {response.status_code} when fetching {url}"
                )

            raw_text = response.text
            return parse_bing_answers_raw(raw_text)

        except Exception as err:
            last_error = err
            if attempt < max_attempts:
                time.sleep(0.5 * attempt)

    raise RuntimeError(
        f"Bing answers failed after {max_attempts} attempts: {last_error}"
    )


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore
        except Exception:
            pass

    query_arg = (
        sys.argv[1] if len(sys.argv) > 1 else "What is the capital of France?"
    )
    proxy_override = sys.argv[2] if len(sys.argv) > 2 else None
    print(f"Asking Bing: {query_arg!r}\n")
    ans = get_bing_answer(query_arg, proxy=proxy_override)
    if ans:
        print("=== ANSWER ===")
        print(ans["text"])
        print("\n=== CITATIONS ===")
        print(json.dumps(ans["citations"], indent=2))
    else:
        print("No answer found.")
