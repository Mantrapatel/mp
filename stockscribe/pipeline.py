"""End-to-end orchestration: research -> select -> generate -> publish."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .discovery import score_candidates
from .models import Article, TopicCandidate
from .publishing.markdown import write_article
from .publishing.site import build_site
from .sources import rss
from .sources import google_trends
from .state import SeenStore

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    candidates: list[TopicCandidate] = field(default_factory=list)
    selected: list[TopicCandidate] = field(default_factory=list)
    articles: list[Article] = field(default_factory=list)
    written_paths: list[Path] = field(default_factory=list)
    site_index: Path | None = None
    dry_run: bool = False


def discover(config: Config, use_trends: bool | None = None, now: datetime | None = None) -> list[TopicCandidate]:
    """Gather news + trends and rank topics by virality potential."""
    now = now or datetime.now(timezone.utc)
    use_trends = config.enable_google_trends if use_trends is None else use_trends

    headlines = rss.fetch_headlines(config.feeds, config.lookback_hours, now=now)
    trends = google_trends.fetch_trends(config.trend_seeds) if use_trends else []
    candidates = score_candidates(headlines, trends, config, now=now)
    log.info("Discovered %d ranked topic candidates", len(candidates))
    return candidates


def _topic_keys(topic: TopicCandidate) -> set[str]:
    """Identity keys for dedup: the lead term plus any multi-word keywords
    (specific enough to mark without over-suppressing generic single words)."""
    keys = {topic.term}
    keys |= {k for k in topic.keywords if " " in k}
    return keys


def _topic_seen(store: SeenStore, topic: TopicCandidate, days: int, now: datetime) -> bool:
    return any(store.is_seen(k, days, now=now) for k in _topic_keys(topic))


def mark_topic(store: SeenStore, topic: TopicCandidate, now: datetime) -> None:
    for key in _topic_keys(topic):
        store.mark(key, now=now)


def select(
    candidates: list[TopicCandidate],
    store: SeenStore,
    config: Config,
    now: datetime | None = None,
) -> list[TopicCandidate]:
    """Pick the top unseen topics above the score threshold."""
    now = now or datetime.now(timezone.utc)
    chosen: list[TopicCandidate] = []
    for cand in candidates:
        if cand.score < config.min_score:
            continue
        if _topic_seen(store, cand, config.dedup_days, now):
            log.info("Skipping already-covered topic: %s", cand.term)
            continue
        chosen.append(cand)
        if len(chosen) >= config.num_articles:
            break
    return chosen


def run(
    config: Config,
    *,
    dry_run: bool = False,
    use_trends: bool | None = None,
    build_site_after: bool | None = None,
    now: datetime | None = None,
    writer=None,
) -> RunResult:
    """Run the full pipeline once. Cron-friendly and idempotent via dedup state."""
    now = now or datetime.now(timezone.utc)
    build_site_after = config.build_site if build_site_after is None else build_site_after

    store = SeenStore(config.state_file)
    store.prune(older_than_days=max(config.dedup_days * 2, 30), now=now)

    candidates = discover(config, use_trends=use_trends, now=now)
    selected = select(candidates, store, config, now=now)
    result = RunResult(candidates=candidates, selected=selected, dry_run=dry_run)

    if dry_run:
        log.info("Dry run: %d topics selected, skipping generation", len(selected))
        return result

    if not selected:
        log.info("Nothing new to write")
        if build_site_after:
            result.site_index = build_site(config.content_dir, config.site_dir, config.platform_name)
        return result

    if writer is None:
        from .generation import ClaudeArticleWriter

        writer = ClaudeArticleWriter(config)

    for topic in selected:
        log.info("Generating article for: %s (score=%.3f)", topic.term, topic.score)
        try:
            article = writer.generate(topic, today=now)
        except Exception as exc:  # noqa: BLE001 - keep going on per-article failure
            log.error("Failed to generate article for %r: %s", topic.term, exc)
            continue
        path = write_article(article, config.content_dir)
        result.articles.append(article)
        result.written_paths.append(path)
        mark_topic(store, topic, now=now)
        log.info("Wrote %s", path)

    store.save()

    if build_site_after:
        result.site_index = build_site(config.content_dir, config.site_dir, config.platform_name)

    return result
