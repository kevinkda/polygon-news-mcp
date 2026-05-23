"""Console-script entry point.

``python -m polygon_news_mcp`` and the ``polygon-news-mcp`` script both land
here, which delegates to :func:`polygon_news_mcp.server.main`.
"""

from __future__ import annotations

from .server import main

if __name__ == "__main__":
    main()
