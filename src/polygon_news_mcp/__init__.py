"""Polygon.io Read-only MCP Server.

A Model Context Protocol (MCP) server exposing 8 tools that wrap the
Polygon.io public API (6 business + 2 meta tools).

Public modules:
    - :mod:`polygon_news_mcp.server` — FastMCP entry point.
    - :mod:`polygon_news_mcp.client` — async httpx client wrapper.
    - :mod:`polygon_news_mcp.cache` — DuckDB local cache.
    - :mod:`polygon_news_mcp.errors` — structured exception hierarchy.
    - :mod:`polygon_news_mcp.models` — Pydantic v2 input schemas.
"""

from __future__ import annotations

__version__ = "0.2.2"

__all__ = ["__version__"]
