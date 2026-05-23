"""Unit tests for polygon_news_mcp.models — Pydantic v2 input schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from polygon_news_mcp.errors import PolygonValidationError
from polygon_news_mcp.models import (
    GetMarketNewsInput,
    GetTickerDetailsInput,
    GetTickerNewsInput,
    ListSecFilingsIndexInput,
    supported_tool_names,
)


class TestGetTickerNewsInput:
    def test_ticker_uppercased(self) -> None:
        v = GetTickerNewsInput(ticker="aapl")
        assert v.ticker == "AAPL"

    def test_default_limit_and_since_days(self) -> None:
        v = GetTickerNewsInput(ticker="AAPL")
        assert v.limit == 10
        assert v.since_days == 7

    def test_garbage_ticker_rejected(self) -> None:
        with pytest.raises((ValidationError, PolygonValidationError)):
            GetTickerNewsInput(ticker="aap!l")

    def test_empty_ticker_rejected(self) -> None:
        with pytest.raises((ValidationError, PolygonValidationError)):
            GetTickerNewsInput(ticker="")

    def test_too_long_ticker_rejected(self) -> None:
        with pytest.raises((ValidationError, PolygonValidationError)):
            GetTickerNewsInput(ticker="A" * 11)

    def test_limit_bounds(self) -> None:
        with pytest.raises(ValidationError):
            GetTickerNewsInput(ticker="AAPL", limit=0)
        with pytest.raises(ValidationError):
            GetTickerNewsInput(ticker="AAPL", limit=1001)

    def test_since_days_bounds(self) -> None:
        with pytest.raises(ValidationError):
            GetTickerNewsInput(ticker="AAPL", since_days=0)
        with pytest.raises(ValidationError):
            GetTickerNewsInput(ticker="AAPL", since_days=366)

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            GetTickerNewsInput(ticker="AAPL", extra="x")  # type: ignore[call-arg]


class TestGetMarketNewsInput:
    def test_default(self) -> None:
        v = GetMarketNewsInput()
        assert v.limit == 20
        assert v.since_hours == 24

    def test_limit_bounds(self) -> None:
        with pytest.raises(ValidationError):
            GetMarketNewsInput(limit=0)
        with pytest.raises(ValidationError):
            GetMarketNewsInput(limit=1001)

    def test_since_hours_bounds(self) -> None:
        with pytest.raises(ValidationError):
            GetMarketNewsInput(since_hours=0)
        with pytest.raises(ValidationError):
            GetMarketNewsInput(since_hours=721)

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            GetMarketNewsInput(bad="x")  # type: ignore[call-arg]


class TestGetTickerDetailsInput:
    def test_uppercase(self) -> None:
        v = GetTickerDetailsInput(ticker="msft")
        assert v.ticker == "MSFT"

    def test_garbage_rejected(self) -> None:
        with pytest.raises((ValidationError, PolygonValidationError)):
            GetTickerDetailsInput(ticker="!!!")

    def test_dot_dash_allowed(self) -> None:
        v = GetTickerDetailsInput(ticker="BRK.B")
        assert v.ticker == "BRK.B"


class TestListSecFilingsIndexInput:
    def test_default(self) -> None:
        v = ListSecFilingsIndexInput(ticker="AAPL")
        assert v.since_days == 90

    def test_since_days_bounds(self) -> None:
        with pytest.raises(ValidationError):
            ListSecFilingsIndexInput(ticker="AAPL", since_days=0)
        with pytest.raises(ValidationError):
            ListSecFilingsIndexInput(ticker="AAPL", since_days=366)

    def test_garbage_rejected(self) -> None:
        with pytest.raises((ValidationError, PolygonValidationError)):
            ListSecFilingsIndexInput(ticker="bad ticker")


def test_supported_tool_names_stable() -> None:
    names = supported_tool_names()
    assert "get_ticker_news" in names
    assert "get_market_news" in names
    assert "get_ticker_details" in names
    assert "list_sec_filings_index" in names
    assert "health_check" in names
    assert "get_server_info" in names
    assert len(set(names)) == len(names)


def test_models_are_frozen() -> None:
    v = GetTickerNewsInput(ticker="AAPL")
    with pytest.raises(ValidationError):
        v.limit = 5  # type: ignore[misc]
