"""Meta tools: ``health_check``, ``get_server_info``, ``get_cache_stats``.

These are local-only — they never touch Polygon.io so they remain available
even when ``POLYGON_API_KEY`` is unset.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import mcp

from ..cache import cache_enabled, get_cache
from ..client import (
    ENV_API_KEY,
    POLYGON_HARD_RATE_LIMIT_PER_MIN,
    resolve_rate_limit,
)
from ..errors import PolygonConfigurationError
from ..models import supported_tool_names

# Captured at import time so health_check stays offline-safe.
_SERVER_VERSION: str | None = None


def _safe_api_key_status() -> dict[str, Any]:
    """Check API key without raising into the caller.

    We deliberately do NOT include the key value in the response — only a
    boolean ``configured`` flag and a redacted reason string.
    """
    raw = os.environ.get(ENV_API_KEY, "").strip()
    if not raw:
        return {"configured": False, "reason": "missing"}
    try:
        from ..client import resolve_api_key

        resolve_api_key()
    except (
        PolygonConfigurationError
    ) as exc:  # pragma: no cover - resolve_api_key only raises on empty key (guarded above)
        return {"configured": False, "reason": exc.hint}
    return {"configured": True, "reason": None}


def _safe_cache_summary() -> dict[str, Any]:
    if not cache_enabled():
        return {"enabled": False, "backend": None, "entries": 0}
    cache = get_cache()
    if cache is None:
        return {"enabled": False, "backend": None, "entries": 0}
    try:
        stats = cache.get_stats()
    except Exception:
        return {"enabled": True, "backend": None, "entries": 0}
    return {
        "enabled": stats.enabled,
        "backend": stats.backend,
        "entries": stats.entries,
    }


async def health_check_impl() -> dict[str, Any]:
    """Local health probe — never calls Polygon."""
    api = _safe_api_key_status()
    cache_summary = _safe_cache_summary()
    return {
        "server_version": _SERVER_VERSION,
        "api_key_configured": api["configured"],
        "api_key_reason": api["reason"],
        "rate_limit_per_min": resolve_rate_limit() if api["configured"] else None,
        "rate_limit_hard_cap_per_min": POLYGON_HARD_RATE_LIMIT_PER_MIN,
        "cache_enabled": cache_summary["enabled"],
        "cache_backend": cache_summary["backend"],
        "cache_entries": cache_summary["entries"],
        "platform_supported": True,
    }


async def get_server_info_impl(*, server_version: str) -> dict[str, Any]:
    """Local server metadata — version + tool list.  Never calls Polygon."""
    global _SERVER_VERSION
    _SERVER_VERSION = server_version
    return {
        "server_version": server_version,
        "mcp_sdk_version": getattr(mcp, "__version__", "unknown"),
        "python_version": (f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"),
        "supported_tools": supported_tool_names(),
        "platform_supported_v1": ["macos>=11", "linux"],
    }


async def get_cache_stats_impl() -> dict[str, Any]:
    """Local cache backend health — never calls Polygon."""
    cache = get_cache()
    if cache is None:
        return {
            "backend": None,
            "enabled": False,
            "entries": 0,
        }
    try:
        return cache.get_stats().to_dict()
    except Exception as exc:  # pragma: no cover
        return {
            "backend": cache.backend.name,
            "enabled": True,
            "entries": 0,
            "error": type(exc).__name__,
        }


__all__ = ["get_cache_stats_impl", "get_server_info_impl", "health_check_impl"]
