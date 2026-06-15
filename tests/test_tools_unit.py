"""Unit tests for the 4 business tools + 2 meta tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import polygon_news_mcp.tools._runtime as runtime_mod
from polygon_news_mcp.errors import PolygonNotFoundError
from polygon_news_mcp.models import (
    GetMarketNewsInput,
    GetTickerDetailsInput,
    GetTickerNewsInput,
    ListSecFilingsIndexInput,
)
from polygon_news_mcp.tools.details import get_ticker_details_impl
from polygon_news_mcp.tools.filings import list_sec_filings_index_impl
from polygon_news_mcp.tools.meta import (
    get_cache_stats_impl,
    get_server_info_impl,
    health_check_impl,
)
from polygon_news_mcp.tools.news import (
    get_market_news_impl,
    get_ticker_news_impl,
)
from tests.conftest import FIXTURE_DIR, FakeRoute


def _seed_routes(fixture_dir: Path) -> list[FakeRoute]:
    """Build a complete route table that satisfies all 4 business tools."""
    news_aapl = json.loads((fixture_dir / "news_aapl.json").read_text(encoding="utf-8"))
    news_market = json.loads((fixture_dir / "news_market.json").read_text(encoding="utf-8"))
    details_aapl = json.loads((fixture_dir / "ticker_details_aapl.json").read_text(encoding="utf-8"))
    filings_aapl = json.loads((fixture_dir / "filings_aapl.json").read_text(encoding="utf-8"))
    return [
        FakeRoute("/v2/reference/news?ticker=AAPL", json_body=news_aapl),
        FakeRoute("/v2/reference/news", json_body=news_market),
        FakeRoute("/v3/reference/tickers/AAPL", json_body=details_aapl),
        FakeRoute("/vX/reference/sec/filings", json_body=filings_aapl),
    ]


# ---------------------------------------------------------------------------
# get_ticker_news
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_ticker_news_normal(make_polygon_client) -> None:
    client = make_polygon_client(_seed_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    out = await get_ticker_news_impl(
        GetTickerNewsInput(ticker="AAPL", limit=10, since_days=7),
    )
    assert out["ticker"] == "AAPL"
    assert out["count"] == 2
    assert out["articles"][0]["title"] == "Apple unveils new iPhone with AI features"
    assert out["articles"][0]["publisher"] == "Reuters"
    assert out["articles"][0]["insights"][0]["sentiment"] == "positive"


@pytest.mark.asyncio
async def test_get_ticker_news_cache_hit(make_polygon_client) -> None:
    client = make_polygon_client(_seed_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    a = await get_ticker_news_impl(GetTickerNewsInput(ticker="AAPL"))
    assert a["_cache_status"] == "miss"
    b = await get_ticker_news_impl(GetTickerNewsInput(ticker="AAPL"))
    assert b["_cache_status"] == "hit"


@pytest.mark.asyncio
async def test_get_ticker_news_cache_bypass(make_polygon_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_polygon_client(_seed_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    a = await get_ticker_news_impl(GetTickerNewsInput(ticker="AAPL"))
    assert a["_cache_status"] == "miss"
    monkeypatch.setenv("POLYGON_CACHE_BYPASS", "1")
    b = await get_ticker_news_impl(GetTickerNewsInput(ticker="AAPL"))
    assert b["_cache_status"] == "bypass"


@pytest.mark.asyncio
async def test_get_ticker_news_empty_results(make_polygon_client) -> None:
    client = make_polygon_client(
        [FakeRoute("/v2/reference/news", json_body={"status": "OK", "results": []})],
    )
    await runtime_mod.set_client_for_tests(client)
    out = await get_ticker_news_impl(GetTickerNewsInput(ticker="ZZZZ"))
    assert out["count"] == 0
    assert out["articles"] == []


@pytest.mark.asyncio
async def test_get_ticker_news_handles_garbage_results(make_polygon_client) -> None:
    """If Polygon returns a non-list ``results``, normalise to empty list."""
    client = make_polygon_client(
        [FakeRoute("/v2/reference/news", json_body={"status": "OK", "results": "garbage"})],
    )
    await runtime_mod.set_client_for_tests(client)
    out = await get_ticker_news_impl(GetTickerNewsInput(ticker="AAPL"))
    assert out["count"] == 0


@pytest.mark.asyncio
async def test_get_ticker_news_publisher_string_form(make_polygon_client) -> None:
    """Some fixture rows have publisher as a bare string (rather than dict)."""
    client = make_polygon_client(_seed_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    out = await get_market_news_impl(GetMarketNewsInput())
    publishers = [a["publisher"] for a in out["articles"]]
    # news_market.json includes a string-valued publisher ("Barron's").
    assert "Barron's" in publishers


# ---------------------------------------------------------------------------
# get_market_news
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_market_news_normal(make_polygon_client) -> None:
    client = make_polygon_client(_seed_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    out = await get_market_news_impl(GetMarketNewsInput(limit=20, since_hours=24))
    assert out["ticker"] is None
    assert out["count"] == 3
    assert any("Fed" in a["title"] for a in out["articles"])


@pytest.mark.asyncio
async def test_get_market_news_5xx(make_polygon_client) -> None:
    from polygon_news_mcp.errors import PolygonTransientError

    client = make_polygon_client(
        [FakeRoute("/v2/reference/news", status_code=503, json_body={})],
    )
    await runtime_mod.set_client_for_tests(client)
    with pytest.raises(PolygonTransientError):
        await get_market_news_impl(GetMarketNewsInput())


# ---------------------------------------------------------------------------
# get_ticker_details
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_ticker_details_normal(make_polygon_client) -> None:
    client = make_polygon_client(_seed_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    out = await get_ticker_details_impl(GetTickerDetailsInput(ticker="AAPL"))
    assert out["ticker"] == "AAPL"
    assert out["name"] == "Apple Inc."
    assert out["primary_exchange"] == "XNAS"
    assert out["address"]["city"] == "CUPERTINO"
    assert out["branding"]["logo_url"] is not None


@pytest.mark.asyncio
async def test_get_ticker_details_404(make_polygon_client) -> None:
    client = make_polygon_client(
        [FakeRoute("/v3/reference/tickers/", status_code=404, json_body={})],
    )
    await runtime_mod.set_client_for_tests(client)
    with pytest.raises(PolygonNotFoundError):
        await get_ticker_details_impl(GetTickerDetailsInput(ticker="ZZZZ"))


@pytest.mark.asyncio
async def test_get_ticker_details_empty_results(make_polygon_client) -> None:
    client = make_polygon_client(
        [FakeRoute("/v3/reference/tickers/", json_body={"status": "OK", "results": None})],
    )
    await runtime_mod.set_client_for_tests(client)
    out = await get_ticker_details_impl(GetTickerDetailsInput(ticker="AAPL"))
    assert out["ticker"] == "AAPL"
    assert out["name"] is None


# ---------------------------------------------------------------------------
# list_sec_filings_index
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sec_filings_index_normal(make_polygon_client) -> None:
    client = make_polygon_client(_seed_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    out = await list_sec_filings_index_impl(
        ListSecFilingsIndexInput(ticker="AAPL", since_days=90),
    )
    assert out["count"] == 2
    assert out["filings"][0]["sentiment"] == "positive"
    assert out["filings"][0]["form_type"] == "10-Q"


@pytest.mark.asyncio
async def test_list_sec_filings_index_garbage_results(make_polygon_client) -> None:
    client = make_polygon_client(
        [FakeRoute("/vX/reference/sec/filings", json_body={"status": "OK", "results": 42})],
    )
    await runtime_mod.set_client_for_tests(client)
    out = await list_sec_filings_index_impl(ListSecFilingsIndexInput(ticker="AAPL"))
    assert out["count"] == 0


# ---------------------------------------------------------------------------
# meta tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_check_offline_safe() -> None:
    out = await health_check_impl()
    assert "api_key_configured" in out
    assert "cache_enabled" in out
    assert out["platform_supported"] is True
    assert out["rate_limit_hard_cap_per_min"] == 1000


@pytest.mark.asyncio
async def test_health_check_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    out = await health_check_impl()
    assert out["api_key_configured"] is False
    assert out["rate_limit_per_min"] is None


@pytest.mark.asyncio
async def test_get_server_info() -> None:
    out = await get_server_info_impl(server_version="9.9.9")
    assert out["server_version"] == "9.9.9"
    assert "supported_tools" in out
    assert len(out["supported_tools"]) == 8


@pytest.mark.asyncio
async def test_get_cache_stats_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    import polygon_news_mcp.cache as cache_mod

    monkeypatch.setenv("POLYGON_CACHE_ENABLED", "1")
    monkeypatch.delenv("POLYGON_CACHE_BACKEND", raising=False)
    cache_mod.reset_cache_singleton()
    out = await get_cache_stats_impl()
    assert out["backend"] == "memory"
    assert "entries" in out
    cache_mod.reset_cache_singleton()


@pytest.mark.asyncio
async def test_get_cache_stats_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    import polygon_news_mcp.cache as cache_mod

    monkeypatch.setenv("POLYGON_CACHE_ENABLED", "0")
    cache_mod.reset_cache_singleton()
    out = await get_cache_stats_impl()
    assert out["enabled"] is False
