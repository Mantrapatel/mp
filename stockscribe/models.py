"""Core data structures shared across the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Headline:
    """A single news item pulled from an RSS feed."""

    title: str
    url: str
    source: str
    published: Optional[datetime] = None
    summary: str = ""


@dataclass
class TrendSignal:
    """A rising/breakout search term discovered via Google Trends.

    `value` is normalized to 0..1, where a Trends "Breakout" maps to 1.0.
    """

    term: str
    value: float
    source: str = "google_trends"


@dataclass
class TopicCandidate:
    """A scored topic assembled from news + trend signals.

    `term` is the lead phrase; `keywords` are related phrases worth weaving into
    the article so it ranks for the cluster, not just the headline term.
    """

    term: str
    keywords: list[str] = field(default_factory=list)
    headlines: list[Headline] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)
    trend_value: float = 0.0
    score: float = 0.0
    components: dict[str, float] = field(default_factory=dict)


@dataclass
class Source:
    """A citation extracted from the model's web research."""

    title: str
    url: str


@dataclass
class Article:
    """A finished, publishable article."""

    title: str
    slug: str
    summary: str
    body_markdown: str
    keywords: list[str]
    sources: list[Source]
    topic_term: str
    virality_score: float
    generated_at: datetime
    model: str
