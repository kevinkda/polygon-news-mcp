"""Unit tests for polygon_news_mcp.cache (pluggable backend facade, v0.7 T0).

.. versionchanged:: 0.3.0
    DuckDB removed; the cache now delegates to a pluggable
    :class:`~polygon_news_mcp.cache_backend.CacheBackend` (memory default).
    These tests exercise the per-table public API tools rely on, plus the
    backend-agnostic stats / singleton / context-manager surface.
"""

from __future__ import annotations

import time

import pytest

from polygon_news_mcp.cache import (
    Cache,
    CacheStats,
    cache_bypass,
    cache_enabled,
    get_cache,
    reset_cache_singleton,
    state_root,
)
from polygon_news_mcp.cache_backend import MemoryBackend


@pytest.fixture
def cache() -> Cache:
    # Tiny per-test memory backend — no shared global, no files.
    return Cache(MemoryBackend(maxsize=0))


# ---------------------------------------------------------------------------
# Env helpers
# ---------------------------------------------------------------------------


def test_cache_enabled_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """v0.2.2 BREAKING: unset env var defaults to disabled (was on)."""
    monkeypatch.delenv("POLYGON_CACHE_ENABLED", raising=False)
    assert cache_enabled() is False


@pytest.mark.parametrize(
    "val",
    ["1", "true", "yes", "on", "TRUE", "Yes", "On", " true ", "  1 ", "\tyes\n"],
)
def test_cache_enabled_truthy_matrix(monkeypatch: pytest.MonkeyPatch, val: str) -> None:
    monkeypatch.setenv("POLYGON_CACHE_ENABLED", val)
    assert cache_enabled() is True


@pytest.mark.parametrize("val", ["0", "false", "no", "off", "FALSE", "nope", "2", "", "   "])
def test_cache_enabled_falsy_matrix(monkeypatch: pytest.MonkeyPatch, val: str) -> None:
    monkeypatch.setenv("POLYGON_CACHE_ENABLED", val)
    assert cache_enabled() is False


def test_cache_enabled_unset_get_cache_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POLYGON_CACHE_ENABLED", raising=False)
    reset_cache_singleton()
    assert get_cache() is None


def test_cache_bypass_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POLYGON_CACHE_BYPASS", raising=False)
    assert cache_bypass() is False


def test_state_root_xdg(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert state_root() == tmp_path


# ---------------------------------------------------------------------------
# Generic JSON-row tables (news, ticker_details, filings_index, dividends)
# ---------------------------------------------------------------------------


class TestNewsCache:
    def test_miss(self, cache: Cache) -> None:
        assert cache.get_news({"k": 1}) is None

    def test_hit(self, cache: Cache) -> None:
        cache.put_news({"k": 1}, {"articles": [{"title": "x"}]}, ticker="AAPL")
        out = cache.get_news({"k": 1})
        assert out is not None
        assert out["articles"][0]["title"] == "x"

    def test_different_params_miss(self, cache: Cache) -> None:
        cache.put_news({"k": 1}, {"x": 1})
        assert cache.get_news({"k": 2}) is None


class TestTickerDetailsCache:
    def test_round_trip(self, cache: Cache) -> None:
        cache.put_ticker_details({"ticker": "AAPL"}, {"name": "Apple"}, ticker="AAPL")
        out = cache.get_ticker_details({"ticker": "AAPL"})
        assert out is not None
        assert out["name"] == "Apple"


class TestFilingsIndexCache:
    def test_round_trip(self, cache: Cache) -> None:
        cache.put_filings_index({"ticker": "AAPL", "since_days": 90}, {"filings": []}, ticker="AAPL")
        out = cache.get_filings_index({"ticker": "AAPL", "since_days": 90})
        assert out is not None


class TestDividendsCache:
    def test_round_trip(self, cache: Cache) -> None:
        cache.put_dividends({"ticker": "AAPL"}, {"results": [{"cash_amount": 0.24}]}, ticker="AAPL")
        out = cache.get_dividends({"ticker": "AAPL"})
        assert out is not None
        assert out["results"][0]["cash_amount"] == 0.24


# ---------------------------------------------------------------------------
# TTL expiry (backend-driven, monotonic-clock)
# ---------------------------------------------------------------------------


class TestTTLExpiry:
    def test_news_expired(self, cache: Cache, monkeypatch: pytest.MonkeyPatch) -> None:
        base = time.monotonic()
        monkeypatch.setattr(time, "monotonic", lambda: base)
        cache.put_news({"k": 1}, {"x": 1})
        # Past the 1h news TTL.
        monkeypatch.setattr(time, "monotonic", lambda: base + 3601)
        assert cache.get_news({"k": 1}) is None

    def test_ticker_details_expired(self, cache: Cache, monkeypatch: pytest.MonkeyPatch) -> None:
        base = time.monotonic()
        monkeypatch.setattr(time, "monotonic", lambda: base)
        cache.put_ticker_details({"ticker": "X"}, {"x": 1})
        monkeypatch.setattr(time, "monotonic", lambda: base + 24 * 3600 + 1)
        assert cache.get_ticker_details({"ticker": "X"}) is None


# ---------------------------------------------------------------------------
# Stats (new backend/enabled/entries shape)
# ---------------------------------------------------------------------------


class TestStats:
    def test_empty(self, cache: Cache) -> None:
        s = cache.get_stats()
        assert isinstance(s, CacheStats)
        assert s.backend == "memory"
        assert s.entries == 0

    def test_entries_counted(self, cache: Cache) -> None:
        cache.put_news({"k": 1}, {"x": 1})
        cache.put_dividends({"k": 2}, {"y": 2})
        s = cache.get_stats()
        assert s.entries == 2

    def test_to_dict_shape(self, cache: Cache) -> None:
        d = cache.get_stats().to_dict()
        for key in ("backend", "enabled", "entries"):
            assert key in d

    def test_stats_size_error_degrades_to_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend = MemoryBackend()

        def boom() -> int:
            raise RuntimeError("size failed")

        monkeypatch.setattr(backend, "size", boom)
        c = Cache(backend)
        assert c.get_stats().entries == 0


# ---------------------------------------------------------------------------
# Reset / lifecycle
# ---------------------------------------------------------------------------


def test_reset_drops_rows(cache: Cache) -> None:
    cache.put_news({"k": 1}, {"x": 1})
    cache.reset()
    assert cache.get_news({"k": 1}) is None


def test_close_idempotent(cache: Cache) -> None:
    cache.close()
    cache.close()


def test_context_manager() -> None:
    with Cache(MemoryBackend()) as c:
        c.put_news({"q": "x"}, {"y": 1})
        assert c.get_news({"q": "x"}) is not None


def test_default_backend_is_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POLYGON_CACHE_BACKEND", raising=False)
    c = Cache()
    assert c.backend.name == "memory"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


def test_singleton_disabled_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLYGON_CACHE_ENABLED", "0")
    reset_cache_singleton()
    assert get_cache() is None


def test_singleton_enabled_returns_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLYGON_CACHE_ENABLED", "1")
    monkeypatch.delenv("POLYGON_CACHE_BACKEND", raising=False)
    reset_cache_singleton()
    a = get_cache()
    b = get_cache()
    assert a is b
    reset_cache_singleton()
