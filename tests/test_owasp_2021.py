"""OWASP Top 10 — 2021 security test suite for polygon-news-mcp.

The 2021 edition adds A04 Insecure Design and A10 SSRF.  For polygon-news-mcp
the dominant concerns remain API-key confidentiality (A02), SSRF via the
ticker parameter (A10), and fail-closed design (A04).  Each test asserts a
concrete invariant — no empty-coverage padding.

Applicability map (2021):
  * A01 Broken Access Control — read-only tool surface; SSRF-shaped ticker rejected
  * A02 Cryptographic Failures — secure cache perms; API-key redaction
  * A03 Injection             — DuckDB bound params + strict ticker/literal enums
  * A04 Insecure Design       — fail-closed API key; free-tier rate cap; bounded limits
  * A05 Security Misconfig     — explicit cache defaults
  * A06 Vulnerable Components  — httpx/pydantic/duckdb declared
  * A07 Identification/AuthN   — API key required; key never echoed
  * A08 Software/Data Integrity— JSON shape validation; cache round-trip integrity
  * A09 Logging & Monitoring   — cache_events audit + JSON server log
  * A10 SSRF                   — ticker cannot redirect outbound Polygon host
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from polygon_news_mcp.cache import Cache

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src" / "polygon_news_mcp"
FAKE_KEY = "AbCdEf0123456789XyZ_secretkey"  # pragma: allowlist secret

SSRF_PAYLOADS = [
    "http://169.254.169.254/latest/meta-data/",
    "https://evil.example/steal",
    "file:///etc/passwd",
    "//evil.example/x",
    "localhost:8080",
    "127.0.0.1",
]


# ===========================================================================
# A01:2021 — Broken Access Control
# ===========================================================================


class TestA01AccessControl:
    @pytest.mark.asyncio
    async def test_tool_surface_is_read_only(self) -> None:
        from polygon_news_mcp.server import app

        for t in await app().list_tools():
            assert not any(v in t.name for v in ("create", "update", "delete", "write", "submit", "post"))

    def test_no_src_file_performs_http_write(self) -> None:
        import re

        pattern = re.compile(r"\.(post|put|delete|patch)\s*\(", re.IGNORECASE)
        offenders = [
            str(py.relative_to(REPO_ROOT)) for py in SRC_ROOT.rglob("*.py") if pattern.search(py.read_text("utf-8"))
        ]
        assert offenders == [], f"mutating HTTP verb present: {offenders}"


# ===========================================================================
# A02:2021 — Cryptographic Failures  (API-key confidentiality)
# ===========================================================================


class TestA02CryptographicFailures:
    def test_cache_file_owner_only_on_posix(self, tmp_path: Path) -> None:
        if sys.platform == "win32":
            pytest.skip("POSIX-only perm semantics")
        cache = Cache(db_path=tmp_path / "c.duckdb")
        try:
            assert stat.S_IMODE(os.stat(tmp_path / "c.duckdb").st_mode) == 0o600
        finally:
            cache.close()

    def test_api_key_never_logged_plaintext(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        from polygon_news_mcp.errors import PolygonTransientError

        log = logging.getLogger("polygon_news_mcp.test")
        with caplog.at_level(logging.WARNING, logger="polygon_news_mcp.test"):
            exc = PolygonTransientError(status_code=500, attempt=1, hint=f"failed ?apiKey={FAKE_KEY}")
            log.warning("transient: %s", exc)
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert FAKE_KEY not in str(exc)
        assert FAKE_KEY not in joined

    def test_api_key_not_written_into_structured_error_fields(self) -> None:
        """Even the raw resolve path never copies the key into an exception field."""
        from polygon_news_mcp.errors import PolygonAuthError

        exc = PolygonAuthError(status_code=403, hint=f"tier denied Bearer {FAKE_KEY}")
        # Only allow-listed fields exist; the key is redacted inside hint.
        assert FAKE_KEY not in exc.hint
        assert not hasattr(exc, "api_key")


# ===========================================================================
# A03:2021 — Injection
# ===========================================================================


class TestA03Injection:
    def test_duckdb_bound_params_block_sql_injection(self, tmp_path: Path) -> None:
        cache = Cache(db_path=tmp_path / "c.duckdb")
        try:
            payload = "'); DELETE FROM dividends_cache;--"
            cache.put_dividends({"k": payload}, {"v": payload})
            assert cache.get_dividends({"k": payload}) == {"v": payload}
        finally:
            cache.close()

    def test_window_days_constrained_to_literal(self) -> None:
        from pydantic import ValidationError

        from polygon_news_mcp.models import GetNewsSentimentAggregateInput

        with pytest.raises(ValidationError):
            GetNewsSentimentAggregateInput(ticker="AAPL", window_days=99)  # type: ignore[arg-type]

    def test_dividend_type_literal_blocks_injection(self) -> None:
        from pydantic import ValidationError

        from polygon_news_mcp.models import GetDividendsInput

        with pytest.raises(ValidationError):
            GetDividendsInput(ticker="AAPL", dividend_type="$(id)")  # type: ignore[arg-type]


# ===========================================================================
# A04:2021 — Insecure Design
# ===========================================================================


class TestA04InsecureDesign:
    def test_fail_closed_without_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from polygon_news_mcp.client import resolve_api_key
        from polygon_news_mcp.errors import PolygonConfigurationError

        monkeypatch.delenv("POLYGON_API_KEY", raising=False)
        with pytest.raises(PolygonConfigurationError):
            resolve_api_key()

    def test_free_tier_rate_cap_enforced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An operator override cannot exceed Polygon's hard per-minute cap."""
        from polygon_news_mcp.client import POLYGON_HARD_RATE_LIMIT_PER_MIN, resolve_rate_limit

        monkeypatch.setenv("POLYGON_RATE_LIMIT_PER_MIN", "100000")
        assert resolve_rate_limit() <= POLYGON_HARD_RATE_LIMIT_PER_MIN

    def test_limit_is_bounded(self) -> None:
        from pydantic import ValidationError

        from polygon_news_mcp.models import GetTickerNewsInput

        with pytest.raises(ValidationError):
            GetTickerNewsInput(ticker="AAPL", limit=10_000_000)


# ===========================================================================
# A05:2021 — Security Misconfiguration
# ===========================================================================


class TestA05Misconfiguration:
    def test_cache_defaults_are_explicit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from polygon_news_mcp.cache import cache_bypass, cache_enabled

        monkeypatch.delenv("POLYGON_CACHE_ENABLED", raising=False)
        monkeypatch.delenv("POLYGON_CACHE_BYPASS", raising=False)
        assert cache_enabled() is False
        assert cache_bypass() is False


# ===========================================================================
# A06:2021 — Vulnerable and Outdated Components
# ===========================================================================


class TestA06Components:
    def test_security_deps_declared(self) -> None:
        body = (REPO_ROOT / "pyproject.toml").read_text("utf-8")
        assert "httpx" in body and "pydantic" in body and "duckdb" in body


# ===========================================================================
# A07:2021 — Identification and Authentication Failures
# ===========================================================================


class TestA07AuthFailures:
    @pytest.mark.asyncio
    async def test_health_reports_auth_state_from_env_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from polygon_news_mcp.tools.meta import health_check_impl

        monkeypatch.delenv("POLYGON_API_KEY", raising=False)
        out = await health_check_impl()
        assert out["api_key_configured"] is False
        assert out["rate_limit_per_min"] is None  # no key → no live rate limit reported

    @pytest.mark.asyncio
    async def test_401_maps_to_auth_error(self, make_polygon_client) -> None:
        """A 401 from Polygon surfaces as a structured PolygonAuthError."""
        from polygon_news_mcp.errors import PolygonAuthError
        from tests.conftest import FakeRoute

        client = make_polygon_client([FakeRoute("/v2/x", status_code=401, json_body={"error": "unauthorized"})])
        with pytest.raises(PolygonAuthError):
            await client.get_json("/v2/x")


# ===========================================================================
# A08:2021 — Software and Data Integrity Failures
# ===========================================================================


class TestA08DataIntegrity:
    @pytest.mark.asyncio
    async def test_unexpected_json_shape_rejected(self, make_polygon_client) -> None:
        from polygon_news_mcp.errors import PolygonTransientError
        from tests.conftest import FakeRoute

        client = make_polygon_client([FakeRoute("/s", text_body='"str"', content_type="application/json")])
        with pytest.raises(PolygonTransientError):
            await client.get_json("/s")

    def test_cache_roundtrip_integrity(self, tmp_path: Path) -> None:
        cache = Cache(db_path=tmp_path / "c.duckdb")
        try:
            payload = {"results": [{"id": "n1", "title": "T"}], "count": 1}
            cache.put_news({"k": "AAPL"}, payload)
            assert cache.get_news({"k": "AAPL"}) == payload
        finally:
            cache.close()


# ===========================================================================
# A09:2021 — Security Logging and Monitoring Failures
# ===========================================================================


class TestA09Logging:
    def test_cache_audit_events_recorded(self, tmp_path: Path) -> None:
        cache = Cache(db_path=tmp_path / "c.duckdb")
        try:
            cache.put_news({"q": "x"}, {"v": 1})
            cache.get_news({"q": "x"})
            assert cache._conn is not None
            count = cache._conn.execute("SELECT COUNT(*) FROM cache_events").fetchone()[0]
            assert count >= 2
        finally:
            cache.close()


# ===========================================================================
# A10:2021 — Server-Side Request Forgery (SSRF)
# ===========================================================================


class TestA10SSRF:
    def test_ticker_cannot_inject_arbitrary_url(self) -> None:
        from polygon_news_mcp.models import GetTickerNewsInput

        for payload in SSRF_PAYLOADS:
            with pytest.raises(Exception):
                GetTickerNewsInput(ticker=payload)

    def test_abs_url_keeps_fixed_base_host(self, make_polygon_client) -> None:
        """_abs_url anchors a relative path to the fixed Polygon base URL."""
        from tests.conftest import FakeRoute

        client = make_polygon_client([FakeRoute("x", json_body={})])
        url = client._abs_url("/v2/reference/news")
        assert url.startswith("https://api.polygon.io/")
        assert "169.254" not in url and "evil.example" not in url

    @pytest.mark.asyncio
    async def test_outbound_host_is_polygon(self, make_polygon_client) -> None:
        """A real tool call only ever targets the configured Polygon host."""
        from polygon_news_mcp.client import PolygonClient
        from tests.conftest import FakePolygonTransport, FakeRoute

        transport = FakePolygonTransport([FakeRoute("/v2/reference/news", json_body={"results": []})])
        client = PolygonClient(
            api_key="test-key",  # pragma: allowlist secret
            rate_limit_per_min=1000,
            base_url="https://api.polygon.io",
            transport=transport,
        )
        await client.get_json("/v2/reference/news?ticker=AAPL")
        for url in transport.call_log:
            assert "api.polygon.io" in url
            assert "169.254" not in url and "evil.example" not in url
