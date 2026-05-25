"""Article generation via the Claude API with live web research + citations."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from .config import Config
from .models import Article, Source, TopicCandidate
from .publishing.markdown import slugify

log = logging.getLogger(__name__)

MAX_CONTINUATIONS = 6  # server tool loops can pause_turn; allow a few resumes

_TOOL_SPECS = {
    "web_search": {"type": "web_search_20260209", "name": "web_search"},
    "web_fetch": {"type": "web_fetch_20260209", "name": "web_fetch"},
}


def build_system_prompt(config: Config) -> str:
    """Stable editorial brief. Kept frozen so it caches across articles."""
    return f"""You are the senior staff writer for "{config.platform_name}", a \
stock-market and trading *literacy* platform. Your readers range from curious \
beginners to active retail traders. Your job is to turn a trending market topic \
into a clear, accurate, genuinely educational article.

NON-NEGOTIABLE STANDARDS
1. Research first. Use the web tools to find current, reputable sources \
(major financial outlets, company filings, official data). Base every factual \
claim on what you actually find — never invent numbers, dates, or quotes.
2. Cite properly. Add inline numbered citations like [1], [2] right after the \
claims they support, and end the article with a "## Sources" section listing \
each numbered source as "[n] Title — URL". Only cite pages you actually read.
3. Teach, don't hype. Explain the mechanics and the "why it matters". Define \
jargon the first time it appears. Present multiple viewpoints and risks; avoid \
breathless or promotional language.
4. Not financial advice. Include a brief, clearly-worded disclaimer that the \
article is educational and not investment advice.
5. Be current and concrete. Anchor the piece to the present moment and the \
specific event driving interest in the topic.

OUTPUT FORMAT (Markdown only — no preamble, no code fences around the article):
- Start with a single H1 title (`# ...`) that is specific and search-friendly.
- Follow with a one- to two-sentence standfirst paragraph summarizing the piece.
- Use H2/H3 sections, short paragraphs, and bullet lists where helpful.
- Weave the provided focus keywords in naturally where they fit; never \
keyword-stuff or sacrifice readability for SEO.
- End with the "## Sources" section, then a final one-line italic disclaimer.
"""


def _headline_context(topic: TopicCandidate, limit: int = 6) -> str:
    lines = []
    for h in topic.headlines[:limit]:
        when = h.published.date().isoformat() if h.published else "recent"
        lines.append(f"- ({when}) {h.title} [{h.source}] {h.url}")
    return "\n".join(lines) if lines else "- (no seed headlines; research from scratch)"


def build_user_prompt(topic: TopicCandidate, config: Config, today: datetime) -> str:
    keywords = ", ".join(topic.keywords) if topic.keywords else topic.term
    return f"""Today is {today.date().isoformat()}.

Write an educational article (~{config.target_words} words) for our trading \
literacy platform about this surging topic:

FOCUS TOPIC: {topic.term}
FOCUS KEYWORDS (weave in naturally): {keywords}

These recent headlines are why interest is spiking — use them as leads, then \
research current details and verify before writing:
{_headline_context(topic)}

Research the topic with the web tools, then write the full article in Markdown \
following all the editorial standards. Make sure a beginner finishes it \
understanding both what is happening and why it matters."""


class GenerationError(RuntimeError):
    pass


class ClaudeArticleWriter:
    """Generates one cited article per topic using the Claude API."""

    def __init__(self, config: Config, client=None):
        self.config = config
        self._system = build_system_prompt(config)
        if client is not None:
            self.client = client
        else:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover
                raise GenerationError(
                    "The 'anthropic' package is required to generate articles. "
                    "Install it with: pip install anthropic"
                ) from exc
            try:
                self.client = anthropic.Anthropic()
            except Exception as exc:  # noqa: BLE001
                raise GenerationError(
                    "Could not initialize the Anthropic client. Set ANTHROPIC_API_KEY. "
                    f"({exc})"
                ) from exc

    def _tools(self, names: list[str]) -> list[dict]:
        return [_TOOL_SPECS[n] for n in names if n in _TOOL_SPECS]

    def generate(self, topic: TopicCandidate, today: datetime | None = None) -> Article:
        today = today or datetime.now(timezone.utc)
        user_prompt = build_user_prompt(topic, self.config, today)
        tool_names = list(self.config.tools)

        try:
            message = self._run(user_prompt, tool_names)
        except Exception as exc:  # noqa: BLE001
            # web_fetch isn't enabled on every account; retry with search only.
            if "web_fetch" in tool_names and _looks_like_tool_error(exc):
                log.warning("web_fetch unavailable (%s); retrying with web_search only", exc)
                message = self._run(user_prompt, ["web_search"])
            else:
                raise GenerationError(f"Article generation failed: {exc}") from exc

        body = _extract_text(message).strip()
        if not body:
            raise GenerationError("Model returned no article text")

        sources = _extract_sources(message)
        title = _extract_title(body) or topic.term.title()
        summary = _extract_summary(body, title)

        return Article(
            title=title,
            slug=slugify(title),
            summary=summary,
            body_markdown=body,
            keywords=topic.keywords or [topic.term],
            sources=sources,
            topic_term=topic.term,
            virality_score=round(topic.score, 4),
            generated_at=datetime.now(timezone.utc),
            model=self.config.model,
        )

    def _run(self, user_prompt: str, tool_names: list[str]):
        messages = [{"role": "user", "content": user_prompt}]
        system = [{"type": "text", "text": self._system, "cache_control": {"type": "ephemeral"}}]
        tools = self._tools(tool_names)

        final = None
        for _ in range(MAX_CONTINUATIONS):
            with self.client.messages.stream(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                system=system,
                thinking={"type": "adaptive"},
                output_config={"effort": self.config.effort},
                tools=tools,
                messages=messages,
            ) as stream:
                for _chunk in stream.text_stream:  # drive the stream to completion
                    pass
                final = stream.get_final_message()

            if getattr(final, "stop_reason", None) == "pause_turn":
                messages.append({"role": "assistant", "content": final.content})
                continue
            return final
        return final


def _looks_like_tool_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "web_fetch" in text or ("tool" in text and "not" in text)


def _extract_text(message) -> str:
    parts = []
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    return "\n".join(parts)


def _extract_sources(message) -> list[Source]:
    """Pull real, grounded citations out of the model's web research.

    Prefers citations attached to text blocks; falls back to the raw
    web_search_tool_result entries the model actually retrieved.
    """
    found: dict[str, str] = {}

    def add(url, title):
        if not url:
            return
        url = str(url)
        title = (str(title).strip() if title else "") or url
        found.setdefault(url, title)

    for block in getattr(message, "content", []) or []:
        btype = getattr(block, "type", None)
        if btype == "text":
            for cite in getattr(block, "citations", None) or []:
                add(getattr(cite, "url", None), getattr(cite, "title", None))
        elif btype == "web_search_tool_result":
            content = getattr(block, "content", None) or []
            for item in content:
                add(getattr(item, "url", None), getattr(item, "title", None))

    return [Source(title=t, url=u) for u, t in found.items()]


def _extract_title(body: str) -> str | None:
    for line in body.splitlines():
        m = re.match(r"^#\s+(.*\S)\s*$", line)
        if m:
            return m.group(1).strip()
    return None


def _extract_summary(body: str, title: str) -> str:
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if line.strip().lstrip("# ").strip() == title.strip():
            for follow in lines[i + 1 :]:
                text = follow.strip()
                if text and not text.startswith("#"):
                    return re.sub(r"\[\d+\]", "", text).strip()
            break
    # fall back to first non-heading paragraph
    for line in lines:
        text = line.strip()
        if text and not text.startswith("#"):
            return re.sub(r"\[\d+\]", "", text).strip()
    return ""
