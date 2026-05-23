"""Bootstrap helpers — load .env from the current working directory.

Kept separate from :mod:`polygon_news_mcp.server` so test code can call it
without pulling in FastMCP / stdio side effects.
"""

from __future__ import annotations


def load_dotenv_cwd() -> None:
    """Best-effort load of ``.env`` from the current working directory.

    Host-injected env vars win because ``override=False``.
    """
    try:
        from dotenv import load_dotenv

        load_dotenv(override=False)
    except ImportError:  # pragma: no cover - python-dotenv is a hard dep
        pass


__all__ = ["load_dotenv_cwd"]
