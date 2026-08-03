#!/usr/bin/env python3
"""Swiss DeepTech news aggregator.

Collects recent news about deep technology in Switzerland from public RSS
feeds, scores each item for Swiss + DeepTech relevance, removes duplicate
stories, and writes a ranked digest as Markdown and HTML.

No API keys needed. Basic use:

    pip install -r requirements.txt
    python scraper.py

Common options:

    python scraper.py --days 7 --limit 20     # last 7 days, top 20 stories
    python scraper.py --min-score 6           # stricter relevance filter

Output lands in ./output/ as digest-YYYY-MM-DD.md and .html
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import sys
import time
from calendar import timegm

try:
    import feedparser
except ImportError:
    sys.exit("Missing dependency 'feedparser'. Run: pip install -r requirements.txt")

from sources import all_feeds
from relevance import score_article, deduplicate, is_excluded
from linkedin import to_linkedin


def _entry_date(entry) -> dt.datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return dt.datetime.fromtimestamp(timegm(parsed), dt.timezone.utc)


def _entry_image(entry) -> str | None:
    """Return an image URL the RSS feed itself provides, if any."""
    media = entry.get("media_thumbnail") or entry.get("media_content")
    if isinstance(media, list) and media and media[0].get("url"):
        return media[0]["url"]
    for link in entry.get("links", []):
        if link.get("rel") == "enclosure" and str(link.get("type", "")).startswith("image"):
            return link.get("href")
    return None


def _publisher(entry, source_label: str) -> str:
    # Google News nests the real publisher under 'source'.
    src = entry.get("source")
    if isinstance(src, dict) and src.get("title"):
        return src["title"]
    if source_label != "Google News":
        return source_label
    # Fallback: many Google News titles end with " - Publisher".
    title = entry.get("title", "")
    if " - " in title:
        return title.rsplit(" - ", 1)[-1].strip()
    return "Google News"


def collect(days: int, min_score: int) -> list[dict]:
    """Fetch all feeds and return a list of relevant, de-duplicated articles."""
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    articles: list[dict] = []
    seen_links = set()

    browser_ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
    for source_label, url in all_feeds(days):
        parsed = feedparser.parse(url, agent=browser_ua)
        if parsed.bozo and not parsed.entries:
            print(f"  ! skipped (unreachable): {source_label} {url}", file=sys.stderr)
            continue

        for entry in parsed.entries:
            link = entry.get("link", "")
            if not link or link in seen_links:
                continue
            # Market-research pages, stock chatter and directory listings use
            # the right vocabulary but never carry the story.
            if is_excluded(link):
                continue

            date = _entry_date(entry)
            if date and date < cutoff:
                continue

            title = entry.get("title", "").strip()
            summary = entry.get("summary", "")
            publisher = _publisher(entry, source_label)

            score = score_article(title, summary, publisher)
            if score < min_score:
                continue

            seen_links.add(link)
            articles.append({
                "title": title,
                "link": link,
                "publisher": publisher,
                "date": date,
                "score": score,
                "summary": summary,
                "image_feed": _entry_image(entry),
            })

    articles = deduplicate(articles)
    # Rank by relevance first, then most recent.
    _oldest = dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    articles.sort(
        key=lambda a: (a["score"], a["date"] or _oldest),
        reverse=True,
    )
    return articles


def _fmt_date(d: dt.datetime | None) -> str:
    return d.strftime("%d %b %Y") if d else "n/a"


def to_markdown(articles: list[dict], days: int) -> str:
    today = dt.date.today().strftime("%d %B %Y")
    lines = [
        f"# Swiss DeepTech news digest",
        f"_Generated {today}, covering the last {days} days. {len(articles)} stories._",
        "",
    ]
    for i, a in enumerate(articles, 1):
        lines.append(
            f"{i}. **[{a['title']}]({a['link']})**  "
            f"\n   {a['publisher']} · {_fmt_date(a['date'])} · relevance {a['score']}"
        )
    if not articles:
        lines.append("_No relevant stories found in this window._")
    return "\n".join(lines) + "\n"


def to_html(articles: list[dict], days: int) -> str:
    today = dt.date.today().strftime("%d %B %Y")
    rows = []
    for i, a in enumerate(articles, 1):
        rows.append(
            f'<li><a href="{html.escape(a["link"])}" target="_blank" rel="noopener">'
            f'{html.escape(a["title"])}</a>'
            f'<div class="meta">{html.escape(a["publisher"])} · {_fmt_date(a["date"])} '
            f'· <span class="score">relevance {a["score"]}</span></div></li>'
        )
    body = "\n".join(rows) or "<p>No relevant stories found in this window.</p>"
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Swiss DeepTech news digest</title>
<style>
  :root {{ --green:#46b96a; --ink:#1b2430; --soft:#5b6472; --line:#e6eae8; --bg:#f6f8f7; }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
         background:var(--bg); color:var(--ink); line-height:1.55; }}
  .wrap {{ max-width:720px; margin:0 auto; padding:2.5rem 1.25rem 4rem; }}
  h1 {{ font-size:1.8rem; letter-spacing:-0.02em; }}
  h1 .dot {{ color:var(--green); }}
  .sub {{ color:var(--soft); margin:0.4rem 0 2rem; font-size:0.95rem; }}
  ol {{ list-style:none; counter-reset:item; }}
  li {{ counter-increment:item; background:#fff; border:1px solid var(--line);
        border-radius:14px; padding:1rem 1.1rem 1rem 3rem; margin-bottom:0.8rem; position:relative; }}
  li::before {{ content:counter(item); position:absolute; left:1rem; top:1rem;
        color:var(--green); font-weight:800; }}
  li a {{ color:var(--ink); text-decoration:none; font-weight:600; }}
  li a:hover {{ color:var(--green); }}
  .meta {{ color:var(--soft); font-size:0.85rem; margin-top:0.3rem; }}
  .score {{ color:var(--green); font-weight:600; }}
  footer {{ color:var(--soft); font-size:0.8rem; margin-top:2rem; }}
</style></head><body>
<div class="wrap">
  <h1>Swiss DeepTech news<span class="dot">.</span></h1>
  <p class="sub">Generated {today} · last {days} days · {len(articles)} stories</p>
  <ol>
    {body}
  </ol>
  <footer>Built with the Swiss DeepTech aggregator.</footer>
</div></body></html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Swiss DeepTech news aggregator")
    ap.add_argument("--days", type=int, default=7, help="How many days back to look (default 7)")
    ap.add_argument("--limit", type=int, default=25, help="Max stories to keep (default 25)")
    ap.add_argument("--min-score", type=int, default=4, help="Minimum relevance score (default 4)")
    ap.add_argument("--outdir", default="output", help="Output directory (default ./output)")
    ap.add_argument("--format", choices=["digest", "linkedin", "both"], default="both",
                    help="What to produce: ranked digest, LinkedIn drafts, or both (default both)")
    ap.add_argument("--posts", type=int, default=7,
                    help="Number of LinkedIn drafts to write, one per day (default 7)")
    ap.add_argument("--max-per-source", type=int, default=2,
                    help="Max posts from any single outlet, for variety (default 2)")
    ap.add_argument("--history", default="../digest/history.json",
                    help="Record of stories already posted, so none repeats")
    args = ap.parse_args()

    print(f"Fetching Swiss DeepTech news (last {args.days} days)...", file=sys.stderr)
    articles = collect(args.days, args.min_score)[: args.limit]
    print(f"Kept {len(articles)} relevant stories.", file=sys.stderr)

    import os
    os.makedirs(args.outdir, exist_ok=True)
    stamp = dt.date.today().isoformat()

    if args.format in ("digest", "both"):
        md_path = os.path.join(args.outdir, f"digest-{stamp}.md")
        html_path = os.path.join(args.outdir, f"digest-{stamp}.html")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(to_markdown(articles, args.days))
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(to_html(articles, args.days))
        print(f"Wrote {md_path}", file=sys.stderr)
        print(f"Wrote {html_path}", file=sys.stderr)

    if args.format in ("linkedin", "both"):
        import json
        from images import enrich_articles
        from relevance import diversify
        from linkedin import build_posts, render_markdown, render_plan_html, COWORK_PROMPT

        # Never post the same story twice, this week or in any earlier run.
        import history as history_mod
        past = history_mod.load(args.history)
        unused = history_mod.filter_seen(articles, past)
        if len(unused) < len(articles):
            print(
                f"Skipped {len(articles) - len(unused)} stories already posted "
                f"in an earlier run.",
                file=sys.stderr,
            )

        # Spread the posts across outlets so one publisher does not take the
        # whole week, then look up each one's image and primary source.
        picks = diversify(unused, args.max_per_source)[: args.posts]
        if len(picks) < args.posts:
            print(
                f"Only {len(picks)} unused stories available for {args.posts} "
                f"posts. Widen --days for more.",
                file=sys.stderr,
            )
        print(
            f"Picked {len(picks)} posts across "
            f"{len({p['publisher'] for p in picks})} outlets "
            f"(max {args.max_per_source} each).",
            file=sys.stderr,
        )
        print("Finding the image and primary source for each post...", file=sys.stderr)
        enrich_articles(picks)

        # Build once, then write the human plan (Markdown), the phone-friendly
        # web page (HTML, served at maxime-droux.com/plan), and the
        # machine-readable posts.json the Cowork workflow schedules from.
        records, mode = build_posts(picks, args.days, top=args.posts)

        li_path = os.path.join(args.outdir, f"linkedin-{stamp}.md")
        with open(li_path, "w", encoding="utf-8") as f:
            f.write(render_markdown(records, mode, args.days))
        print(f"Wrote {li_path}", file=sys.stderr)

        plan_path = os.path.join(args.outdir, "plan.html")
        with open(plan_path, "w", encoding="utf-8") as f:
            f.write(render_plan_html(records, mode, args.days))
        print(f"Wrote {plan_path}", file=sys.stderr)

        json_path = os.path.join(args.outdir, "posts.json")
        payload = {
            "generated": stamp,
            "mode": mode,
            "note": "Times are local. Schedule each post at its time on its date.",
            "cowork_prompt": COWORK_PROMPT,
            "posts": records,
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"Wrote {json_path}", file=sys.stderr)

        # Remember what went out, so a later run never repeats it.
        history_mod.save(args.history, history_mod.record(past, picks))
        print(f"Recorded {len(picks)} stories in {args.history}", file=sys.stderr)


if __name__ == "__main__":
    main()
