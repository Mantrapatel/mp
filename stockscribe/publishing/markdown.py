"""Write articles to Markdown with YAML front-matter, and read them back.

Markdown files in `content/` are the canonical store: human-readable, portable,
and the source the static site is rendered from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from ..models import Article, Source

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def slugify(text: str, max_len: int = 70) -> str:
    slug = _SLUG_STRIP.sub("-", text.lower()).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rsplit("-", 1)[0]
    return slug or "article"


@dataclass
class StoredArticle:
    """An article parsed back from disk for site rendering."""

    meta: dict
    body: str
    path: Path

    @property
    def title(self) -> str:
        return str(self.meta.get("title", self.path.stem))

    @property
    def date(self) -> str:
        return str(self.meta.get("date", ""))


def article_filename(article: Article) -> str:
    return f"{article.generated_at.date().isoformat()}-{article.slug}.md"


def write_article(article: Article, content_dir: str | Path) -> Path:
    content_dir = Path(content_dir)
    content_dir.mkdir(parents=True, exist_ok=True)
    path = content_dir / article_filename(article)

    meta = {
        "title": article.title,
        "date": article.generated_at.date().isoformat(),
        "generated_at": article.generated_at.isoformat(),
        "slug": article.slug,
        "topic": article.topic_term,
        "keywords": list(article.keywords),
        "virality_score": article.virality_score,
        "model": article.model,
        "summary": article.summary,
        "sources": [{"title": s.title, "url": s.url} for s in article.sources],
    }
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    path.write_text(f"---\n{front}\n---\n\n{article.body_markdown.strip()}\n")
    return path


def read_article(path: str | Path) -> StoredArticle:
    path = Path(path)
    text = path.read_text()
    m = _FRONT_MATTER.match(text)
    if m:
        meta = yaml.safe_load(m.group(1)) or {}
        body = m.group(2)
    else:
        meta, body = {}, text
    return StoredArticle(meta=meta, body=body, path=path)


def load_articles(content_dir: str | Path) -> list[StoredArticle]:
    content_dir = Path(content_dir)
    if not content_dir.exists():
        return []
    articles = [read_article(p) for p in content_dir.glob("*.md")]
    articles.sort(key=lambda a: (a.meta.get("generated_at", ""), a.date), reverse=True)
    return articles


def sources_from_meta(meta: dict) -> list[Source]:
    return [Source(title=s.get("title", ""), url=s.get("url", "")) for s in meta.get("sources", [])]
