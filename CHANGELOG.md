# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-05-24

Initial scaffold.

### Added

- 6 read-only MCP tools wrapping the Polygon.io public API:
  - `get_ticker_news(ticker, limit=10, since_days=7)`
  - `get_market_news(limit=20, since_hours=24)`
  - `get_ticker_details(ticker)`
  - `list_sec_filings_index(ticker, since_days=90)`
- 2 meta tools: `health_check` and `get_server_info` (offline-safe).
- DuckDB local cache with per-table TTL (1 h / 24 h / 6 h).
- Token-bucket rate limiter (sliding 60-second window, default 5 req/min,
  hard cap 1000 req/min).
- Structured error hierarchy: `PolygonValidationError`,
  `PolygonAuthError`, `PolygonNotFoundError`, `PolygonRateLimitError`,
  `PolygonTransientError`, `PolygonConfigurationError`.
- Pydantic v2 input schemas with anchored ticker regex.
- Stdio-hardened FastMCP server with rotating file logs under
  `${XDG_STATE_HOME}/polygon-news-mcp/logs/`.
- Explicit `mcp_app._mcp_server.version = SERVER_VERSION` so
  `serverInfo.version` reports the project release tag from day one
  (instead of the underlying mcp framework version) — including the
  `test_initialize_reports_release_tag_version` regression test.
- Documentation: README (en + zh), `docs/REGISTER.md`,
  `docs/THREAT_MODEL.md`, `docs/RELEASE.md`, `CONTRIBUTING.md`.

[Unreleased]: https://github.com/kevinkda/polygon-news-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/kevinkda/polygon-news-mcp/releases/tag/v0.1.0
