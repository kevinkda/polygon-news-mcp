"""Unit tests for polygon_news_mcp.cache (DuckDB)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from polygon_news_mcp.cache import (
    Cache,
    CacheStats,
    cache_bypass,
    cache_enabled,
    default_db_path,
    get_cache,
    reset_cache_singleton,
    state_root,
)


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(tmp_path / "cache.duckdb")


# ---------------------------------------------------------------------------
# Env helpers
# ---------------------------------------------------------------------------


def test_cache_enabled_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POLYGON_CACHE_ENABLED", raising=False)
    assert cache_enabled() is True


@pytest.mark.parametrize("val,expected", [("1", True), ("yes", True), ("0", False), ("no", False)])
def test_cache_enabled_truthy(monkeypatch: pytest.MonkeyPatch, val: str, expected: bool) -> None:
    monkeypatch.setenv("POLYGON_CACHE_ENABLED", val)
    assert cache_enabled() is expected


def test_cache_bypass_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POLYGON_CACHE_BYPASS", raising=False)
    assert cache_bypass() is False


def test_default_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    p = default_db_path()
    assert "polygon-news-mcp" in str(p)
    assert p.name == "cache.duckdb"


def test_state_root_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert state_root() == tmp_path


# ---------------------------------------------------------------------------
# Generic JSON-row tables (news, ticker_details, filings_index)
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


# ---------------------------------------------------------------------------
# TTL expiry
# ---------------------------------------------------------------------------


class TestTTLExpiry:
    def test_news_expired(self, cache: Cache) -> None:
        cache.put_news({"k": 1}, {"x": 1})
        assert cache._conn is not None
        old = (datetime.now(tz=UTC).replace(tzinfo=None)) - timedelta(hours=2)
        cache._conn.execute("UPDATE news_cache SET fetched_at = ?", [old])
        assert cache.get_news({"k": 1}) is None

    def test_ticker_details_expired(self, cache: Cache) -> None:
        cache.put_ticker_details({"ticker": "X"}, {"x": 1})
        assert cache._conn is not None
        old = (datetime.now(tz=UTC).replace(tzinfo=None)) - timedelta(hours=25)
        cache._conn.execute("UPDATE ticker_details_cache SET fetched_at = ?", [old])
        assert cache.get_ticker_details({"ticker": "X"}) is None

    def test_filings_index_expired(self, cache: Cache) -> None:
        cache.put_filings_index({"k": 1}, {"x": 1})
        assert cache._conn is not None
        old = (datetime.now(tz=UTC).replace(tzinfo=None)) - timedelta(hours=7)
        cache._conn.execute("UPDATE filings_index_cache SET fetched_at = ?", [old])
        assert cache.get_filings_index({"k": 1}) is None


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_empty(self, cache: Cache) -> None:
        s = cache.get_stats()
        assert isinstance(s, CacheStats)
        assert s.hits_24h == 0
        assert s.misses_24h == 0
        assert s.hit_rate_24h is None

    def test_hit_recorded(self, cache: Cache) -> None:
        cache.put_news({"k": 1}, {"x": 1})
        cache.get_news({"k": 1})  # hit
        cache.get_news({"k": 99})  # miss
        s = cache.get_stats()
        assert s.hits_24h >= 1
        assert s.misses_24h >= 1
        assert s.hit_rate_24h is not None

    def test_to_dict_shape(self, cache: Cache) -> None:
        d = cache.get_stats().to_dict()
        for key in (
            "db_path",
            "enabled",
            "size_mb",
            "rows_per_table",
            "expired_rows",
            "hit_rate_24h",
            "hits_24h",
            "misses_24h",
        ):
            assert key in d


# ---------------------------------------------------------------------------
# Reset / corruption isolation
# ---------------------------------------------------------------------------


def test_reset_drops_rows(cache: Cache) -> None:
    cache.put_news({"k": 1}, {"x": 1})
    cache.reset()
    assert cache.get_news({"k": 1}) is None


def test_corrupt_db_quarantined(tmp_path: Path) -> None:
    db = tmp_path / "cache.duckdb"
    db.write_bytes(b"this is not a valid duckdb file" * 1000)
    cache = Cache(db)
    assert any(p.name.startswith("cache.duckdb.corrupt-") for p in tmp_path.iterdir())
    cache.put_news({"k": 1}, {"x": 1})
    assert cache.get_news({"k": 1}) is not None
    cache.close()


def test_close_idempotent(cache: Cache) -> None:
    cache.close()
    cache.close()


def test_context_manager(tmp_path: Path) -> None:
    with Cache(tmp_path / "ctx.duckdb") as c:
        c.put_news({"q": "x"}, {"y": 1})
        assert c.get_news({"q": "x"}) is not None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


def test_singleton_disabled_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLYGON_CACHE_ENABLED", "0")
    reset_cache_singleton()
    assert get_cache() is None


def test_singleton_enabled_returns_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("POLYGON_CACHE_ENABLED", "1")
    reset_cache_singleton()
    a = get_cache()
    b = get_cache()
    assert a is b


# ---------------------------------------------------------------------------
# Error paths — DuckDB connection lost
# ---------------------------------------------------------------------------


def test_get_when_connection_lost(cache: Cache) -> None:
    cache._conn = None
    assert cache.get_news({"k": 1}) is None
    assert cache.get_ticker_details({"k": 1}) is None
    assert cache.get_filings_index({"k": 1}) is None
    cache.put_news({"k": 1}, {"x": 1})  # no-op


def test_count_expired_unknown_table(cache: Cache) -> None:
    assert cache._count_expired("not_a_table") == 0


def test_db_open_error_does_not_propagate(tmp_path: Path) -> None:
    bad = tmp_path / "dirpath"
    bad.mkdir()
    c = Cache(bad)
    assert isinstance(c, Cache)


def test_duckdb_imports() -> None:
    assert hasattr(duckdb, "connect")
