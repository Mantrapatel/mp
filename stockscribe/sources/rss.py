"""Fetch recent finance headlines from RSS feeds."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from time import mktime
from urllib.parse import urlparse

from ..models import Headline

log = logging.getLogger(__name__)

# Many outlets reject feedparser's default UA; present a browser-like one.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_REQUEST_HEADERS = {
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
}


def _source_name(feed_obj, feed_url: str) -> str:
    title = getattr(getattr(feed_obj, "feed", None), "title", None)
    if title:
        return str(title)
    return urlparse(feed_url).netloc or feed_url


def _parsed_datetime(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        struct = getattr(entry, attr, None)
        if struct:
            try:
                return datetime.fromtimestamp(mktime(struct), tz=timezone.utc)
            except (ValueError, OverflowError):
                continue
    return None


def fetch_headlines(feeds: list[str], lookback_hours: int, now: datetime | None = None) -> list[Headline]:
    """Pull entries from each feed, keeping only those within the lookback
    window. A failing feed is logged and skipped rather than aborting the run.
    """
    import feedparser  # imported lazily so unit tests don't require it

    now = now or datetime.now(timezone.utc)
    cutoff_seconds = lookback_hours * 3600
    out: list[Headline] = []
    seen_urls: set[str] = set()

    for url in feeds:
        try:
            parsed = feedparser.parse(url, agent=_USER_AGENT, request_headers=_REQUEST_HEADERS)
        except Exception as exc:  # noqa: BLE001 - never let one feed kill the run
            log.warning("Failed to fetch feed %s: %s", url, exc)
            continue

        source = _source_name(parsed, url)
        for entry in getattr(parsed, "entries", []):
            link = getattr(entry, "link", "") or ""
            title = (getattr(entry, "title", "") or "").strip()
            if not title or not link or link in seen_urls:
                continue
            published = _parsed_datetime(entry)
            if published is not None:
                age = (now - published).total_seconds()
                if age > cutoff_seconds or age < -3600:
                    continue
            seen_urls.add(link)
            out.append(
                Headline(
                    title=title,
                    url=link,
                    source=source,
                    published=published,
                    summary=(getattr(entry, "summary", "") or "").strip(),
                )
            )

    log.info("Fetched %d headlines from %d feeds", len(out), len(feeds))
    return out
