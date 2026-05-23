"""FastMCP server entry point — 7 outward-facing tools.

The first thing this module does is harden stdio so no stray ``print`` /
log line pollutes the JSON-RPC stream:

* monkey-patch ``builtins.print`` so the default ``file`` is ``sys.stderr``;
* install a :class:`RotatingFileHandler` writing to
  ``${XDG_STATE_HOME}/polygon-news-mcp/logs/server.log``;
* force ``httpx`` / ``httpcore`` to ``WARNING``.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 0) Stdio hardening — must run BEFORE we import anything that might log /
#    print at import time (httpx, etc).
# ---------------------------------------------------------------------------
import builtins
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


def _harden_stdio() -> None:
    """Install the print + logging mitigations."""
    _orig_print = builtins.print

    def _safe_print(*args: Any, file: Any = None, **kwargs: Any) -> None:
        _orig_print(*args, file=file or sys.stderr, **kwargs)

    builtins.print = _safe_print

    from . import cache as _cache_mod

    log_dir: Path | None = _cache_mod.state_root() / "polygon-news-mcp" / "logs"
    try:
        assert log_dir is not None
        log_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    except OSError:
        log_dir = None

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_dir is not None:
        try:
            file_handler = RotatingFileHandler(
                log_dir / "server.log",
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setFormatter(
                logging.Formatter('{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":%(message)r}')
            )
            handlers.append(file_handler)
        except OSError:
            pass

    level = os.environ.get("LOG_LEVEL", "WARNING").upper()
    logging.basicConfig(
        handlers=handlers,
        level=getattr(logging, level, logging.WARNING),
        format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":%(message)r}',
        force=True,
    )
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


_harden_stdio()


# ---------------------------------------------------------------------------
# 0b) Load .env from the current working directory.  Host-injected env vars
#     win because ``override=False``.
# ---------------------------------------------------------------------------
from .bootstrap import load_dotenv_cwd  # noqa: E402

load_dotenv_cwd()


# ---------------------------------------------------------------------------
# Imports after hardening
# ---------------------------------------------------------------------------

from typing import Final  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402

from . import __version__ as SERVER_VERSION  # noqa: E402
from .errors import (  # noqa: E402
    PolygonAuthError,
    PolygonConfigurationError,
    PolygonError,
    PolygonNotFoundError,
    PolygonRateLimitError,
    PolygonTransientError,
    PolygonValidationError,
)
from .models import (  # noqa: E402
    GetMarketNewsInput,
    GetTickerDetailsInput,
    GetTickerNewsInput,
    ListSecFilingsIndexInput,
)
from .tools import details, filings, meta, news  # noqa: E402

log = logging.getLogger("polygon_news_mcp.server")

SERVER_NAME: Final[str] = "polygon-news-mcp"


# ---------------------------------------------------------------------------
# Error framing — convert structured exceptions to JSON-friendly dicts so
# the MCP client surfaces actionable messages instead of stack traces.
# ---------------------------------------------------------------------------


def _frame_error(exc: BaseException) -> dict[str, Any]:
    """Convert any exception into a structured error envelope."""
    if isinstance(exc, PolygonValidationError):
        return {"error": "validation", "field": exc.field, "reason": exc.reason}
    if isinstance(exc, PolygonConfigurationError):
        return {"error": "configuration", "hint": exc.hint}
    if isinstance(exc, PolygonAuthError):
        return {"error": "auth", "status_code": exc.status_code, "hint": exc.hint}
    if isinstance(exc, PolygonNotFoundError):
        return {"error": "not_found", "resource": exc.resource, "hint": exc.hint}
    if isinstance(exc, PolygonRateLimitError):
        return {
            "error": "rate_limit",
            "retry_after_seconds": exc.retry_after_seconds,
            "plan_hint": exc.plan_hint,
        }
    if isinstance(exc, PolygonTransientError):
        return {
            "error": "transient",
            "status_code": exc.status_code,
            "attempt": exc.attempt,
            "hint": exc.hint,
        }
    if isinstance(exc, PolygonError):
        return {"error": "polygon_error", "type": type(exc).__name__}
    return {"error": "internal", "type": type(exc).__name__}


# ---------------------------------------------------------------------------
# FastMCP wiring
# ---------------------------------------------------------------------------


def _build_mcp() -> FastMCP:
    mcp_app = FastMCP(SERVER_NAME)

    # FastMCP ctor (mcp SDK 1.27.x) does not expose a ``version=`` kwarg, so the
    # underlying lowlevel ``Server.version`` defaults to ``None`` and the
    # ``initialize`` response falls back to
    # ``importlib.metadata.version("mcp")`` (framework version).
    # Inject the project release tag directly on the lowlevel server so
    # ``serverInfo.version`` reflects this package's ``__version__``.
    mcp_app._mcp_server.version = SERVER_VERSION

    @mcp_app.tool()
    async def get_ticker_news(
        ticker: str,
        limit: int = 10,
        since_days: int = 7,
    ) -> dict[str, Any]:
        """Return the most recent Polygon news articles mentioning *ticker*.

        ``ticker`` is a US stock symbol (e.g. ``"AAPL"``).
        ``limit`` ≤ 1000 articles, ``since_days`` ≤ 365.
        """
        try:
            args = GetTickerNewsInput(
                ticker=ticker,
                limit=limit,
                since_days=since_days,
            )
            return await news.get_ticker_news_impl(args)
        except PolygonError as exc:
            return _frame_error(exc)

    @mcp_app.tool()
    async def get_market_news(
        limit: int = 20,
        since_hours: int = 24,
    ) -> dict[str, Any]:
        """Return the most recent market-wide news articles (no ticker filter).

        ``limit`` ≤ 1000 articles, ``since_hours`` ≤ 720 (30 days).
        """
        try:
            args = GetMarketNewsInput(
                limit=limit,
                since_hours=since_hours,
            )
            return await news.get_market_news_impl(args)
        except PolygonError as exc:
            return _frame_error(exc)

    @mcp_app.tool()
    async def get_ticker_details(ticker: str) -> dict[str, Any]:
        """Return Polygon's reference metadata (name, exchange, SIC, address,
        branding) for *ticker*.

        Complementary to Schwab Market Data's quote endpoint, which carries
        pricing but very little static metadata.
        """
        try:
            args = GetTickerDetailsInput(ticker=ticker)
            return await details.get_ticker_details_impl(args)
        except PolygonError as exc:
            return _frame_error(exc)

    @mcp_app.tool()
    async def list_sec_filings_index(
        ticker: str,
        since_days: int = 90,
    ) -> dict[str, Any]:
        """Return Polygon's SEC filings index entries for *ticker*.

        Complementary to ``sec-edgar-mcp`` — Polygon adds optional
        ``sentiment`` / ``category`` annotations.  Use ``sec-edgar-mcp``
        for the canonical SEC EDGAR feed and filing bodies.
        """
        try:
            args = ListSecFilingsIndexInput(ticker=ticker, since_days=since_days)
            return await filings.list_sec_filings_index_impl(args)
        except PolygonError as exc:
            return _frame_error(exc)

    @mcp_app.tool()
    async def health_check() -> dict[str, Any]:
        """Local health probe.  Never calls Polygon."""
        return await meta.health_check_impl()

    @mcp_app.tool()
    async def get_server_info() -> dict[str, Any]:
        """Local server metadata.  Never calls Polygon."""
        return await meta.get_server_info_impl(server_version=SERVER_VERSION)

    return mcp_app


# Lazy build so test collection (which imports server) doesn't fail when
# stdio is already connected to pytest's capture.
_app: FastMCP | None = None


def app() -> FastMCP:
    global _app
    if _app is None:
        _app = _build_mcp()
    return _app


def main() -> None:
    """Console-script entry point."""
    log.info('{"event":"server_start","version":"%s"}', SERVER_VERSION)
    app().run()


__all__ = [
    "SERVER_NAME",
    "SERVER_VERSION",
    "app",
    "main",
]
