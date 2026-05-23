"""``get_ticker_details`` implementation.

Polygon endpoint: ``GET /v3/reference/tickers/{ticker}``

Reference data — name, exchange, market, locale, share class, SIC code,
description, branding logos, etc.  Complementary to Schwab Market Data's
quote endpoint (which carries pricing but very little static metadata).

Reference: https://polygon.io/docs/stocks/get_v3_reference_tickers__ticker
"""

from __future__ import annotations

from typing import Any

from ..cache import Cache
from ..client import PolygonClient
from ..models import GetTickerDetailsInput
from ._runtime import call_with_cache


async def get_ticker_details_impl(args: GetTickerDetailsInput) -> dict[str, Any]:
    """Return Polygon's reference metadata for *args.ticker*."""

    async def fetch(client: PolygonClient) -> dict[str, Any]:
        path = f"/v3/reference/tickers/{args.ticker}"
        raw = await client.get_json(path)
        return _normalise(raw, ticker=args.ticker)

    def _lookup(cache: Cache) -> dict[str, Any] | None:
        return cache.get_ticker_details({"ticker": args.ticker})

    def _store(cache: Cache, raw: dict[str, Any]) -> None:
        cache.put_ticker_details(
            {"ticker": args.ticker},
            raw,
            ticker=args.ticker,
        )

    return await call_with_cache(fetch, cache_lookup=_lookup, cache_store=_store)


def _normalise(raw: dict[str, Any], *, ticker: str) -> dict[str, Any]:
    """Flatten the ``{"results": {...}, "status": "OK"}`` Polygon envelope."""
    results = raw.get("results")
    if not isinstance(results, dict):
        results = {}
    address = results.get("address")
    address = address if isinstance(address, dict) else {}
    branding = results.get("branding")
    branding = branding if isinstance(branding, dict) else {}
    return {
        "ticker": results.get("ticker") or ticker,
        "name": results.get("name"),
        "market": results.get("market"),
        "locale": results.get("locale"),
        "primary_exchange": results.get("primary_exchange"),
        "type": results.get("type"),
        "active": results.get("active"),
        "currency_name": results.get("currency_name"),
        "cik": results.get("cik"),
        "composite_figi": results.get("composite_figi"),
        "share_class_figi": results.get("share_class_figi"),
        "market_cap": results.get("market_cap"),
        "phone_number": results.get("phone_number"),
        "address": {
            "address1": address.get("address1"),
            "city": address.get("city"),
            "state": address.get("state"),
            "postal_code": address.get("postal_code"),
        },
        "description": results.get("description"),
        "sic_code": results.get("sic_code"),
        "sic_description": results.get("sic_description"),
        "homepage_url": results.get("homepage_url"),
        "total_employees": results.get("total_employees"),
        "list_date": results.get("list_date"),
        "share_class_shares_outstanding": results.get("share_class_shares_outstanding"),
        "weighted_shares_outstanding": results.get("weighted_shares_outstanding"),
        "round_lot": results.get("round_lot"),
        "branding": {
            "logo_url": branding.get("logo_url"),
            "icon_url": branding.get("icon_url"),
        },
        "polygon_status": raw.get("status"),
        "request_id": raw.get("request_id"),
    }


__all__ = ["get_ticker_details_impl"]
