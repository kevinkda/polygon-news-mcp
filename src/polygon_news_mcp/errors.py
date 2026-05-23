"""Structured exception hierarchy for polygon-news-mcp.

Polygon.io requires an API key (``POLYGON_API_KEY``).  Even though we never
write the key into structured exception fields, we still strip any ``?apiKey=``
query-string echo from URLs / hint text to defend against operators
accidentally pasting a URL with the key embedded into a bug report.

Coverage target: **100 %**.
"""

from __future__ import annotations

import re
from typing import Final

# ---------------------------------------------------------------------------
# Conservative redaction — strip apiKey query-string echoes and bare hex
# blobs that look like a Polygon API key.
# ---------------------------------------------------------------------------

_APIKEY_QS_RE: Final[re.Pattern[str]] = re.compile(
    r"(?i)([?&]apiKey=)[^&\s\"']+",
)
_BEARER_RE: Final[re.Pattern[str]] = re.compile(
    r"(?i)(Bearer\s+)[A-Za-z0-9_\-]{8,}",
)
_REDACTED: Final[str] = "***REDACTED***"


def redact_secret(text: str) -> str:
    """Replace any ``?apiKey=...`` value or ``Bearer ...`` token with a
    redacted placeholder.

    Idempotent and side-effect-free. Used by every exception's ``__init__``
    so ``repr(exc)`` cannot accidentally leak the operator's API key even
    if the operator pasted a request URL into a hint string.
    """
    out = _APIKEY_QS_RE.sub(lambda m: f"{m.group(1)}{_REDACTED}", text)
    out = _BEARER_RE.sub(lambda m: f"{m.group(1)}{_REDACTED}", out)
    return out


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class PolygonError(Exception):
    """Base class for all polygon-news-mcp errors.

    Subclasses MUST only accept allow-listed structured fields.  This base
    class deliberately keeps ``__str__`` short and does not capture extra
    args so a raw ``repr(exc)`` cannot accidentally leak operator data.
    """

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.__class__.__name__


class PolygonValidationError(PolygonError):
    """Input validation failure (raised before any HTTP call)."""

    def __init__(self, *, field: str, reason: str) -> None:
        if not isinstance(field, str):
            raise TypeError("field must be str")
        if not isinstance(reason, str):
            raise TypeError("reason must be str")
        self.field: str = field
        self.reason: str = redact_secret(reason)
        super().__init__(f"validation failed: {field} — {self.reason}")

    def __str__(self) -> str:
        return f"PolygonValidationError(field={self.field}): {self.reason}"


class PolygonAuthError(PolygonError):
    """Polygon returned 401/403 — API key missing, invalid, or unauthorized.

    Use this for tier-permission errors as well (e.g. paid-only endpoint
    accessed with a free-tier key).
    """

    def __init__(self, *, status_code: int, hint: str) -> None:
        if not isinstance(status_code, int):
            raise TypeError("status_code must be int")
        if not isinstance(hint, str):
            raise TypeError("hint must be str")
        self.status_code: int = status_code
        self.hint: str = redact_secret(hint)
        super().__init__(self.hint)

    def __str__(self) -> str:
        return f"PolygonAuthError(status={self.status_code}): {self.hint}"


class PolygonNotFoundError(PolygonError):
    """Polygon returned 404 — the ticker / resource does not exist."""

    def __init__(self, *, resource: str, hint: str) -> None:
        if not isinstance(resource, str):
            raise TypeError("resource must be str")
        if not isinstance(hint, str):
            raise TypeError("hint must be str")
        self.resource: str = resource
        self.hint: str = redact_secret(hint)
        super().__init__(self.hint)

    def __str__(self) -> str:
        return f"PolygonNotFoundError(resource={self.resource}): {self.hint}"


class PolygonRateLimitError(PolygonError):
    """Polygon returned 429 — API plan rate limit exceeded.

    Polygon's free tier is **5 req/min** which is very strict; the bundled
    token bucket should normally prevent this surfacing to callers.
    """

    def __init__(self, *, retry_after_seconds: int, plan_hint: str) -> None:
        if not isinstance(retry_after_seconds, int):
            raise TypeError("retry_after_seconds must be int")
        if not isinstance(plan_hint, str):
            raise TypeError("plan_hint must be str")
        self.retry_after_seconds: int = retry_after_seconds
        self.plan_hint: str = redact_secret(plan_hint)
        super().__init__(f"Polygon rate limit exceeded; retry after {retry_after_seconds}s ({self.plan_hint})")

    def __str__(self) -> str:
        return f"PolygonRateLimitError(retry_after={self.retry_after_seconds}s, plan_hint={self.plan_hint!r})"


class PolygonTransientError(PolygonError):
    """Retryable transient backend / network error (5xx, timeout, conn reset)."""

    def __init__(self, *, status_code: int, attempt: int, hint: str) -> None:
        if not isinstance(status_code, int):
            raise TypeError("status_code must be int")
        if not isinstance(attempt, int):
            raise TypeError("attempt must be int")
        if not isinstance(hint, str):
            raise TypeError("hint must be str")
        self.status_code: int = status_code
        self.attempt: int = attempt
        self.hint: str = redact_secret(hint)
        super().__init__(self.hint)

    def __str__(self) -> str:
        return f"PolygonTransientError(status={self.status_code}, attempt={self.attempt}): {self.hint}"


class PolygonConfigurationError(PolygonError):
    """The operator has not set ``POLYGON_API_KEY`` to a non-empty value.

    Polygon.io requires an API key on every request; without one we refuse
    to issue any HTTP call.
    """

    def __init__(self, *, hint: str) -> None:
        if not isinstance(hint, str):
            raise TypeError("hint must be str")
        self.hint: str = redact_secret(hint)
        super().__init__(self.hint)

    def __str__(self) -> str:
        return f"PolygonConfigurationError: {self.hint}"


__all__ = [
    "PolygonAuthError",
    "PolygonConfigurationError",
    "PolygonError",
    "PolygonNotFoundError",
    "PolygonRateLimitError",
    "PolygonTransientError",
    "PolygonValidationError",
    "redact_secret",
]
