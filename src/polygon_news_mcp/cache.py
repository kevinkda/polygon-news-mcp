"""Pluggable response cache for Polygon.io data (v0.7 T0).

.. versionchanged:: 0.3.0
    ⚠️ **BREAKING** — the embedded DuckDB cache is removed.  The cache now
    delegates to a pluggable :class:`~polygon_news_mcp.cache_backend.CacheBackend`:

    * **memory** (default) — in-process LRU + TTL, zero external
      dependency, concurrency-safe, non-blocking (no global ``RLock``,
      no file locks).
    * **clickhouse** (opt-in) — ``pip install polygon-news-mcp[clickhouse]``
      + ``POLYGON_CLICKHOUSE_URL`` + ``POLYGON_CACHE_BACKEND=clickhouse``
      for derived-analysis history persistence.

    Selection via ``POLYGON_CACHE_BACKEND`` (``memory`` | ``clickhouse``,
    default ``memory``).  Derived-analysis history without ClickHouse
    degrades to a ``requires_clickhouse_persistence`` signal; core tools
    are unaffected.

TTLs (per task spec):
    * news_cache           — 1  h  (news feeds churn fast)
    * ticker_details_cache — 24 h  (reference data is stable)
    * filings_index_cache  — 6  h  (Polygon's SEC filings index)
    * dividends_cache      — 24 h  (dividends are declared on a slow cadence)

Failure mode: best-effort — every backend swallows storage errors and the
caller falls through to the live API.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from . import _platform
from .cache_backend import (
    CacheBackend,
    get_cache_backend,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_TTL_NEWS_S: Final[int] = 1 * 3600
DEFAULT_TTL_TICKER_DETAILS_S: Final[int] = 24 * 3600
DEFAULT_TTL_FILINGS_INDEX_S: Final[int] = 6 * 3600
DEFAULT_TTL_DIVIDENDS_S: Final[int] = 24 * 3600

CACHE_DIR_NAME: Final[str] = "polygon-news-mcp"

ENV_CACHE_ENABLED: Final[str] = "POLYGON_CACHE_ENABLED"
ENV_CACHE_BYPASS: Final[str] = "POLYGON_CACHE_BYPASS"

_NEWS_TABLE: Final[str] = "news_cache"
_TICKER_DETAILS_TABLE: Final[str] = "ticker_details_cache"
_FILINGS_INDEX_TABLE: Final[str] = "filings_index_cache"
_DIVIDENDS_TABLE: Final[str] = "dividends_cache"


def _truthy(raw: str | None, *, default: bool) -> bool:
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def cache_enabled() -> bool:
    """Honor ``POLYGON_CACHE_ENABLED`` (default off — opt-in).

    .. versionchanged:: 0.2.2
        cache now opt-in, default disabled.  Set ``POLYGON_CACHE_ENABLED=true``
        to re-enable the read-through cache.
    """
    return _truthy(os.environ.get(ENV_CACHE_ENABLED), default=False)


def cache_bypass() -> bool:
    """Honor ``POLYGON_CACHE_BYPASS`` (default off — single-call force fresh)."""
    return _truthy(os.environ.get(ENV_CACHE_BYPASS), default=False)


def state_root() -> Path:
    """Cross-platform state-directory root.

    Thin re-export of :func:`polygon_news_mcp._platform.state_root` kept for
    backwards compatibility with existing call sites (``server.py`` log dir).
    """
    return _platform.state_root()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash_params(params: dict[str, Any]) -> str:
    blob = json.dumps(params, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Stats payload
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CacheStats:
    backend: str
    enabled: bool
    entries: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "enabled": self.enabled,
            "entries": self.entries,
        }


# ---------------------------------------------------------------------------
# Cache facade
# ---------------------------------------------------------------------------


class Cache:
    """Backend-agnostic response cache.  One instance per process.

    Delegates all storage to a :class:`CacheBackend` (memory by default,
    ClickHouse when opted in).  The legacy per-table public API is kept so
    tools require no changes.
    """

    def __init__(self, backend: CacheBackend | None = None) -> None:
        self.backend: CacheBackend = backend if backend is not None else get_cache_backend()

    def close(self) -> None:
        # Pluggable backends own their own lifecycle; nothing to close for
        # the memory backend, and the ClickHouse client is process-scoped.
        return None

    def __enter__(self) -> Cache:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        del exc_type, exc, tb
        self.close()

    # ----------------------------------------------- generic JSON tables

    def _get(self, table: str, key: str) -> dict[str, Any] | None:
        return self.backend.get(table, key)

    def _put(self, table: str, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        self.backend.set(table, key, value, ttl_seconds)

    # ---------------------------------------------- per-table public APIs

    def get_news(self, params: dict[str, Any]) -> dict[str, Any] | None:
        return self._get(_NEWS_TABLE, _hash_params(params))

    def put_news(
        self,
        params: dict[str, Any],
        raw: dict[str, Any],
        *,
        ticker: str | None = None,
    ) -> None:
        del ticker  # retained for API compatibility; backend keys on params hash
        self._put(_NEWS_TABLE, _hash_params(params), raw, DEFAULT_TTL_NEWS_S)

    def get_ticker_details(self, params: dict[str, Any]) -> dict[str, Any] | None:
        return self._get(_TICKER_DETAILS_TABLE, _hash_params(params))

    def put_ticker_details(
        self,
        params: dict[str, Any],
        raw: dict[str, Any],
        *,
        ticker: str | None = None,
    ) -> None:
        del ticker
        self._put(_TICKER_DETAILS_TABLE, _hash_params(params), raw, DEFAULT_TTL_TICKER_DETAILS_S)

    def get_filings_index(self, params: dict[str, Any]) -> dict[str, Any] | None:
        return self._get(_FILINGS_INDEX_TABLE, _hash_params(params))

    def put_filings_index(
        self,
        params: dict[str, Any],
        raw: dict[str, Any],
        *,
        ticker: str | None = None,
    ) -> None:
        del ticker
        self._put(_FILINGS_INDEX_TABLE, _hash_params(params), raw, DEFAULT_TTL_FILINGS_INDEX_S)

    def get_dividends(self, params: dict[str, Any]) -> dict[str, Any] | None:
        return self._get(_DIVIDENDS_TABLE, _hash_params(params))

    def put_dividends(
        self,
        params: dict[str, Any],
        raw: dict[str, Any],
        *,
        ticker: str | None = None,
    ) -> None:
        del ticker
        self._put(_DIVIDENDS_TABLE, _hash_params(params), raw, DEFAULT_TTL_DIVIDENDS_S)

    # --------------------------------------------------------------- stats

    def get_stats(self) -> CacheStats:
        try:
            entries = self.backend.size()
        except Exception:
            entries = 0
        return CacheStats(
            backend=self.backend.name,
            enabled=cache_enabled(),
            entries=entries,
        )

    def reset(self) -> None:
        """Drop all rows.  Test-only convenience."""
        self.backend.clear()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_singleton: Cache | None = None
_singleton_lock = threading.Lock()


def get_cache() -> Cache | None:
    """Return the process-wide cache, or ``None`` if disabled."""
    if not cache_enabled():
        return None
    global _singleton
    if _singleton is not None:
        return _singleton
    with _singleton_lock:
        if _singleton is None:  # pragma: no branch - double-checked lock; race side not deterministically testable
            _singleton = Cache()
    return _singleton


def reset_cache_singleton() -> None:
    """Test helper — drop the singleton so the next call re-creates it."""
    global _singleton
    with _singleton_lock:
        if _singleton is not None:
            _singleton.close()
            _singleton = None


__all__ = [
    "CACHE_DIR_NAME",
    "DEFAULT_TTL_DIVIDENDS_S",
    "DEFAULT_TTL_FILINGS_INDEX_S",
    "DEFAULT_TTL_NEWS_S",
    "DEFAULT_TTL_TICKER_DETAILS_S",
    "ENV_CACHE_BYPASS",
    "ENV_CACHE_ENABLED",
    "Cache",
    "CacheStats",
    "cache_bypass",
    "cache_enabled",
    "get_cache",
    "reset_cache_singleton",
    "state_root",
]
