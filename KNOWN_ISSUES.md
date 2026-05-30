# Known Issues

Tracked known issues and limitations for `polygon-news-mcp`. For resolved
issues see [CHANGELOG.md](./CHANGELOG.md).

## Open

### `get_earnings_calendar` requires a paid Polygon tier (8-K fallback in use)

Polygon's free-tier REST surface has no dedicated earnings-calendar
endpoint with EPS / revenue estimates vs actuals; only
`/vX/reference/financials` (paid-only for full coverage) exists.
`get_earnings_calendar` is therefore **deferred** until paid-tier access
is wired up. Until then, use
`sec-edgar-mcp.get_8k_with_items(item_codes=["2.02"])` as the
earnings-detection fallback (see `docs/REGISTER.md#earnings-calendar-fallback`).

### Free-tier rate limit on burst sentiment scans

The default token-bucket limiter is tuned for Polygon's free tier
(sliding 60-second window, ~5 req/min). Burst `get_news_sentiment_aggregate`
scans across many tickers will back off (30 s exponential). The user has
permanently declined a paid upgrade, so this is an **accepted limitation**
(R3), not a defect.

## Upstream / Deferred

- **`mcp` 1.x → 2.x major bump deferred** — requires the compatibility
  checklist run manually; dependabot ignores the major bump.
- **`POLYGON_API_KEY` quota abuse risk** — the key is the only secret;
  leaking it via logs / URLs would let an attacker burn the plan quota.
  Mitigated by redaction + secret-scanning gates. See
  `docs/THREAT_MODEL.md`.

## Resolved

See [CHANGELOG.md](./CHANGELOG.md) for the full history.
