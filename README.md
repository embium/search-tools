# Search Tools MCP Server

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server that provides AI-powered web search capabilities using **Brave Search** and **Bing Copilot**.

## Features

- **Brave Search** – General web search via the Brave Search API.
- **Bing AI Answers** – Pull summarized AI-generated answers from Bing Copilot.
- Simple, lightweight, and easy to integrate with any MCP-compatible client (e.g., Claude Desktop, Cline, or Continue).

## Prerequisites

- [uv](https://github.com/astral-sh/uv) for dependency management and running the server.
- A proxy URL with access to Brave Search and Bing (set via the `PROXY_URL` environment variable).

## Installation

1. Clone the repository:

   ```bash
   git clone <repo-url>
   cd search-tools
   ```

2. Install dependencies:

   ```bash
   uv sync
   ```

## Configuration

Set the `PROXY_URL` environment variable to your proxy endpoint. This is required for both Brave and Bing search functionality.

```bash
export PROXY_URL="https://your-proxy-url"
```

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

### Example: Claude Desktop

1. Open `claude_desktop_config.json`:
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Windows**: `%APPDATA%/Claude/claude_desktop_config.json`

2. Add the server block above under the `mcpServers` key.

3. Restart Claude Desktop. The search tools will be available in your conversations.

## Project Structure

```
search-tools/
├── main.py           # MCP server entry point
├── pyproject.toml    # Project metadata and dependencies
├── uv.lock           # Locked dependency versions
└── README.md         # You're here!
```

## License

MIT
