"""Free, no-LLM article generation.

Builds a cited "what's moving and why" roundup directly from the news headlines
the discovery step already gathered. No API key, no cost: every fact and link
comes from real RSS items, so the output is genuinely attributed rather than
invented. Lower-effort than the Claude writer, but fully automatic and free.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone

from .config import Config
from .models import Article, Source, TopicCandidate
from .publishing.markdown import slugify


def _clean(text: str, limit: int = 220) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(".,;:") + "…"
    return text


def _lead(term: str) -> str:
    return term[:1].upper() + term[1:] if term else term


class TemplateArticleWriter:
    """Assembles a cited roundup article from a topic's headlines. No network, no LLM."""

    def __init__(self, config: Config):
        self.config = config

    def generate(self, topic: TopicCandidate, today: datetime | None = None) -> Article:
        today = today or datetime.now(timezone.utc)
        lead = _lead(topic.term)
        title = f"{lead}: What's Moving and Why Traders Are Watching"

        # Deduplicate headlines by URL, keep order (already recency-sorted).
        seen: set[str] = set()
        items = [h for h in topic.headlines if h.url and not (h.url in seen or seen.add(h.url))]

        n_sources = len(topic.sources)
        outlets = ", ".join(sorted(topic.sources)) if topic.sources else "financial news outlets"
        summary = (
            f"A roundup of the latest on {topic.term}: what's happening across "
            f"{n_sources or 'several'} outlet(s) and the key terms to know."
        )

        parts: list[str] = [f"# {title}", ""]
        parts.append(
            f"**{lead}** is drawing attention across financial news right now"
            + (f" ({outlets})" if topic.sources else "")
            + ". Below is a curated summary of the latest coverage, with links to the "
            "original reporting so you can dig into the details yourself."
        )
        parts.append("")

        if items:
            parts.append("## What's happening")
            for h in items[:8]:
                when = h.published.date().isoformat() if h.published else ""
                snippet = _clean(h.summary)
                line = f"- **[{h.title}]({h.url})** — {h.source}"
                if when:
                    line += f" ({when})"
                if snippet:
                    line += f". {snippet}"
                parts.append(line)
            parts.append("")

        focus = [k for k in topic.keywords if k and k != topic.term]
        if focus:
            parts.append("## Key terms in this story")
            parts.append(
                "Worth understanding as you read the coverage above: "
                + ", ".join(f"**{k}**" for k in focus[:8])
                + "."
            )
            parts.append("")

        parts.append("## Why it matters")
        parts.append(
            f"When a topic like {topic.term} surges across multiple outlets at once, it "
            "usually signals a shift in sentiment, a notable event, or fresh data that "
            "traders are repricing. Read the linked sources for the specifics, compare how "
            "different outlets frame the story, and be cautious of headlines that imply a "
            "move is guaranteed to continue."
        )
        parts.append("")

        sources: list[Source] = []
        seen_src: set[str] = set()
        for h in items:
            if h.url not in seen_src:
                seen_src.add(h.url)
                sources.append(Source(title=f"{h.source} — {h.title}", url=h.url))

        if sources:
            parts.append("## Sources")
            for i, s in enumerate(sources, 1):
                parts.append(f"[{i}] {s.title} — {s.url}")
            parts.append("")

        parts.append(
            "*Automated roundup that links to original reporting. Educational only — "
            "not investment advice.*"
        )

        body = "\n".join(parts).strip() + "\n"

        return Article(
            title=title,
            slug=slugify(title),
            summary=summary,
            body_markdown=body,
            keywords=topic.keywords or [topic.term],
            sources=sources,
            topic_term=topic.term,
            virality_score=round(topic.score, 4),
            generated_at=today,
            model="template-free",
        )
