from datetime import datetime, timezone

import pytest

from stockscribe.models import Article, Source
from stockscribe.publishing.markdown import slugify, write_article

NOW = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)


def _article(title="Nvidia Earnings Explained"):
    return Article(
        title=title,
        slug=slugify(title),
        summary="A clear explainer.",
        body_markdown=f"# {title}\n\nIntro paragraph.\n\n## Body\nSome **content** [1].\n\n## Sources\n[1] CNBC — https://cnbc.com/a",
        keywords=["nvidia earnings", "chip stocks"],
        sources=[Source(title="CNBC", url="https://cnbc.com/a")],
        topic_term="nvidia earnings",
        virality_score=8.0,
        generated_at=NOW,
        model="claude-opus-4-7",
    )


def test_build_site_renders_index_and_posts(tmp_path):
    pytest.importorskip("markdown")
    from stockscribe.publishing.site import build_site

    content = tmp_path / "content"
    site = tmp_path / "site"
    write_article(_article(), content)

    index = build_site(content, site, platform_name="The Trading Desk")
    assert index.exists()

    index_html = index.read_text()
    assert "The Trading Desk" in index_html
    assert "Nvidia Earnings Explained" in index_html
    assert "nvidia earnings" in index_html  # keyword chip

    posts = list((site / "posts").glob("*.html"))
    assert len(posts) == 1
    post_html = posts[0].read_text()
    assert "<h1" in post_html
    assert "Sources" in post_html
    assert (site / "assets" / "style.css").exists()


def test_build_site_handles_empty_content(tmp_path):
    pytest.importorskip("markdown")
    from stockscribe.publishing.site import build_site

    index = build_site(tmp_path / "content", tmp_path / "site")
    assert index.exists()
    assert "No articles yet" in index.read_text()


def test_rss_parsing_with_fixture(tmp_path):
    feedparser = pytest.importorskip("feedparser")
    from stockscribe.sources.rss import fetch_headlines

    rss_xml = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <title>Test Wire</title>
      <item>
        <title>Nvidia earnings beat estimates</title>
        <link>https://example.com/nvda</link>
        <description>Chip giant tops forecasts</description>
      </item>
    </channel></rss>"""
    feed_file = tmp_path / "feed.xml"
    feed_file.write_text(rss_xml)

    # feedparser accepts a local path/URL string
    headlines = fetch_headlines([str(feed_file)], lookback_hours=48, now=NOW)
    assert len(headlines) == 1
    assert headlines[0].title == "Nvidia earnings beat estimates"
    assert headlines[0].url == "https://example.com/nvda"
    assert headlines[0].source == "Test Wire"
