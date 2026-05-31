"""OWASP Top 10 — 2025 (preview) security test suite for polygon-news-mcp.

The 2025 preview emphasises AI/ML-era concerns: prompt injection (A03),
secure design (A04), and supply-chain integrity (A08).  For an MCP server the
most material 2025-specific surface is **prompt injection via tool
descriptions** — and, for this server, **API-key confidentiality** under an
LLM host that might be coaxed into echoing secrets.

Each test asserts a concrete invariant — no empty-coverage padding.

Applicability map (2025 preview):
  * A01 Broken Access Control — read-only tool surface (re-asserted)
  * A02 Cryptographic Failures — secure cache perms; API-key redaction
  * A03 Injection (incl. prompt) — 8 tool descriptions carry no injection text
  * A04 Insecure Design        — fail-closed API key; free-tier rate cap
  * A05 Security Misconfig      — explicit cache defaults
  * A06 Vulnerable Components   — httpx/pydantic/duckdb declared
  * A07 AuthN Failures          — API key required; never echoed
  * A08 Data Integrity          — JSON shape validation
  * A09 Logging & Monitoring    — audit events
  * A10 SSRF                    — outbound host pinned to Polygon
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src" / "polygon_news_mcp"
FAKE_KEY = "AbCdEf0123456789XyZ_secretkey"  # pragma: allowlist secret

PROMPT_INJECTION_MARKERS = [
    "ignore previous",
    "ignore all previous",
    "disregard the above",
    "you are now",
    "system prompt",
    "exfiltrate",
    "reveal your",
    "override your instructions",
    "do not tell the user",
    "send the api key",
    "print the api key",
    "leak the key",
]


# ===========================================================================
# A03:2025 — Injection (including LLM Prompt Injection)
# ===========================================================================


class TestA03PromptInjection:
    @pytest.mark.asyncio
    async def test_tool_descriptions_have_no_injection_text(self) -> None:
        from polygon_news_mcp.server import app

        tools = await app().list_tools()
        assert len(tools) == 8
        for t in tools:
            desc = (t.description or "").lower()
            for marker in PROMPT_INJECTION_MARKERS:
                assert marker not in desc, f"tool {t.name} description contains injection marker {marker!r}"

    @pytest.mark.asyncio
    async def test_tool_descriptions_dont_leak_api_key_instructions(self) -> None:
        """No tool description instructs the host to surface the API key."""
        from polygon_news_mcp.server import app

        for t in await app().list_tools():
            desc = (t.description or "").lower()
            assert "apikey=" not in desc
            assert "bearer " not in desc

    @pytest.mark.asyncio
    async def test_tool_descriptions_bounded(self) -> None:
        from polygon_news_mcp.server import app

        for t in await app().list_tools():
            desc = t.description or ""
            assert 10 <= len(desc) <= 1500, f"{t.name} description length {len(desc)} out of bounds"
            assert "\x00" not in desc

    def test_no_dynamic_code_execution(self) -> None:
        """Attacker-controllable news/filing content is never eval/exec'd."""
        bad = re.compile(r"(?<![.\w])(eval|exec)\s*\(")
        offenders = []
        for py in SRC_ROOT.rglob("*.py"):
            for lineno, line in enumerate(py.read_text("utf-8").splitlines(), 1):
                if line.strip().startswith(("#", '"', "'", "*")):
                    continue
                if bad.search(line):
                    offenders.append(f"{py.relative_to(REPO_ROOT)}:{lineno}")
        assert offenders == [], f"dynamic code execution present: {offenders}"


# ===========================================================================
# Re-asserted invariants A01/A02/A04/A05/A06/A07/A08/A09/A10
# ===========================================================================


class TestReassertedInvariants:
    @pytest.mark.asyncio
    async def test_a01_read_only_surface(self) -> None:
        from polygon_news_mcp.server import app

        for t in await app().list_tools():
            assert not any(v in t.name for v in ("create", "delete", "update", "write"))

    def test_a02_cache_perms(self, tmp_path: Path) -> None:
        import os
        import stat
        import sys

        from polygon_news_mcp.cache import Cache

        if sys.platform == "win32":
            pytest.skip("POSIX-only perm semantics")
        cache = Cache(db_path=tmp_path / "c.duckdb")
        try:
            assert stat.S_IMODE(os.stat(tmp_path / "c.duckdb").st_mode) == 0o600
        finally:
            cache.close()

    def test_a02_api_key_redacted(self) -> None:
        from polygon_news_mcp.errors import redact_secret

        assert FAKE_KEY not in redact_secret(f"?apiKey={FAKE_KEY}")

    def test_a04_rate_cap_clamped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from polygon_news_mcp.client import POLYGON_HARD_RATE_LIMIT_PER_MIN, resolve_rate_limit

        monkeypatch.setenv("POLYGON_RATE_LIMIT_PER_MIN", "999999")
        assert resolve_rate_limit() <= POLYGON_HARD_RATE_LIMIT_PER_MIN

    def test_a05_cache_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from polygon_news_mcp.cache import cache_bypass, cache_enabled

        monkeypatch.delenv("POLYGON_CACHE_ENABLED", raising=False)
        monkeypatch.delenv("POLYGON_CACHE_BYPASS", raising=False)
        assert cache_enabled() and not cache_bypass()

    def test_a06_deps_declared(self) -> None:
        body = (REPO_ROOT / "pyproject.toml").read_text("utf-8")
        assert "httpx" in body and "pydantic" in body and "duckdb" in body

    def test_a07_fail_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from polygon_news_mcp.client import resolve_api_key
        from polygon_news_mcp.errors import PolygonConfigurationError

        monkeypatch.delenv("POLYGON_API_KEY", raising=False)
        with pytest.raises(PolygonConfigurationError):
            resolve_api_key()

    @pytest.mark.asyncio
    async def test_a08_json_shape_validation(self, make_polygon_client) -> None:
        from polygon_news_mcp.errors import PolygonTransientError
        from tests.conftest import FakeRoute

        client = make_polygon_client([FakeRoute("/s", text_body="true", content_type="application/json")])
        with pytest.raises(PolygonTransientError):
            await client.get_json("/s")

    def test_a09_audit_events(self, tmp_path: Path) -> None:
        from polygon_news_mcp.cache import Cache

        cache = Cache(db_path=tmp_path / "c.duckdb")
        try:
            cache.put_news({"q": "z"}, {"v": 1})
            assert cache._conn is not None
            n = cache._conn.execute("SELECT COUNT(*) FROM cache_events WHERE kind='write'").fetchone()[0]
            assert n >= 1
        finally:
            cache.close()

    def test_a10_ssrf_ticker_rejected(self) -> None:
        from polygon_news_mcp.models import GetTickerDetailsInput

        with pytest.raises(Exception):
            GetTickerDetailsInput(ticker="http://169.254.169.254/")
