from datetime import datetime, timezone

import pytest

from stockscribe.models import Article, Source
from stockscribe.publishing.markdown import (
    article_filename,
    load_articles,
    read_article,
    slugify,
    write_article,
)

NOW = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Nvidia Earnings Beat!", "nvidia-earnings-beat"),
        ("Fed & Rates: What Now?", "fed-rates-what-now"),
        ("   ", "article"),
    ],
)
def test_slugify(text, expected):
    assert slugify(text) == expected


def _article():
    return Article(
        title="Why Nvidia's Earnings Sent Chip Stocks Soaring",
        slug=slugify("Why Nvidia's Earnings Sent Chip Stocks Soaring"),
        summary="A beginner-friendly look at the rally.",
        body_markdown="# Why Nvidia's Earnings Sent Chip Stocks Soaring\n\nIntro.\n\n## Body\nText [1].\n\n## Sources\n[1] Foo — https://example.com",
        keywords=["nvidia earnings", "chip stocks", "ai"],
        sources=[Source(title="Foo", url="https://example.com")],
        topic_term="nvidia earnings",
        virality_score=12.34,
        generated_at=NOW,
        model="claude-opus-4-7",
    )


def test_write_then_read_roundtrip(tmp_path):
    art = _article()
    path = write_article(art, tmp_path)
    assert path.name == article_filename(art)
    assert path.name.startswith("2026-05-25-")

    stored = read_article(path)
    assert stored.meta["title"] == art.title
    assert stored.meta["keywords"] == art.keywords
    assert stored.meta["virality_score"] == 12.34
    assert stored.meta["sources"][0]["url"] == "https://example.com"
    assert "## Sources" in stored.body
    assert stored.body.startswith("#")


def test_load_articles_sorted_newest_first(tmp_path):
    a1 = _article()
    a2 = _article()
    a2.generated_at = datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc)
    a2.slug = "older-piece"
    a2.title = "Older Piece"
    write_article(a1, tmp_path)
    write_article(a2, tmp_path)

    loaded = load_articles(tmp_path)
    assert len(loaded) == 2
    assert loaded[0].title == a1.title  # newest first
