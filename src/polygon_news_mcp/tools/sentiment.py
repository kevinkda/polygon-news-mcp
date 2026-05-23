"""``get_news_sentiment_aggregate`` implementation.

Aggregates Polygon's per-article ``insights[].sentiment`` annotations
over a configurable look-back window into a single per-ticker summary:

* counts of positive / neutral / negative articles,
* a weighted score in ``[-1.0, +1.0]`` (``positive - negative`` over total),
* the top publishers by article count,
* a short list of the most "significant" articles (publisher
  diversity + sentiment magnitude as a heuristic).

The aggregation is **in-process** — it makes one call to
``get_ticker_news_impl`` (which is already DuckDB-cached at 1 h TTL) and
projects the output.  No additional Polygon endpoint is touched.

This means a fresh ``get_news_sentiment_aggregate`` call costs at most
**one** upstream Polygon request per ``(ticker, window_days)`` pair
within the news cache TTL, and zero requests on a cache hit.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Final

from ..models import GetNewsSentimentAggregateInput, GetTickerNewsInput
from .news import get_ticker_news_impl

#: How many articles to pull from ``get_ticker_news`` for the window.
#: Polygon caps ``limit`` at 1000 server-side; we use that ceiling so the
#: aggregate is computed over as many articles as are available.
_FETCH_LIMIT: Final[int] = 1000

#: ``top_publishers`` and ``most_significant_articles`` cap.
_TOP_N: Final[int] = 5

#: Heuristic weight for the "most significant article" ranking.
#: Articles with explicit sentiment (positive / negative) score higher
#: than neutral / unknown; ties broken by publication recency.
_SIGNIFICANCE_BY_SENTIMENT: Final[dict[str, int]] = {
    "positive": 2,
    "negative": 2,
    "neutral": 1,
}


async def get_news_sentiment_aggregate_impl(
    args: GetNewsSentimentAggregateInput,
) -> dict[str, Any]:
    """Return an aggregated sentiment summary for *args.ticker* over the window."""
    news = await get_ticker_news_impl(
        GetTickerNewsInput(
            ticker=args.ticker,
            limit=_FETCH_LIMIT,
            since_days=args.window_days,
        ),
    )
    articles_raw = news.get("articles") or []
    articles: list[dict[str, Any]] = [a for a in articles_raw if isinstance(a, dict)]

    distribution = _count_sentiments(articles, ticker=args.ticker)
    total = sum(distribution.values())
    score = _sentiment_score(distribution, total=total)
    publishers = _top_publishers(articles)
    significant = _most_significant_articles(articles, ticker=args.ticker)

    return {
        "ticker": args.ticker,
        "window_days": args.window_days,
        "total_articles": total,
        "sentiment_distribution": distribution,
        "sentiment_score": score,
        "top_publishers": publishers,
        "most_significant_articles": significant,
        # Inherit the underlying cache status from the news call so the
        # caller can tell whether the upstream Polygon request was made.
        "_cache_status": news.get("_cache_status", "disabled"),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ticker_sentiment(article: dict[str, Any], *, ticker: str) -> str | None:
    """Return the sentiment annotation for *ticker* on *article*.

    Polygon attaches per-ticker insights (each article can mention several
    tickers).  We pick the entry whose ``ticker`` matches *args.ticker*
    case-insensitively; if there is no exact match, we fall back to the
    first insight (which is what the upstream UI shows).
    """
    insights_raw = article.get("insights")
    if not isinstance(insights_raw, list) or not insights_raw:
        return None
    target = ticker.upper()
    fallback: str | None = None
    for entry in insights_raw:
        if not isinstance(entry, dict):
            continue
        sentiment = entry.get("sentiment")
        if not isinstance(sentiment, str):
            continue
        entry_ticker = entry.get("ticker")
        if isinstance(entry_ticker, str) and entry_ticker.upper() == target:
            return sentiment.lower()
        if fallback is None:
            fallback = sentiment.lower()
    return fallback


def _count_sentiments(
    articles: list[dict[str, Any]],
    *,
    ticker: str,
) -> dict[str, int]:
    distribution: dict[str, int] = {"positive": 0, "neutral": 0, "negative": 0}
    for article in articles:
        sentiment = _ticker_sentiment(article, ticker=ticker)
        if sentiment in distribution:
            distribution[sentiment] += 1
    return distribution


def _sentiment_score(distribution: dict[str, int], *, total: int) -> float:
    """Weighted score in ``[-1.0, +1.0]``.

    ``(positive - negative) / total``; returns ``0.0`` when there are no
    classified articles (rather than raising).
    """
    if total <= 0:
        return 0.0
    raw = (distribution.get("positive", 0) - distribution.get("negative", 0)) / total
    # Clamp defensively — even though the math can't escape [-1, +1] given
    # the inputs, the rounding below makes the contract explicit.
    return round(max(-1.0, min(1.0, raw)), 4)


def _top_publishers(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for article in articles:
        publisher = article.get("publisher")
        if isinstance(publisher, str) and publisher.strip():
            counter[publisher.strip()] += 1
    return [{"publisher": p, "count": c} for p, c in counter.most_common(_TOP_N)]


def _most_significant_articles(
    articles: list[dict[str, Any]],
    *,
    ticker: str,
) -> list[dict[str, Any]]:
    """Pick the top-N "significant" articles by a simple heuristic.

    Score = ``sentiment_weight * publisher_distinctiveness`` where the
    publisher distinctiveness is ``1 / count_of_articles_from_that_publisher``
    in the window — i.e. an article from a publisher that only ran one
    piece on this ticker is considered more diagnostic than one of ten
    pieces from the same wire service.  Ties broken by recency.
    """
    publisher_counts: Counter[str] = Counter()
    for article in articles:
        publisher = article.get("publisher")
        if isinstance(publisher, str) and publisher.strip():
            publisher_counts[publisher.strip()] += 1

    scored: list[tuple[float, str, dict[str, Any], str | None]] = []
    for article in articles:
        sentiment = _ticker_sentiment(article, ticker=ticker)
        weight = _SIGNIFICANCE_BY_SENTIMENT.get(sentiment or "", 0)
        if weight == 0:
            continue
        publisher = article.get("publisher")
        publisher_name = publisher.strip() if isinstance(publisher, str) else ""
        publisher_n = publisher_counts.get(publisher_name, 1) or 1
        distinctiveness = 1.0 / publisher_n
        score = weight * distinctiveness
        published_utc = article.get("published_utc")
        published_str = published_utc if isinstance(published_utc, str) else ""
        scored.append((score, published_str, article, sentiment))

    # Sort by (score desc, published_utc desc) so newer ties win.
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)

    out: list[dict[str, Any]] = []
    for _score, _published, article, sentiment in scored[:_TOP_N]:
        out.append(
            {
                "title": article.get("title"),
                "published_utc": article.get("published_utc"),
                "sentiment": sentiment,
                "publisher": article.get("publisher"),
                "article_url": article.get("article_url"),
            },
        )
    return out


__all__ = ["get_news_sentiment_aggregate_impl"]
