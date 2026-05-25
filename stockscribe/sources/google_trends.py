"""Harvest rising/breakout finance queries from Google Trends.

Google Trends has no official API and pytrends is rate-limit prone, so every
call is defensive: any failure degrades to "no trend signal" rather than
breaking the pipeline. RSS alone still produces useful topics.
"""

from __future__ import annotations

import logging

from ..models import TrendSignal

log = logging.getLogger(__name__)

# pytrends reports rising values as an integer percentage, or the sentinel
# "Breakout" for >5000% growth. We normalize to 0..1.
_BREAKOUT_VALUE = 1.0
_CAP_PERCENT = 1000.0


def _normalize(value) -> float:
    if isinstance(value, str):
        if value.strip().lower() == "breakout":
            return _BREAKOUT_VALUE
        try:
            value = float(value.replace("%", "").replace(",", "").strip())
        except ValueError:
            return _BREAKOUT_VALUE
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(pct / _CAP_PERCENT, 1.0))


def fetch_trends(seeds: list[str], geo: str = "US") -> list[TrendSignal]:
    try:
        from pytrends.request import TrendReq  # imported lazily
    except ImportError:
        log.warning("pytrends not installed; skipping Google Trends signals")
        return []

    signals: dict[str, float] = {}
    try:
        pytrends = TrendReq(hl="en-US", tz=0)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not initialize pytrends: %s", exc)
        return []

    for seed in seeds:
        try:
            pytrends.build_payload([seed], timeframe="now 7-d", geo=geo)
            related = pytrends.related_queries()
            rising = (related.get(seed) or {}).get("rising")
            if rising is None:
                continue
            for _, row in rising.iterrows():
                term = str(row.get("query", "")).strip()
                if not term:
                    continue
                val = _normalize(row.get("value"))
                signals[term] = max(signals.get(term, 0.0), val)
        except Exception as exc:  # noqa: BLE001
            log.warning("Google Trends lookup failed for seed %r: %s", seed, exc)
            continue

    out = [TrendSignal(term=t, value=v) for t, v in signals.items()]
    log.info("Collected %d rising trend signals", len(out))
    return out
