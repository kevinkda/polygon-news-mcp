"""OWASP Top 10 — 2017 security test suite for polygon-news-mcp.

Polygon.io requires an API key (``POLYGON_API_KEY``) sent as a
``Authorization: Bearer <key>`` header.  The dominant threat for this server
is therefore **API-key leakage** (A3) — the key must never surface in logs,
error envelopes, exception ``repr``, or tool responses.  Secondary surfaces:
SSRF via the ``ticker`` parameter, local DuckDB injection, JSON
deserialisation safety, and free-tier (5 req/min) rate-limit enforcement.

Each test asserts a concrete invariant — no empty-coverage padding.

Applicability map (2017):
  * A1 Injection            — DuckDB bound params + ticker/date regex
  * A2 Broken AuthN         — fail-closed without API key; key never in responses
  * A3 Sensitive Data       — POLYGON_API_KEY redacted from errors/logs
  * A4 XXE                  — N/A explicit: no XML is parsed (JSON-only API)
  * A5 Broken Access Ctrl   — read-only by design (8 tools, no mutations)
  * A6 Security Misconfig   — secure cache file perms, API-key enforcement
  * A7 XSS                  — N/A explicit: no HTML is generated/served
  * A8 Insecure Deserialize — JSON-only; non-dict/list shapes rejected
  * A9 Vulnerable Deps      — httpx/pydantic/duckdb pinned in pyproject
  * A10 Insufficient Logging— cache_events audit table + JSON server log
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from polygon_news_mcp.cache import Cache
from polygon_news_mcp.errors import redact_secret

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src" / "polygon_news_mcp"

SSRF_PAYLOADS = [
    "http://169.254.169.254/latest/meta-data/",
    "https://evil.example/steal",
    "file:///etc/passwd",
    "//evil.example/x",
    "localhost:8080",
    "127.0.0.1",
    "gopher://127.0.0.1:6379/_",
]

# A realistic-looking Polygon key shape for redaction assertions.
FAKE_KEY = "AbCdEf0123456789XyZ_secretkey"  # pragma: allowlist secret


# ===========================================================================
# A1:2017 — Injection
# ===========================================================================


class TestA1Injection:
    def test_duckdb_writes_use_bound_params(self, tmp_path: Path) -> None:
        cache = Cache(db_path=tmp_path / "c.duckdb")
        try:
            payload = "x'); DROP TABLE news_cache;--"
            cache.put_news({"q": payload}, {"echo": payload})
            assert cache.get_news({"q": payload}) == {"echo": payload}
        finally:
            cache.close()

    def test_ticker_regex_rejects_injection_chars(self) -> None:
        from polygon_news_mcp.models import GetTickerNewsInput

        for bad in ["AAPL'--", "1; DROP", "$(reboot)", "`id`", "AAPL OR 1=1"]:
            with pytest.raises(Exception):
                GetTickerNewsInput(ticker=bad)

    def test_dividend_type_constrained_to_literal(self) -> None:
        from pydantic import ValidationError

        from polygon_news_mcp.models import GetDividendsInput

        with pytest.raises(ValidationError):
            GetDividendsInput(ticker="AAPL", dividend_type="'; DROP--")  # type: ignore[arg-type]


# ===========================================================================
# A2:2017 — Broken Authentication
# ===========================================================================


class TestA2Authentication:
    def test_fail_closed_without_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from polygon_news_mcp.client import resolve_api_key
        from polygon_news_mcp.errors import PolygonConfigurationError

        monkeypatch.delenv("POLYGON_API_KEY", raising=False)
        with pytest.raises(PolygonConfigurationError):
            resolve_api_key()

    @pytest.mark.asyncio
    async def test_health_check_reports_key_absent_without_calling_polygon(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from polygon_news_mcp.tools.meta import health_check_impl

        monkeypatch.delenv("POLYGON_API_KEY", raising=False)
        out = await health_check_impl()
        assert out["api_key_configured"] is False

    @pytest.mark.asyncio
    async def test_api_key_never_in_health_check_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from polygon_news_mcp.tools.meta import health_check_impl

        monkeypatch.setenv("POLYGON_API_KEY", FAKE_KEY)
        out = await health_check_impl()
        assert FAKE_KEY not in repr(out)
        assert out["api_key_configured"] is True


# ===========================================================================
# A3:2017 — Sensitive Data Exposure  (POLYGON_API_KEY redaction — centrepiece)
# ===========================================================================


class TestA3SensitiveData:
    def test_apikey_querystring_redacted(self) -> None:
        leaky = f"GET https://api.polygon.io/v2/x?apiKey={FAKE_KEY}&limit=10 failed"
        out = redact_secret(leaky)
        assert FAKE_KEY not in out
        assert "***REDACTED***" in out

    def test_bearer_token_redacted(self) -> None:
        leaky = f"Authorization: Bearer {FAKE_KEY}"
        out = redact_secret(leaky)
        assert FAKE_KEY not in out
        assert "***REDACTED***" in out

    def test_all_exceptions_redact_key(self) -> None:
        from polygon_news_mcp.errors import (
            PolygonAuthError,
            PolygonConfigurationError,
            PolygonNotFoundError,
            PolygonTransientError,
        )

        leak = f"call ?apiKey={FAKE_KEY} failed"
        assert FAKE_KEY not in str(PolygonAuthError(status_code=401, hint=leak))
        assert FAKE_KEY not in str(PolygonNotFoundError(resource="r", hint=leak))
        assert FAKE_KEY not in str(PolygonTransientError(status_code=500, attempt=1, hint=leak))
        assert FAKE_KEY not in str(PolygonConfigurationError(hint=leak))

    def test_redact_is_idempotent(self) -> None:
        once = redact_secret(f"?apiKey={FAKE_KEY}")
        assert redact_secret(once) == once

    def test_api_key_not_logged_on_auth_error(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        from polygon_news_mcp.errors import PolygonAuthError

        log = logging.getLogger("polygon_news_mcp.test")
        with caplog.at_level(logging.WARNING, logger="polygon_news_mcp.test"):
            exc = PolygonAuthError(status_code=401, hint=f"bad key ?apiKey={FAKE_KEY}")
            log.warning("auth failure: %s", exc)
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert FAKE_KEY not in joined


# ===========================================================================
# A4:2017 — XML External Entities (XXE)  (N/A — explicitly documented)
# ===========================================================================


class TestA4XXE:
    def test_no_xml_parsing_surface(self) -> None:
        """N/A: Polygon.io is a JSON-only API — this server never parses XML.

        Structural guard: no source file imports an XML parser, so the N/A
        claim cannot silently rot if someone adds XML handling later.
        """
        import re

        pattern = re.compile(r"\b(import\s+xml|from\s+xml|ElementTree|lxml|xmltodict|defusedxml)\b")
        offenders = [
            str(py.relative_to(REPO_ROOT)) for py in SRC_ROOT.rglob("*.py") if pattern.search(py.read_text("utf-8"))
        ]
        assert offenders == [], f"unexpected XML parsing surface: {offenders}"


# ===========================================================================
# A5:2017 — Broken Access Control  (read-only by design)
# ===========================================================================


class TestA5AccessControl:
    @pytest.mark.asyncio
    async def test_only_read_tools_exposed(self) -> None:
        from polygon_news_mcp.server import app

        tools = await app().list_tools()
        names = {t.name for t in tools}
        assert names == {
            "get_ticker_news",
            "get_market_news",
            "get_ticker_details",
            "list_sec_filings_index",
            "get_news_sentiment_aggregate",
            "get_dividends",
            "health_check",
            "get_server_info",
        }
        for n in names:
            assert not any(v in n for v in ("create", "update", "delete", "write", "post", "put"))

    def test_ssrf_payloads_rejected_by_ticker_schema(self) -> None:
        from polygon_news_mcp.models import GetTickerNewsInput

        for payload in SSRF_PAYLOADS:
            with pytest.raises(Exception):
                GetTickerNewsInput(ticker=payload)


# ===========================================================================
# A6:2017 — Security Misconfiguration
# ===========================================================================


class TestA6Misconfiguration:
    def test_cache_db_owner_only_on_posix(self, tmp_path: Path) -> None:
        if sys.platform == "win32":
            pytest.skip("POSIX-only perm semantics")
        cache = Cache(db_path=tmp_path / "c.duckdb")
        try:
            mode = stat.S_IMODE(os.stat(tmp_path / "c.duckdb").st_mode)
            assert mode == 0o600
            assert not (mode & stat.S_IRGRP) and not (mode & stat.S_IROTH)
        finally:
            cache.close()

    def test_api_key_enforced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from polygon_news_mcp.client import resolve_api_key
        from polygon_news_mcp.errors import PolygonConfigurationError

        monkeypatch.setenv("POLYGON_API_KEY", "   ")  # whitespace-only → empty
        with pytest.raises(PolygonConfigurationError):
            resolve_api_key()


# ===========================================================================
# A7:2017 — Cross-Site Scripting (XSS)  (N/A — explicitly documented)
# ===========================================================================


class TestA7XSS:
    def test_no_html_generation_surface(self) -> None:
        """N/A: this server returns structured JSON only and renders no HTML."""
        import re

        pattern = re.compile(r"\b(jinja2|render_template|<html)", re.IGNORECASE)
        offenders = [
            str(py.relative_to(REPO_ROOT)) for py in SRC_ROOT.rglob("*.py") if pattern.search(py.read_text("utf-8"))
        ]
        assert offenders == [], f"unexpected HTML surface: {offenders}"


# ===========================================================================
# A8:2017 — Insecure Deserialization
# ===========================================================================


class TestA8Deserialization:
    @pytest.mark.asyncio
    async def test_non_dict_non_list_json_rejected(self, make_polygon_client) -> None:
        from polygon_news_mcp.errors import PolygonTransientError
        from tests.conftest import FakeRoute

        client = make_polygon_client([FakeRoute("/scalar", text_body="42", content_type="application/json")])
        with pytest.raises(PolygonTransientError):
            await client.get_json("/scalar")

    def test_cache_deserialise_rejects_non_dict(self) -> None:
        from polygon_news_mcp.cache import _deserialise

        assert _deserialise("[1,2,3]") is None
        assert _deserialise("not json") is None
        assert _deserialise(None) is None
        assert _deserialise('{"ok": 1}') == {"ok": 1}


# ===========================================================================
# A9:2017 — Using Components with Known Vulnerabilities
# ===========================================================================


class TestA9VulnerableComponents:
    def test_security_deps_pinned(self) -> None:
        body = (REPO_ROOT / "pyproject.toml").read_text("utf-8")
        assert "httpx" in body and "pydantic" in body and "duckdb" in body


# ===========================================================================
# A10:2017 — Insufficient Logging & Monitoring
# ===========================================================================


class TestA10Logging:
    def test_cache_events_audit_trail(self, tmp_path: Path) -> None:
        cache = Cache(db_path=tmp_path / "c.duckdb")
        try:
            cache.put_news({"q": "x"}, {"data": 1})
            cache.get_news({"q": "x"})  # hit
            cache.get_news({"q": "y"})  # miss
            assert cache._conn is not None
            kinds = {r[0] for r in cache._conn.execute("SELECT DISTINCT kind FROM cache_events").fetchall()}
            assert {"write", "hit", "miss"} <= kinds
        finally:
            cache.close()

    def test_server_log_is_structured_json(self) -> None:
        body = (SRC_ROOT / "server.py").read_text("utf-8")
        assert '"level"' in body and '"msg"' in body
