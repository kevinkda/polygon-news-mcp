"""Boundary-value security tests for polygon-news-mcp.

Probes the edges of every numeric and string input: minimum, maximum,
just below/above the limit, empty, single-char, and max-length.  Boundary
handling is where off-by-one validation bugs hide and where an attacker
probes for an unbounded fetch.  No empty-coverage padding.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from polygon_news_mcp.errors import PolygonValidationError
from polygon_news_mcp.models import (
    GetDividendsInput,
    GetMarketNewsInput,
    GetNewsSentimentAggregateInput,
    GetTickerDetailsInput,
    GetTickerNewsInput,
    ListSecFilingsIndexInput,
)

# ===========================================================================
# ticker_news limit (ge=1 le=1000) / since_days (ge=1 le=365)
# ===========================================================================


class TestTickerNewsBoundaries:
    def test_limit_min(self) -> None:
        assert GetTickerNewsInput(ticker="AAPL", limit=1).limit == 1

    def test_limit_max(self) -> None:
        assert GetTickerNewsInput(ticker="AAPL", limit=1000).limit == 1000

    def test_limit_below_min(self) -> None:
        with pytest.raises(ValidationError):
            GetTickerNewsInput(ticker="AAPL", limit=0)

    def test_limit_above_max(self) -> None:
        with pytest.raises(ValidationError):
            GetTickerNewsInput(ticker="AAPL", limit=1001)

    def test_since_days_min_max(self) -> None:
        assert GetTickerNewsInput(ticker="AAPL", since_days=1).since_days == 1
        assert GetTickerNewsInput(ticker="AAPL", since_days=365).since_days == 365

    def test_since_days_above_max(self) -> None:
        with pytest.raises(ValidationError):
            GetTickerNewsInput(ticker="AAPL", since_days=366)


# ===========================================================================
# market_news since_hours (ge=1 le=720)
# ===========================================================================


class TestMarketNewsBoundaries:
    def test_since_hours_min_max(self) -> None:
        assert GetMarketNewsInput(since_hours=1).since_hours == 1
        assert GetMarketNewsInput(since_hours=720).since_hours == 720

    def test_since_hours_above_max(self) -> None:
        with pytest.raises(ValidationError):
            GetMarketNewsInput(since_hours=721)

    def test_since_hours_zero(self) -> None:
        with pytest.raises(ValidationError):
            GetMarketNewsInput(since_hours=0)


# ===========================================================================
# ticker length (1-10 chars) + regex
# ===========================================================================


class TestTickerBoundaries:
    def test_single_char_ticker(self) -> None:
        assert GetTickerDetailsInput(ticker="F").ticker == "F"

    def test_max_len_ticker(self) -> None:
        assert GetTickerDetailsInput(ticker="ABCDEFGHIJ").ticker == "ABCDEFGHIJ"

    def test_overlength_ticker_rejected(self) -> None:
        with pytest.raises((ValidationError, PolygonValidationError)):
            GetTickerDetailsInput(ticker="ABCDEFGHIJK")  # 11 chars

    def test_empty_ticker_rejected(self) -> None:
        with pytest.raises((ValidationError, PolygonValidationError)):
            GetTickerDetailsInput(ticker="")

    def test_lowercase_upcased(self) -> None:
        assert GetTickerDetailsInput(ticker="aapl").ticker == "AAPL"

    def test_invalid_first_char_rejected(self) -> None:
        with pytest.raises((ValidationError, PolygonValidationError)):
            GetTickerDetailsInput(ticker="1ABC")  # must start with a letter


# ===========================================================================
# dividends since_days (ge=1 le=3650) + dividend_type literal
# ===========================================================================


class TestDividendsBoundaries:
    def test_since_days_min_max(self) -> None:
        assert GetDividendsInput(ticker="AAPL", since_days=1).since_days == 1
        assert GetDividendsInput(ticker="AAPL", since_days=3650).since_days == 3650

    def test_since_days_above_max(self) -> None:
        with pytest.raises(ValidationError):
            GetDividendsInput(ticker="AAPL", since_days=3651)

    def test_valid_dividend_types(self) -> None:
        for t in ("all", "regular", "special", "unspecified"):
            assert GetDividendsInput(ticker="AAPL", dividend_type=t).dividend_type == t  # type: ignore[arg-type]

    def test_invalid_dividend_type(self) -> None:
        with pytest.raises(ValidationError):
            GetDividendsInput(ticker="AAPL", dividend_type="bonus")  # type: ignore[arg-type]


# ===========================================================================
# sentiment window_days literal {1, 7, 30}
# ===========================================================================


class TestSentimentBoundaries:
    def test_valid_windows(self) -> None:
        for w in (1, 7, 30):
            assert GetNewsSentimentAggregateInput(ticker="AAPL", window_days=w).window_days == w  # type: ignore[arg-type]

    def test_invalid_window_rejected(self) -> None:
        for bad in (0, 2, 14, 31, 365):
            with pytest.raises(ValidationError):
                GetNewsSentimentAggregateInput(ticker="AAPL", window_days=bad)  # type: ignore[arg-type]


# ===========================================================================
# filings since_days (ge=1 le=365)
# ===========================================================================


class TestFilingsBoundaries:
    def test_since_days_min_max(self) -> None:
        assert ListSecFilingsIndexInput(ticker="AAPL", since_days=1).since_days == 1
        assert ListSecFilingsIndexInput(ticker="AAPL", since_days=365).since_days == 365

    def test_since_days_above_max(self) -> None:
        with pytest.raises(ValidationError):
            ListSecFilingsIndexInput(ticker="AAPL", since_days=366)


# ===========================================================================
# extra-field rejection (extra="forbid")
# ===========================================================================


class TestExtraFieldRejection:
    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GetTickerNewsInput(ticker="AAPL", evil_field="x")  # type: ignore[call-arg]

    def test_unknown_field_rejected_on_market_news(self) -> None:
        with pytest.raises(ValidationError):
            GetMarketNewsInput(injected=True)  # type: ignore[call-arg]
