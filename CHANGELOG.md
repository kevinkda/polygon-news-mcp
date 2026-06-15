# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-06-15

### Changed

- ⚠️ **BREAKING: the embedded DuckDB cache is removed and replaced by a
  pluggable cache backend (v0.7 T0).** The cache now delegates to a
  `CacheBackend` selected via `POLYGON_CACHE_BACKEND`:
  - **memory** (default) — in-process LRU + per-entry TTL built on stdlib
    `OrderedDict` + a short-held `threading.Lock` that only ever wraps dict
    mutations (never I/O). Zero external dependency, concurrency-safe, and
    non-blocking — it removes the old single-connection DuckDB + global
    `RLock` that could serialise the asyncio event loop, plus all on-disk
    cache files, file locks, and the corrupt-DB quarantine machinery.
  - **clickhouse** (opt-in) — `pip install polygon-news-mcp[clickhouse]`
    + `POLYGON_CLICKHOUSE_URL` + `POLYGON_CACHE_BACKEND=clickhouse` for
    durable derived-analysis history (`append_timeseries` /
    `query_timeseries`). `clickhouse_connect` is imported lazily, so a
    default install never pays for it; a missing extra raises a friendly
    `ClickHouseNotInstalledError`.
- **Removed the `duckdb` runtime dependency.** ClickHouse is an opt-in
  `[clickhouse]` extra only; the default install ships with **zero new
  dependencies** and works out of the box.
- **Graceful degradation without ClickHouse.** Derived-analysis time-series
  calls on the memory backend return a structured
  `{"status": "requires_clickhouse_persistence", "hint": ...}` signal
  instead of raising — core tools (news / ticker details / filings index /
  dividends) see zero behavioural change.
- **`get_cache_stats` / `health_check` fields changed.** The DuckDB-specific
  `db_path` / `size_mb` / `rows_per_table` / `expired_rows` / `hit_rate_24h`
  / `hits_24h` / `misses_24h` fields are replaced by `backend` (the active
  backend name) and `entries` (live response-cache entry count).
- The per-table public cache API (`get_news` / `put_news` /
  `get_ticker_details` / `get_filings_index` / `get_dividends` …) is
  unchanged, so all tools and their behaviour are unaffected. 100%
  line+branch coverage preserved (memory concurrency/LRU/TTL, ClickHouse via
  a mocked client, degradation, and factory fallback paths).



### Changed

- ⚠️ **BREAKING: DuckDB cache is now opt-in (default DISABLED).**
  `cache_enabled()` flips its default from `True` to `False`, so an
  unset `POLYGON_CACHE_ENABLED` now yields **no cache** — no DuckDB file
  is created and every tool hits Polygon live, reporting
  `_cache_status: "disabled"`. Re-enable explicitly with
  `POLYGON_CACHE_ENABLED=true` (also accepts `1` / `yes` / `on`, case- and
  whitespace-insensitive). This zeroes the default on-disk footprint and
  removes implicit persistent state for fresh installs and CI. Tests,
  `.env.example`, `README.md`, and `README_zh.md` updated; 100% coverage
  preserved (truthy/falsy matrix + unset→`get_cache()` None gate added).

## [0.2.1] - 2026-05-31

### Added

- **Test campaign batch 3 — 100% coverage + full security suite (from
  zero).** Raised line+branch coverage from 88.58% to **100.00%** (363
  tests, up from 193) and built the complete security test matrix
  mirroring the batch-1 schwab-positions-mcp template. polygon-news-mcp
  previously had **no security tests**; this release establishes the
  baseline:
  - `tests/test_coverage_completion.py` — drives every residual
    `file:line` branch to 100% (server error-framing + per-tool except
    branches, stdio-harden OSError paths, `_runtime` cache lookup/store
    exceptions, meta api-key/cache branches, cache DuckDB-error
    resilience + quarantine, client JSON-shape + `_abs_url`
    normalisation, news/filings/sentiment non-dict-entry skips).
  - `tests/test_owasp_2017.py`, `tests/test_owasp_2021.py`,
    `tests/test_owasp_2025.py` — OWASP Top 10 across all three editions.
    The centrepiece is **`POLYGON_API_KEY` confidentiality**: the key is
    asserted absent from error envelopes, exception `repr`/`str`, logs,
    cache payloads, and tool responses (`redact_secret` strips both
    `?apiKey=` query strings and `Bearer` tokens). **N/A categories are
    explicitly documented with source-drift guards**: A4 XXE (Polygon is
    a JSON-only API — no XML parser imported) and A7:2017 XSS (no HTML
    surface).
  - `tests/test_pentest.py` — active attacker simulation: SSRF via
    ticker, SQL/command injection, **API-key exfiltration** (error repr,
    framed envelope, cache payload), resource exhaustion, free-tier
    rate-limit evasion, and info-leak guards.
  - `tests/test_exception.py` — exception type guards, HTTP-layer error
    mapping (401/403/404/invalid-JSON/5xx), cache best-effort
    resilience, and API-key/PII scrubbing.
  - `tests/test_boundary.py` — boundary-value sweeps for every numeric
    and string input (limit, since_days, since_hours, ticker length,
    dividend_type / window_days literals, extra-field rejection).

### Changed

- CI coverage gate (`tool.coverage.report.fail_under`) raised from 85 to
  **100**.
- `markdownlint-cli2` pre-commit hook gated to `stages: [manual]` (aligns
  with gitleaks) because the `npx --yes` invocation times out on
  locked-down corporate networks; CI still runs markdownlint on the
  public-network reusable workflow.
- Three `# pragma: no cover` / `# pragma: no branch` annotations added to
  provably-unreachable defensive branches (token-bucket `wait<=0`
  continue, double-checked-lock race sides, the `resolve_api_key`
  config-error path that only fires on an empty key already guarded
  upstream) with documented rationale.

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
