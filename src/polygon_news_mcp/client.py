"""Async httpx wrapper for Polygon.io.

Polygon.io rate limits:

* Free tier — **5 requests per minute** (very strict).
* Starter ($29/mo) — 5x free tier.
* Developer ($79/mo) — much higher.

We implement a sliding **60-second window** token bucket and default to
``5 req/min`` (the free-tier ceiling).  Operators on a paid plan can raise
the budget via ``POLYGON_RATE_LIMIT_PER_MIN``; an absolute hard cap of
1000 req/min protects against typo'd large values.

Required behaviour:

* API key is mandatory.  We refuse to issue requests without
  ``POLYGON_API_KEY`` set.
* Token-bucket rate limiter (sliding 60-second window) — tokens replenish
  smoothly, do **not** hold a slot across retry sleeps.
* The API key is sent via the ``Authorization: Bearer ...`` header (the
  request URL never contains the key, so logs / exception text cannot
  accidentally echo it).
* Errors are normalised:
    - 401/403 → :class:`PolygonAuthError`
    - 404     → :class:`PolygonNotFoundError`
    - 429     → :class:`PolygonRateLimitError`
    - 5xx / network → :class:`PolygonTransientError` (retried with backoff)
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from collections import deque
from typing import Any, Final

import httpx

from .errors import (
    PolygonAuthError,
    PolygonConfigurationError,
    PolygonNotFoundError,
    PolygonRateLimitError,
    PolygonTransientError,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration knobs
# ---------------------------------------------------------------------------

#: Hard ceiling regardless of operator override (defends against typos).
POLYGON_HARD_RATE_LIMIT_PER_MIN: Final[int] = 1000

#: Default target rate (free-tier safe).
DEFAULT_RATE_LIMIT_PER_MIN: Final[int] = 5

DEFAULT_MAX_RETRIES_429: Final[int] = 2
DEFAULT_MAX_RETRIES_5XX: Final[int] = 3
DEFAULT_BACKOFF_BASE_SEC: Final[float] = 0.5
DEFAULT_REQUEST_TIMEOUT_SEC: Final[float] = 30.0

ENV_API_KEY: Final[str] = "POLYGON_API_KEY"
ENV_RATE_LIMIT: Final[str] = "POLYGON_RATE_LIMIT_PER_MIN"
ENV_BASE_URL: Final[str] = "POLYGON_BASE_URL"

# ---------------------------------------------------------------------------
# Hosts
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL: Final[str] = "https://api.polygon.io"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def resolve_api_key() -> str:
    """Return the configured API key or raise :class:`PolygonConfigurationError`.

    The returned value is **never** logged or written into structured
    exception fields.
    """
    raw = os.environ.get(ENV_API_KEY, "").strip()
    if not raw:
        raise PolygonConfigurationError(
            hint=(
                f"{ENV_API_KEY} is not set.  Polygon.io requires an API key "
                "on every request.  Sign up for a free account at "
                "https://polygon.io/dashboard/api-keys and put the key in "
                ".env as POLYGON_API_KEY=...."
            ),
        )
    return raw


def resolve_rate_limit() -> int:
    """Return the active per-minute rate limit (≤ ``POLYGON_HARD_RATE_LIMIT_PER_MIN``)."""
    target = _env_int(ENV_RATE_LIMIT, DEFAULT_RATE_LIMIT_PER_MIN)
    target = max(target, 1)
    if target > POLYGON_HARD_RATE_LIMIT_PER_MIN:
        log.warning(
            '{"event":"rate_limit_clamped","requested":%d,"max":%d}',
            target,
            POLYGON_HARD_RATE_LIMIT_PER_MIN,
        )
        target = POLYGON_HARD_RATE_LIMIT_PER_MIN
    return target


def resolve_base_url() -> str:
    """Return the active Polygon base URL.

    Override via ``POLYGON_BASE_URL`` (used by integration tests).
    """
    raw = os.environ.get(ENV_BASE_URL, "").strip()
    if raw:
        return raw.rstrip("/")
    return DEFAULT_BASE_URL


# ---------------------------------------------------------------------------
# Token-bucket rate limiter (sliding 60-second window).
# ---------------------------------------------------------------------------


class TokenBucket:
    """Sliding-N-second token bucket.

    We track outbound timestamps in a deque; before each request we evict
    timestamps older than ``window_seconds`` and, if the deque is at
    capacity, sleep until the oldest one ages out.  This gives us a smooth
    ≤capacity req per window without holding the slot across retry sleeps
    (we record the timestamp **after** the request is admitted).
    """

    def __init__(self, capacity: int, window_seconds: float = 60.0) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self.capacity: int = capacity
        self.window_seconds: float = window_seconds
        self._timestamps: deque[float] = deque()
        self._lock: asyncio.Lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._timestamps and (now - self._timestamps[0]) >= self.window_seconds:
                    self._timestamps.popleft()
                if len(self._timestamps) < self.capacity:
                    self._timestamps.append(now)
                    return
                wait = self.window_seconds - (now - self._timestamps[0])
                if wait <= 0:  # pragma: no cover - unreachable: eviction at >=window guarantees wait>0
                    continue
                await asyncio.sleep(wait)

    def tokens_remaining(self) -> int:
        """Best-effort current-window headroom (no eviction; for stats only)."""
        now = time.monotonic()
        live = sum(1 for ts in self._timestamps if (now - ts) < self.window_seconds)
        return max(0, self.capacity - live)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class PolygonClient:
    """Async Polygon.io client with rate limiting and structured errors.

    One instance per process.  Construct via :func:`make_client` so the
    API key / rate-limit / timeout knobs are pulled from env.
    """

    def __init__(
        self,
        *,
        api_key: str,
        rate_limit_per_min: int,
        base_url: str = DEFAULT_BASE_URL,
        timeout_sec: float = DEFAULT_REQUEST_TIMEOUT_SEC,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key: str = api_key
        self.base_url: str = base_url.rstrip("/")
        self.bucket: TokenBucket = TokenBucket(rate_limit_per_min, window_seconds=60.0)
        self._client: httpx.AsyncClient = httpx.AsyncClient(
            timeout=timeout_sec,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate",
                "User-Agent": "polygon-news-mcp",
            },
            transport=transport,
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> PolygonClient:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        del exc_type, exc, tb
        await self.aclose()

    # ------------------------------------------------------------ requests

    def _abs_url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    async def _request_with_retries(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Issue a single HTTP request with retries, rate limit, and error mapping."""
        last_exc: Exception | None = None
        for attempt in range(DEFAULT_MAX_RETRIES_5XX + 1):
            await self.bucket.acquire()
            try:
                resp = await self._client.request(method, url, params=params)
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ReadError) as exc:
                last_exc = exc
                if attempt >= DEFAULT_MAX_RETRIES_5XX:
                    raise PolygonTransientError(
                        status_code=0,
                        attempt=attempt,
                        hint=f"network error: {type(exc).__name__}",
                    ) from exc
                await asyncio.sleep(_backoff_delay(attempt))
                continue

            if resp.status_code == 200:
                return resp
            if resp.status_code in (401, 403):
                raise PolygonAuthError(
                    status_code=resp.status_code,
                    hint=(
                        "Polygon rejected the API key (status "
                        f"{resp.status_code}).  Verify POLYGON_API_KEY is "
                        "valid and the endpoint is included in your plan."
                    ),
                )
            if resp.status_code == 404:
                raise PolygonNotFoundError(
                    resource=url,
                    hint=f"Polygon returned 404 for {url}",
                )
            if resp.status_code == 429:
                if attempt >= DEFAULT_MAX_RETRIES_429:
                    retry_after = _parse_retry_after(resp)
                    raise PolygonRateLimitError(
                        retry_after_seconds=retry_after,
                        plan_hint=(
                            "Polygon free tier is 5 req/min; if you hit this "
                            "regularly, upgrade your plan or lower "
                            "POLYGON_RATE_LIMIT_PER_MIN."
                        ),
                    )
                await asyncio.sleep(_parse_retry_after(resp))
                continue
            if 500 <= resp.status_code < 600:
                if attempt >= DEFAULT_MAX_RETRIES_5XX:
                    raise PolygonTransientError(
                        status_code=resp.status_code,
                        attempt=attempt,
                        hint=f"upstream {resp.status_code}",
                    )
                await asyncio.sleep(_backoff_delay(attempt))
                continue
            # Other 4xx — non-retryable, surface as transient with attempt=0.
            raise PolygonTransientError(
                status_code=resp.status_code,
                attempt=attempt,
                hint=f"unexpected {resp.status_code}",
            )

        # Should be unreachable — every loop branch either returns or raises.
        raise PolygonTransientError(  # pragma: no cover - defensive
            status_code=0,
            attempt=DEFAULT_MAX_RETRIES_5XX,
            hint=f"retry budget exhausted: {last_exc!r}",
        )

    # ---------------------------------------------------------------- API

    async def get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """GET ``base_url + path`` and parse as JSON.

        ``path`` may be either a path (``/v2/reference/news``) or a
        full URL (used by pagination ``next_url`` cursors).
        """
        url = self._abs_url(path)
        resp = await self._request_with_retries("GET", url, params=params)
        try:
            data = resp.json()
        except ValueError as exc:
            raise PolygonTransientError(
                status_code=resp.status_code,
                attempt=0,
                hint=f"invalid json from {path}",
            ) from exc
        if not isinstance(data, (dict, list)):
            raise PolygonTransientError(
                status_code=resp.status_code,
                attempt=0,
                hint=f"unexpected json shape from {path}",
            )
        if isinstance(data, list):
            return {"items": data}
        return data


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _parse_retry_after(resp: httpx.Response) -> int:
    raw = resp.headers.get("Retry-After", "")
    try:
        v = int(raw)
        return max(0, min(v, 120))
    except ValueError:
        return 1


def _backoff_delay(attempt: int) -> float:
    """Exponential back-off with jitter."""
    base = DEFAULT_BACKOFF_BASE_SEC * (2**attempt)
    return float(base + random.random() * 0.25)


def make_client(transport: httpx.AsyncBaseTransport | None = None) -> PolygonClient:
    """Build a configured :class:`PolygonClient` from env."""
    return PolygonClient(
        api_key=resolve_api_key(),
        rate_limit_per_min=resolve_rate_limit(),
        base_url=resolve_base_url(),
        transport=transport,
    )


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MAX_RETRIES_5XX",
    "DEFAULT_MAX_RETRIES_429",
    "DEFAULT_RATE_LIMIT_PER_MIN",
    "DEFAULT_REQUEST_TIMEOUT_SEC",
    "ENV_API_KEY",
    "ENV_BASE_URL",
    "ENV_RATE_LIMIT",
    "POLYGON_HARD_RATE_LIMIT_PER_MIN",
    "PolygonClient",
    "TokenBucket",
    "make_client",
    "resolve_api_key",
    "resolve_base_url",
    "resolve_rate_limit",
]
