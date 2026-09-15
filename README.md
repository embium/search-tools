# Search Tools MCP Server

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server built with [FastMCP](https://github.com/jlowin/fastmcp) that exposes web search and AI answer tools powered by **Brave Search** and **Bing Copilot**.

## Features

| Tool | Source | Description |
|------|--------|-------------|
| `search` | Brave Search | General web search with result extraction, news filtering, and pagination. |
| `answer` | Bing Copilot | Ask a question and get a summarized AI-generated answer with citations. |

**Resource:** `info://about` — Returns basic server metadata.

## Prerequisites

- **Python** ≥ 3.13
- [uv](https://docs.astral.sh/uv/) (recommended) or `pip`
- A proxy with access to Brave Search and Bing (configured via the `PROXY_URL` environment variable)

## Installation

Clone the repository and install dependencies:

```bash
git clone <repo-url>
cd search-tools
uv sync          # recommended
# OR
pip install -r requirements.txt
```

## Configuration

Set the `PROXY_URL` environment variable to your proxy endpoint. This is required for both search providers.

```bash
export PROXY_URL="https://your-proxy-url"
```

Alternatively, create a `.env` file in the project root (the server loads it automatically via `python-dotenv`).

## Usage

Add the following server configuration to your MCP client:

```json
{
  "command": "uv",
  "args": [
    "--directory",
    "~/dev/search-tools",
    "run",
    "main.py"
  ],
  "env": {
    "PROXY_URL": "YOUR_PROXY_HERE"
  },
  "type": "stdio",
  "active": true
}
```

### Claude Desktop Example

1. Open your Claude Desktop configuration file:
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Windows**: `%APPDATA%/Claude/claude_desktop_config.json`

2. Add the JSON block above under the `mcpServers` key.

3. Restart Claude Desktop — the `search` and `answer` tools will be available in chat.

## Available Tools

### `search`

Search the web using Brave Search.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | — | Search query string |
| `max_results` | `int` | `10` | Maximum number of results |
| `region` | `str` | `"us-en"` | Region/locale code |
| `safesearch` | `"on" \| "moderate" \| "off"` | `"moderate"` | Safe-search level |
| `timelimit` | `"d" \| "w" \| "m" \| "y" \| null` | `null` | Time limit filter |
| `page` | `int` | `1` | Results page number |
| `timeout` | `int` | `15` | Request timeout in seconds |
| `max_attempts` | `int` | `3` | Retry attempts on transient failures |
| `extraction` | `bool` | `false` | Extract full article content from result pages |
| `proxy` | `str \| null` | `null` | Override proxy URL for this call |
| `news` | `bool` | `false` | Search news instead of general web |
| `format` | `"html" \| "markdown"` | `"html"` | Content extraction format |

### `answer`

Get an AI-generated answer from Bing Copilot with citations.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | — | Question to ask |
| `timeout` | `int` | `15` | Request timeout in seconds |
| `max_attempts` | `int` | `3` | Retry attempts on transient failures |
| `proxy` | `str \| null` | `null` | Override proxy URL for this call |

## Project Structure

```
search-tools/
├── main.py              # MCP server entry point (FastMCP)
├── pyproject.toml       # Project metadata & uv dependencies
├── requirements.txt     # Alternative pip requirements
├── uv.lock              # Locked dependency versions
├── .python-version      # Python version pin (≥3.13)
├── brave/
│   ├── __init__.py
│   └── search.py        # Brave Search implementation
├── bing/
│   ├── __init__.py
│   └── answer.py        # Bing Copilot answer implementation
└── README.md            # You are here
```

## Key Dependencies

- [`fastmcp`](https://github.com/jlowin/fastmcp) ≥ 4.0 — MCP framework
- [`curl-cffi`](https://github.com/yifeikong/curl_cffi) ≥ 0.16 — TLS fingerprint spoofing for scraping
- [`trafilatura`](https://github.com/adbar/trafilatura) ≥ 2.2 — Article content extraction
- `beautifulsoup4` ≥ 4.15 — HTML parsing
- `fake-useragent` ≥ 2.2 — Rotating user-agents

## License

MIT
