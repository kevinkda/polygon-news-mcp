# polygon-news-mcp

[English](./README.md) | [简体中文](./README_zh.md)

![License](https://img.shields.io/badge/license-MIT-blue)
![Python](https://img.shields.io/badge/python-3.11+-blue)
![Status](https://img.shields.io/badge/status-alpha-orange)

Read-only **Model Context Protocol (MCP)** server that wraps the
[Polygon.io](https://polygon.io/) public API as **8 tools**
(6 business + 2 meta) for use inside Cursor, Claude Code, and any
MCP-aware agent.

> **Read-only** — every tool issues plain HTTPS GETs against
> `https://api.polygon.io/`. Nothing is ever written back to Polygon.

---

## Why a separate repo

`polygon-news-mcp` is sister to
[`schwab-marketdata-mcp`](https://github.com/kevinkda/schwab-marketdata-mcp)
and [`sec-edgar-mcp`](https://github.com/kevinkda/sec-edgar-mcp). It fills
the gap that Schwab's market-data feed leaves open: **news**, ticker
**reference metadata**, and an **SEC filings index with sentiment**.

| Capability                  | Schwab MD | SEC EDGAR | **Polygon (here)** |
| --------------------------- | --------- | --------- | ------------------ |
| Quotes, candles, options    | yes       | no        | no                 |
| Filings (10-K / 10-Q / 8-K) | no        | yes       | index only         |
| News + sentiment            | no        | no        | yes                |
| Ticker reference metadata   | partial   | partial   | yes                |
| Dividends                   | partial   | no        | yes                |
| Earnings calendar           | partial   | 8-K 2.02  | deferred to v0.3   |

All three repos share the same hardening discipline:

- Pluggable response cache (1 h news / 24 h ticker details / 6 h filings) —
  **disabled by default (opt-in)**; enable with `POLYGON_CACHE_ENABLED=true`.
  Default backend is in-process **memory** (zero dependency); an opt-in
  **ClickHouse** backend (`[clickhouse]` extra) adds durable history.
- httpx async client with token-bucket rate limit (free tier: 5 req/min).
- Pydantic v2 input validation (anchored ticker regex).
- Stdio hardening so log lines never corrupt the JSON-RPC stream.
- Structured error hierarchy (`PolygonAuthError`, `PolygonNotFoundError`,
  `PolygonRateLimitError`, `PolygonValidationError`, `PolygonTransientError`).

---

## Cost & authentication

- **Cost:** free tier ($0) supports **5 req/min** — usable for interactive
  research but rate-limited. Paid tiers start at $29/mo (Starter, 5x rate)
  and $79/mo (Developer).
- **Auth:** Polygon requires an API key on every request. Get one for free
  at <https://polygon.io/dashboard/api-keys> and put it in `.env` as
  `POLYGON_API_KEY=...`.

The key is sent via the `Authorization: Bearer ...` header; it is **never**
embedded in the request URL, so nothing the server logs can echo it.

---

## Quick start

```bash
git clone https://github.com/kevinkda/polygon-news-mcp.git
cd polygon-news-mcp

uv sync --extra dev
uv run pre-commit install

cp .env.example .env
# edit .env — set POLYGON_API_KEY=<your-key>

uv run polygon-news-mcp        # start the MCP server on stdio
```

Register the server with Cursor / Claude Desktop — see
[`docs/REGISTER.md`](./docs/REGISTER.md).

---

## Tooling surface

The server exposes **8 tools**: 6 business + 2 meta.

> **`get_earnings_calendar` is deferred to v0.3 pending Polygon paid-tier
> validation.** Polygon's free-tier REST surface does not include a
> dedicated earnings-calendar endpoint (only `/vX/reference/financials`
> for filed financial statements).  Until paid-tier access is wired up,
> use `sec-edgar-mcp.get_8k_with_items(item_codes=["2.02"])` to detect
> earnings 8-K filings as a fallback — see
> [`docs/REGISTER.md`](./docs/REGISTER.md#earnings-calendar-fallback).

### `get_ticker_news`

- **When to use:** to pull the most recent news articles mentioning a single
  ticker — the "what is being said about $TICKER" query.
- **Input:** `ticker: str` (e.g. `"AAPL"`), `limit: int = 10` (1-1000),
  `since_days: int = 7` (1-365).
- **Returns:** `{ ticker, count, articles: [{ id, publisher, title, author,
  published_utc, article_url, tickers, description, keywords, insights:
  [{ ticker, sentiment, sentiment_reasoning }, ...] }, ...] }`.
- **Example call:**

  ```python
  get_ticker_news(ticker="AAPL", limit=20, since_days=14)
  ```

### `get_market_news`

- **When to use:** to pull the most recent market-wide news (no ticker
  filter) — the "what's moving the tape today" query.
- **Input:** `limit: int = 20` (1-1000), `since_hours: int = 24` (1-720).
- **Returns:** same shape as `get_ticker_news` with `ticker = null`.
- **Example call:**

  ```python
  get_market_news(limit=50, since_hours=12)
  ```

### `get_ticker_details`

- **When to use:** to fetch Polygon's reference metadata for a ticker —
  name, exchange, SIC code, address, branding logos, market cap, etc. Pair
  with Schwab Market Data's quote endpoint for a complete picture.
- **Input:** `ticker: str`.
- **Returns:** `{ ticker, name, market, locale, primary_exchange, type,
  active, currency_name, cik, market_cap, address, description, sic_code,
  homepage_url, total_employees, list_date, branding: { logo_url,
  icon_url } }`.
- **Example call:**

  ```python
  get_ticker_details(ticker="MSFT")
  ```

### `list_sec_filings_index`

- **When to use:** to list a ticker's SEC filings with Polygon's value-add
  annotations — `sentiment` and `category` — that the raw SEC EDGAR feed
  does not carry. Pair with `sec-edgar-mcp.get_filing_text` to drill into
  the body of any filing.
- **Input:** `ticker: str`, `since_days: int = 90` (1-365).
- **Returns:** `{ ticker, since_days, count, filings: [{ accession_number,
  form_type, filed_date, period_of_report, company_name, ticker, cik,
  sentiment, category, filing_url, primary_document_url }, ...] }`.
- **Example call:**

  ```python
  list_sec_filings_index(ticker="AAPL", since_days=180)
  ```

### `get_news_sentiment_aggregate`

- **When to use:** to roll up Polygon's per-article
  `insights[].sentiment` annotations into a single per-ticker summary
  over a fixed look-back window — the "what's the news mood on $TICKER
  this week / this month" query.  Drives the *shakeout-with-news*
  playbook (combine with Schwab's price action + a news sentiment
  reading to confirm or reject a shakeout).
- **Input:** `ticker: str`, `window_days: 1 | 7 | 30 = 7`.
- **Returns:** `{ ticker, window_days, total_articles,
  sentiment_distribution: { positive, neutral, negative },
  sentiment_score (-1.0 to +1.0), top_publishers: [{ publisher, count }],
  most_significant_articles: [{ title, published_utc, sentiment,
  publisher, article_url }] }`.
- **Example call:**

  ```python
  get_news_sentiment_aggregate(ticker="MSFT", window_days=30)
  ```

  This does **not** issue a new Polygon request when the underlying
  `get_ticker_news` cache is warm — the aggregation is in-process.

### `get_dividends`

- **When to use:** to fetch a ticker's dividend history with full
  declaration / record / ex-dividend / pay dates and the cash amount.
  Drives the *dividend-tracker* playbook — pair with Schwab Market Data
  for the price action around each ex-date.
- **Input:** `ticker: str`, `since_days: int = 365` (1-3650),
  `dividend_type: "all" | "regular" | "special" | "unspecified" = "all"`.
- **Returns:** `{ ticker, since_days, count, dividends: [{ ticker,
  ex_dividend_date, pay_date, declaration_date, record_date, cash_amount,
  currency, frequency, dividend_type }, ...] }`.
  `dividend_type` is normalised to `"regular"` (Polygon `CD`),
  `"special"` (Polygon `SC`), or `"unspecified"`.
- **Example call:**

  ```python
  get_dividends(ticker="AAPL", since_days=730, dividend_type="regular")
  ```

### `health_check` (meta)

Local probe: returns server version, cache state, rate-limit budget, API
key status. Never calls Polygon.

### `get_server_info` (meta)

Local metadata: server version, supported tools, MCP SDK version, OS hint.
Never calls Polygon.

---

## Cache TTLs

| Table                  | TTL  | Rationale                                          |
| ---------------------- | ---- | -------------------------------------------------- |
| `news_cache`           | 1 h  | News feeds churn fast.                             |
| `ticker_details_cache` | 24 h | Reference data is stable.                          |
| `filings_index_cache`  | 6 h  | Filings are filed throughout each business day.    |
| `dividends_cache`      | 24 h | Dividend declarations are slow-cadence.            |

The cache is **disabled by default (opt-in)** — every tool hits Polygon live,
reporting `_cache_status: "disabled"`. Enable it explicitly with
`POLYGON_CACHE_ENABLED=true` (also accepts `1` / `yes` / `on`). Once enabled,
override with `POLYGON_CACHE_BYPASS=1` for a single-call force-fresh.

### Cache backend (v0.3.0)

⚠️ **BREAKING (v0.3.0):** the embedded DuckDB cache is removed in favour of a
pluggable backend selected via `POLYGON_CACHE_BACKEND`:

| Backend | Default | Dependency | Notes |
| --- | --- | --- | --- |
| `memory` | ✅ | none (stdlib) | In-process LRU + TTL, concurrency-safe, non-blocking, no files. |
| `clickhouse` | — | `pip install polygon-news-mcp[clickhouse]` + `POLYGON_CLICKHOUSE_URL` | Durable derived-analysis history. |

Without ClickHouse, derived-analysis history degrades to a
`requires_clickhouse_persistence` signal; the four core tools are unaffected.
`get_cache_stats` / `health_check` now report `backend` + `entries` (the old
DuckDB `db_path` / `size_mb` / `hit_rate_24h` fields are gone).

---

## Documentation

- [`docs/REGISTER.md`](./docs/REGISTER.md) — Cursor / Claude Desktop
  registration steps.
- [`docs/THREAT_MODEL.md`](./docs/THREAT_MODEL.md) — STRIDE analysis.
- [`docs/RELEASE.md`](./docs/RELEASE.md) — release / version process.
- [`CONTRIBUTING.md`](./CONTRIBUTING.md) — contributor workflow.

---

## License

MIT — see [LICENSE](./LICENSE).

---

## Responsible use

Polygon.io's data is licensed for the operator's use under their plan
terms. This server is intended for **interactive single-user research**;
do not embed it in a service that fan-outs more than your plan's published
rate limit. The free-tier ceiling is 5 req/min and the bundled token
bucket defaults to that — raise `POLYGON_RATE_LIMIT_PER_MIN` only if your
plan permits.
