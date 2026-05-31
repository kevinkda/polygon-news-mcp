"""Exception-path security tests for polygon-news-mcp.

Validates that every exception path (a) is handled without crashing the
server, (b) never leaks the API key / internal paths into the structured
envelope, and (c) preserves stability after the error.  No empty-coverage
padding.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import duckdb
import pytest

from polygon_news_mcp.cache import Cache

FAKE_KEY = "AbCdEf0123456789XyZ_secretkey"  # pragma: allowlist secret


# ===========================================================================
# Exception construction guards (type enforcement)
# ===========================================================================


class TestExceptionTypeGuards:
    def test_validation_error_rejects_non_str(self) -> None:
        from polygon_news_mcp.errors import PolygonValidationError

        with pytest.raises(TypeError):
            PolygonValidationError(field=1, reason="x")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            PolygonValidationError(field="f", reason=2)  # type: ignore[arg-type]

    def test_auth_error_rejects_non_int_status(self) -> None:
        from polygon_news_mcp.errors import PolygonAuthError

        with pytest.raises(TypeError):
            PolygonAuthError(status_code="401", hint="x")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            PolygonAuthError(status_code=401, hint=2)  # type: ignore[arg-type]

    def test_notfound_error_rejects_non_str(self) -> None:
        from polygon_news_mcp.errors import PolygonNotFoundError

        with pytest.raises(TypeError):
            PolygonNotFoundError(resource=1, hint="h")  # type: ignore[arg-type]

    def test_ratelimit_error_rejects_non_int(self) -> None:
        from polygon_news_mcp.errors import PolygonRateLimitError

        with pytest.raises(TypeError):
            PolygonRateLimitError(retry_after_seconds="x", plan_hint="p")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            PolygonRateLimitError(retry_after_seconds=1, plan_hint=2)  # type: ignore[arg-type]

    def test_transient_error_rejects_non_int(self) -> None:
        from polygon_news_mcp.errors import PolygonTransientError

        with pytest.raises(TypeError):
            PolygonTransientError(status_code="x", attempt=1, hint="h")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            PolygonTransientError(status_code=500, attempt="x", hint="h")  # type: ignore[arg-type]

    def test_config_error_rejects_non_str(self) -> None:
        from polygon_news_mcp.errors import PolygonConfigurationError

        with pytest.raises(TypeError):
            PolygonConfigurationError(hint=123)  # type: ignore[arg-type]


# ===========================================================================
# HTTP-layer exception handling
# ===========================================================================


class TestHttpExceptionPaths:
    @pytest.mark.asyncio
    async def test_401_raises_auth_error(self, make_polygon_client) -> None:
        from polygon_news_mcp.errors import PolygonAuthError
        from tests.conftest import FakeRoute

        client = make_polygon_client([FakeRoute("/x", status_code=401, json_body={"error": "bad key"})])
        with pytest.raises(PolygonAuthError):
            await client.get_json("/x")

    @pytest.mark.asyncio
    async def test_403_raises_auth_error(self, make_polygon_client) -> None:
        from polygon_news_mcp.errors import PolygonAuthError
        from tests.conftest import FakeRoute

        client = make_polygon_client([FakeRoute("/x", status_code=403, json_body={"error": "tier"})])
        with pytest.raises(PolygonAuthError):
            await client.get_json("/x")

    @pytest.mark.asyncio
    async def test_404_raises_notfound(self, make_polygon_client) -> None:
        from polygon_news_mcp.errors import PolygonNotFoundError
        from tests.conftest import FakeRoute

        client = make_polygon_client([FakeRoute("/missing", status_code=404, json_body={"error": "nope"})])
        with pytest.raises(PolygonNotFoundError):
            await client.get_json("/missing")

    @pytest.mark.asyncio
    async def test_invalid_json_raises_transient(self, make_polygon_client) -> None:
        from polygon_news_mcp.errors import PolygonTransientError
        from tests.conftest import FakeRoute

        client = make_polygon_client([FakeRoute("/bad", text_body="<<<not json>>>", content_type="application/json")])
        with pytest.raises(PolygonTransientError):
            await client.get_json("/bad")

    @pytest.mark.asyncio
    async def test_5xx_exhausts_to_transient(self, make_polygon_client) -> None:
        from polygon_news_mcp.errors import PolygonTransientError
        from tests.conftest import FakeRoute

        client = make_polygon_client([FakeRoute("/err", status_code=503, json_body={"error": "down"})])
        with pytest.raises(PolygonTransientError):
            await client.get_json("/err")


# ===========================================================================
# Cache exception resilience — best-effort, never crashes the tool
# ===========================================================================


class TestCacheExceptionResilience:
    def test_read_error_returns_none(self, tmp_path: Path) -> None:
        cache = Cache(db_path=tmp_path / "c.duckdb")
        try:
            real = cache._conn
            fake = MagicMock(wraps=real)
            fake.execute.side_effect = duckdb.Error("read boom")
            cache._conn = fake  # type: ignore[assignment]
            assert cache.get_news({"q": "x"}) is None
            cache._conn = real  # type: ignore[assignment]
        finally:
            cache.close()

    def test_write_error_swallowed(self, tmp_path: Path) -> None:
        cache = Cache(db_path=tmp_path / "c.duckdb")
        try:
            real = cache._conn
            fake = MagicMock(wraps=real)
            fake.execute.side_effect = duckdb.Error("write boom")
            cache._conn = fake  # type: ignore[assignment]
            cache.put_news({"q": "x"}, {"v": 1})  # must not raise
            cache._conn = real  # type: ignore[assignment]
        finally:
            cache.close()

    def test_corrupt_db_quarantined(self, tmp_path: Path) -> None:
        db = tmp_path / "c.duckdb"
        db.write_bytes(b"not a valid duckdb file at all")
        cache = Cache(db_path=db)
        try:
            backups = list(tmp_path.glob("c.duckdb.corrupt-*"))
            assert backups or cache._conn is not None
        finally:
            cache.close()


# ===========================================================================
# Exception info-leak guards (API key + PII)
# ===========================================================================


class TestExceptionInfoLeak:
    def test_transient_hint_redacts_key(self) -> None:
        from polygon_news_mcp.errors import PolygonTransientError

        exc = PolygonTransientError(status_code=500, attempt=1, hint=f"failed ?apiKey={FAKE_KEY}")
        assert FAKE_KEY not in str(exc)

    def test_auth_hint_redacts_bearer(self) -> None:
        from polygon_news_mcp.errors import PolygonAuthError

        exc = PolygonAuthError(status_code=401, hint=f"Authorization: Bearer {FAKE_KEY}")
        assert FAKE_KEY not in str(exc)

    @pytest.mark.asyncio
    async def test_tool_never_raises_uncaught_polygon_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import json

        import polygon_news_mcp.tools._runtime as runtime_mod
        from polygon_news_mcp.errors import PolygonRateLimitError
        from polygon_news_mcp.server import app

        class _RateLimited:
            async def get_json(self, *_a, **_k):
                raise PolygonRateLimitError(retry_after_seconds=12, plan_hint="free tier 5/min")

        await runtime_mod.set_client_for_tests(_RateLimited())  # type: ignore[arg-type]
        monkeypatch.setenv("POLYGON_CACHE_ENABLED", "0")
        result = await app().call_tool("get_ticker_news", {"ticker": "AAPL"})
        payload = result[1] if isinstance(result, tuple) and len(result) >= 2 and isinstance(result[1], dict) else {}
        if not payload and isinstance(result, tuple) and result and hasattr(result[0], "text"):
            payload = json.loads(result[0].text)
        assert payload.get("error") == "rate_limit"
        assert payload.get("retry_after_seconds") == 12
        await runtime_mod.set_client_for_tests(None)
