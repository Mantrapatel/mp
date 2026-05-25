from datetime import datetime, timezone
from types import SimpleNamespace

from stockscribe.config import Config
from stockscribe.generation import (
    ClaudeArticleWriter,
    _extract_sources,
    _extract_summary,
    _extract_title,
    _looks_like_tool_error,
    build_system_prompt,
    build_user_prompt,
)
from stockscribe.models import Headline, TopicCandidate

NOW = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)

SAMPLE = """# Nvidia Earnings: What the Blowout Means for Chip Stocks

Nvidia's results sent the sector higher [1]. Here's what beginners should know.

## Background
The chipmaker reported strong demand [2].

## Sources
[1] CNBC — https://cnbc.com/a
[2] Reuters — https://reuters.com/b

*This article is educational and not investment advice.*
"""


def test_extract_title_and_summary():
    assert _extract_title(SAMPLE) == "Nvidia Earnings: What the Blowout Means for Chip Stocks"
    summary = _extract_summary(SAMPLE, _extract_title(SAMPLE))
    assert summary.startswith("Nvidia's results sent the sector higher")
    assert "[1]" not in summary  # citation markers stripped from the summary


def test_extract_sources_from_blocks():
    text_block = SimpleNamespace(
        type="text",
        text="body",
        citations=[SimpleNamespace(url="https://cnbc.com/a", title="CNBC story")],
    )
    search_block = SimpleNamespace(
        type="web_search_tool_result",
        content=[
            SimpleNamespace(url="https://reuters.com/b", title="Reuters"),
            SimpleNamespace(url="https://cnbc.com/a", title="dupe"),  # dedup by url
        ],
    )
    message = SimpleNamespace(content=[text_block, search_block])
    sources = _extract_sources(message)
    urls = {s.url for s in sources}
    assert urls == {"https://cnbc.com/a", "https://reuters.com/b"}


def test_looks_like_tool_error():
    assert _looks_like_tool_error(Exception("web_fetch is not enabled"))
    assert not _looks_like_tool_error(Exception("rate limit exceeded"))


def test_prompts_include_topic_and_keywords():
    cfg = Config()
    topic = TopicCandidate(term="nvidia earnings", keywords=["nvidia earnings", "chip stocks"])
    sys_prompt = build_system_prompt(cfg)
    assert cfg.platform_name in sys_prompt
    assert "Sources" in sys_prompt
    user = build_user_prompt(topic, cfg, NOW)
    assert "nvidia earnings" in user
    assert "chip stocks" in user
    assert "2026-05-25" in user


# --- exercise the full generate() path with a fake Anthropic client ---


class _FakeStream:
    def __init__(self, message):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        return iter(["chunk"])

    def get_final_message(self):
        return self._message


class _FakeMessages:
    def __init__(self, message):
        self._message = message
        self.calls = 0

    def stream(self, **kwargs):
        self.calls += 1
        return _FakeStream(self._message)


class _FakeClient:
    def __init__(self, message):
        self.messages = _FakeMessages(message)


def test_generate_builds_article_with_fake_client():
    message = SimpleNamespace(
        stop_reason="end_turn",
        content=[
            SimpleNamespace(type="text", text=SAMPLE, citations=[]),
            SimpleNamespace(
                type="web_search_tool_result",
                content=[SimpleNamespace(url="https://cnbc.com/a", title="CNBC")],
            ),
        ],
    )
    writer = ClaudeArticleWriter(Config(), client=_FakeClient(message))
    topic = TopicCandidate(
        term="nvidia earnings",
        keywords=["nvidia earnings", "chip stocks"],
        headlines=[Headline(title="Nvidia beats", url="https://x/1", source="CNBC", published=NOW)],
        score=9.9,
    )
    article = writer.generate(topic, today=NOW)
    assert article.title.startswith("Nvidia Earnings")
    assert article.slug
    assert article.keywords == ["nvidia earnings", "chip stocks"]
    assert any(s.url == "https://cnbc.com/a" for s in article.sources)
    assert article.model == "claude-opus-4-7"
    assert article.virality_score == 9.9
