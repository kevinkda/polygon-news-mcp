"""Unit tests for polygon_news_mcp.client."""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest

from polygon_news_mcp.client import (
    DEFAULT_BASE_URL,
    POLYGON_HARD_RATE_LIMIT_PER_MIN,
    PolygonClient,
    TokenBucket,
    _backoff_delay,
    _parse_retry_after,
    make_client,
    resolve_api_key,
    resolve_base_url,
    resolve_rate_limit,
)
from polygon_news_mcp.errors import (
    PolygonAuthError,
    PolygonConfigurationError,
    PolygonNotFoundError,
    PolygonRateLimitError,
    PolygonTransientError,
)
from tests.conftest import FakeRoute

# ---------------------------------------------------------------------------
# resolve_api_key / resolve_rate_limit / resolve_base_url
# ---------------------------------------------------------------------------


class TestResolveApiKey:
    def test_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("POLYGON_API_KEY", "good-key")
        assert resolve_api_key() == "good-key"

    def test_missing_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("POLYGON_API_KEY", raising=False)
        with pytest.raises(PolygonConfigurationError):
            resolve_api_key()

    def test_empty_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("POLYGON_API_KEY", "   ")
        with pytest.raises(PolygonConfigurationError):
            resolve_api_key()


class TestResolveRateLimit:
    def test_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("POLYGON_RATE_LIMIT_PER_MIN", raising=False)
        assert resolve_rate_limit() == 5

    def test_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("POLYGON_RATE_LIMIT_PER_MIN", "25")
        assert resolve_rate_limit() == 25

    def test_clamped_to_hard_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("POLYGON_RATE_LIMIT_PER_MIN", "999999")
        assert resolve_rate_limit() == POLYGON_HARD_RATE_LIMIT_PER_MIN

    def test_negative_clamped_to_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("POLYGON_RATE_LIMIT_PER_MIN", "-3")
        assert resolve_rate_limit() == 1

    def test_garbage_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("POLYGON_RATE_LIMIT_PER_MIN", "abc")
        assert resolve_rate_limit() == 5


class TestResolveBaseUrl:
    def test_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("POLYGON_BASE_URL", raising=False)
        assert resolve_base_url() == DEFAULT_BASE_URL

    def test_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("POLYGON_BASE_URL", "https://example.test/")
        assert resolve_base_url() == "https://example.test"


# ---------------------------------------------------------------------------
# TokenBucket
# ---------------------------------------------------------------------------


class TestTokenBucket:
    @pytest.mark.asyncio
    async def test_admits_under_capacity(self) -> None:
        b = TokenBucket(capacity=3, window_seconds=60)
        await b.acquire()
        await b.acquire()
        await b.acquire()
        assert b.tokens_remaining() == 0

    @pytest.mark.asyncio
    async def test_blocks_over_capacity(self) -> None:
        # Use a tiny window so the test runs fast.
        b = TokenBucket(capacity=2, window_seconds=0.6)
        await b.acquire()
        await b.acquire()
        before = asyncio.get_event_loop().time()
        await b.acquire()
        after = asyncio.get_event_loop().time()
        assert (after - before) > 0.3

    def test_capacity_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            TokenBucket(capacity=0)

    def test_window_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            TokenBucket(capacity=1, window_seconds=0)


# ---------------------------------------------------------------------------
# Backoff helpers
# ---------------------------------------------------------------------------


class TestBackoff:
    def test_backoff_grows(self) -> None:
        a = _backoff_delay(0)
        b = _backoff_delay(2)
        assert b > a
        assert isinstance(a, float)

    def test_parse_retry_after_int(self) -> None:
        resp = httpx.Response(429, headers={"Retry-After": "7"})
        assert _parse_retry_after(resp) == 7

    def test_parse_retry_after_clamped(self) -> None:
        resp = httpx.Response(429, headers={"Retry-After": "9999"})
        assert _parse_retry_after(resp) == 120

    def test_parse_retry_after_garbage(self) -> None:
        resp = httpx.Response(429, headers={"Retry-After": "later"})
        assert _parse_retry_after(resp) == 1

    def test_parse_retry_after_missing(self) -> None:
        resp = httpx.Response(429)
        assert _parse_retry_after(resp) == 1


# ---------------------------------------------------------------------------
# Client request paths — normal / 401 / 404 / 429 / 5xx + json
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_json_normal_path(make_polygon_client) -> None:
    client = make_polygon_client(
        [FakeRoute("/v2/reference/news", json_body={"status": "OK", "results": []})],
    )
    data = await client.get_json("/v2/reference/news")
    assert data["status"] == "OK"
    await client.aclose()


@pytest.mark.asyncio
async def test_get_json_list_wrapped(make_polygon_client) -> None:
    client = make_polygon_client(
        [FakeRoute("/v2/reference/news", json_body=[{"a": 1}, {"b": 2}])],
    )
    data = await client.get_json("/v2/reference/news")
    assert data == {"items": [{"a": 1}, {"b": 2}]}
    await client.aclose()


@pytest.mark.asyncio
async def test_get_json_404(make_polygon_client) -> None:
    client = make_polygon_client(
        [FakeRoute("/missing", status_code=404, json_body={"error": "nope"})],
    )
    with pytest.raises(PolygonNotFoundError):
        await client.get_json("/missing")
    await client.aclose()


@pytest.mark.asyncio
async def test_get_json_401(make_polygon_client) -> None:
    client = make_polygon_client(
        [FakeRoute("/v2/reference/news", status_code=401, json_body={})],
    )
    with pytest.raises(PolygonAuthError) as excinfo:
        await client.get_json("/v2/reference/news")
    assert excinfo.value.status_code == 401
    await client.aclose()


@pytest.mark.asyncio
async def test_get_json_403(make_polygon_client) -> None:
    client = make_polygon_client(
        [FakeRoute("/v2/reference/news", status_code=403, json_body={})],
    )
    with pytest.raises(PolygonAuthError):
        await client.get_json("/v2/reference/news")
    await client.aclose()


@pytest.mark.asyncio
async def test_get_json_429_eventually_raises(make_polygon_client) -> None:
    client = make_polygon_client(
        [FakeRoute("/throttle", status_code=429, json_body={}, headers={"Retry-After": "0"})],
    )
    with pytest.raises(PolygonRateLimitError):
        await client.get_json("/throttle")
    await client.aclose()


@pytest.mark.asyncio
async def test_get_json_5xx_eventually_raises(make_polygon_client) -> None:
    client = make_polygon_client(
        [FakeRoute("/boom", status_code=503, json_body={})],
    )
    with pytest.raises(PolygonTransientError) as excinfo:
        await client.get_json("/boom")
    assert excinfo.value.status_code == 503
    await client.aclose()


@pytest.mark.asyncio
async def test_get_json_unexpected_4xx(make_polygon_client) -> None:
    client = make_polygon_client(
        [FakeRoute("/teapot", status_code=418, json_body={})],
    )
    with pytest.raises(PolygonTransientError):
        await client.get_json("/teapot")
    await client.aclose()


@pytest.mark.asyncio
async def test_get_json_invalid_json(make_polygon_client) -> None:
    routes = [FakeRoute("/badjson", text_body="<not-json>", content_type="application/json")]
    client = make_polygon_client(routes)
    with pytest.raises(PolygonTransientError):
        await client.get_json("/badjson")
    await client.aclose()


@pytest.mark.asyncio
async def test_get_json_full_url_passthrough(make_polygon_client) -> None:
    """``get_json`` accepts a full URL (used by Polygon's pagination cursor)."""
    client = make_polygon_client(
        [FakeRoute("/v2/reference/news?cursor=", json_body={"status": "OK", "results": []})],
    )
    out = await client.get_json("https://api.polygon.io/v2/reference/news?cursor=abc")
    assert out["status"] == "OK"
    await client.aclose()


# ---------------------------------------------------------------------------
# make_client + helpers
# ---------------------------------------------------------------------------


def test_make_client_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLYGON_API_KEY", "x")
    c = make_client()
    assert isinstance(c, PolygonClient)


@pytest.mark.asyncio
async def test_client_async_context(make_polygon_client) -> None:
    client = make_polygon_client([FakeRoute("/x", json_body={"ok": True})])
    async with client as c:
        d = await c.get_json("/x")
    assert d == {"ok": True}


# ---------------------------------------------------------------------------
# Network errors → PolygonTransientError after retries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_network_error_eventually_transient() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated dns failure")

    transport = httpx.MockTransport(handler)
    client = PolygonClient(
        api_key="test",  # pragma: allowlist secret
        rate_limit_per_min=1000,
        transport=transport,
    )
    with pytest.raises(PolygonTransientError) as excinfo:
        await client.get_json("/x")
    assert excinfo.value.status_code == 0
    await client.aclose()


# Ensure a stray env var doesn't leak
def test_env_isolation() -> None:
    assert "POLYGON_API_KEY" in os.environ
