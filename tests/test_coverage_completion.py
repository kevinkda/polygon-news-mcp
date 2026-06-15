"""Coverage completion suite — drive the residual uncovered branches to 100%.

Targets the specific ``file:line`` gaps from ``pytest --cov-report=term-missing``
against the v0.2.0 baseline (88.58%).  No empty-coverage padding: each test
asserts a concrete observable invariant.

Gap map (baseline 88.58%):
    * server.py        — stdio-harden OSError branches, _frame_error, tool excepts
    * tools/_runtime.py— double-checked lock, cache lookup/store exceptions
    * tools/meta.py    — api-key missing / config-invalid, cache disabled/None/error
    * cache.py         — quarantine reopen, get/put DuckDB errors, expired, stats
    * client.py        — non-dict json shape, _abs_url path normalisation
    * errors.py        — PolygonTransientError.__str__
    * models.py        — ticker validator non-str passthrough
    * tools/news/filings/sentiment — non-dict entry skips
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import polygon_news_mcp.tools._runtime as runtime_mod
from polygon_news_mcp.cache import Cache
from polygon_news_mcp.cache_backend import MemoryBackend


def _extract_payload(result: Any) -> dict[str, Any]:
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


# ===========================================================================
# server.py
# ===========================================================================


class TestServerGaps:
    def test_frame_error_all_branches(self) -> None:
        """_frame_error maps every structured exception to its envelope (125-148)."""
        from polygon_news_mcp import server as srv
        from polygon_news_mcp.errors import (
            PolygonAuthError,
            PolygonConfigurationError,
            PolygonError,
            PolygonNotFoundError,
            PolygonRateLimitError,
            PolygonTransientError,
            PolygonValidationError,
        )

        assert srv._frame_error(PolygonValidationError(field="ticker", reason="bad")) == {
            "error": "validation",
            "field": "ticker",
            "reason": "bad",
        }
        assert srv._frame_error(PolygonConfigurationError(hint="set key"))["error"] == "configuration"
        au = srv._frame_error(PolygonAuthError(status_code=401, hint="bad key"))
        assert au["error"] == "auth" and au["status_code"] == 401
        nf = srv._frame_error(PolygonNotFoundError(resource="r", hint="h"))
        assert nf["error"] == "not_found" and nf["resource"] == "r"
        rl = srv._frame_error(PolygonRateLimitError(retry_after_seconds=12, plan_hint="free tier"))
        assert rl["error"] == "rate_limit" and rl["retry_after_seconds"] == 12
        tr = srv._frame_error(PolygonTransientError(status_code=503, attempt=1, hint="up"))
        assert tr["error"] == "transient" and tr["status_code"] == 503
        assert srv._frame_error(PolygonError())["error"] == "polygon_error"
        assert srv._frame_error(ValueError("boom")) == {"error": "internal", "type": "ValueError"}

    def test_harden_stdio_tolerates_log_dir_oserror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If the log dir cannot be created, hardening still completes (42-43)."""
        from polygon_news_mcp import server as srv

        def boom_mkdir(*_a: Any, **_k: Any) -> None:
            raise OSError("read-only fs")

        monkeypatch.setattr(Path, "mkdir", boom_mkdir)
        srv._harden_stdio()  # must not raise

    def test_harden_stdio_tolerates_file_handler_oserror(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """A failing RotatingFileHandler is swallowed (58-59)."""
        from polygon_news_mcp import server as srv

        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))

        def boom_handler(*_a: Any, **_k: Any) -> None:
            raise OSError("cannot open log file")

        monkeypatch.setattr(srv, "RotatingFileHandler", boom_handler)
        srv._harden_stdio()  # must not raise

    def test_safe_print_defaults_to_stderr(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The patched print routes to stderr by default (line 32)."""
        from polygon_news_mcp import server as srv

        srv._harden_stdio()
        print("polygon-coverage-probe")
        captured = capsys.readouterr()
        assert "polygon-coverage-probe" in captured.err
        assert "polygon-coverage-probe" not in captured.out

    def test_main_runs_app(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """main() logs start and calls app().run() (320-321)."""
        from polygon_news_mcp import server as srv

        ran: list[int] = []
        fake_app = MagicMock()
        fake_app.run = lambda: ran.append(1)
        monkeypatch.setattr(srv, "app", lambda: fake_app)
        srv.main()
        assert ran == [1]

    @pytest.mark.asyncio
    async def test_each_tool_frames_polygon_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Every tool's `except PolygonError` branch returns an envelope (185-291).

        We inject a client whose get_json raises PolygonNotFoundError so each
        impl propagates a PolygonError into the tool try/except.
        """
        from polygon_news_mcp.errors import PolygonNotFoundError
        from polygon_news_mcp.server import app

        class _BoomClient:
            async def get_json(self, *_a: Any, **_k: Any) -> dict[str, Any]:
                raise PolygonNotFoundError(resource="x", hint="nope")

        await runtime_mod.set_client_for_tests(_BoomClient())  # type: ignore[arg-type]
        monkeypatch.setenv("POLYGON_CACHE_ENABLED", "0")
        a = app()
        calls = [
            ("get_ticker_news", {"ticker": "AAPL"}),
            ("get_market_news", {}),
            ("get_ticker_details", {"ticker": "AAPL"}),
            ("list_sec_filings_index", {"ticker": "AAPL"}),
            ("get_news_sentiment_aggregate", {"ticker": "AAPL", "window_days": 7}),
            ("get_dividends", {"ticker": "AAPL"}),
        ]
        for name, kwargs in calls:
            result = await a.call_tool(name, kwargs)
            payload = _extract_payload(result)
            assert payload.get("error") in {"not_found", "polygon_error", "internal"}, (name, payload)
        await runtime_mod.set_client_for_tests(None)


# ===========================================================================
# tools/_runtime.py
# ===========================================================================


class TestRuntimeGaps:
    @pytest.mark.asyncio
    async def test_get_client_double_checked_lock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        runtime_mod.reset_client_cache()
        built: list[int] = []

        def fake_make_client() -> Any:
            built.append(1)
            return MagicMock(name="PolygonClient")

        monkeypatch.setattr(runtime_mod, "make_client", fake_make_client)
        c1, c2 = await asyncio.gather(runtime_mod.get_client(), runtime_mod.get_client())
        assert c1 is c2 and built == [1]
        runtime_mod.reset_client_cache()

    @pytest.mark.asyncio
    async def test_cache_lookup_exception_falls_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(runtime_mod, "get_cache", lambda: MagicMock())
        monkeypatch.setattr(runtime_mod, "cache_bypass", lambda: False)

        async def fetch(_c: Any) -> dict[str, Any]:
            return {"ok": True}

        def boom_lookup(_c: Any) -> dict[str, Any] | None:
            raise RuntimeError("lookup boom")

        async def fake_get_client() -> Any:
            return MagicMock()

        monkeypatch.setattr(runtime_mod, "get_client", fake_get_client)
        out = await runtime_mod.call_with_cache(fetch, cache_lookup=boom_lookup)
        assert out["ok"] and out["_cache_status"] == "miss"

    @pytest.mark.asyncio
    async def test_cache_store_exception_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(runtime_mod, "get_cache", lambda: MagicMock())
        monkeypatch.setattr(runtime_mod, "cache_bypass", lambda: False)

        async def fetch(_c: Any) -> dict[str, Any]:
            return {"v": 1}

        def boom_store(_c: Any, _p: dict[str, Any]) -> None:
            raise RuntimeError("store boom")

        async def fake_get_client() -> Any:
            return MagicMock()

        monkeypatch.setattr(runtime_mod, "get_client", fake_get_client)
        out = await runtime_mod.call_with_cache(fetch, cache_store=boom_store)
        assert out["v"] == 1 and out["_cache_status"] == "miss"

    @pytest.mark.asyncio
    async def test_cache_bypass_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(runtime_mod, "get_cache", lambda: MagicMock())
        monkeypatch.setattr(runtime_mod, "cache_bypass", lambda: True)

        async def fetch(_c: Any) -> dict[str, Any]:
            return {"v": 2}

        async def fake_get_client() -> Any:
            return MagicMock()

        monkeypatch.setattr(runtime_mod, "get_client", fake_get_client)
        out = await runtime_mod.call_with_cache(fetch, cache_lookup=lambda c: None)
        assert out["_cache_status"] == "bypass"


# ===========================================================================
# tools/meta.py
# ===========================================================================


class TestMetaGaps:
    def test_api_key_status_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from polygon_news_mcp.tools import meta

        monkeypatch.delenv("POLYGON_API_KEY", raising=False)
        assert meta._safe_api_key_status() == {"configured": False, "reason": "missing"}

    def test_api_key_status_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from polygon_news_mcp.tools import meta

        monkeypatch.setenv("POLYGON_API_KEY", "live-key-123")
        assert meta._safe_api_key_status() == {"configured": True, "reason": None}

    def test_cache_summary_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from polygon_news_mcp.tools import meta

        monkeypatch.setattr(meta, "cache_enabled", lambda: False)
        assert meta._safe_cache_summary() == {"enabled": False, "backend": None, "entries": 0}

    def test_cache_summary_get_cache_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from polygon_news_mcp.tools import meta

        monkeypatch.setattr(meta, "cache_enabled", lambda: True)
        monkeypatch.setattr(meta, "get_cache", lambda: None)
        assert meta._safe_cache_summary()["enabled"] is False

    def test_cache_summary_stats_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from polygon_news_mcp.tools import meta

        broken = MagicMock()
        broken.get_stats.side_effect = RuntimeError("backend gone")
        monkeypatch.setattr(meta, "cache_enabled", lambda: True)
        monkeypatch.setattr(meta, "get_cache", lambda: broken)
        assert meta._safe_cache_summary() == {"enabled": True, "backend": None, "entries": 0}


# ===========================================================================
# errors.py / models.py
# ===========================================================================


class TestErrorAndModelGaps:
    def test_transient_error_str(self) -> None:
        """PolygonTransientError.__str__ renders status+attempt (line 148)."""
        from polygon_news_mcp.errors import PolygonTransientError

        s = str(PolygonTransientError(status_code=503, attempt=2, hint="upstream"))
        assert "503" in s and "attempt=2" in s

    def test_ticker_validator_passthrough_non_str(self) -> None:
        """The module-level ticker normaliser returns non-str input untouched (line 63)."""
        from polygon_news_mcp.models import _normalise_ticker

        sentinel = object()
        assert _normalise_ticker(sentinel) is sentinel
        # And it upper-cases a valid str ticker.
        assert _normalise_ticker("aapl") == "AAPL"


# ===========================================================================
# client.py
# ===========================================================================


class TestClientGaps:
    @pytest.mark.asyncio
    async def test_get_json_rejects_non_dict_non_list(self, make_polygon_client) -> None:
        """A scalar JSON body raises PolygonTransientError (333)."""
        from polygon_news_mcp.errors import PolygonTransientError
        from tests.conftest import FakeRoute

        client = make_polygon_client([FakeRoute("/scalar", text_body="42", content_type="application/json")])
        with pytest.raises(PolygonTransientError):
            await client.get_json("/scalar")

    def test_abs_url_normalises_relative_path(self, make_polygon_client) -> None:
        """A path without a leading slash is normalised onto the base URL (230)."""
        from tests.conftest import FakeRoute

        client = make_polygon_client([FakeRoute("x", json_body={})])
        url = client._abs_url("v3/reference/tickers")
        assert url == "https://api.polygon.io/v3/reference/tickers"

    def test_abs_url_passes_absolute_through(self, make_polygon_client) -> None:
        from tests.conftest import FakeRoute

        client = make_polygon_client([FakeRoute("x", json_body={})])
        assert client._abs_url("https://api.polygon.io/v2/x") == "https://api.polygon.io/v2/x"

    def test_abs_url_leading_slash_preserved(self, make_polygon_client) -> None:
        from tests.conftest import FakeRoute

        client = make_polygon_client([FakeRoute("x", json_body={})])
        assert client._abs_url("/v2/y") == "https://api.polygon.io/v2/y"


# ===========================================================================
# tools/news.py, tools/filings.py, tools/sentiment.py — non-dict entry skips
# ===========================================================================


class TestToolEntrySkips:
    def test_news_skips_non_dict_entries(self) -> None:
        """News normalisation skips non-dict result entries (news.py 88)."""
        from polygon_news_mcp.tools.news import _normalise_news

        raw = {"results": ["not-a-dict", {"id": "a", "title": "T", "publisher": {"name": "P"}}]}
        out = _normalise_news(raw, ticker="AAPL")
        assert out["count"] == 1

    def test_filings_skips_non_dict_entries(self) -> None:
        """Filings normalisation skips non-dict result entries (filings.py 57)."""
        from polygon_news_mcp.tools.filings import _normalise

        raw = {"results": ["junk", {"id": "f1", "type": "10-K"}]}
        out = _normalise(raw, ticker="AAPL", since_days=90)
        assert out["count"] == 1

    def test_sentiment_extract_skips_non_dict_and_non_str(self) -> None:
        """Sentiment extraction skips non-dict insights + non-str sentiment (101/108)."""
        from polygon_news_mcp.tools.sentiment import _ticker_sentiment

        article = {
            "insights": [
                "not-a-dict",
                {"sentiment": 123},  # non-str sentiment → skipped
                {"sentiment": "positive", "ticker": "MSFT"},  # fallback (no match)
                {"sentiment": "negative", "ticker": "AAPL"},  # exact match → returned
            ]
        }
        assert _ticker_sentiment(article, ticker="AAPL") == "negative"

    def test_sentiment_extract_uses_fallback(self) -> None:
        from polygon_news_mcp.tools.sentiment import _ticker_sentiment

        article = {"insights": [{"sentiment": "Neutral", "ticker": "OTHER"}]}
        assert _ticker_sentiment(article, ticker="AAPL") == "neutral"

    def test_sentiment_no_insights_returns_none(self) -> None:
        from polygon_news_mcp.tools.sentiment import _ticker_sentiment

        assert _ticker_sentiment({"insights": []}, ticker="AAPL") is None
        assert _ticker_sentiment({"insights": "not-a-list"}, ticker="AAPL") is None

    def test_sentiment_fallback_set_once_then_returns(self) -> None:
        """Two non-matching insights: fallback set on first, second skips the
        `if fallback is None` set (sentiment 108->99 branch), then returned."""
        from polygon_news_mcp.tools.sentiment import _ticker_sentiment

        article = {
            "insights": [
                {"sentiment": "Positive", "ticker": "OTHER1"},  # sets fallback
                {"sentiment": "Negative", "ticker": "OTHER2"},  # fallback already set → 108->99
            ]
        }
        # No ticker match → returns the FIRST fallback (positive).
        assert _ticker_sentiment(article, ticker="AAPL") == "positive"


# ===========================================================================
# cache.py — DuckDB-error resilience, quarantine, stats, helpers
# ===========================================================================


class TestCacheGaps:
    def test_get_delegates_to_backend(self) -> None:
        cache = Cache(backend=MemoryBackend())
        assert cache._get("news_cache", "k") is None
        cache._put("news_cache", "k", {"x": 1}, 60)
        assert cache._get("news_cache", "k") == {"x": 1}

    def test_put_then_get_each_table(self) -> None:
        cache = Cache(backend=MemoryBackend())
        cache.put_news({"q": "x"}, {"data": 1})
        cache.put_ticker_details({"t": "AAPL"}, {"name": "Apple"})
        cache.put_filings_index({"t": "AAPL"}, {"filings": []})
        cache.put_dividends({"t": "AAPL"}, {"results": []})
        assert cache.get_news({"q": "x"}) == {"data": 1}
        assert cache.get_ticker_details({"t": "AAPL"})["name"] == "Apple"
        assert cache.get_filings_index({"t": "AAPL"}) == {"filings": []}
        assert cache.get_dividends({"t": "AAPL"}) == {"results": []}

    def test_expired_row_returns_none(self) -> None:
        cache = Cache(backend=MemoryBackend())
        cache.backend.set("news_cache", "k", {"data": 1}, 0)
        assert cache.backend.get("news_cache", "k") is None

    def test_get_stats_shape(self) -> None:
        cache = Cache(backend=MemoryBackend())
        cache.put_news({"q": "x"}, {"data": 1})
        stats = cache.get_stats()
        assert stats.backend == "memory"
        assert stats.entries == 1
        assert "backend" in stats.to_dict()

    def test_get_stats_size_error_degrades(self) -> None:
        backend = MemoryBackend()
        backend.size = lambda: (_ for _ in ()).throw(RuntimeError("size fail"))  # type: ignore[method-assign]
        cache = Cache(backend=backend)
        assert cache.get_stats().entries == 0

    def test_reset_clears_rows(self) -> None:
        cache = Cache(backend=MemoryBackend())
        cache.put_news({"q": "x"}, {"data": 1})
        cache.reset()
        assert cache.get_news({"q": "x"}) is None

    def test_close_and_context_manager(self) -> None:
        with Cache(backend=MemoryBackend()) as cache:
            cache.put_news({"q": "x"}, {"data": 1})
            assert cache.get_news({"q": "x"}) is not None
        cache.close()  # idempotent

    def test_default_backend_is_memory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("POLYGON_CACHE_BACKEND", raising=False)
        assert Cache().backend.name == "memory"

    def test_get_cache_singleton_reuse(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import polygon_news_mcp.cache as cache_mod

        cache_mod.reset_cache_singleton()
        monkeypatch.setattr(cache_mod, "cache_enabled", lambda: True)
        assert cache_mod.get_cache() is cache_mod.get_cache()
        cache_mod.reset_cache_singleton()

    def test_get_cache_disabled_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import polygon_news_mcp.cache as cache_mod

        monkeypatch.setattr(cache_mod, "cache_enabled", lambda: False)
        assert cache_mod.get_cache() is None
