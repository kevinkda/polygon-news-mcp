"""Unit tests for the v0.2 (Sprint C) tools: dividends + news_sentiment_aggregate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import polygon_news_mcp.tools._runtime as runtime_mod
from polygon_news_mcp.errors import (
    PolygonAuthError,
    PolygonRateLimitError,
    PolygonTransientError,
)
from polygon_news_mcp.models import (
    GetDividendsInput,
    GetNewsSentimentAggregateInput,
)
from polygon_news_mcp.tools.dividends import get_dividends_impl
from polygon_news_mcp.tools.sentiment import get_news_sentiment_aggregate_impl
from tests.conftest import FIXTURE_DIR, FakeRoute


def _dividends_routes(fixture_dir: Path) -> list[FakeRoute]:
    body = json.loads((fixture_dir / "dividends_aapl.json").read_text(encoding="utf-8"))
    return [FakeRoute("/v3/reference/dividends", json_body=body)]


def _sentiment_routes(fixture_dir: Path) -> list[FakeRoute]:
    body = json.loads((fixture_dir / "news_msft.json").read_text(encoding="utf-8"))
    return [FakeRoute("/v2/reference/news?ticker=MSFT", json_body=body)]


# ---------------------------------------------------------------------------
# get_dividends
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_dividends_normal(make_polygon_client) -> None:
    client = make_polygon_client(_dividends_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    out = await get_dividends_impl(
        GetDividendsInput(ticker="AAPL", since_days=365, dividend_type="all"),
    )
    assert out["ticker"] == "AAPL"
    assert out["count"] == 4
    assert out["dividends"][0]["ex_dividend_date"] == "2026-05-09"
    assert out["dividends"][0]["dividend_type"] == "regular"
    # Special and unspecified types translate to user-friendly synonyms.
    types = [row["dividend_type"] for row in out["dividends"]]
    assert "special" in types
    assert "unspecified" in types
    assert out["_cache_status"] == "miss"


@pytest.mark.asyncio
async def test_get_dividends_cache_hit(make_polygon_client) -> None:
    client = make_polygon_client(_dividends_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    a = await get_dividends_impl(GetDividendsInput(ticker="AAPL"))
    assert a["_cache_status"] == "miss"
    b = await get_dividends_impl(GetDividendsInput(ticker="AAPL"))
    assert b["_cache_status"] == "hit"


@pytest.mark.asyncio
async def test_get_dividends_empty_results(make_polygon_client) -> None:
    client = make_polygon_client(
        [FakeRoute("/v3/reference/dividends", json_body={"status": "OK", "results": []})],
    )
    await runtime_mod.set_client_for_tests(client)
    out = await get_dividends_impl(GetDividendsInput(ticker="ZZZZ"))
    assert out["count"] == 0
    assert out["dividends"] == []


@pytest.mark.asyncio
async def test_get_dividends_garbage_results(make_polygon_client) -> None:
    """Non-list ``results`` → empty list; non-dict rows skipped."""
    client = make_polygon_client(
        [
            FakeRoute(
                "/v3/reference/dividends",
                json_body={"status": "OK", "results": [42, "garbage", {"ex_dividend_date": "2025-05-01"}]},
            ),
        ],
    )
    await runtime_mod.set_client_for_tests(client)
    out = await get_dividends_impl(GetDividendsInput(ticker="AAPL"))
    assert out["count"] == 1
    assert out["dividends"][0]["ex_dividend_date"] == "2025-05-01"


@pytest.mark.asyncio
async def test_get_dividends_garbage_results_not_a_list(make_polygon_client) -> None:
    client = make_polygon_client(
        [FakeRoute("/v3/reference/dividends", json_body={"status": "OK", "results": 7})],
    )
    await runtime_mod.set_client_for_tests(client)
    out = await get_dividends_impl(GetDividendsInput(ticker="AAPL"))
    assert out["count"] == 0


@pytest.mark.asyncio
async def test_get_dividends_auth_error(make_polygon_client) -> None:
    client = make_polygon_client(
        [FakeRoute("/v3/reference/dividends", status_code=401, json_body={})],
    )
    await runtime_mod.set_client_for_tests(client)
    with pytest.raises(PolygonAuthError):
        await get_dividends_impl(GetDividendsInput(ticker="AAPL"))


@pytest.mark.asyncio
async def test_get_dividends_rate_limit(make_polygon_client) -> None:
    client = make_polygon_client(
        [FakeRoute("/v3/reference/dividends", status_code=429, json_body={}, headers={"Retry-After": "0"})],
    )
    await runtime_mod.set_client_for_tests(client)
    with pytest.raises(PolygonRateLimitError):
        await get_dividends_impl(GetDividendsInput(ticker="AAPL"))


@pytest.mark.asyncio
async def test_get_dividends_5xx_retry_exhausted(make_polygon_client) -> None:
    client = make_polygon_client(
        [FakeRoute("/v3/reference/dividends", status_code=503, json_body={})],
    )
    await runtime_mod.set_client_for_tests(client)
    with pytest.raises(PolygonTransientError):
        await get_dividends_impl(GetDividendsInput(ticker="AAPL"))


@pytest.mark.asyncio
async def test_get_dividends_filter_translation(make_polygon_client) -> None:
    """``regular`` should send Polygon's two-letter ``CD`` filter on the wire."""
    client = make_polygon_client(_dividends_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    out = await get_dividends_impl(
        GetDividendsInput(ticker="AAPL", dividend_type="regular"),
    )
    assert out["count"] == 4
    # Inspect the captured outbound URL to confirm the filter was applied.
    transport = client._client._transport  # type: ignore[attr-defined]
    assert any("dividend_type=CD" in u for u in transport.call_log)


@pytest.mark.asyncio
async def test_get_dividends_filter_special_translation(make_polygon_client) -> None:
    client = make_polygon_client(_dividends_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    await get_dividends_impl(
        GetDividendsInput(ticker="AAPL", dividend_type="special"),
    )
    transport = client._client._transport  # type: ignore[attr-defined]
    assert any("dividend_type=SC" in u for u in transport.call_log)


@pytest.mark.asyncio
async def test_get_dividends_unknown_upstream_type_passes_through(make_polygon_client) -> None:
    """If Polygon returns a code we don't recognise, surface it raw."""
    client = make_polygon_client(
        [
            FakeRoute(
                "/v3/reference/dividends",
                json_body={
                    "status": "OK",
                    "results": [
                        {
                            "ticker": "AAPL",
                            "ex_dividend_date": "2026-05-09",
                            "cash_amount": 0.25,
                            "dividend_type": "ZZ",
                        },
                    ],
                },
            ),
        ],
    )
    await runtime_mod.set_client_for_tests(client)
    out = await get_dividends_impl(GetDividendsInput(ticker="AAPL"))
    assert out["dividends"][0]["dividend_type"] == "ZZ"


@pytest.mark.asyncio
async def test_get_dividends_non_numeric_cash_amount(make_polygon_client) -> None:
    client = make_polygon_client(
        [
            FakeRoute(
                "/v3/reference/dividends",
                json_body={
                    "status": "OK",
                    "results": [
                        {
                            "ticker": "AAPL",
                            "ex_dividend_date": "2026-05-09",
                            "cash_amount": None,
                        },
                    ],
                },
            ),
        ],
    )
    await runtime_mod.set_client_for_tests(client)
    out = await get_dividends_impl(GetDividendsInput(ticker="AAPL"))
    assert out["dividends"][0]["cash_amount"] is None


@pytest.mark.asyncio
async def test_get_dividends_since_days_max_boundary(make_polygon_client) -> None:
    """``since_days`` accepts up to 3650 (≈ 10 y); above that → ValidationError."""
    client = make_polygon_client(_dividends_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    out = await get_dividends_impl(
        GetDividendsInput(ticker="AAPL", since_days=3650),
    )
    assert out["since_days"] == 3650


# ---------------------------------------------------------------------------
# get_news_sentiment_aggregate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_news_sentiment_aggregate_normal(make_polygon_client) -> None:
    client = make_polygon_client(_sentiment_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    out = await get_news_sentiment_aggregate_impl(
        GetNewsSentimentAggregateInput(ticker="MSFT", window_days=7),
    )
    assert out["ticker"] == "MSFT"
    assert out["window_days"] == 7
    # 6 articles total in fixture; one has no insights → falls out of dist.
    assert out["total_articles"] == 5
    assert out["sentiment_distribution"]["positive"] == 3
    assert out["sentiment_distribution"]["neutral"] == 1
    assert out["sentiment_distribution"]["negative"] == 1
    # Score = (3 - 1) / 5 = 0.4
    assert out["sentiment_score"] == 0.4


@pytest.mark.asyncio
async def test_get_news_sentiment_aggregate_top_publishers(make_polygon_client) -> None:
    client = make_polygon_client(_sentiment_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    out = await get_news_sentiment_aggregate_impl(
        GetNewsSentimentAggregateInput(ticker="MSFT", window_days=7),
    )
    publisher_names = [p["publisher"] for p in out["top_publishers"]]
    assert "Reuters" in publisher_names
    # Reuters appears twice in the fixture, the most of any publisher.
    reuters_entry = next(p for p in out["top_publishers"] if p["publisher"] == "Reuters")
    assert reuters_entry["count"] == 2
    assert len(out["top_publishers"]) <= 5


@pytest.mark.asyncio
async def test_get_news_sentiment_aggregate_significant_articles(make_polygon_client) -> None:
    client = make_polygon_client(_sentiment_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    out = await get_news_sentiment_aggregate_impl(
        GetNewsSentimentAggregateInput(ticker="MSFT", window_days=7),
    )
    sig = out["most_significant_articles"]
    assert 1 <= len(sig) <= 5
    # Every significant article carries a sentiment label.
    assert all(a["sentiment"] in {"positive", "neutral", "negative"} for a in sig)
    # The CNBC antitrust article is the only "negative" one and CNBC has
    # only 1 article, so it should rank highly.
    assert any("antitrust" in (a["title"] or "").lower() for a in sig)


@pytest.mark.asyncio
async def test_get_news_sentiment_aggregate_empty(make_polygon_client) -> None:
    client = make_polygon_client(
        [FakeRoute("/v2/reference/news?ticker=MSFT", json_body={"status": "OK", "results": []})],
    )
    await runtime_mod.set_client_for_tests(client)
    out = await get_news_sentiment_aggregate_impl(
        GetNewsSentimentAggregateInput(ticker="MSFT"),
    )
    assert out["total_articles"] == 0
    assert out["sentiment_distribution"] == {"positive": 0, "neutral": 0, "negative": 0}
    assert out["sentiment_score"] == 0.0
    assert out["top_publishers"] == []
    assert out["most_significant_articles"] == []


@pytest.mark.asyncio
async def test_get_news_sentiment_aggregate_window_30d(make_polygon_client) -> None:
    """Different window_days hash to a different cache key (separate miss)."""
    client = make_polygon_client(_sentiment_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    a = await get_news_sentiment_aggregate_impl(
        GetNewsSentimentAggregateInput(ticker="MSFT", window_days=7),
    )
    assert a["_cache_status"] == "miss"
    # Same ticker, different window → news cache miss again.
    b = await get_news_sentiment_aggregate_impl(
        GetNewsSentimentAggregateInput(ticker="MSFT", window_days=30),
    )
    assert b["_cache_status"] == "miss"


@pytest.mark.asyncio
async def test_get_news_sentiment_aggregate_cache_hit_via_news(make_polygon_client) -> None:
    """A second identical call should be served from the news cache."""
    client = make_polygon_client(_sentiment_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    a = await get_news_sentiment_aggregate_impl(
        GetNewsSentimentAggregateInput(ticker="MSFT", window_days=7),
    )
    assert a["_cache_status"] == "miss"
    b = await get_news_sentiment_aggregate_impl(
        GetNewsSentimentAggregateInput(ticker="MSFT", window_days=7),
    )
    assert b["_cache_status"] == "hit"


@pytest.mark.asyncio
async def test_get_news_sentiment_aggregate_auth_error(make_polygon_client) -> None:
    client = make_polygon_client(
        [FakeRoute("/v2/reference/news", status_code=403, json_body={})],
    )
    await runtime_mod.set_client_for_tests(client)
    with pytest.raises(PolygonAuthError):
        await get_news_sentiment_aggregate_impl(
            GetNewsSentimentAggregateInput(ticker="MSFT"),
        )


@pytest.mark.asyncio
async def test_get_news_sentiment_aggregate_5xx(make_polygon_client) -> None:
    client = make_polygon_client(
        [FakeRoute("/v2/reference/news", status_code=503, json_body={})],
    )
    await runtime_mod.set_client_for_tests(client)
    with pytest.raises(PolygonTransientError):
        await get_news_sentiment_aggregate_impl(
            GetNewsSentimentAggregateInput(ticker="MSFT"),
        )


@pytest.mark.asyncio
async def test_get_news_sentiment_aggregate_falls_back_to_first_insight(
    make_polygon_client,
) -> None:
    """If no insight matches the queried ticker, use the first one found."""
    fake_body = {
        "status": "OK",
        "results": [
            {
                "id": "x1",
                "publisher": {"name": "Reuters"},
                "title": "AAPL article tagging MSFT only",
                "published_utc": "2026-05-23T16:00:00Z",
                "tickers": ["AAPL"],
                # No insight for AAPL; only insight is for MSFT (positive).
                # The aggregator should fall back to the first insight.
                "insights": [
                    {"ticker": "MSFT", "sentiment": "positive"},
                ],
            },
        ],
    }
    client = make_polygon_client(
        [FakeRoute("/v2/reference/news?ticker=AAPL", json_body=fake_body)],
    )
    await runtime_mod.set_client_for_tests(client)
    out = await get_news_sentiment_aggregate_impl(
        GetNewsSentimentAggregateInput(ticker="AAPL"),
    )
    assert out["sentiment_distribution"]["positive"] == 1


@pytest.mark.asyncio
async def test_get_news_sentiment_aggregate_skips_garbage_insights(
    make_polygon_client,
) -> None:
    fake_body = {
        "status": "OK",
        "results": [
            {
                "id": "x1",
                "publisher": {"name": "Reuters"},
                "title": "Garbage insights",
                "published_utc": "2026-05-23T16:00:00Z",
                "tickers": ["AAPL"],
                "insights": ["not-a-dict", {"ticker": "AAPL", "sentiment": 42}],
            },
            {
                "id": "x2",
                "publisher": "",
                "title": "Empty publisher",
                "published_utc": "2026-05-22T16:00:00Z",
                "tickers": ["AAPL"],
                "insights": [],
            },
            {
                "id": "x3",
                "publisher": None,
                "title": "Null publisher",
                "published_utc": "2026-05-21T16:00:00Z",
                "tickers": ["AAPL"],
                "insights": "not-a-list",
            },
        ],
    }
    client = make_polygon_client(
        [FakeRoute("/v2/reference/news?ticker=AAPL", json_body=fake_body)],
    )
    await runtime_mod.set_client_for_tests(client)
    out = await get_news_sentiment_aggregate_impl(
        GetNewsSentimentAggregateInput(ticker="AAPL"),
    )
    # All three articles produce no usable sentiment.
    assert out["total_articles"] == 0
    # ``top_publishers`` is independent of sentiment — Reuters is the
    # only non-empty publisher in the fixture.
    assert out["top_publishers"] == [{"publisher": "Reuters", "count": 1}]
    # No usable sentiments → no significant articles.
    assert out["most_significant_articles"] == []


@pytest.mark.asyncio
async def test_get_news_sentiment_aggregate_window_1d(make_polygon_client) -> None:
    client = make_polygon_client(_sentiment_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    out = await get_news_sentiment_aggregate_impl(
        GetNewsSentimentAggregateInput(ticker="MSFT", window_days=1),
    )
    assert out["window_days"] == 1
    assert out["total_articles"] >= 0


@pytest.mark.asyncio
async def test_get_news_sentiment_aggregate_score_bounds() -> None:
    """Cover the helpers directly to lock in the math."""
    from polygon_news_mcp.tools.sentiment import _sentiment_score

    assert _sentiment_score({"positive": 5, "neutral": 0, "negative": 0}, total=5) == 1.0
    assert _sentiment_score({"positive": 0, "neutral": 0, "negative": 5}, total=5) == -1.0
    assert _sentiment_score({"positive": 1, "neutral": 1, "negative": 1}, total=3) == 0.0
    # Defensive zero-total path.
    assert _sentiment_score({"positive": 0, "neutral": 0, "negative": 0}, total=0) == 0.0
