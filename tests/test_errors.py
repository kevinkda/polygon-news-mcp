"""Unit tests for polygon_news_mcp.errors."""

from __future__ import annotations

import pytest

from polygon_news_mcp.errors import (
    PolygonAuthError,
    PolygonConfigurationError,
    PolygonError,
    PolygonNotFoundError,
    PolygonRateLimitError,
    PolygonTransientError,
    PolygonValidationError,
    redact_secret,
)


class TestRedactSecret:
    def test_redacts_apikey_query(self) -> None:
        out = redact_secret("https://api.polygon.io/v2/x?apiKey=ABC123XYZ&other=1")
        assert "ABC123XYZ" not in out
        assert "REDACTED" in out
        assert "other=1" in out

    def test_redacts_bearer_token(self) -> None:
        out = redact_secret("Authorization: Bearer abc123_supersecret_token")
        assert "abc123_supersecret_token" not in out
        assert "REDACTED" in out

    def test_idempotent(self) -> None:
        once = redact_secret("?apiKey=SECRET123")
        twice = redact_secret(once)
        assert once == twice

    def test_no_secret_unchanged(self) -> None:
        text = "no secrets here"
        assert redact_secret(text) == text

    def test_redacts_multiple(self) -> None:
        out = redact_secret("?apiKey=A1 and Bearer B2tokenmoretext")
        assert "A1" not in out
        assert "B2tokenmoretext" not in out


class TestPolygonValidationError:
    def test_round_trip(self) -> None:
        err = PolygonValidationError(field="ticker", reason="bad ?apiKey=SECRET inside")
        assert err.field == "ticker"
        assert "SECRET" not in str(err)
        assert "REDACTED" in err.reason

    def test_field_must_be_str(self) -> None:
        with pytest.raises(TypeError):
            PolygonValidationError(field=123, reason="x")  # type: ignore[arg-type]

    def test_reason_must_be_str(self) -> None:
        with pytest.raises(TypeError):
            PolygonValidationError(field="x", reason=123)  # type: ignore[arg-type]


class TestPolygonAuthError:
    def test_round_trip(self) -> None:
        err = PolygonAuthError(status_code=401, hint="unauthorized")
        assert err.status_code == 401
        assert "unauthorized" in str(err)

    def test_status_code_must_be_int(self) -> None:
        with pytest.raises(TypeError):
            PolygonAuthError(status_code="401", hint="x")  # type: ignore[arg-type]

    def test_hint_must_be_str(self) -> None:
        with pytest.raises(TypeError):
            PolygonAuthError(status_code=401, hint=1)  # type: ignore[arg-type]


class TestPolygonNotFoundError:
    def test_round_trip(self) -> None:
        err = PolygonNotFoundError(resource="ticker:AAPL", hint="no such ticker")
        assert err.resource == "ticker:AAPL"
        assert "no such ticker" in str(err)

    def test_resource_must_be_str(self) -> None:
        with pytest.raises(TypeError):
            PolygonNotFoundError(resource=1, hint="x")  # type: ignore[arg-type]

    def test_hint_must_be_str(self) -> None:
        with pytest.raises(TypeError):
            PolygonNotFoundError(resource="x", hint=1)  # type: ignore[arg-type]


class TestPolygonRateLimitError:
    def test_round_trip(self) -> None:
        err = PolygonRateLimitError(retry_after_seconds=5, plan_hint="free tier 5/min")
        assert err.retry_after_seconds == 5
        assert "5s" in str(err) or "retry_after=5" in str(err)

    def test_int_required(self) -> None:
        with pytest.raises(TypeError):
            PolygonRateLimitError(retry_after_seconds="5", plan_hint="x")  # type: ignore[arg-type]

    def test_plan_hint_must_be_str(self) -> None:
        with pytest.raises(TypeError):
            PolygonRateLimitError(retry_after_seconds=5, plan_hint=1)  # type: ignore[arg-type]


class TestPolygonTransientError:
    def test_round_trip(self) -> None:
        err = PolygonTransientError(status_code=503, attempt=2, hint="upstream busy")
        assert err.status_code == 503
        assert err.attempt == 2

    def test_types(self) -> None:
        with pytest.raises(TypeError):
            PolygonTransientError(status_code="503", attempt=1, hint="x")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            PolygonTransientError(status_code=503, attempt="1", hint="x")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            PolygonTransientError(status_code=503, attempt=1, hint=1)  # type: ignore[arg-type]


class TestPolygonConfigurationError:
    def test_round_trip(self) -> None:
        err = PolygonConfigurationError(hint="set POLYGON_API_KEY in .env")
        assert "POLYGON_API_KEY" in str(err)

    def test_redacts_apikey_in_hint(self) -> None:
        err = PolygonConfigurationError(hint="paste this URL: ?apiKey=SECRET to test")
        assert "SECRET" not in str(err)

    def test_hint_must_be_str(self) -> None:
        with pytest.raises(TypeError):
            PolygonConfigurationError(hint=123)  # type: ignore[arg-type]


def test_polygon_error_is_exception_subclass() -> None:
    assert issubclass(PolygonError, Exception)
    assert issubclass(PolygonValidationError, PolygonError)
    assert issubclass(PolygonAuthError, PolygonError)
    assert issubclass(PolygonNotFoundError, PolygonError)
    assert issubclass(PolygonRateLimitError, PolygonError)
    assert issubclass(PolygonTransientError, PolygonError)
    assert issubclass(PolygonConfigurationError, PolygonError)
