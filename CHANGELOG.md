# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-05-24

### Added

- (Sprint A) Cross-platform `_platform.py` shim with 23 tests covering
  POSIX/Windows file ops (file locking, `secure_chmod`,
  `restrictive_umask`, `state_root`, `notify_desktop`). 100% line +
  branch coverage.
- (Sprint A) `windows-latest` runner in CI matrix with `posix_only`
  pytest markers for platform-divergent tests.
- (Sprint A) CodeQL workflow for Python static analysis
  (push/PR + Mon 02:30 UTC).
- (Sprint C) **`get_news_sentiment_aggregate` (5th business tool)** —
  aggregates the per-article `insights[].sentiment` annotations from
  `get_ticker_news` over a fixed look-back window
  (`window_days: 1 | 7 | 30 = 7`) into a single per-ticker summary:
  distribution (`{positive, neutral, negative}`), weighted score in
  `[-1.0, +1.0]`, top-5 publishers by article count, and the most
  "significant" articles by a publisher-diversity ×
  sentiment-magnitude heuristic. Reuses the existing 1 h news cache,
  so a typical call costs at most one upstream Polygon request per
  `(ticker, window_days)` pair. Drives the *shakeout-with-news*
  playbook.
- (Sprint C) **`get_dividends` (6th business tool)** — dividend
  history per ticker with `ex_dividend_date`, `pay_date`,
  `declaration_date`, `record_date`, `cash_amount`, `currency`,
  `frequency`, and a normalised `dividend_type` filter
  (`all` / `regular` / `special` / `unspecified`) that maps onto
  Polygon's `CD` / `SC` / `""` two-letter codes. TTL 24 h. Drives the
  *dividend-tracker* playbook.
- (Sprint C) New DuckDB cache table `dividends_cache` (TTL 24 h) —
  independent from the 6 h `filings_index_cache` so a fresh dividend
  pull does not invalidate filings caches.
- 30+ new unit tests (Sprint C) across `tests/test_v0_2_tools.py` and
  the model / server-integration suites, exercising happy-path, empty
  results, garbage upstream payloads, 401 / 429 / 5xx error mapping,
  dividend type filter translation, sentiment cache-hit semantics, and
  Literal `window_days` validation. Plus 23 platform tests (Sprint A).

### Changed

- Tool count: 6 → 8 (6 business + 2 meta).
- `models.supported_tool_names()` now lists all 8 tools.
- README / README_zh / `docs/REGISTER.md` describe the 8-tool surface
  and the dividends cache row.
- Total test count on Linux: 132 → 193; total branch coverage stays
  ≥ 86% (currently 88.58%).

### Deferred

- **`get_earnings_calendar` is deferred to v0.3** pending Polygon
  paid-tier validation. Polygon's free-tier REST surface does not
  include a dedicated earnings-calendar endpoint with EPS / revenue
  estimates vs actuals; only `/vX/reference/financials` (filed
  financial statements, paid-only for full coverage) exists. Until
  paid-tier access is wired up, use
  `sec-edgar-mcp.get_8k_with_items(item_codes=["2.02"])` as the
  earnings-detection fallback — see
  [`docs/REGISTER.md`](./docs/REGISTER.md#earnings-calendar-fallback).

### Compatibility

- `_platform.py` shim provides Windows native support
  (Tier A experimental).
- Test count: 193 passed on Linux (88.58% coverage).

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

[Unreleased]: https://github.com/kevinkda/polygon-news-mcp/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/kevinkda/polygon-news-mcp/releases/tag/v0.2.0
[0.1.0]: https://github.com/kevinkda/polygon-news-mcp/releases/tag/v0.1.0
