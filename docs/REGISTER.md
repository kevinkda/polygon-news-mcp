# Register `polygon-news-mcp` with your MCP host

This guide shows how to wire the server up inside Cursor and Claude Desktop.

> **Prereq:** finish the bootstrap in the [Quick Start](../README.md#quick-start)
> first — `uv sync --extra dev`, copy `.env.example` to `.env`, and set
> `POLYGON_API_KEY` to your Polygon.io key.  Without that env var the
> server refuses to issue any HTTP request.

---

## Cursor (`mcp.json`)

Open Cursor → Settings → MCP → "Add New MCP Server", or edit
`~/.cursor/mcp.json` directly:

```json
{
  "mcpServers": {
    "polygon-news-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "/opt/workspace/code/kevinkda/polygon-news-mcp",
        "run",
        "polygon-news-mcp"
      ],
      "envFile": "/opt/workspace/code/kevinkda/polygon-news-mcp/.env"
    }
  }
}
```

- Replace the `--directory` path with wherever you cloned the repo.
- `envFile` points at the `.env` you populated; Cursor reads it before
  spawning the server so `POLYGON_API_KEY` reaches the process.

Restart Cursor.  In the agent panel you should see 8 tools come online:

```text
get_ticker_news
get_market_news
get_ticker_details
list_sec_filings_index
get_news_sentiment_aggregate
get_dividends
health_check
get_server_info
```

---

## Claude Desktop (`claude_desktop_config.json`)

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "polygon-news-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/polygon-news-mcp",
        "run",
        "polygon-news-mcp"
      ],
      "env": {
        "POLYGON_API_KEY": "<your-polygon-api-key>"
      }
    }
  }
}
```

Claude Desktop does not support `envFile` so we inline the env var.  Quit
and restart Claude.

---

## Verifying the connection

Once registered, ask the agent:

> Run health_check on polygon-news-mcp

Expected response (the agent will surface this from the tool):

```json
{
  "server_version": "0.1.0",
  "api_key_configured": true,
  "rate_limit_per_min": 5,
  "rate_limit_hard_cap_per_min": 1000,
  "cache_enabled": true,
  "cache_size_mb": 0.0,
  "platform_supported": true
}
```

If `api_key_configured` is `false`, the server is running but
`POLYGON_API_KEY` is not reaching the process.  Re-check `envFile`
or `env` in the host config.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Tools don't show up | wrong `--directory` path | absolute path required |
| `PolygonConfigurationError` on every call | missing `POLYGON_API_KEY` | populate `.env`; restart host |
| `PolygonAuthError(status=401)` | bad / revoked key | regenerate at <https://polygon.io/dashboard/api-keys> |
| `PolygonAuthError(status=403)` | endpoint not in your plan | upgrade your Polygon plan, or stop using that tool |
| `PolygonRateLimitError` | exceeded plan rate limit | lower `POLYGON_RATE_LIMIT_PER_MIN`, upgrade plan |
| `PolygonNotFoundError: ticker:XYZ` | ticker not in Polygon's catalog | check spelling / case |

---

## Earnings calendar fallback

`get_earnings_calendar` is **deferred to v0.3** pending Polygon paid-tier
validation.  Polygon's free-tier REST surface does not include a
dedicated earnings-calendar endpoint with EPS / revenue
estimates-vs-actuals; only `/vX/reference/financials` (filed financial
statements) is available, and that endpoint requires a paid plan
(Starter $29+/mo) for full historical coverage.

Until a paid Polygon tier is wired up, use the SEC EDGAR fallback —
8-K Item 2.02 ("Results of Operations and Financial Condition") is the
canonical earnings-release form, and `sec-edgar-mcp` can list and read
those filings directly:

```python
# Detect every earnings 8-K filed in the last 30 days for AAPL.
sec_edgar_mcp.get_8k_with_items(
    ticker="AAPL",
    item_codes=["2.02"],
    since_days=30,
)
```

The SEC EDGAR feed lags Polygon's real-time earnings calendar by a few
minutes (companies file the 8-K shortly *after* the press release), so
this fallback is suited for *post-announcement* analysis (parsing the
press-release exhibit, computing the surprise vs the prior consensus
once the consensus is known) rather than *pre-announcement*
calendar-driven scans.  For pre-announcement scans, upgrade Polygon to
a tier that includes `/vX/reference/financials` and re-open the v0.3
ticket.
