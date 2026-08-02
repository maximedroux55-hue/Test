# Swiss DeepTech news aggregator

Collects recent news about **deep technology in Switzerland** from public RSS
feeds, scores each story for Swiss + DeepTech relevance, removes duplicate
stories reported by several outlets, and writes a ranked digest as Markdown and
HTML.

It reads from RSS feeds (including Google News search feeds) rather than
scraping web pages directly. That is deliberate: feeds are stable, layout-proof,
and respectful of sites' terms, so the tool needs far less maintenance than a
traditional scraper.

## Setup (once)

You need Python 3.10 or newer.

```bash
cd deeptech-news
pip install -r requirements.txt
```

## Run it

```bash
python scraper.py                      # digest + LinkedIn drafts (default)
python scraper.py --format digest      # ranked digest only
python scraper.py --format linkedin    # Climb LinkedIn drafts only
python scraper.py --days 14            # widen the window
python scraper.py --limit 15           # shorter digest
python scraper.py --min-score 6        # stricter relevance filter
```

Output is written to `output/`:

- `digest-YYYY-MM-DD.md` and `.html` — the ranked list of stories.
- `linkedin-YYYY-MM-DD.md` — ready-to-edit Climb Ventures LinkedIn drafts for
  the top stories (catchy title, emoji bullets, Swiss flag on Swiss summaries,
  Climb positioning, varied layouts).

> The LinkedIn drafts are a strong starting point, not final copy. Because the
> tool reads RSS feeds rather than full article text, review and polish each
> draft before posting. For fully AI-written summaries, see "Going further".

> Note: this must run from a machine or environment with normal internet
> access. It will not fetch news from inside a restricted/sandboxed network.

## Customising the sources

Open `sources.py`:

- `GOOGLE_NEWS_QUERIES` is the main knob. Add or edit search phrases to change
  what the tool looks for. Each query is already scoped to Switzerland.
- `DIRECT_FEEDS` lists institution and media feeds (EPFL, ETH, Startupticker,
  swissinfo). Feeds that are unreachable are skipped automatically.

## Tuning relevance

Open `relevance.py`:

- `SWISS_TERMS` and `DEEPTECH_TERMS` are weighted keyword lists. Raise a weight
  to make a term count for more; add terms you care about (company names,
  cantons, specific technologies).
- A story is kept only if it has at least one Swiss signal AND one DeepTech
  signal.

## Files

| File | Purpose |
|------|---------|
| `scraper.py` | Main program: fetch, filter, rank, write output |
| `sources.py` | The list of feeds and search queries |
| `relevance.py` | Scoring and de-duplication logic |
| `linkedin.py` | Turns stories into Climb LinkedIn post drafts |
| `ai_writer.py` | Optional: writes posts in Max's voice via the Claude API |
| `requirements.txt` | Python dependencies |
| `output/` | Generated digests (git-ignored) |

## AI-written posts (optional)

The LinkedIn drafts work with zero setup using built-in templates. For fully
written posts in Max's voice, the tool can call the **Claude API** instead. This
is automatic when an API key is present, and falls back to templates when it is
not.

To turn it on:

1. Create an API key at https://console.anthropic.com. This is separate from a
   Claude.ai subscription and is billed per use (a weekly digest costs cents).
2. Provide the key:
   - **Locally:** `export ANTHROPIC_API_KEY=sk-ant-...` before running.
   - **In GitHub Actions:** add a repository secret named `ANTHROPIC_API_KEY`
     (Settings, then Secrets and variables, then Actions). The workflow already
     passes it through.

Optional: set `ANTHROPIC_MODEL` (default `claude-opus-5`) to use a cheaper model
such as `claude-sonnet-5`.

The digest header notes which mode produced the posts, so you always know
whether you are looking at AI-written or template drafts.
