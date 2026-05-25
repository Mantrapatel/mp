from datetime import datetime, timedelta, timezone

from stockscribe.config import Config
from stockscribe.discovery import extract_terms, recency_weight, score_candidates
from stockscribe.models import Headline, TrendSignal

NOW = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)


def test_recency_weight_decays_with_age():
    fresh = recency_weight(NOW, NOW, half_life_hours=24)
    half_old = recency_weight(NOW - timedelta(hours=24), NOW, half_life_hours=24)
    older = recency_weight(NOW - timedelta(hours=48), NOW, half_life_hours=24)
    assert fresh == 1.0
    assert abs(half_old - 0.5) < 1e-9
    assert older < half_old < fresh


def test_recency_weight_undated_is_neutral():
    assert recency_weight(None, NOW, half_life_hours=24) == 0.5


def test_extract_terms_picks_tickers_acronyms_and_phrases():
    terms = extract_terms("Nvidia earnings beat sends $NVDA and AI stocks soaring")
    assert "$nvda" in terms
    assert "nvda" in terms  # acronym form
    assert "ai" in terms
    assert "nvidia earnings" in terms
    # bigram must not start/end on a stopword
    assert "and ai" not in terms


def test_extract_terms_filters_stopwords_and_boilerplate():
    terms = extract_terms("The stock market is up today")
    # "stock", "market", "today" are domain stopwords; nothing meaningful remains
    assert "stock market" not in terms
    assert "the stock" not in terms


def _h(title, source, hours_ago, summary=""):
    return Headline(
        title=title,
        url=f"https://x/{source}/{abs(hash((title, source))) % 100000}",
        source=source,
        published=NOW - timedelta(hours=hours_ago),
        summary=summary,
    )


def _find(cands, phrase):
    """Locate the cluster whose lead term or keyword cluster covers a phrase."""
    for c in cands:
        if phrase == c.term or phrase in c.keywords:
            return c
    return None


def test_score_rewards_diversity_and_recency_and_clusters():
    cfg = Config()
    headlines = [
        _h("Nvidia earnings crush estimates", "CNBC", 1),
        _h("Nvidia earnings spark rally", "MarketWatch", 2),
        _h("Nvidia earnings lift chip sector", "Yahoo", 3),
        _h("Sleepy utility stock barely moves", "OneBlog", 40),
    ]
    cands = score_candidates(headlines, [], cfg, now=NOW)
    top = cands[0]
    # The broadly-covered, fresh story should be the top cluster.
    assert "nvidia" in top.term or "earnings" in top.term
    # Overlapping terms collapse into one story-level cluster.
    cluster = _find(cands, "nvidia earnings")
    assert cluster is top
    assert "nvidia earnings" in cluster.keywords
    assert len(cluster.sources) == 3  # CNBC + MarketWatch + Yahoo, deduped


def test_trend_signal_boosts_score():
    cfg = Config()
    headlines = [
        _h("Quantum computing stock jumps", "CNBC", 2),
        _h("Quantum computing names in focus", "Yahoo", 3),
    ]
    no_trend = score_candidates(headlines, [], cfg, now=NOW)
    with_trend = score_candidates(
        headlines, [TrendSignal(term="quantum computing", value=1.0)], cfg, now=NOW
    )

    def cluster_score(cands, phrase):
        c = _find(cands, phrase)
        return c.score if c else 0.0

    assert cluster_score(with_trend, "quantum computing") > cluster_score(no_trend, "quantum computing")


def test_pure_trend_term_surfaces_without_news():
    cfg = Config()
    cands = score_candidates([], [TrendSignal(term="meme stock squeeze", value=1.0)], cfg, now=NOW)
    assert any(c.term == "meme stock squeeze" for c in cands)


def test_keywords_attached():
    cfg = Config()
    headlines = [
        _h("Fed rate cut hopes lift bank stocks", "CNBC", 1),
        _h("Fed rate cut would help bank stocks", "Yahoo", 2),
        _h("Bank stocks rally on Fed rate cut bets", "MarketWatch", 2),
    ]
    cands = score_candidates(headlines, [], cfg, now=NOW)
    assert cands
    assert cands[0].keywords  # at least the lead term
    assert cands[0].keywords[0] == cands[0].term
