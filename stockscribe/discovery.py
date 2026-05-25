"""Turn raw news + trend signals into ranked, scored topic candidates.

The scoring model estimates "virality potential" by combining four signals:

  * momentum   - Google Trends "rising"/"breakout" terms (a leading signal that
                 a query is about to surge), boosted heavily.
  * frequency  - how many distinct recent headlines mention the term.
  * recency    - newer mentions count more (exponential decay by half-life).
  * diversity  - how many distinct outlets carry the term (broad pickup, not
                 one outlet hammering a story).

Everything here is deterministic and free of network/SDK calls so it can be
unit-tested in isolation.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import datetime, timezone

from .config import Config
from .models import Headline, TopicCandidate, TrendSignal

# Common English words plus finance filler that carry no topical signal.
STOPWORDS: frozenset[str] = frozenset(
    """
    a an the and or but if then else for to of in on at by with from as is are was
    were be been being this that these those it its it's they them their there here
    what which who whom how when where why all any both each few more most other some
    such no nor not only own same so than too very can will just should now about into
    over after before up down out off above below again further once you your we our us
    he she his her i me my mine do does did doing have has had having would could may
    might must shall vs versus amid amid's says say said new latest update report
    stock stocks market markets share shares today week year day high low close
    """.split()
)

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'&.-]*[A-Za-z]|[A-Za-z]")
_TICKER_RE = re.compile(r"\$[A-Za-z]{1,5}\b")
_ALLCAPS_RE = re.compile(r"\b[A-Z]{2,5}\b")


def recency_weight(published: datetime | None, now: datetime, half_life_hours: float) -> float:
    """Exponential decay in [0, 1]. Undated items get a neutral 0.5."""
    if published is None:
        return 0.5
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (now - published).total_seconds() / 3600.0)
    return 0.5 ** (age_hours / max(half_life_hours, 0.1))


def _norm(term: str) -> str:
    return " ".join(term.lower().split())


def extract_terms(title: str) -> set[str]:
    """Extract candidate key-phrases from a headline.

    Returns a set of normalized terms: cashtags ($NVDA), uppercase acronyms
    (NVDA, AI), and stopword-free bigrams/trigrams.
    """
    terms: set[str] = set()

    for ticker in _TICKER_RE.findall(title):
        terms.add(ticker.lower())
    for acronym in _ALLCAPS_RE.findall(title):
        terms.add(acronym.lower())

    words = [w.lower() for w in _WORD_RE.findall(title)]
    content = [w for w in words if w not in STOPWORDS and len(w) > 2]

    # n-grams over the original (non-filtered) token stream, but require the
    # n-gram to contain at least one content word and no leading/trailing
    # stopword so phrases read naturally.
    for n in (2, 3):
        for i in range(len(words) - n + 1):
            gram = words[i : i + n]
            if gram[0] in STOPWORDS or gram[-1] in STOPWORDS:
                continue
            if not any(w not in STOPWORDS and len(w) > 2 for w in gram):
                continue
            terms.add(" ".join(gram))

    # Strong single content words (e.g. "nvidia", "powell", "earnings").
    for w in content:
        terms.add(w)

    return terms


def _trend_lookup(trends: list[TrendSignal]) -> dict[str, float]:
    out: dict[str, float] = {}
    for t in trends:
        out[_norm(t.term)] = max(out.get(_norm(t.term), 0.0), t.value)
    return out


def _trend_boost(term: str, trend_map: dict[str, float]) -> float:
    """Best fuzzy match of a candidate term against trending queries."""
    if term in trend_map:
        return trend_map[term]
    best = 0.0
    for tt, val in trend_map.items():
        if term in tt or tt in term:
            best = max(best, val * 0.7)  # partial overlap discounted
    return best


def score_candidates(
    headlines: list[Headline],
    trends: list[TrendSignal],
    config: Config,
    now: datetime | None = None,
) -> list[TopicCandidate]:
    """Rank topics by virality potential. Highest score first."""
    now = now or datetime.now(timezone.utc)
    trend_map = _trend_lookup(trends)

    # Per-term aggregates.
    recency_sum: dict[str, float] = defaultdict(float)
    sources: dict[str, set[str]] = defaultdict(set)
    docs: dict[str, list[Headline]] = defaultdict(list)

    for h in headlines:
        weight = recency_weight(h.published, now, config.recency_half_life_hours)
        terms = extract_terms(f"{h.title} {h.summary}".strip())
        for term in terms:
            recency_sum[term] += weight
            sources[term].add(h.source)
            docs[term].append(h)

    # Pure trend terms with no news yet are still worth surfacing.
    for term, val in trend_map.items():
        if term not in recency_sum:
            recency_sum[term] = 0.0
            sources.setdefault(term, set())
            docs.setdefault(term, [])

    candidates: list[TopicCandidate] = []
    for term, freq in recency_sum.items():
        n_sources = len(sources[term])
        diversity = 1.0 + math.log1p(n_sources)
        trend_val = _trend_boost(term, trend_map)
        base = freq * diversity
        score = base * (1.0 + config.trend_weight * trend_val)

        # Drop weak noise: single undated mention from one source and no trend.
        if score <= 0 and trend_val <= 0:
            continue
        if n_sources < 2 and trend_val <= 0 and freq < 1.0:
            continue

        candidates.append(
            TopicCandidate(
                term=term,
                headlines=sorted(
                    docs[term],
                    key=lambda h: recency_weight(h.published, now, config.recency_half_life_hours),
                    reverse=True,
                ),
                sources=set(sources[term]),
                trend_value=trend_val,
                score=score,
                components={
                    "frequency": round(freq, 4),
                    "diversity": round(diversity, 4),
                    "trend": round(trend_val, 4),
                    "sources": float(n_sources),
                },
            )
        )

    # Deterministic ordering: score desc, then term for stable tie-breaks.
    candidates.sort(key=lambda c: (c.score, c.term), reverse=True)
    candidates = candidates[: config.max_candidates]
    return cluster_candidates(candidates)


def _terms_related(a: str, b: str) -> bool:
    """True if one term's words are a subset of the other's (e.g. 'nvidia' vs
    'nvidia earnings'), meaning they almost certainly describe the same story."""
    sa, sb = set(a.split()), set(b.split())
    return bool(sa) and bool(sb) and (sa <= sb or sb <= sa)


def cluster_candidates(
    candidates: list[TopicCandidate],
    overlap_threshold: float = 0.34,
    max_keywords: int = 8,
) -> list[TopicCandidate]:
    """Merge term candidates that describe the same story into one topic.

    Candidates are merged into an existing higher-scoring lead when they share a
    meaningful fraction of source headlines or when their terms are subset-related.
    Absorbed terms become the lead's focus keywords. This yields one article per
    story (with a rich keyword cluster) instead of several near-duplicates.
    """
    leads: list[TopicCandidate] = []
    for cand in candidates:
        cand_urls = {h.url for h in cand.headlines}
        target: TopicCandidate | None = None
        for lead in leads:
            lead_urls = {h.url for h in lead.headlines}
            if cand_urls and lead_urls:
                inter = len(cand_urls & lead_urls)
                denom = min(len(cand_urls), len(lead_urls))
                if inter and inter / denom >= overlap_threshold:
                    target = lead
                    break
            if _terms_related(cand.term, lead.term):
                target = lead
                break

        if target is None:
            cand.keywords = [cand.term]
            leads.append(cand)
            continue

        if cand.term not in target.keywords:
            target.keywords.append(cand.term)
        seen_urls = {h.url for h in target.headlines}
        for h in cand.headlines:
            if h.url not in seen_urls:
                target.headlines.append(h)
                seen_urls.add(h.url)
        target.sources |= cand.sources
        target.trend_value = max(target.trend_value, cand.trend_value)

    for lead in leads:
        ordered = [lead.term] + [k for k in lead.keywords if k != lead.term]
        seen: set[str] = set()
        lead.keywords = [k for k in ordered if not (k in seen or seen.add(k))][:max_keywords]
        lead.components["sources"] = float(len(lead.sources))

    leads.sort(key=lambda c: (c.score, c.term), reverse=True)
    return leads
