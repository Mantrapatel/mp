"""Persistent dedup state so repeated runs stay self-sustaining.

We record the normalized term of every topic we publish, with a timestamp.
Selection skips terms seen within `dedup_days`, so a scheduled/cron run keeps
producing fresh articles instead of rehashing yesterday's news.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def normalize_term(term: str) -> str:
    return " ".join(term.lower().split())


class SeenStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._seen: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text())
                self._seen = dict(raw.get("seen", {}))
            except (json.JSONDecodeError, OSError, AttributeError):
                self._seen = {}

    def is_seen(self, term: str, within_days: int, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        ts = self._seen.get(normalize_term(term))
        if ts is None:
            return False
        try:
            when = datetime.fromisoformat(ts)
        except ValueError:
            return False
        return (now - when) <= timedelta(days=within_days)

    def mark(self, term: str, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        self._seen[normalize_term(term)] = now.isoformat()

    def prune(self, older_than_days: int, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        cutoff = now - timedelta(days=older_than_days)
        kept: dict[str, str] = {}
        for term, ts in self._seen.items():
            try:
                if datetime.fromisoformat(ts) >= cutoff:
                    kept[term] = ts
            except ValueError:
                continue
        self._seen = kept

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"seen": self._seen}
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True))
