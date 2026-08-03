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

            # Google News names the real outlet even while its link is still a
            # redirect, so an excluded site can be spotted here already.
            if is_excluded(publisher):
                continue

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


# Stages that mean money changed hands. Partnerships and plain research news
# are kept in archive.json but do not belong on a page of rounds.
_FINANCING_STAGES = {
    "Pre-seed", "Seed", "Series A", "Series B", "Series C", "Series D",
    "Growth", "IPO", "Acquisition", "Grant",
}


def _is_round(story: dict) -> bool:
    """True when the story reports a financing or exit event."""
    if (story.get("stage") or "").strip() in _FINANCING_STAGES:
        return True
    # A stated amount is a round even when the stage was never named.
    return bool((story.get("amount") or "").strip())


def render_archive_html(known: dict) -> str:
    """A browsable page of the financing rounds found, newest first."""
    everything = sorted(
        known.values(),
        key=lambda e: (e.get("last_seen", ""), e.get("score") or 0),
        reverse=True,
    )
    stories = [s for s in everything if _is_round(s)]
    hidden = len(everything) - len(stories)
    posted = sum(1 for s in stories if s.get("posted"))
    sources = len({s.get("publisher", "") for s in stories if s.get("publisher")})
    rows = []
    for s in stories:
        tag = ' <span class="tag posted">posted</span>' if s.get("posted") else ""
        company = html.escape(s.get("company") or "") or "&mdash;"
        stage_text = html.escape(s.get("stage") or "")
        stage = f'<span class="stage">{stage_text}</span>' if stage_text else ""
        category_text = html.escape(s.get("category") or "")
        category = f'<span class="cat">{category_text}</span>' if category_text else ""
        total_text = html.escape(s.get("total_raised") or "")
        total = f'<span class="total">tot {total_text}</span>' if total_text else ""
        # Lead investor first, then the rest.
        lead = (s.get("lead_investor") or "").strip()
        rest = [x.strip() for x in (s.get("investors") or "").split(",") if x.strip()]
        rest = [x for x in rest if x.lower() != lead.lower()]
        investors = ", ".join(([f"{lead} (lead)"] if lead else []) + rest)
        rows.append(
            f'<tr>'
            f'<td class="co"><a href="{html.escape(s.get("link",""))}" target="_blank" '
            f'rel="noopener" title="{html.escape(s.get("title",""))}">{company}</a>{tag}</td>'
            f'<td>{category}</td>'
            f'<td>{stage}</td>'
            f'<td class="amt">{html.escape(s.get("amount") or "")}'
            f'{total}</td>'
            f'<td class="inv">{html.escape(investors)}</td>'
            f'<td class="loc">{html.escape(s.get("spinoff_origin") or "")}</td>'
            f'<td class="loc">{html.escape(s.get("location") or "")}</td>'
            f'<td class="d">{html.escape(s.get("published") or s.get("first_seen",""))}</td>'
            f'</tr>'
        )
    body = "\n".join(rows) or '<tr><td colspan="8">No financing rounds recorded yet.</td></tr>'
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Swiss DeepTech rounds</title><meta name="robots" content="noindex">
<style>
  :root {{ --green:#46b96a; --ink:#1b2430; --soft:#5b6472; --line:#e6eae8; --bg:#f6f8f7; }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
         background:var(--bg); color:var(--ink); line-height:1.5; }}
  .wrap {{ max-width:960px; margin:0 auto; padding:2rem 1rem 4rem; }}
  h1 {{ font-size:1.6rem; letter-spacing:-0.02em; }} h1 .dot {{ color:var(--green); }}
  .sub {{ color:var(--soft); margin:0.4rem 0 1rem; font-size:0.9rem; }}
  input {{ width:100%; padding:0.7rem 0.9rem; border:1px solid var(--line);
          border-radius:10px; font-size:1rem; margin-bottom:1rem; }}
  .box {{ background:#fff; border:1px solid var(--line); border-radius:14px; overflow-x:auto; }}
  table {{ width:100%; border-collapse:collapse; font-size:0.9rem; }}
  th, td {{ text-align:left; padding:0.6rem 0.8rem; border-bottom:1px solid var(--line);
           vertical-align:top; }}
  th {{ color:var(--soft); font-size:0.78rem; text-transform:uppercase; letter-spacing:0.04em; }}
  td.co {{ font-weight:600; }}
  td.amt {{ color:var(--ink); font-weight:600; white-space:nowrap; }}
  td.inv {{ color:var(--soft); }}
  td.loc, td.d {{ color:var(--soft); white-space:nowrap; }}
  a {{ color:var(--ink); text-decoration:none; }} a:hover {{ color:var(--green); }}
  .tag.posted {{ background:var(--green); color:#fff; border-radius:6px;
                padding:0.05rem 0.4rem; font-size:0.7rem; font-weight:700; }}
  .cat {{ background:#eef4f0; color:#2f6b46; border-radius:6px;
         padding:0.1rem 0.45rem; font-size:0.76rem; font-weight:600;
         white-space:nowrap; }}
  .stage {{ border:1px solid var(--line); border-radius:6px; padding:0.1rem 0.45rem;
           font-size:0.76rem; font-weight:600; white-space:nowrap; }}
  .total {{ display:block; color:var(--soft); font-size:0.72rem; font-weight:500; }}
</style></head><body>
<div class="wrap">
  <h1>Swiss DeepTech rounds<span class="dot">.</span></h1>
  <p class="sub">{len(stories)} financing rounds &middot; {posted} posted &middot; {sources} sources
  &middot; <span title="Research, partnerships and other non-financing news, kept in archive.json">{hidden} other stories hidden</span></p>
  <input id="q" placeholder="Filter by company, sector, investor or city..." oninput="filter()">
  <div class="box"><table>
    <thead><tr><th>Company</th><th>Category</th><th>Stage</th><th>Amount</th>
      <th>Investors</th><th>Spin-off</th><th>HQ</th><th>Date</th></tr></thead>
    <tbody id="rows">
{body}
    </tbody>
  </table></div>
</div>
<script>
  function filter() {{
    var q = document.getElementById('q').value.toLowerCase();
    var rows = document.querySelectorAll('#rows tr');
    for (var i = 0; i < rows.length; i++) {{
      rows[i].style.display = rows[i].innerText.toLowerCase().indexOf(q) > -1 ? '' : 'none';
    }}
  }}
</script>
</body></html>
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
    ap.add_argument("--archive", default="../digest/archive.json",
                    help="Append-only record of every story ever found")
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
        #
        # Enrichment is where a Google News redirect finally reveals its real
        # publisher, so a story can turn out to come from an excluded site only
        # at this point. Work through the pool in batches and top up, rather
        # than ending the week a post short.
        print("Finding the image and primary source for each post...", file=sys.stderr)
        pool = diversify(unused, args.max_per_source)
        picks, cursor, dropped, paywalled = [], 0, 0, 0
        while len(picks) < args.posts and cursor < len(pool):
            batch = pool[cursor: cursor + (args.posts - len(picks))]
            cursor += len(batch)
            enrich_articles(batch)
            for art in batch:
                if is_excluded(art.get("link", "")):
                    dropped += 1
                    continue
                if art.get("paywalled"):
                    paywalled += 1
                    continue
                picks.append(art)
        if dropped:
            print(
                f"Dropped {dropped} stories that resolved to an excluded site.",
                file=sys.stderr,
            )
        if paywalled:
            print(
                f"Dropped {paywalled} stories behind a paywall.",
                file=sys.stderr,
            )
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

        # Keep every story found, not just the ones posted, so the record
        # builds up over time instead of being overwritten each run.
        import archive as archive_mod
        from extract import extract_fields
        from images import article_text

        # Read the articles themselves. Feed summaries are a sentence or two,
        # which is why investors and founders were mostly blank.
        print(f"Fetching {len(articles)} articles in full...", file=sys.stderr)
        got = 0
        for art in articles:
            art["fulltext"] = article_text(art.get("link", ""), limit=6000)
            if art["fulltext"]:
                got += 1
        print(f"  read {got}/{len(articles)} in full", file=sys.stderr)

        print("Reading deal facts from each story...", file=sys.stderr)
        for art, facts in zip(articles, extract_fields(articles)):
            art.update(facts)
        named = sum(1 for a in articles if a.get("company"))
        print(f"  identified a company in {named}/{len(articles)} stories",
              file=sys.stderr)

        # Articles often skip the location, so check the company's own site.
        from hq_lookup import fill_missing
        blanks = sum(1 for a in articles if a.get("company") and not a.get("location"))
        if blanks:
            print(f"Looking up {blanks} missing headquarters...", file=sys.stderr)
            print(f"  found {fill_missing(articles)} of them", file=sys.stderr)
        known = archive_mod.load(args.archive)
        before = len(known)
        known = archive_mod.record(known, articles, picks)
        archive_mod.save(args.archive, known)
        print(
            f"Archive: {len(known)} stories total ({len(known) - before} new "
            f"this run) in {args.archive}",
            file=sys.stderr,
        )
        with open(os.path.join(args.outdir, "archive.html"), "w", encoding="utf-8") as f:
            f.write(render_archive_html(known))


if __name__ == "__main__":
    main()
