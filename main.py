from fastmcp import FastMCP

from brave.search import search_brave
from bing.answer import get_bing_answer, BingAnswer

from typing import Any, Literal

mcp = FastMCP("Search")


@mcp.tool()
def search(
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
) -> list[Any]:
    """
    Search the Brave search engine
    """
    return search_brave(
        query,
        max_results,
        region,
        safesearch,
        timelimit,
        page,
        timeout,
        max_attempts,
        extraction,
        proxy,
        news,
        format,
    )


@mcp.tool()
def answer(
    query: str,
    timeout: int = 15,
    max_attempts: int = 3,
    proxy: str | None = None,
) -> BingAnswer | None:
    """
    Ask Bing a question and receive an answer with citations.
    """

    return get_bing_answer(query, timeout, max_attempts, proxy)


# 2. Define a RESOURCE (Static or dynamic data the AI can read)
@mcp.resource("info://about")
def get_server_info() -> str:
    """Provide system information about this server."""
    return "This is a custom Python MCP server built using FastMCP."


if __name__ == "__main__":
    # Run the server using standard input/output (stdio) transport
    mcp.run(transport="stdio")
