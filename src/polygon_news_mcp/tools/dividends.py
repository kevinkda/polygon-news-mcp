"""``get_dividends`` implementation.

Polygon endpoint: ``GET /v3/reference/dividends?ticker={ticker}``

Returns historical dividend payments for a ticker — ex-dividend date,
pay date, declaration date, record date, cash amount, frequency, and
dividend type (CD = Cash Dividend / regular, SC = Special Cash, etc.).

Reference: https://polygon.io/docs/stocks/get_v3_reference_dividends

Cache TTL: 24 h.  Dividends are declared at most once per quarter for
most issuers, so a daily refresh is more than enough.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final

from ..cache import Cache
from ..client import PolygonClient
from ..models import GetDividendsInput
from ._runtime import call_with_cache

_DIVIDENDS_PATH: Final[str] = "/v3/reference/dividends"

#: Translation between user-friendly synonyms and Polygon's filter values.
#: Polygon uses ``CD`` for regular cash dividends and ``SC`` for special
#: cash dividends.  ``unspecified`` maps to the empty string (Polygon's
#: documented sentinel for no-type-set rows).  ``all`` issues no filter.
_DIVIDEND_TYPE_FILTER: Final[dict[str, str | None]] = {
    "all": None,
    "regular": "CD",
    "special": "SC",
    "unspecified": "",
}

#: Mirror of ``_DIVIDEND_TYPE_FILTER`` for normalising upstream responses
#: back into the user-visible synonyms (so callers do not have to know
#: the Polygon two-letter codes).
_REVERSE_DIVIDEND_TYPE: Final[dict[str, str]] = {
    "CD": "regular",
    "SC": "special",
    "": "unspecified",
}


async def get_dividends_impl(args: GetDividendsInput) -> dict[str, Any]:
    """Return Polygon's dividend history for *args.ticker*."""

    async def fetch(client: PolygonClient) -> dict[str, Any]:
        cutoff = datetime.now(tz=UTC).date() - timedelta(days=args.since_days)
        params: dict[str, Any] = {
            "ticker": args.ticker,
            "ex_dividend_date.gte": cutoff.isoformat(),
            "order": "desc",
            "sort": "ex_dividend_date",
            "limit": 1000,
        }
        upstream_filter = _DIVIDEND_TYPE_FILTER.get(args.dividend_type)
        if upstream_filter is not None:
            params["dividend_type"] = upstream_filter
        raw = await client.get_json(_DIVIDENDS_PATH, params=params)
        return _normalise(raw, ticker=args.ticker, since_days=args.since_days)

    def _lookup(cache: Cache) -> dict[str, Any] | None:
        return cache.get_dividends(_cache_params(args))

    def _store(cache: Cache, raw: dict[str, Any]) -> None:
        cache.put_dividends(_cache_params(args), raw, ticker=args.ticker)

    return await call_with_cache(fetch, cache_lookup=_lookup, cache_store=_store)


def _normalise(raw: dict[str, Any], *, ticker: str, since_days: int) -> dict[str, Any]:
    """Flatten Polygon's ``{"results":[...], "status":"OK"}`` envelope."""
    results_raw = raw.get("results", [])
    if not isinstance(results_raw, list):
        results_raw = []
    dividends: list[dict[str, Any]] = []
    for entry in results_raw:
        if not isinstance(entry, dict):
            continue
        dividends.append(_clean_row(entry, ticker=ticker))
    return {
        "ticker": ticker,
        "since_days": since_days,
        "count": len(dividends),
        "dividends": dividends,
        "polygon_status": raw.get("status"),
        "request_id": raw.get("request_id"),
    }


def _clean_row(entry: dict[str, Any], *, ticker: str) -> dict[str, Any]:
    """Project one Polygon dividend row into a stable shape."""
    raw_type = entry.get("dividend_type")
    # Map Polygon's two-letter code to a user-friendly synonym; if
    # Polygon returns something we don't recognise, surface it raw
    # rather than dropping the row entirely.
    normalised_type = _REVERSE_DIVIDEND_TYPE.get(raw_type, raw_type) if isinstance(raw_type, str) else None
    cash_amount_raw = entry.get("cash_amount")
    cash_amount = float(cash_amount_raw) if isinstance(cash_amount_raw, (int, float)) else None
    return {
        "ticker": entry.get("ticker") or ticker,
        "ex_dividend_date": entry.get("ex_dividend_date"),
        "pay_date": entry.get("pay_date"),
        "declaration_date": entry.get("declaration_date"),
        "record_date": entry.get("record_date"),
        "cash_amount": cash_amount,
        "currency": entry.get("currency"),
        "frequency": entry.get("frequency"),
        "dividend_type": normalised_type,
    }


def _cache_params(args: GetDividendsInput) -> dict[str, Any]:
    return {
        "ticker": args.ticker,
        "since_days": args.since_days,
        "dividend_type": args.dividend_type,
    }


__all__ = ["get_dividends_impl"]
