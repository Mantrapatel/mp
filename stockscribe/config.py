"""Configuration loading with sane defaults.

Config is layered: built-in defaults -> optional YAML file -> CLI overrides
(applied by the caller). Keeping defaults here means the tool runs out of the
box with no config file.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

# Free, public finance RSS feeds. These carry real-time market headlines and
# require no API key.
DEFAULT_FEEDS: list[str] = [
    "https://feeds.content.dowjones.io/public/rss/mw_topstories",      # MarketWatch top stories
    "https://feeds.content.dowjones.io/public/rss/mw_marketpulse",     # MarketWatch market pulse
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",           # CNBC top news
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",            # CNBC markets
    "https://finance.yahoo.com/news/rssindex",                         # Yahoo Finance
    "https://www.investing.com/rss/news_25.rss",                       # Investing.com stock market
    "https://seekingalpha.com/market_currents.xml",                    # Seeking Alpha market currents
]

# Seed terms whose Google Trends "rising" queries we harvest as early
# virality signals.
DEFAULT_TREND_SEEDS: list[str] = [
    "stock market",
    "stocks",
    "investing",
    "stock to buy",
]


@dataclass
class Config:
    # --- discovery ---
    feeds: list[str] = field(default_factory=lambda: list(DEFAULT_FEEDS))
    trend_seeds: list[str] = field(default_factory=lambda: list(DEFAULT_TREND_SEEDS))
    enable_google_trends: bool = True
    lookback_hours: int = 48
    recency_half_life_hours: float = 24.0
    trend_weight: float = 2.0
    max_candidates: int = 40

    # --- selection ---
    num_articles: int = 3
    min_score: float = 0.0
    dedup_days: int = 14

    # --- generation ---
    model: str = "claude-opus-4-7"
    effort: str = "high"
    max_tokens: int = 16000
    target_words: int = 1500
    tools: list[str] = field(default_factory=lambda: ["web_search", "web_fetch"])
    platform_name: str = "The Trading Desk"

    # --- output ---
    content_dir: str = "content"
    site_dir: str = "site"
    state_file: str = ".stockscribe_state.json"
    build_site: bool = True

    @staticmethod
    def load(path: str | Path | None) -> "Config":
        cfg = Config()
        if path is None:
            return cfg
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Config file not found: {p}")
        data: dict[str, Any] = yaml.safe_load(p.read_text()) or {}
        return cfg.merged(data)

    def merged(self, data: dict[str, Any]) -> "Config":
        """Return a copy with the given keys overridden. Unknown keys raise."""
        known = {f.name for f in self.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"Unknown config keys: {', '.join(sorted(unknown))}")
        clean = {k: v for k, v in data.items() if v is not None}
        return replace(self, **clean)
