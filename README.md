# StockScribe

A self-sustaining content engine for a **stock-trading literacy platform**. It
researches which market topics and keywords are about to *break out*, then writes
educational, properly-cited articles around them and publishes a browsable site.

```
research (RSS + Google Trends) → virality scoring + keyword extraction
   → dedup → pick top topics → Claude writes a cited article (live web research)
   → Markdown store + static HTML site → record topics so the next run is fresh
```

## How it finds "about to go viral" topics

`stockscribe/discovery.py` scores every candidate topic by combining four signals:

| Signal | Source | Why it matters |
|---|---|---|
| **Momentum** | Google Trends *rising/breakout* queries | leading indicator that a search term is surging |
| **Frequency** | finance RSS headlines | how much the news cycle is converging on it |
| **Recency** | headline timestamps (exp. decay) | fresh stories weigh far more than stale ones |
| **Diversity** | distinct outlets | broad pickup beats one outlet hammering a story |

Score = `recency-weighted frequency × source diversity × (1 + trend_weight × trend)`.
Each topic also gets a cluster of related **keywords** (co-occurring terms) so the
article ranks for the whole theme, not just the headline phrase.

## Citations are real, not invented

Articles are written by **Claude (`claude-opus-4-7`)** using the server-side
`web_search` / `web_fetch` tools. The published source list is built from the URLs
the model **actually retrieved** during research (`web_search_tool_result` blocks),
so citations are grounded rather than free-text. The editorial brief enforces inline
`[n]` citations, a `## Sources` section, jargon definitions, and a
"not investment advice" disclaimer.

## Install

```bash
pip install -r requirements.txt        # or: pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...    # required for `run` (generation)
```

## Use

```bash
# 1. See what's trending right now — no API spend, no writing
stockscribe discover

# 2. Run the whole pipeline: research → generate → publish
stockscribe run --num 3

# 3. Research/select only (no Claude calls)
stockscribe run --dry-run

# 4. Rebuild the browsable site from the Markdown store
stockscribe build-site
```

Open `site/index.html` to browse the platform. Markdown lives in `content/`.

### Self-sustaining / scheduled use

One `stockscribe run` is the whole loop and is safe to schedule (cron, GitHub
Action, etc.). A dedup store (`.stockscribe_state.json`) records every topic it
covers, so repeated runs keep producing **fresh** articles and never rehash a
topic within `dedup_days` (default 14). Example daily cron:

```cron
0 13 * * *  cd /path/to/repo && ANTHROPIC_API_KEY=... stockscribe run --num 2
```

## Configure

Everything has sensible defaults. To customize, copy `config.example.yaml` and pass
it with `--config`. Notable keys: `feeds`, `trend_seeds`, `num_articles`,
`dedup_days`, `model`, `effort`, `target_words`, `tools`, `content_dir`, `site_dir`.

CLI overrides: `--num`, `--no-trends`, `--no-site`, `--output-dir`, `-v/--verbose`.

## Resilience

- No `ANTHROPIC_API_KEY`? Use `discover` / `--dry-run` for the research path.
- Google Trends rate-limited or down → degrades to RSS-only automatically.
- A dead feed is logged and skipped; one bad feed never aborts a run.
- `web_fetch` not enabled on your account → retries with `web_search` only.

## Tests

```bash
python -m pytest -q
```

The suite covers the pure logic — virality scoring, keyword extraction, dedup
state, Markdown round-trip, source extraction, and site rendering — with no
network or API calls.

## Layout

```
stockscribe/
  discovery.py        # keyword extraction + virality scoring (pure)
  config.py           # defaults + YAML loading
  state.py            # dedup store (self-sustaining runs)
  sources/rss.py      # finance RSS headlines
  sources/google_trends.py
  generation.py       # Claude writer: web research + grounded citations
  publishing/markdown.py  # canonical Markdown store
  publishing/site.py      # static HTML site renderer
  pipeline.py         # orchestration
  cli.py              # `stockscribe` command
content/              # generated Markdown (the canonical store)
site/                 # generated browsable site (rebuildable)
```

*Educational content only — not investment advice.*
