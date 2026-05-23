"""Pydantic v2 input schemas for every outward-facing tool.

Polygon.io accepts US-style stock tickers (uppercase letters with optional
``.``, ``-``, ``/``).  We validate strictly because Polygon's matching is
exact-case and an unsanitised lower-case symbol would yield 404.

Coverage target: **100 %**.
"""

from __future__ import annotations

import re
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

# ---------------------------------------------------------------------------
# Regexes — anchored to prevent partial-match Pydantic search semantics.
# ---------------------------------------------------------------------------

#: US stock ticker — uppercase letters, dot, dash, slash; 1-10 chars.
TICKER_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Z][A-Z0-9.\-/]{0,9}$")


# ---------------------------------------------------------------------------
# Constrained string types
# ---------------------------------------------------------------------------

Ticker = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=10,
    ),
]


# ---------------------------------------------------------------------------
# Base — strict-by-default mixin
# ---------------------------------------------------------------------------


class _BaseInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        frozen=True,
    )


def _normalise_ticker(value: object) -> object:
    if isinstance(value, str):
        v = value.strip().upper()
        if not TICKER_RE.match(v):
            from .errors import PolygonValidationError

            raise PolygonValidationError(
                field="ticker",
                reason=f"must match {TICKER_RE.pattern}",
            )
        return v
    return value


# ---------------------------------------------------------------------------
# Concrete schemas — one per tool.
# ---------------------------------------------------------------------------


class GetTickerNewsInput(_BaseInput):
    """Input for ``get_ticker_news``."""

    ticker: Ticker
    limit: int = Field(default=10, ge=1, le=1000)
    since_days: int = Field(default=7, ge=1, le=365)

    @field_validator("ticker", mode="before")
    @classmethod
    def _upper_ticker(cls, v: object) -> object:
        return _normalise_ticker(v)


class GetMarketNewsInput(_BaseInput):
    """Input for ``get_market_news``."""

    limit: int = Field(default=20, ge=1, le=1000)
    since_hours: int = Field(default=24, ge=1, le=720)


class GetTickerDetailsInput(_BaseInput):
    """Input for ``get_ticker_details``."""

    ticker: Ticker

    @field_validator("ticker", mode="before")
    @classmethod
    def _upper_ticker(cls, v: object) -> object:
        return _normalise_ticker(v)


class ListSecFilingsIndexInput(_BaseInput):
    """Input for ``list_sec_filings_index``."""

    ticker: Ticker
    since_days: int = Field(default=90, ge=1, le=365)

    @field_validator("ticker", mode="before")
    @classmethod
    def _upper_ticker(cls, v: object) -> object:
        return _normalise_ticker(v)


class HealthCheckInput(_BaseInput):
    """Input for ``health_check`` — empty."""


class GetServerInfoInput(_BaseInput):
    """Input for ``get_server_info`` — empty."""


# ---------------------------------------------------------------------------
# v0.2 — Sprint C schemas
# ---------------------------------------------------------------------------


class GetNewsSentimentAggregateInput(_BaseInput):
    """Input for ``get_news_sentiment_aggregate``.

    Aggregates the ``insights[].sentiment`` annotations on Polygon news
    articles over a fixed look-back window to produce a single per-ticker
    sentiment summary (distribution, weighted score, top publishers,
    significant articles).

    The aggregation re-uses the existing ``get_ticker_news`` cache, so
    this tool issues at most one upstream Polygon request per
    ``(ticker, window_days)`` pair within the news cache TTL.
    """

    ticker: Ticker
    window_days: Literal[1, 7, 30] = 7

    @field_validator("ticker", mode="before")
    @classmethod
    def _upper_ticker(cls, v: object) -> object:
        return _normalise_ticker(v)


class GetDividendsInput(_BaseInput):
    """Input for ``get_dividends``.

    Polygon endpoint: ``GET /v3/reference/dividends?ticker=...``.

    ``dividend_type`` mirrors Polygon's filter values (``"CD"`` / ``"SC"``
    / ``""``).  We accept user-friendly synonyms (``regular`` / ``special``
    / ``unspecified`` / ``all``) and translate them inside the tool layer.
    """

    ticker: Ticker
    since_days: int = Field(default=365, ge=1, le=3650)
    dividend_type: Literal["all", "regular", "special", "unspecified"] = "all"

    @field_validator("ticker", mode="before")
    @classmethod
    def _upper_ticker(cls, v: object) -> object:
        return _normalise_ticker(v)


# ---------------------------------------------------------------------------
# Tool registry — lets ``get_server_info`` enumerate tools without importing
# the server module (avoids a circular import in __init__).
# ---------------------------------------------------------------------------

_SUPPORTED_TOOLS: Final[tuple[str, ...]] = (
    "get_ticker_news",
    "get_market_news",
    "get_ticker_details",
    "list_sec_filings_index",
    "get_news_sentiment_aggregate",
    "get_dividends",
    "health_check",
    "get_server_info",
)


def supported_tool_names() -> list[str]:
    """Stable list of tool names the server exposes."""
    return list(_SUPPORTED_TOOLS)


__all__ = [
    "TICKER_RE",
    "GetDividendsInput",
    "GetMarketNewsInput",
    "GetNewsSentimentAggregateInput",
    "GetServerInfoInput",
    "GetTickerDetailsInput",
    "GetTickerNewsInput",
    "HealthCheckInput",
    "ListSecFilingsIndexInput",
    "Ticker",
    "supported_tool_names",
]
