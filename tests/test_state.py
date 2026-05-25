from datetime import datetime, timedelta, timezone

from stockscribe.state import SeenStore, normalize_term

NOW = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)


def test_normalize_term():
    assert normalize_term("  Nvidia   Earnings ") == "nvidia earnings"


def test_mark_and_seen_within_window(tmp_path):
    store = SeenStore(tmp_path / "state.json")
    assert not store.is_seen("Nvidia earnings", within_days=14, now=NOW)
    store.mark("Nvidia earnings", now=NOW)
    assert store.is_seen("nvidia   EARNINGS", within_days=14, now=NOW)


def test_not_seen_after_window(tmp_path):
    store = SeenStore(tmp_path / "state.json")
    store.mark("topic", now=NOW - timedelta(days=20))
    assert not store.is_seen("topic", within_days=14, now=NOW)


def test_persistence_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    store = SeenStore(path)
    store.mark("topic a", now=NOW)
    store.save()

    reopened = SeenStore(path)
    assert reopened.is_seen("topic a", within_days=14, now=NOW)


def test_prune_drops_old_entries(tmp_path):
    store = SeenStore(tmp_path / "state.json")
    store.mark("old", now=NOW - timedelta(days=40))
    store.mark("recent", now=NOW)
    store.prune(older_than_days=30, now=NOW)
    store.save()

    reopened = SeenStore(tmp_path / "state.json")
    assert reopened.is_seen("recent", within_days=60, now=NOW)
    assert not reopened.is_seen("old", within_days=60, now=NOW)
