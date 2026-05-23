"""Server integration tests — exercise the FastMCP wiring with a fake client.

We do NOT bring up real stdio here (that would require a subprocess); we
exercise the wired tool callables directly via the in-process FastMCP
app object.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import polygon_news_mcp.tools._runtime as runtime_mod
from polygon_news_mcp.server import SERVER_VERSION, app
from tests.conftest import FIXTURE_DIR, FakeRoute


def _seed_routes(fixture_dir: Path) -> list[FakeRoute]:
    news_aapl = json.loads((fixture_dir / "news_aapl.json").read_text(encoding="utf-8"))
    news_market = json.loads((fixture_dir / "news_market.json").read_text(encoding="utf-8"))
    news_msft = json.loads((fixture_dir / "news_msft.json").read_text(encoding="utf-8"))
    details_aapl = json.loads((fixture_dir / "ticker_details_aapl.json").read_text(encoding="utf-8"))
    filings_aapl = json.loads((fixture_dir / "filings_aapl.json").read_text(encoding="utf-8"))
    dividends_aapl = json.loads((fixture_dir / "dividends_aapl.json").read_text(encoding="utf-8"))
    return [
        FakeRoute("/v2/reference/news?ticker=AAPL", json_body=news_aapl),
        FakeRoute("/v2/reference/news?ticker=MSFT", json_body=news_msft),
        FakeRoute("/v2/reference/news", json_body=news_market),
        FakeRoute("/v3/reference/tickers/AAPL", json_body=details_aapl),
        FakeRoute("/vX/reference/sec/filings", json_body=filings_aapl),
        FakeRoute("/v3/reference/dividends", json_body=dividends_aapl),
    ]


@pytest.mark.asyncio
async def test_app_exports_eight_tools() -> None:
    a = app()
    tools = await a.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "get_ticker_news",
        "get_market_news",
        "get_ticker_details",
        "list_sec_filings_index",
        "get_news_sentiment_aggregate",
        "get_dividends",
        "health_check",
        "get_server_info",
    }


@pytest.mark.asyncio
async def test_call_get_ticker_news_through_app(make_polygon_client) -> None:
    client = make_polygon_client(_seed_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    a = app()
    result = await a.call_tool(
        "get_ticker_news",
        {"ticker": "AAPL", "limit": 10, "since_days": 7},
    )
    payload = _extract_payload(result)
    assert payload["ticker"] == "AAPL"
    assert payload["count"] == 2


@pytest.mark.asyncio
async def test_call_get_market_news_through_app(make_polygon_client) -> None:
    client = make_polygon_client(_seed_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    a = app()
    result = await a.call_tool("get_market_news", {"limit": 20, "since_hours": 24})
    payload = _extract_payload(result)
    assert payload["count"] == 3


@pytest.mark.asyncio
async def test_call_get_ticker_details_through_app(make_polygon_client) -> None:
    client = make_polygon_client(_seed_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    a = app()
    result = await a.call_tool("get_ticker_details", {"ticker": "AAPL"})
    payload = _extract_payload(result)
    assert payload["name"] == "Apple Inc."


@pytest.mark.asyncio
async def test_call_list_sec_filings_index_through_app(make_polygon_client) -> None:
    client = make_polygon_client(_seed_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    a = app()
    result = await a.call_tool(
        "list_sec_filings_index",
        {"ticker": "AAPL", "since_days": 90},
    )
    payload = _extract_payload(result)
    assert payload["count"] == 2


@pytest.mark.asyncio
async def test_call_get_dividends_through_app(make_polygon_client) -> None:
    client = make_polygon_client(_seed_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    a = app()
    result = await a.call_tool(
        "get_dividends",
        {"ticker": "AAPL", "since_days": 365, "dividend_type": "all"},
    )
    payload = _extract_payload(result)
    assert payload["ticker"] == "AAPL"
    assert payload["count"] == 4


@pytest.mark.asyncio
async def test_call_get_news_sentiment_aggregate_through_app(make_polygon_client) -> None:
    client = make_polygon_client(_seed_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    a = app()
    result = await a.call_tool(
        "get_news_sentiment_aggregate",
        {"ticker": "MSFT", "window_days": 7},
    )
    payload = _extract_payload(result)
    assert payload["ticker"] == "MSFT"
    assert payload["window_days"] == 7
    assert payload["total_articles"] >= 1


@pytest.mark.asyncio
async def test_call_get_news_sentiment_aggregate_invalid_window(make_polygon_client) -> None:
    """``window_days=2`` is not a valid Literal; FastMCP intercepts the
    Pydantic ``ValidationError`` and re-raises it as ``ToolError`` before
    our ``_frame_error`` wrapper can run.  We just verify the call
    surfaces a structured failure rather than letting a raw exception leak.
    """
    from mcp.server.fastmcp.exceptions import ToolError

    client = make_polygon_client(_seed_routes(FIXTURE_DIR))
    await runtime_mod.set_client_for_tests(client)
    a = app()
    with pytest.raises(ToolError):
        await a.call_tool(
            "get_news_sentiment_aggregate",
            {"ticker": "MSFT", "window_days": 2},
        )


@pytest.mark.asyncio
async def test_call_health_check_through_app() -> None:
    a = app()
    result = await a.call_tool("health_check", {})
    payload = _extract_payload(result)
    assert "rate_limit_hard_cap_per_min" in payload


@pytest.mark.asyncio
async def test_call_get_server_info_through_app() -> None:
    a = app()
    result = await a.call_tool("get_server_info", {})
    payload = _extract_payload(result)
    assert payload["server_version"] == SERVER_VERSION
    assert len(payload["supported_tools"]) == 8


def test_initialize_reports_release_tag_version() -> None:
    """``serverInfo.version`` must report the project's release tag
    (``polygon_news_mcp.__version__``), NOT the underlying mcp Python SDK
    framework version (e.g. ``1.27.1``).

    Regression test — FastMCP's ctor does not accept a ``version=`` kwarg,
    so the lowlevel ``Server.version`` defaults to ``None`` and the server
    falls back to ``importlib.metadata.version("mcp")``.  ``server.py``
    must explicitly assign ``mcp_app._mcp_server.version = SERVER_VERSION``
    so the ``initialize`` response carries the project tag.
    """
    from polygon_news_mcp import __version__ as expected_version

    a = app()
    init_options = a._mcp_server.create_initialization_options()
    assert init_options.server_name == "polygon-news-mcp"
    assert init_options.server_version == expected_version, (
        f"server_version={init_options.server_version!r} should equal "
        f"package __version__={expected_version!r}; if it equals the "
        "mcp SDK version, the FastMCP._mcp_server.version override "
        "in server.py was lost."
    )


@pytest.mark.asyncio
async def test_validation_error_framed(make_polygon_client) -> None:
    """A validation failure surfaces as a structured error envelope, not a
    raw exception leaking out of the tool callable."""
    client = make_polygon_client([])
    await runtime_mod.set_client_for_tests(client)
    a = app()
    result = await a.call_tool(
        "get_ticker_news",
        {"ticker": "bad ticker!", "limit": 10, "since_days": 7},
    )
    payload = _extract_payload(result)
    assert payload.get("error") == "validation"
    assert payload.get("field") == "ticker"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _extract_payload(result):  # type: ignore[no-untyped-def]
    """Best-effort extraction of the structured payload from a CallToolResult."""
    if isinstance(result, tuple):
        if len(result) >= 2 and isinstance(result[1], dict):
            return result[1]
        if result and hasattr(result[0], "text"):
            return json.loads(result[0].text)
        return {}
    sc = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
    if isinstance(sc, dict):
        return sc
    content = getattr(result, "content", None)
    if content and hasattr(content[0], "text"):
        return json.loads(content[0].text)
    return {}
