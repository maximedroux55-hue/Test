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
import re
import sys
import time
from calendar import timegm

try:
    import feedparser
except ImportError:
    sys.exit("Missing dependency 'feedparser'. Run: pip install -r requirements.txt")

import money
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


# A figure on its own is not a round. Hitachi Energy putting USD 9B into a
# factory is capital expenditure, and a laboratory being awarded research money
# is not a company being financed.
_NOT_A_ROUND = re.compile(
    r"expand\w*\s+(?:its\s+)?(?:\w+\s+){0,2}(?:production|manufacturing|capacity|site|plant)|"
    r"opens?\s+(?:a\s+)?(?:new\s+)?(?:factory|plant|site|campus|office)|"
    r"production\s+(?:line|facility|site)|"
    r"research\s+(?:grant|project|programme|program)\b|"
    r"professorship|chair\s+of\b",
    re.IGNORECASE,
)

# Institutions receive research money; they are not companies raising rounds.
_INSTITUTIONS = re.compile(
    r"^(epfl|eth|empa|csem|psi|idiap|agroscope|universit|hochschule|"
    r"hes-so|zhaw|fhnw|supsi|inselspital|chuv|hug)\b",
    re.IGNORECASE,
)


def _is_round(story: dict) -> bool:
    """True when the story reports one company being financed.

    A row needs a company, since a row with no name records nothing. It needs
    to be one company, since an award split across three startups is not a
    round. It needs a stage or an amount. And it must not be one of the things
    that merely carry a number: a factory investment, or a grant to a lab.
    """
    company = (story.get("company") or "").strip()
    if not company or re.search(r",|/| and ", company, re.IGNORECASE):
        return False
    if _INSTITUTIONS.match(company):
        return False
    if not ((story.get("stage") or "").strip() in _FINANCING_STAGES
            or (story.get("amount") or "").strip()):
        return False
    text = f"{story.get('title', '')} {story.get('description', '')}"
    return not _NOT_A_ROUND.search(text)


def _company_stem(name: str) -> str:
    """A company name reduced so spellings of it match each other."""
    stem = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    return re.sub(r"(ag|sa|sarl|gmbh|ltd|inc|bv|nv|holding|group)$", "", stem)


# Fields where a longer answer is a better answer, so the fuller of two
# outlets' versions wins rather than whichever was seen first.
_PREFER_LONGER = ("investors", "founders", "description", "use_of_funds",
                  "customers")


def merge_deals(stories: list) -> list:
    """One row per round, not one row per article.

    The same round gets written up by several outlets, and each leaves
    something out: GGBa named CCRAFT's city, The Quantum Insider named its
    technology, and keying on the article URL made them two half-empty rows.
    Rows for the same company and amount are folded together, taking the value
    each outlet did have.
    """
    groups, order = {}, []
    for story in stories:
        stem = _company_stem(story.get("company", ""))
        if not stem:
            continue
        # Amount pins the round: two rounds for one company in a year are
        # different deals and must not collapse into one.
        _, value = money.parse(story.get("amount", ""))
        key = (stem, int(value))
        if key not in groups:
            groups[key] = dict(story)
            groups[key]["sources"] = []
            order.append(key)
        merged = groups[key]
        for field, value2 in story.items():
            if field in ("sources", "key"):
                continue
            existing = merged.get(field)
            if not isinstance(value2, str):
                if not existing:
                    merged[field] = value2
                continue
            if not value2.strip():
                continue
            if not (existing or "").strip():
                merged[field] = value2
            elif field in _PREFER_LONGER and len(value2) > len(existing):
                merged[field] = value2
            elif field == "company" and existing.islower() and not value2.islower():
                # One outlet wrote "valuemize", another "Valuemize".
                merged[field] = value2
        publisher = (story.get("publisher") or "").strip()
        if publisher and publisher not in merged["sources"]:
            merged["sources"].append(publisher)
        merged["posted"] = merged.get("posted") or story.get("posted")

    out = []
    for key in order:
        deal = groups[key]
        name = deal.get("company") or ""
        # An outlet that lower-cased the name should not decide how it reads.
        # Only when every letter is lower, so SWISSto12 is left alone.
        if name.islower():
            deal["company"] = name[:1].upper() + name[1:]
        out.append(deal)
    return out


def _report_coverage(known: dict) -> None:
    """Print how full the archive actually is, field by field.

    Without this the only way to tell whether a run read the articles properly
    was to open the page and count blanks.
    """
    import provenance

    raw = [s for s in known.values() if _is_round(s)]
    merged = merge_deals(raw)
    rounds = [s for s in merged if _is_swiss(s)]
    if not rounds:
        return
    fields = ("company", "description", "category", "stage", "amount",
              "location", "investors", "founders",
              "spinoff_origin", "founded", "total_raised")
    merged_away = len(raw) - len(merged)
    print(f"Coverage over {len(rounds)} Swiss rounds"
          f"{f' ({merged_away} duplicate write-ups merged'if merged_away else ' ('}"
          f"{', ' if merged_away else ''}{len(merged) - len(rounds)} foreign held back):",
          file=sys.stderr)
    for field in fields:
        filled = sum(1 for s in rounds if (s.get(field) or "").strip())
        print(f"  {field:<15} {filled:>3}/{len(rounds)}"
              f"  {100 * filled // len(rounds):>3}%", file=sys.stderr)
    total = sum(money.in_chf(s.get("amount", "")) for s in rounds)
    print(f"  tracked {money.compact(total)} across the rounds with an amount",
          file=sys.stderr)
    sources = provenance.summary(rounds)
    if sources:
        print("  facts by source: "
              + ", ".join(f"{v} from {k}" for k, v in sources.items()),
              file=sys.stderr)


# Cities and cantons that put a company in Switzerland. A location written as
# "Munich, DE" or "Leipzig, DE" is explicitly not.
_SWISS_HOME = re.compile(
    r"z(?:ü|u)rich|geneva|gen(?:è|e)ve|lausanne|basel|b(?:â|a)le|bern|berne|"
    r"lugano|sion|fribourg|neuch(?:â|a)tel|winterthur|zug|st\.?\s*gallen|"
    r"renens|schlieren|d(?:ü|u)bendorf|biel|bienne|lucerne|luzern|thun|"
    r"yverdon|villigen|chiasso|glattbrugg|vaud|valais|ticino|switzerland|"
    r"lugano|martigny|monthey|nyon|morges|vevey|montreux|aarau|baden|olten",
    re.IGNORECASE,
)


# What marks a company as Swiss when its headquarters was never recorded.
_SWISS_SIGNAL = re.compile(
    r"\bswiss\b|\bswitzerland\b|\bschweiz\w*\b|\bsuisse\b|\bsvizzer\w+\b|"
    r"\bepfl\b|\beth\s*z|\bcsem\b|\bempa\b|\bidiap\b|\bpsi\b",
    re.IGNORECASE,
)


def _is_swiss(story: dict) -> bool:
    """Is this a Swiss company?

    The database is Swiss DeepTech, so a foreign company with a Swiss angle in
    the coverage does not belong: Prodlane is in Leipzig and SkyPilot is
    American. A recorded headquarters decides it outright.

    Where no headquarters was found, the row is kept only if something else
    says Swiss, such as an EPFL spin-off or a story about a Swiss company we
    simply failed to place. Dropping those outright would quietly lose real
    Swiss rounds for want of a city.
    """
    location = (story.get("location") or "").strip()
    if location:
        if re.search(r",\s*[A-Z]{2}$", location):
            return False
        return bool(_SWISS_HOME.search(location))
    origin = (story.get("spinoff_origin") or "").lower()
    if any(s in origin for s in
           ("eth", "epfl", "csem", "empa", "psi", "idiap", "univers", "hsg")):
        return True
    return bool(_SWISS_SIGNAL.search(
        f"{story.get('title', '')} {story.get('description', '')}"))


def _provenance(story: dict, field: str) -> str:
    """Where a fact came from, in words. Empty when it was not recorded."""
    return ((story.get("provenance") or {}).get(field) or "").strip()


def _investor_line(story: dict) -> str:
    """The investors named, or "" when none was.

    Who led a round is usually not written down anywhere free, so it is not
    called out separately. Any lead that was found is simply listed with the
    rest, which keeps the rows where the lead was the only name we got.
    """
    names, seen = [], set()
    for value in (story.get("lead_investor"), story.get("investors")):
        for name in (value or "").split(","):
            name = name.strip(" .;")
            if name and name.lower() not in seen:
                seen.add(name.lower())
                names.append(name)
    return ", ".join(names)


def render_archive_html(known: dict) -> str:
    """A browsable page of the financing rounds found, newest first.

    Nine rigid columns left a hole wherever a fact was missing, and articles
    routinely withhold investors and founders, so most of the table read as
    blank. The columns here are the ones that are almost always known, and
    everything else sits under the company name and only appears when it is
    actually there, so a missing fact costs a phrase rather than a gap.
    """
    everything = sorted(
        known.values(),
        key=lambda e: (e.get("published") or e.get("first_seen") or "",
                       e.get("score") or 0),
        reverse=True,
    )
    rounds = merge_deals([s for s in everything if _is_round(s)])
    # Swiss DeepTech, so a foreign company that happened to make Swiss news is
    # not a row here. It stays in archive.json, which is the raw record.
    stories = [s for s in rounds if _is_swiss(s)]
    foreign = len(rounds) - len(stories)
    hidden = len(everything) - len(rounds)
    posted = sum(1 for s in stories if s.get("posted"))
    with_investors = sum(1 for s in stories if _investor_line(s))
    with_founders = sum(1 for s in stories if (s.get("founders") or "").strip())
    placed = sum(1 for s in stories if (s.get("location") or "").strip())
    tracked = money.compact(sum(money.in_chf(s.get("amount", "")) for s in stories))

    rows = []
    for s in stories:
        tag = ' <span class="tag posted">posted</span>' if s.get("posted") else ""
        company = html.escape(s.get("company") or "") or html.escape(
            (s.get("title") or "")[:40])
        link = html.escape(s.get("link", ""))

        desc = html.escape(s.get("description") or "")
        if not desc:
            # Better the headline than an empty line under the name.
            desc = html.escape((s.get("title") or "").strip())
        desc = f'<div class="desc">{desc}</div>' if desc else ""

        # Everything the article happened to give, written out only when it is
        # there. No fact, no fragment, so nothing renders as a blank cell.
        bits = []
        investors = _investor_line(s)
        if investors:
            bits.append(f'Backed by <b>{html.escape(investors)}</b>')
        founders = (s.get("founders") or "").strip()
        if founders:
            bits.append(f'Founded by {html.escape(founders)}')
        origin = (s.get("spinoff_origin") or "").strip()
        if origin:
            bits.append(f'{html.escape(origin)} spin-off')
        seat = (s.get("legal_seat") or "").strip()
        if seat and seat.lower() != (s.get("location") or "").strip().lower():
            bits.append(f'registered in {html.escape(seat)}')
        year = (s.get("founded") or "").strip()
        if year:
            bits.append(f'est. {html.escape(year)}')
        staff = (s.get("employees") or "").strip()
        if staff:
            bits.append(f'{html.escape(staff)} staff')
        valuation = (s.get("valuation") or "").strip()
        if valuation:
            bits.append(f'valued {html.escape(valuation)}')
        use = (s.get("use_of_funds") or "").strip()
        if use:
            bits.append(html.escape(use))
        outlets = [p for p in (s.get("sources") or []) if p]
        if len(outlets) > 1:
            bits.append(f'{len(outlets)} sources: {html.escape(", ".join(outlets))}')
        meta = f'<div class="meta">{" &middot; ".join(bits)}</div>' if bits else ""

        stage_text = html.escape(s.get("stage") or "")
        stage = (f'<span class="stage">{stage_text}</span>' if stage_text
                 else '<span class="nd">round</span>')
        category_text = html.escape(s.get("category") or "")
        category = (f'<span class="cat">{category_text}</span>' if category_text
                    else '<span class="nd">n/d</span>')
        amount_text = html.escape(s.get("amount") or "")
        amount = amount_text or '<span class="nd">undisclosed</span>'
        chf = money.in_chf(s.get("amount", ""))
        note = []
        if (s.get("total_raised") or "").strip():
            note.append(f'{html.escape(s["total_raised"])} total')
        # The franc figure is only worth showing where it is not the currency.
        if chf and not amount_text.upper().startswith("CHF"):
            note.append(f'≈ {money.compact(chf)}')
        total = f'<span class="total">{" &middot; ".join(note)}</span>' if note else ""

        location_text = (s.get("location") or "").strip()
        where = (_provenance(s, "location")
                 or "as written in the coverage") if location_text else ""
        location = (f'<span title="Source: {html.escape(where)}">'
                    f'{html.escape(location_text)}</span>' if location_text
                    else '<span class="nd" title="Swiss company, city not '
                         'found yet">CH</span>')

        rows.append(
            f'<tr data-chf="{chf}">'
            f'<td class="co"><a href="{link}" target="_blank" rel="noopener" '
            f'title="{html.escape(s.get("title",""))}">{company}</a>{tag}'
            f'{desc}{meta}</td>'
            f'<td>{category}</td>'
            f'<td>{stage}</td>'
            f'<td class="amt">{amount}{total}</td>'
            f'<td class="loc">{location}</td>'
            f'<td class="d">{html.escape(s.get("published") or s.get("first_seen",""))}</td>'
            f'</tr>'
        )
    body = "\n".join(rows) or (
        '<tr><td colspan="6" class="nd">No financing rounds recorded yet. '
        'The next run will fill this in.</td></tr>')
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Swiss DeepTech rounds</title><meta name="robots" content="noindex">
<style>
  :root {{ --green:#46b96a; --ink:#1b2430; --soft:#5b6472; --faint:#9aa3ad;
          --line:#e6eae8; --bg:#f6f8f7; }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
         background:var(--bg); color:var(--ink); line-height:1.5; }}
  .wrap {{ max-width:1040px; margin:0 auto; padding:2rem 1rem 4rem; }}
  h1 {{ font-size:1.6rem; letter-spacing:-0.02em; }} h1 .dot {{ color:var(--green); }}
  .sub {{ color:var(--soft); margin:0.4rem 0 1rem; font-size:0.9rem; }}
  .stats {{ display:flex; flex-wrap:wrap; gap:0.6rem; margin:0 0 1rem; }}
  .stat {{ background:#fff; border:1px solid var(--line); border-radius:12px;
          padding:0.55rem 0.9rem; flex:1 1 auto; min-width:110px; }}
  .stat b {{ display:block; font-size:1.25rem; letter-spacing:-0.02em; }}
  .stat span {{ color:var(--soft); font-size:0.74rem; text-transform:uppercase;
               letter-spacing:0.04em; }}
  input {{ width:100%; padding:0.7rem 0.9rem; border:1px solid var(--line);
          border-radius:10px; font-size:1rem; margin-bottom:1rem; }}
  .box {{ background:#fff; border:1px solid var(--line); border-radius:14px; overflow-x:auto; }}
  table {{ width:100%; border-collapse:collapse; font-size:0.9rem; }}
  th, td {{ text-align:left; padding:0.7rem 0.8rem; border-bottom:1px solid var(--line);
           vertical-align:top; }}
  th {{ color:var(--soft); font-size:0.78rem; text-transform:uppercase; letter-spacing:0.04em; }}
  tr:last-child td {{ border-bottom:none; }}
  td.co {{ font-weight:600; min-width:15rem; }}
  .desc {{ font-weight:400; color:var(--soft); font-size:0.84rem; margin-top:0.15rem; }}
  .meta {{ font-weight:400; color:var(--faint); font-size:0.78rem; margin-top:0.25rem; }}
  .meta b {{ color:var(--soft); font-weight:600; }}
  td.amt {{ color:var(--ink); font-weight:600; white-space:nowrap; }}
  td.loc, td.d {{ color:var(--soft); white-space:nowrap; }}
  a {{ color:var(--ink); text-decoration:none; }} a:hover {{ color:var(--green); }}
  .nd {{ color:var(--faint); font-weight:400; font-size:0.82rem; }}
  .tag.posted {{ background:var(--green); color:#fff; border-radius:6px;
                padding:0.05rem 0.4rem; font-size:0.7rem; font-weight:700;
                vertical-align:middle; }}
  .cat {{ background:#eef4f0; color:#2f6b46; border-radius:6px;
         padding:0.1rem 0.45rem; font-size:0.76rem; font-weight:600;
         white-space:nowrap; }}
  .stage {{ border:1px solid var(--line); border-radius:6px; padding:0.1rem 0.45rem;
           font-size:0.76rem; font-weight:600; white-space:nowrap; }}
  .total {{ display:block; color:var(--soft); font-size:0.72rem; font-weight:500; }}
  .foreign {{ background:#f3f0ea; color:#8a6d3b; border-radius:5px;
             padding:0.02rem 0.3rem; font-size:0.68rem; font-weight:700; }}
  .controls {{ display:flex; gap:0.6rem; align-items:center; margin-bottom:1rem;
              flex-wrap:wrap; }}
  .controls input[type=text] {{ flex:1 1 16rem; margin:0; }}
  .toggle {{ display:flex; align-items:center; gap:0.4rem; font-size:0.85rem;
            color:var(--soft); background:#fff; border:1px solid var(--line);
            border-radius:10px; padding:0.62rem 0.8rem; cursor:pointer;
            white-space:nowrap; }}
  .note {{ color:var(--faint); font-size:0.76rem; margin-top:0.8rem; }}
  .live {{ color:var(--soft); font-size:0.82rem; white-space:nowrap; }}
</style></head><body>
<div class="wrap">
  <h1>Swiss DeepTech rounds<span class="dot">.</span></h1>
  <p class="sub">Swiss companies only, newest first. One row per round: where several
  outlets covered the same one, their facts are combined.
  <span title="Kept in archive.json, which is the raw record">{foreign} foreign-headquartered rounds and {hidden} non-financing stories are held back.</span></p>
  <div class="stats">
    <div class="stat"><b>{len(stories)}</b><span>rounds</span></div>
    <div class="stat"><b>{tracked or "&ndash;"}</b><span>tracked</span></div>
    <div class="stat"><b>{placed}</b><span>with a city</span></div>
    <div class="stat"><b>{with_investors}</b><span>with investors</span></div>
    <div class="stat"><b>{with_founders}</b><span>with founders</span></div>
    <div class="stat"><b>{posted}</b><span>posted</span></div>
  </div>
  <div class="controls">
    <input type="text" id="q" placeholder="Filter by company, sector, investor, founder or city..." oninput="filter()">
    <span class="live" id="count"></span>
  </div>
  <div class="box"><table>
    <thead><tr><th>Company</th><th>Sector</th><th>Stage</th><th>Raised</th>
      <th>HQ</th><th>Date</th></tr></thead>
    <tbody id="rows">
{body}
    </tbody>
  </table></div>
  <p class="note">Amounts are shown as the article wrote them. The franc figure beside a
  foreign currency, and the total above, are converted at fixed indicative rates and are
  meant for scale rather than accounting. Hover a headquarters to see where it came from.</p>
</div>
<script>
  function filter() {{
    var q = document.getElementById('q').value.toLowerCase();
    var rows = document.querySelectorAll('#rows tr');
    var shown = 0, total = 0;
    for (var i = 0; i < rows.length; i++) {{
      var row = rows[i];
      var matches = row.innerText.toLowerCase().indexOf(q) > -1;
      row.style.display = matches ? '' : 'none';
      if (matches) {{ shown++; total += parseInt(row.getAttribute('data-chf') || '0', 10); }}
    }}
    var box = document.getElementById('count');
    if (box) {{
      box.innerHTML = shown + ' round' + (shown === 1 ? '' : 's')
        + (total ? ' &middot; ' + (total >= 1e9 ? (total / 1e9).toFixed(1) + 'B'
                                                : Math.round(total / 1e6) + 'M') + ' CHF' : '');
    }}
  }}
  filter();
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
    # The weekly posts and the deal database are two separate jobs that happen
    # to read the same feeds. Either can be run without the other, so a problem
    # in one cannot cost the other its output.
    ap.add_argument("--archive-only", action="store_true",
                    help="Only fill the archive: write no posts and touch no history. "
                         "Use with a wide --days to backfill past rounds.")
    ap.add_argument("--posts-only", action="store_true",
                    help="Only write the posts: do not read articles in full and "
                         "do not touch the archive.")
    args = ap.parse_args()
    if args.archive_only and args.posts_only:
        sys.exit("Pick one of --archive-only and --posts-only, not both.")

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

    # A backfill run fills the archive from a wide window. It must not write
    # posts: that would overwrite the week already planned and burn stories in
    # history that were never actually published.
    picks, mode = [], ""
    if args.format in ("linkedin", "both") and not args.archive_only:
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

    if not args.posts_only:
        # The database is a separate job from the weekly posts. It reads the
        # same feeds, but nothing it does may cost the posts their run, so a
        # failure here is reported and stepped over rather than raised.
        try:
            build_archive(articles, picks, args)
        except Exception as exc:
            import traceback
            print(f"\n!! The archive stage failed: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            traceback.print_exc()

    _flag_missing_ai(articles, mode, args)


def build_archive(articles: list, picks: list, args) -> None:
    """Fill the deal database from this run's stories.

    Kept separate from the post building above: the posts are a weekly editorial
    job and this is a record that grows, and neither should depend on the other
    having worked.
    """
    import os

    # Keep every story found, not just the ones posted, so the record
    # builds up over time instead of being overwritten each run.
    import archive as archive_mod
    from extract import extract_fields
    from images import article_text

    # Only the seven picked posts had their Google News redirect resolved, so
    # every other story went into the archive as a news.google.com link. Asking
    # that URL for the article text returns Google's own redirect page, which
    # holds no facts, so those rows were extracted from the feed summary alone.
    # Resolve them all before reading.
    from google_news import is_google_news_url, resolve_url
    redirects = [a for a in articles if is_google_news_url(a.get("link", ""))]
    if redirects:
        print(f"Resolving {len(redirects)} Google News links to the publisher...",
              file=sys.stderr)
        done = 0
        for art in redirects:
            real = resolve_url(art["link"])
            if real:
                art["link"] = real
                done += 1
        print(f"  resolved {done}/{len(redirects)}", file=sys.stderr)

    # Read the articles themselves. Feed summaries are a sentence or two,
    # which is why investors and founders were mostly blank.
    print(f"Fetching {len(articles)} articles in full...", file=sys.stderr)
    got = 0
    for art in articles:
        art["fulltext"] = article_text(art.get("link", ""), limit=6000)
        if art["fulltext"]:
            got += 1
    print(f"  read {got}/{len(articles)} in full", file=sys.stderr)

    # Some publishers refuse us outright, and those stories reached the archive
    # with nothing but a headline: two rounds sat there nameless because The
    # Quantum Insider and EU-Startups would not serve the page. The company is
    # usually named in the headline even so, and its own site will say the rest.
    from extract import _company_from_headline
    from hq_lookup import company_pages

    blocked = [a for a in articles
               if not a.get("fulltext") and _company_from_headline(a.get("title", ""))]
    if blocked:
        print(f"Falling back to the company's own site for {len(blocked)} "
              f"stories the publisher would not serve...", file=sys.stderr)
        recovered = 0
        for art in blocked:
            name = _company_from_headline(art.get("title", ""))
            domain, text = company_pages(name, art.get("website", ""))
            if text:
                art["fulltext"] = text
                art["company"] = art.get("company") or name
                art.setdefault("website", domain)
                recovered += 1
        print(f"  recovered {recovered}/{len(blocked)}", file=sys.stderr)

    print("Reading deal facts from each story...", file=sys.stderr)
    for art, facts in zip(articles, extract_fields(articles)):
        art.update(facts)
    named = sum(1 for a in articles if a.get("company"))
    print(f"  identified a company in {named}/{len(articles)} stories",
          file=sys.stderr)

    # News write-ups give the amount and little else, so read each
    # company's own site for the investors, founders and the rest.
    from extract import fill_from_company_sites
    fill_from_company_sites([a for a in articles if _is_round(a)])

    # The commercial register is authoritative for the registered seat.
    from registries import fill_from_registries
    fill_from_registries([a for a in articles if _is_round(a)])

    # Anything still without a location gets the address lookup.
    from hq_lookup import fill_missing
    blanks = sum(1 for a in articles if a.get("company") and not a.get("location"))
    if blanks:
        print(f"Looking up {blanks} missing headquarters...", file=sys.stderr)
        print(f"  found {fill_missing(articles)} of them", file=sys.stderr)

    # Max's corrections go on last, over everything the lookups produced.
    import corrections
    corrections.apply(articles)

    known = archive_mod.load(args.archive)
    before = len(known)
    known = archive_mod.record(known, articles, picks)
    # Again over the whole database, not just this run's stories. A correction
    # has to reach rows recorded weeks ago, and clearing a wrong value has to
    # work at all: the archive never replaces something with a blank on its own.
    corrections.apply(list(known.values()))
    archive_mod.save(args.archive, known)
    print(
        f"Archive: {len(known)} stories total ({len(known) - before} new "
        f"this run) in {args.archive}",
        file=sys.stderr,
    )
    _report_coverage(known)
    with open(os.path.join(args.outdir, "archive.html"), "w", encoding="utf-8") as f:
        f.write(render_archive_html(known))


def _flag_missing_ai(articles: list, mode: str, args) -> None:
    """Leave a marker when this run silently fell back to no AI.

    When the API is unreachable the run still succeeds: template posts go out
    and the archive fills with keyword guesses. That happened twice without
    anyone noticing, so the workflow turns this marker into a failed run and an
    email rather than a quietly worse week.
    """
    import os

    import extract as extract_mod

    if not os.environ.get("ANTHROPIC_API_KEY") or not articles:
        return

    problems = []
    if not args.archive_only and mode and mode.lower().startswith("template"):
        problems.append("the posts are template drafts rather than written in "
                        "Max's voice")
    if not args.posts_only and extract_mod.LAST_RUN_OK == 0:
        problems.append("the archive rows were filled by keyword guessing "
                        "rather than read from the articles")
    if not problems:
        return

    reason = extract_mod.LAST_RUN_ERROR or "every request failed"
    note = ("The Anthropic API was unavailable for this run, so "
            + " and ".join(problems) + f".\n{reason}")
    with open(os.path.join(args.outdir, "AI_UNAVAILABLE"), "w",
              encoding="utf-8") as f:
        f.write(note)
    print(f"\n!! {note}", file=sys.stderr)


if __name__ == "__main__":
    main()
