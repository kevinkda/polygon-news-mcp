"""``get_ticker_news`` and ``get_market_news`` implementations.

Polygon endpoint: ``GET /v2/reference/news``

Common params:
    * ``ticker`` — optional, filters to news mentioning a specific ticker.
    * ``published_utc.gte`` / ``published_utc.lte`` — RFC 3339 timestamps.
    * ``limit`` — 1-1000, default 10 server-side.
    * ``order``, ``sort`` — ordering knobs (we always sort descending by
      ``published_utc``).

Reference: https://polygon.io/docs/stocks/get_v2_reference_news
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ..cache import Cache
from ..client import PolygonClient
from ..models import GetMarketNewsInput, GetTickerNewsInput
from ._runtime import call_with_cache

_NEWS_PATH: str = "/v2/reference/news"


async def get_ticker_news_impl(args: GetTickerNewsInput) -> dict[str, Any]:
    """Return the most recent news articles mentioning *args.ticker*."""

    async def fetch(client: PolygonClient) -> dict[str, Any]:
        cutoff = datetime.now(tz=UTC) - timedelta(days=args.since_days)
        params: dict[str, Any] = {
            "ticker": args.ticker,
            "limit": args.limit,
            "order": "desc",
            "sort": "published_utc",
            "published_utc.gte": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        raw = await client.get_json(_NEWS_PATH, params=params)
        return _normalise_news(raw, ticker=args.ticker)

    def _lookup(cache: Cache) -> dict[str, Any] | None:
        return cache.get_news(_ticker_cache_params(args))

    def _store(cache: Cache, raw: dict[str, Any]) -> None:
        cache.put_news(_ticker_cache_params(args), raw, ticker=args.ticker)

    return await call_with_cache(fetch, cache_lookup=_lookup, cache_store=_store)


async def get_market_news_impl(args: GetMarketNewsInput) -> dict[str, Any]:
    """Return the most recent market-wide news (no ticker filter)."""

    async def fetch(client: PolygonClient) -> dict[str, Any]:
        cutoff = datetime.now(tz=UTC) - timedelta(hours=args.since_hours)
        params: dict[str, Any] = {
            "limit": args.limit,
            "order": "desc",
            "sort": "published_utc",
            "published_utc.gte": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        raw = await client.get_json(_NEWS_PATH, params=params)
        return _normalise_news(raw, ticker=None)

    def _lookup(cache: Cache) -> dict[str, Any] | None:
        return cache.get_news(_market_cache_params(args))

    def _store(cache: Cache, raw: dict[str, Any]) -> None:
        cache.put_news(_market_cache_params(args), raw)

    return await call_with_cache(fetch, cache_lookup=_lookup, cache_store=_store)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_news(raw: dict[str, Any], *, ticker: str | None) -> dict[str, Any]:
    """Normalise Polygon's ``{"results":[...], "status":"OK", ...}`` envelope."""
    results_raw = raw.get("results", [])
    if not isinstance(results_raw, list):
        results_raw = []
    articles: list[dict[str, Any]] = []
    for entry in results_raw:
        if not isinstance(entry, dict):
            continue
        articles.append(_clean_article(entry))
    return {
        "ticker": ticker,
        "count": len(articles),
        "articles": articles,
        "polygon_status": raw.get("status"),
        "request_id": raw.get("request_id"),
    }


def _clean_article(entry: dict[str, Any]) -> dict[str, Any]:
    """Flatten one Polygon news article into a stable shape."""
    insights_raw = entry.get("insights")
    insights: list[dict[str, Any]] = []
    if isinstance(insights_raw, list):
        for ins in insights_raw:
            if not isinstance(ins, dict):
                continue
            insights.append(
                {
                    "ticker": ins.get("ticker"),
                    "sentiment": ins.get("sentiment"),
                    "sentiment_reasoning": ins.get("sentiment_reasoning"),
                }
            )
    return {
        "id": entry.get("id"),
        "publisher": _publisher_name(entry.get("publisher")),
        "title": entry.get("title"),
        "author": entry.get("author"),
        "published_utc": entry.get("published_utc"),
        "article_url": entry.get("article_url"),
        "tickers": entry.get("tickers") or [],
        "description": entry.get("description"),
        "keywords": entry.get("keywords") or [],
        "insights": insights,
    }


def _publisher_name(publisher: Any) -> str | None:
    if isinstance(publisher, dict):
        name = publisher.get("name")
        return str(name) if isinstance(name, str) else None
    if isinstance(publisher, str):
        return publisher
    return None


def _ticker_cache_params(args: GetTickerNewsInput) -> dict[str, Any]:
    return {
        "scope": "ticker",
        "ticker": args.ticker,
        "limit": args.limit,
        "since_days": args.since_days,
    }


def _market_cache_params(args: GetMarketNewsInput) -> dict[str, Any]:
    return {
        "scope": "market",
        "limit": args.limit,
        "since_hours": args.since_hours,
    }


__all__ = ["get_market_news_impl", "get_ticker_news_impl"]
