from datetime import datetime, timezone

from stockscribe.config import Config
from stockscribe.generation_free import TemplateArticleWriter, _clean
from stockscribe.models import Headline, TopicCandidate

NOW = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)


def test_clean_strips_html_and_truncates():
    assert _clean("<p>Hello &amp; welcome</p>") == "Hello & welcome"
    long = "word " * 100
    out = _clean(long, limit=50)
    assert len(out) <= 51 and out.endswith("…")


def test_free_writer_builds_cited_roundup():
    topic = TopicCandidate(
        term="fed rate cut",
        keywords=["fed rate cut", "interest rates", "bonds"],
        headlines=[
            Headline("Fed signals a rate cut is coming", "https://cnbc.com/a", "CNBC", NOW, "<b>Markets</b> rallied."),
            Headline("Rate cut bets lift bank stocks", "https://yahoo.com/b", "Yahoo Finance", NOW),
            Headline("Dup link should be deduped", "https://cnbc.com/a", "CNBC", NOW),
        ],
        sources={"CNBC", "Yahoo Finance"},
        score=18.4,
    )
    writer = TemplateArticleWriter(Config())
    art = writer.generate(topic, today=NOW)

    assert art.model == "template-free"
    assert art.title.startswith("Fed rate cut")
    assert art.body_markdown.startswith("# ")
    # real, deduped source links
    urls = [s.url for s in art.sources]
    assert urls == ["https://cnbc.com/a", "https://yahoo.com/b"]
    assert "## Sources" in art.body_markdown
    assert "https://cnbc.com/a" in art.body_markdown
    # html stripped from snippet
    assert "<b>" not in art.body_markdown
    assert "Markets rallied" in art.body_markdown
    # keywords surfaced
    assert "interest rates" in art.body_markdown


def test_free_writer_handles_no_headlines():
    topic = TopicCandidate(term="meme stock squeeze", keywords=["meme stock squeeze"], score=5.0)
    art = TemplateArticleWriter(Config()).generate(topic, today=NOW)
    assert art.title
    assert art.body_markdown.startswith("# ")
    assert art.sources == []
