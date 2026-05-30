# Security

`polygon-news-mcp` is a read-only MCP server that issues plain HTTPS GETs
against Polygon.io (news, sentiment, ticker details, dividends, filings
index). It has **no OAuth, no refresh token, no order-placement path, and
no customer-account data** — but unlike `sec-edgar-mcp` it carries one
long-lived bearer-style API key.

For the full STRIDE catalogue and trust-boundary detail, see
[`docs/THREAT_MODEL.md`](./THREAT_MODEL.md). This document is the short
operator-facing summary.

## Threat model (summary)

The single asset to defend is `POLYGON_API_KEY`. The main threats:

- **API key leak** → leaking it via logs, exception text, or accidental
  URL echoes would let an attacker burn the operator's plan quota.
  Mitigated by redaction on error / URL paths; never logged.
- **Plan rate-limit abuse** → exceeding the per-minute budget gets the key
  throttled or temporarily blocked by Polygon. A token-bucket limiter
  (sliding 60-second window, default ~5 req/min) plus 30 s exponential
  backoff keeps within the free tier.
- **TLS spoofing / MITM** → httpx `verify=True` always; never disabled.
  Cache writes are local-process only, protected by DuckDB's file lock;
  corruption is detected and the database is quarantined.
- **Bulk redistribution** → Polygon's ToS restricts resale of their data;
  this server is for interactive single-user research only.

## Secret handling

- `POLYGON_API_KEY` is sourced from `.env` (git-ignored); it is the only
  secret.
- The key is never logged; error paths and URL echoes redact it.
- Pre-commit runs `detect-secrets`; CI runs `gitleaks-action@v2` on every
  push and PR to block accidental key commits.

## Read/write boundary

This MCP is **read-only by design**: it performs HTTPS GET requests only
against Polygon.io; there is no write / mutation path of any kind.

## Reporting security issues

Open a private security advisory on GitHub:
<https://github.com/kevinkda/polygon-news-mcp/security/advisories>.
Do **not** open a public issue with the details.
