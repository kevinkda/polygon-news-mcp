# Threat Model — `polygon-news-mcp`

## Summary

`polygon-news-mcp` is a read-only MCP server that issues plain HTTPS GETs
against Polygon.io.  Compared to `schwab-marketdata-mcp` the attack
surface is small — there is no OAuth, no refresh token, no order-placement
path, and no customer-account data — but unlike `sec-edgar-mcp` we do
carry a long-lived bearer-style API key.

The remaining concerns are:

1. Operator-supplied **`POLYGON_API_KEY`** is the only secret.  Leaking it
   via logs, exception text, or accidental URL echoes would let an
   attacker burn through the operator's plan quota.
2. **Plan rate limiting** — exceeding the per-minute budget gets the
   key throttled (or temporarily blocked) by Polygon.
3. **Bulk redistribution** — Polygon's terms of service restrict resale
   of their data; this server is intended for **interactive single-user
   research**.

## STRIDE

### Spoofing

- **Threat:** an attacker spoofs the Polygon TLS endpoint and serves
  forged news / sentiment data to influence agent decisions.
- **Mitigation:** httpx defaults to `verify=True`; we never disable TLS
  verification.  Operators must keep their CA bundle current (managed by
  the OS / `certifi`).

### Tampering

- **Threat:** a man-in-the-middle alters response bodies.
- **Mitigation:** TLS as above.  Cache writes are local-process only and
  protected by DuckDB's own file lock; corruption is detected and the
  database is quarantined (`cache.duckdb.corrupt-<ts>`).

### Repudiation

- **Threat:** the operator denies running a query.
- **Mitigation:** every tool call is logged to
  `${XDG_STATE_HOME}/polygon-news-mcp/logs/server.log` (rotated, 5 × 10
  MiB by default).  No PII is logged at the default WARNING level.

### Information disclosure

- **Threat:** operator's `POLYGON_API_KEY` leaks via exception text or
  logs.
- **Mitigation:**
  - The key is sent only as the `Authorization: Bearer ...` header,
    **never** as a `?apiKey=...` URL query string.  This means request
    URLs surfaced in logs / exception text contain no secret material.
  - Every custom exception calls `redact_secret()` in its constructor;
    structured fields are typed (`field: str`, etc.) so a raw `repr(exc)`
    cannot accidentally include an Authorization header echo, and any
    `?apiKey=` substring (e.g. from an operator pasting a Polygon-style
    URL into a hint string) is redacted defensively.
  - The key value is **never** included in `health_check` output —
    only a boolean `api_key_configured` flag.
- **Threat:** news / filings bodies stored in DuckDB cache are
  world-readable.
- **Mitigation:** parent dir created with `0o700`, DB file `chmod 0o600`
  on POSIX (best-effort no-op on Windows; relying on
  `%LOCALAPPDATA%` ACL inheritance).

### Denial of service

- **Threat:** agent fan-out exceeds Polygon's per-minute ceiling and gets
  the key throttled / temporarily blocked.
- **Mitigation:** in-process token-bucket (sliding 60-second window),
  default 5 req/min (free-tier safe), hard cap 1000 req/min.  429
  responses are retried with `Retry-After`.
- **Threat:** large news payloads exhaust agent memory or MCP frame
  budget.
- **Mitigation:** Polygon's `/v2/reference/news` caps `limit` at 1000
  per page; we forward the request unchanged and let the agent paginate
  if needed.

### Elevation of privilege

- **Threat:** server escalates beyond read-only.
- **Mitigation:** the server only issues HTTP GETs.  Polygon does not
  expose a write API on any endpoint we use.

## Out of scope

- **Bulk re-publication** of Polygon data is **explicitly not a supported
  use case**.  Operators who do so are responsible for compliance with
  Polygon's terms of service.
- **Trading**: this server is data-only.  Order placement is delegated to
  separate broker MCPs (Schwab, etc.) — never wire a trading tool into
  this codebase.

## Cache failure modes

| Failure | Behavior |
| --- | --- |
| DB file does not exist | created on demand under `XDG_STATE_HOME` |
| DB file is corrupt | renamed `cache.duckdb.corrupt-<ts>`; fresh DB created |
| Disk full / read-only fs | every method logs WARNING and returns `None` |
| Concurrent process opens | DuckDB intra-process lock serialises writes |

In every failure case the cache **degrades to a no-op**; the live Polygon
API path is still followed, with the rate limiter honoured.
