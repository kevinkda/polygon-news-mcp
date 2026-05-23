"""``list_sec_filings_index`` implementation.

Polygon endpoint: ``GET /vX/reference/sec/filings``

Polygon publishes its own SEC filings index with **sentiment** and
**category** annotations that the raw SEC EDGAR feed does not carry —
this is the value-add over ``sec-edgar-mcp``.

Reference: https://polygon.io/docs/stocks/get_vx_reference_sec_filings
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ..cache import Cache
from ..client import PolygonClient
from ..models import ListSecFilingsIndexInput
from ._runtime import call_with_cache

_FILINGS_PATH: str = "/vX/reference/sec/filings"


async def list_sec_filings_index_impl(args: ListSecFilingsIndexInput) -> dict[str, Any]:
    """Return Polygon's SEC filings index entries for *args.ticker*."""

    async def fetch(client: PolygonClient) -> dict[str, Any]:
        cutoff = datetime.now(tz=UTC).date() - timedelta(days=args.since_days)
        params: dict[str, Any] = {
            "ticker": args.ticker,
            "filed_date.gte": cutoff.isoformat(),
            "order": "desc",
            "sort": "filed_date",
            "limit": 100,
        }
        raw = await client.get_json(_FILINGS_PATH, params=params)
        return _normalise(raw, ticker=args.ticker, since_days=args.since_days)

    def _lookup(cache: Cache) -> dict[str, Any] | None:
        return cache.get_filings_index(_cache_params(args))

    def _store(cache: Cache, raw: dict[str, Any]) -> None:
        cache.put_filings_index(_cache_params(args), raw, ticker=args.ticker)

    return await call_with_cache(fetch, cache_lookup=_lookup, cache_store=_store)


def _normalise(raw: dict[str, Any], *, ticker: str, since_days: int) -> dict[str, Any]:
    """Flatten Polygon's filings index payload."""
    results_raw = raw.get("results", [])
    if not isinstance(results_raw, list):
        results_raw = []
    filings: list[dict[str, Any]] = []
    for entry in results_raw:
        if not isinstance(entry, dict):
            continue
        filings.append(
            {
                "accession_number": entry.get("accession_number"),
                "form_type": entry.get("form_type") or entry.get("type"),
                "filed_date": entry.get("filed_date"),
                "period_of_report": entry.get("period_of_report"),
                "company_name": entry.get("company_name"),
                "ticker": entry.get("ticker") or ticker,
                "cik": entry.get("cik"),
                "sentiment": entry.get("sentiment"),
                "category": entry.get("category"),
                "filing_url": entry.get("filing_url"),
                "primary_document_url": entry.get("primary_document_url"),
            }
        )
    return {
        "ticker": ticker,
        "since_days": since_days,
        "count": len(filings),
        "filings": filings,
        "polygon_status": raw.get("status"),
        "request_id": raw.get("request_id"),
        "note": (
            "Polygon's SEC filings index includes optional 'sentiment' "
            "and 'category' fields that the raw SEC EDGAR feed does not. "
            "Use sec-edgar-mcp.get_company_filings for the canonical SEC "
            "feed and sec-edgar-mcp.get_filing_text for the body."
        ),
    }


def _cache_params(args: ListSecFilingsIndexInput) -> dict[str, Any]:
    return {
        "ticker": args.ticker,
        "since_days": args.since_days,
    }


__all__ = ["list_sec_filings_index_impl"]
