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
import os
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


def collect(days: int, min_score: int, backfill_months: int = 0,
            keep_all_coverage: bool = False) -> list[dict]:
    """Fetch all feeds and return a list of relevant, de-duplicated articles."""
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    articles: list[dict] = []
    seen_links = set()

    feeds = list(all_feeds(days))
    if backfill_months:
        # An RSS feed holds only its latest items, so a wider window finds
        # nothing older. Reaching back means asking Google News for one month
        # at a time, which is what these feeds do.
        from google_news import backfill_feeds
        extra = backfill_feeds(backfill_months)
        print(f"Walking back {backfill_months} months over {len(extra)} "
              f"archive searches...", file=sys.stderr)
        feeds += extra

    browser_ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
    for source_label, url in feeds:
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

    if keep_all_coverage:
        # The database wants every write-up of a round, not one of them.
        # Deduplication picks a survivor by score, and it kept Tech Funding
        # News over Startupticker for GR3N, dropping the write-up that named
        # the round and its investors. The rows are merged later, where each
        # outlet contributes what it had.
        before = len(articles)
        kept = deduplicate(articles)
        print(f"Keeping {before - len(kept)} further write-ups of stories "
              f"already covered, to merge their facts.", file=sys.stderr)
    else:
        articles = deduplicate(articles)
    # Rank by relevance first, then most recent.
    _oldest = dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    articles.sort(
        key=lambda a: (a["score"], a["date"] or _oldest),
        reverse=True,
    )
    return articles


def _fmt_date(d: dt.datetime | None) -> str:
    return d.strftime("%d %b %Y") if d else ""


# submissions.py stamps a story Max sent in with this, so it outranks anything
# the scoring found. It is a marker, not a measurement, and printing it as
# "relevance 999" beside a story with no date looked like a broken row.
SUBMITTED = 999


def _rank(article: dict) -> str:
    """How a story earned its place, in words rather than a raw number."""
    score = article.get("score") or 0
    return "sent in" if score >= SUBMITTED else f"relevance {score}"


def _meta_line(a: dict, sep: str = " · ") -> str:
    """Publisher, date and rank, skipping whatever is not known."""
    parts = [a.get("publisher") or "", _fmt_date(a.get("date")), _rank(a)]
    return sep.join(p for p in parts if p)


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
            f"\n   {_meta_line(a)}"
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
            f'<div class="meta">{html.escape(_meta_line(a))}</div></li>'
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
# Bodies as well as schools: the Swiss Academy of Sciences taking a grant is
# not a Swiss DeepTech round.
_INSTITUTIONS = re.compile(
    r"^(epfl|eth|empa|csem|psi|idiap|agroscope|universit|hochschule|"
    r"hes-so|zhaw|fhnw|supsi|inselspital|chuv|hug)\b"
    r"|\b(academy|akademie|acad(?:é|e)mie|society|soci(?:é|e)t(?:é|e)\s+suisse|"
    r"association|verband|foundation|fondation|stiftung|federal\s+office|"
    r"confederation|canton\s+of)\b",
    re.IGNORECASE,
)


def _is_round(story: dict) -> bool:
    """True when the story reports one company being financed.

    A row needs a company, since a row with no name records nothing. It needs
    to be one company, since an award split across three startups is not a
    round. It needs a stage or an amount. And it must not be one of the things
    that merely carry a number: a factory investment, or a grant to a lab.

    Three kinds of story reach this point looking like rounds and are not.
    An acquisition is an exit: the price is not capital into the company, and
    the funds named are the sellers' old backers rather than anyone putting
    money in. A grant to a research project is not a company being financed.
    And a grant reported without a figure is not evidence of anything that can
    be counted, however real the money.
    """
    stage = (story.get("stage") or "").strip()
    if stage in ("Acquisition", "Partnership"):
        return False
    if stage == "Grant":
        if (story.get("category") or "").strip() == "Research":
            return False
        if not (story.get("amount") or "").strip():
            return False

    company = (story.get("company") or "").strip()
    if not company or re.search(r",|/| and ", company, re.IGNORECASE):
        return False
    # Searched, not matched from the start: the body is rarely the first word,
    # as in "Swiss Academy of Sciences".
    if _INSTITUTIONS.search(company):
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

# Outlets to believe first where two disagree. Startupticker writes the fullest
# Swiss round coverage there is, so its version of a round leads and its
# article is the one the row links to.
_PREFERRED_SOURCES = ("startupticker",)


def _source_rank(story: dict) -> int:
    """Lower comes first when merging a round's write-ups."""
    text = f"{story.get('publisher', '')} {story.get('link', '')}".lower()
    for rank, name in enumerate(_PREFERRED_SOURCES):
        if name in text:
            return rank
    return len(_PREFERRED_SOURCES)


def _same_size(a: float, b: float, tolerance: float = 0.05) -> bool:
    """Two figures close enough to be the same round.

    Not equality, because the francs come from fixed indicative rates and the
    outlets converted at their own: USD 4.95M and EUR 4.29M are the same money
    quoted twice, 0.7 per cent apart once converted. Kept tight, because a seed
    and the Series A after it are multiples apart, never five per cent.
    """
    if a == b:
        return True
    if not a or not b:
        return False
    return abs(a - b) <= tolerance * max(a, b)


def merge_deals(stories: list) -> list:
    """One row per round, not one row per article.

    The same round gets written up by several outlets, and each leaves
    something out: GGBa named CCRAFT's city, The Quantum Insider named its
    technology, and keying on the article URL made them two half-empty rows.
    Rows for the same company and amount are folded together, taking the value
    each outlet did have.

    Where two outlets both have a value, the preferred one wins, except for the
    lists of investors and founders, where the longer answer is the fuller one
    whoever wrote it.
    """
    groups, order, sizes = {}, [], {}
    # Group first, then merge each round's write-ups in order of preference, so
    # the outlet trusted most is the one that sets the values and the link.
    by_key = {}
    for story in stories:
        stem = _company_stem(story.get("company", ""))
        if not stem:
            continue
        # Amount pins the round: two rounds for one company in a year are
        # different deals and must not collapse into one. Compared in francs,
        # because the same round is written up in different currencies:
        # Exclaim Robotics raised "USD 4.95M" in one paper and "EUR 4.29M" in
        # another, which as raw numbers looked like two rounds and put the
        # company on the page twice, counting the money twice with it.
        chf = money.in_chf(story.get("amount", "")) or 0
        # AI Infrastructure Capital's round was written up as EUR 16M by one
        # outlet and USD 16M by another. In francs those are 14 per cent apart,
        # so they read as two rounds and the company appeared twice. The same
        # figure under two currency labels is one round and a disagreement
        # about the label, so the bare magnitude counts as a match too.
        _, size = money.parse(story.get("amount", ""))
        key = next((k for k in order
                    if k[0] == stem
                    and (_same_size(sizes[k][0], chf)
                         or (size and sizes[k][1] == size))), None)
        if key is None:
            key = (stem, chf)
            by_key[key] = []
            sizes[key] = (chf, size)
            order.append(key)
        by_key[key].append(story)

    for key in order:
        for story in sorted(by_key[key], key=_source_rank):
            if key not in groups:
                groups[key] = dict(story)
                groups[key]["sources"] = []
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
                elif (field == "company" and existing.islower()
                      and not value2.islower()):
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
        # When the round entered the database, which is the earliest of its
        # write-ups. Taking the preferred outlet's date instead would make a
        # round look new because a second outlet covered it this morning.
        seen = [s.get("first_seen") for s in by_key[key] if s.get("first_seen")]
        if seen:
            deal["first_seen"] = min(seen)
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
    r"lugano|martigny|monthey|nyon|morges|vevey|montreux|aarau|baden|olten|"
    # AI Infrastructure Capital sits in Pfäffikon and read as foreign for want
    # of its town being on this list. A missing name here is a Swiss company
    # quietly dropped from a Swiss database, so the list is generous.
    r"pf(?:ä|a)ffikon|rotkreuz|rapperswil|w(?:ä|a)denswil|horgen|k(?:ü|u)snacht|"
    r"baar|cham|risch|steinhausen|hünenberg|allschwil|muttenz|reinach|pratteln|"
    r"kloten|opfikon|wallisellen|r(?:ü|u)schlikon|regensdorf|uster|"
    r"chur|solothurn|schaffhausen|frauenfeld|kreuzlingen|arbon|"
    r"sierre|sion|monthey|delémont|delemont|la\s+chaux-de-fonds|le\s+locle|"
    r"ecublens|(?:plan-les-ouates|meyrin|carouge|lancy|onex|versoix|vernier)|"
    r"bulle|marly|granges|epalinges|st-sulpice|saint-sulpice|crissier|"
    r"schwyz|obwalden|nidwalden|appenzell|glarus|graub(?:ü|u)nden|thurgau|"
    r"aargau|basel-land|baselland|jura|uri|z(?:ü|u)g",
    re.IGNORECASE,
)


# What marks a company as Swiss when its headquarters was never recorded. The
# word alone will not do: SkyPilot is in Berkeley and its headline says it wants
# to be "the Switzerland of AI compute", which put an American company on a
# Swiss page. The country has to be attached to the company.
_SWISS_SIGNAL = re.compile(
    r"\bswiss(?:\s+\w+){0,3}\s+(?:startup|start-up|company|firm|scaleup|"
    r"scale-up|spin-?off|spin-?out|group|maker|manufacturer)\b|"
    r"\bswiss-based\b|\bswitzerland-based\b|\bbased\s+in\s+switzerland\b|"
    r"\bschweizer\s+\w+|\bstart-?up\s+suisse\b|\bsoci(?:é|e)t(?:é|e)\s+suisse\b|"
    r"\b(?:z(?:ü|u)rich|geneva|gen(?:è|e)ve|lausanne|basel|bern|lugano|zug|"
    r"neuch(?:â|a)tel|winterthur|renens|sion)-based\b|"
    r"\bepfl\b|\beth\s*z(?:ü|u)rich\b|\bcsem\b|\bempa\b|\bidiap\b",
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
        country = re.search(r",\s*([A-Z]{2})$", location)
        if country:
            # "Chiasso, CH" is Switzerland; "Leipzig, DE" is not.
            return country.group(1) == "CH"
        return bool(_SWISS_HOME.search(location))
    origin = (story.get("spinoff_origin") or "").lower()
    if any(s in origin for s in
           ("eth", "epfl", "csem", "empa", "psi", "idiap", "univers", "hsg")):
        return True
    return bool(_SWISS_SIGNAL.search(
        f"{story.get('title', '')} {story.get('description', '')}"))


def plausibly_swiss(story: dict) -> bool:
    """Could this be a post on Max's Swiss DeepTech feed?

    _is_swiss decides database rows, which carry a headquarters and a spin-off
    origin. A post candidate has a headline and a summary and nothing else, and
    judging it the same way threw out four of five real posts.

    So the looser test the picks need: it came from a Swiss outlet, or the
    story itself says Swiss about the company. That keeps a Swiss round covered
    by Sifted and drops "Toronto startup Terminal raises $20-million to become
    the 'Switzerland' of telematics trade", which scored 19 and was one pick
    away from going out under his name.
    """
    from urllib.parse import urlsplit

    # A headquarters on record settles it, whoever published the story. A Swiss
    # outlet writing up global funding led by Anthropic in San Francisco is
    # Swiss journalism, not Swiss DeepTech.
    if (story.get("location") or "").strip():
        return _is_swiss(story)

    host = urlsplit(story.get("link") or "").netloc.lower()
    if host.endswith(".ch") or host.endswith(".swiss"):
        return True
    return bool(_SWISS_SIGNAL.search(
        f"{story.get('title', '')} {story.get('summary', '')} "
        f"{story.get('description', '')}"))


def is_closed(story: dict) -> bool:
    """Has the transaction actually completed?

    An announced deal is not capital raised. Terra Quantum's USD 190M was a
    ceiling on a de-SPAC that had not closed, quoted gross and assuming no
    redemptions, and it sat in the database's total as though the money had
    arrived. Announced deals stay on the page, marked, and out of every sum.
    """
    return (story.get("status") or "").strip().lower() != "announced"


def counted(stories: list) -> list:
    """The rounds whose amounts may be added up."""
    return [s for s in stories if is_closed(s)]


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


# The facts Max can set by hand, in the order they read on a card. Anything
# here goes into corrections.json, which is applied after every lookup and
# always wins, so a value he types survives every future run.
_FIXABLE = [
    ("description", "What it does"),
    ("category", "Sector"),
    ("stage", "Stage"),
    ("amount", "Raised"),
    ("amount_note", "Note on the amount"),
    ("lead_investor", "Lead investor"),
    ("investors", "Investors"),
    ("founders", "Founders"),
    ("spinoff_origin", "Spin-off from"),
    ("location", "HQ"),
    ("legal_seat", "Registered in"),
    ("website", "Website"),
    ("founded", "Founded"),
    ("employees", "Staff"),
    ("total_raised", "Total raised"),
    ("valuation", "Valuation"),
    ("use_of_funds", "Use of funds"),
]

CORRECTIONS_EDIT_URL = ("https://github.com/maximedroux55-hue/Test/edit/"
                        "claude/questions-9a5egd/deeptech-news/corrections.json")

# The Worker that commits a fact typed into the page. It holds the GitHub key
# as a secret, so the page never carries one. Same Worker as the run button.
CORRECTIONS_SAVE_URL = ("https://md-news-button.maxime-droux55.workers.dev/"
                        "correction")


# How long a shortlist is treated as still in use. A run that overwrites one
# Max has not finished with does not just replace a page: it records every
# story on it as used, so the ones he had not picked yet are gone for good.
SHORTLIST_LIFE = dt.timedelta(days=6)


def week_still_running(outdir: str, today: dt.date | None = None) -> bool:
    """Is the shortlist on disk still the one being worked through?

    The old rule read the last scheduled date, which worked while every story
    was handed a day. A shortlist has no days: Max picks from it and the days
    are decided when he copies the instruction. So the question became how old
    the list is, and anything inside SHORTLIST_LIFE is treated as live.

    Running by hand still forces a rebuild.
    """
    import json as _json

    today = today or _zurich_now().date()
    try:
        with open(os.path.join(outdir, "posts.json"), encoding="utf-8") as f:
            saved = _json.load(f)
    except Exception:
        return False

    # A file written before the shortlist existed still carries a day per post.
    # Read it the old way rather than rebuilding over a week being posted.
    dates = [(p.get("date") or "").strip()
             for p in saved.get("posts", []) if p.get("date")]
    if dates and max(dates) >= today.isoformat():
        print(f"The plan on disk runs to {max(dates)} and is still being "
              f"posted. Leaving it alone. Run it by hand to rebuild anyway.",
              file=sys.stderr)
        return True

    made = (saved.get("generated") or "").strip()
    try:
        made_on = dt.date.fromisoformat(made[:10])
    except ValueError:
        return False
    if today - made_on < SHORTLIST_LIFE:
        print(f"The shortlist on disk was built on {made_on.isoformat()} and "
              f"is still current. Leaving it alone: rebuilding now would "
              f"record every story on it as used, including the ones not "
              f"picked yet. Run it by hand to rebuild anyway.",
              file=sys.stderr)
        return True
    return False


# Words that only appear in a German, French or Italian headline. Ambiguous
# ones are left out on purpose: "die", "per" and "con" are English too, and a
# false reading here sends the wrong copy of a story to the page.
_NOT_ENGLISH = re.compile(
    r"\b(der|das|und|f(?:ü|u)r|erh(?:ä|a)lt|millionen|franken|unternehmen|"
    r"sammelt|sichert|lanciert|gr(?:ü|u)ndet|schweizer|schweiz|"
    r"pour|avec|dans|une|ses|leur|millions|l(?:è|e)ve|suisse|soci(?:é|e)t(?:é|e)|"
    r"entreprise|veut|cha(?:î|i)ne|d(?:é|e)veloppe|"
    r"milioni|raccoglie|azienda|svizzera)\b",
    re.IGNORECASE,
)


def _in_english(story: dict) -> bool:
    """Is this the English write-up?

    Startupticker publishes the same piece at /en/ and /de/, and a French trade
    title covers the same round again. The address says so outright where the
    outlet has language paths; where it does not, the headline does.
    """
    # Google News appends " - Publisher" to a headline, and the publisher can
    # be Italian while the article is English: "Switzerland confirms its
    # leading position in deep tech - Università della Svizzera italiana".
    title = re.sub(r"\s+[-|]\s+[^-|]+$", "", story.get("title") or "").strip()
    # The headline decides, not the address. Startupticker files German pieces
    # under /en/, so the path alone called "Humboldt AI lanciert KI-Tool für
    # den CV-Check" English.
    if _NOT_ENGLISH.search(title):
        return False
    link = (story.get("link") or "").lower()
    if "/en/" in link or "/eng/" in link:
        return True
    return not re.search(r"/(de|fr|it)/", link)


# What kind of news this is, in the order the tests are applied. First match
# wins, so the specific patterns sit above the general ones. Written in the
# three languages Swiss outlets publish in, because the page carries all three.
_KINDS = (
    ("Appointment", r"professor|professur|appoint|nomination|named\s+(?:new|as)|"
                    r"steps\s+down|joins\s+as|emeritus|rector|rektor|"
                    r"ernannt|berufen|nomm(?:é|e)|succ(?:è|e)de"),
    ("Grant", r"\bgrant\b|granted\b|f(?:ö|o)rdermittel|f(?:ö|o)rderung|"
              r"innosuisse|venture\s?kick|eic\s+accelerator|snsf|"
              r"subvention|bourse|prix\b|award(?:ed)?\b"),
    ("Acquisition", r"acqui(?:re|red|sition)|takeover|buys\b|merger|"
                    r"(?:ü|u)bernimmt|(?:ü|u)bernahme|rachat|rach(?:è|e)te"),
    # A round the reader failed to pin down still reads as a round in the
    # headline: "SeasON Energy erhält Millionenfinanzierung" had no figure the
    # extractor could use, and landed in General.
    ("Round", r"raises?\b|raised\b|funding\s+round|finanzierung|"
              r"l(?:è|e)ve\s+des\s+fonds|closes?\s+a\s+.{0,20}round|"
              r"pre-?seed|seed\s+round|series\s+[a-e]\b"),
    ("Expansion", r"expands?\b|expansion|new\s+(?:plant|site|factory|office)|"
                  r"opens?\s+(?:a\s+)?(?:plant|site|factory|office|hub)|"
                  r"production\s+at|erweitert|s'implante"),
    ("Regulatory", r"fda\b|ce\s+mark|clearance|approval|authoris|authoriz|"
                   r"zulassung|homologation|first-in-human"),
    ("Award", r"prize|winner|wins\b|crowns|laureate|preis|gewinnt|"
              r"laur(?:é|e)at|remporte"),
    ("Policy", r"neutrality|sovereign|regulation|parliament|kantonsparlament|"
               r"government|bundesrat|federal\s+council|export\s+ban|"
               r"strategy|policy|politique|gesetz|loi\b"),
    ("Partnership", r"partner(?:s|ship)|teams?\s+up|collaborat|joint\s+venture|"
                    r"kooperation|partenariat"),
    ("Launch", r"launch|unveil|introduc|lanciert|lance\b|ships?\b|"
               r"brings?\b|rolls?\s+out|goes\s+live"),
    ("Research", r"research|scientist|stud(?:y|ies)|discover|finds?\b|"
                 r"reveals?\b|identif|detect|breakthrough|"
                 r"forscher|studie|chercheur|(?:é|e)tude"),
)


def _kind(story: dict) -> str:
    """One word for what happened, so the page can be read and filtered by it.

    A financing round, a grant, a professor's appointment and a lake-water
    discovery are all Swiss DeepTech news and all read the same in a list. The
    label is what tells them apart at a glance.
    """
    stage = (story.get("stage") or "").strip().lower()
    if stage == "grant":
        return "Grant"
    if stage == "acquisition":
        return "Acquisition"
    if stage == "partnership":
        return "Partnership"
    if _is_round(story):
        return "Round"
    # The headline only. The description is written by the reader, and one
    # stray word in it ("an article on Switzerland as an AI research hub")
    # filed an opinion piece under Research.
    text = re.sub(r"\s+[-|]\s+[^-|]+$", "", story.get("title") or "")
    for label, pattern in _KINDS:
        if re.search(pattern, text, re.IGNORECASE):
            return label
    # A lab's own newsroom is publishing research whether or not the headline
    # says so: "A lipid switch that blocks anthrax" carries no keyword at all.
    from urllib.parse import urlsplit
    host = urlsplit(story.get("link") or "").netloc.lower()
    if any(host.endswith(d) for d in _LABS):
        return "Research"
    return "General"


# Newsrooms that only ever publish research: their institution is the signal.
_LABS = ("epfl.ch", "ethz.ch", "empa.ch", "psi.ch", "csem.ch", "idiap.ch",
         "unibas.ch", "unige.ch", "uzh.ch", "unil.ch", "unibe.ch", "usi.ch",
         "wsl.ch", "eawag.ch", "agroscope.admin.ch", "zurich.ibm.com")


def _news_rank(story: dict) -> tuple:
    """Which copy of a story survives deduplication. Lower is better.

    Startupticker in English first, because it covers the beat and writes it
    plainly; then anything else in English; then the rest. Within a tier the
    higher-scoring story wins, as before.
    """
    from urllib.parse import urlsplit

    host = urlsplit(story.get("link") or "").netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    english = _in_english(story)
    if host == "startupticker.ch" and english:
        tier = 0
    elif english:
        tier = 1
    elif host == "startupticker.ch":
        tier = 2
    else:
        tier = 3
    return (-tier, story.get("score") or 0)


def render_news_html(known: dict, now: dt.datetime | None = None) -> str:
    """Everything Swiss the tracker has ever seen, not only the money.

    The database answers "which rounds closed". This answers "what happened":
    a grant, a professor's result, a spin-off, a product launch and a Series B
    all count as Swiss DeepTech news, and only the last of them is a round.
    Nothing here is filtered for being a financing story.
    """
    import corrections as _corrections

    now = now or _zurich_now()
    stories = [s for s in known.values()
               if plausibly_swiss(s)
               and not _corrections.is_blocked(s.get("company", ""))]
    # One entry per story. Exclaim Robotics was on here three times, once in
    # French, which is a reading list of the same news repeated.
    before = len(stories)
    stories = deduplicate(stories, key=_news_rank)
    # Two write-ups of one round can be worded far enough apart to survive the
    # headline check: "Exclaim Robotics raises USD 4.95 million" and "Swiss
    # Startup Exclaim Robotics Emerges From Stealth With Nearly $5M". Same
    # company, same money, one story. Same rule as the database uses.
    kept, seen = [], []
    for story in stories:
        stem = _company_stem(story.get("company", "")) if _is_round(story) else ""
        if stem:
            chf = money.in_chf(story.get("amount", "")) or 0
            _, size = money.parse(story.get("amount", ""))
            if any(other == stem and (_same_size(c, chf) or (size and z == size))
                   for other, c, z in seen):
                continue
            seen.append((stem, chf, size))
        kept.append(story)
    stories = kept
    merged = before - len(stories)
    stories.sort(key=lambda e: (e.get("published") or e.get("first_seen") or "",
                                e.get("score") or 0),
                 reverse=True)

    def when(s):
        return (s.get("published") or s.get("first_seen") or "").strip()

    sectors = sorted({(s.get("category") or "").strip()
                      for s in stories if s.get("category")})
    _kind_order = ["Round", "Grant", "Award", "Acquisition", "Partnership",
                   "Regulatory", "Launch", "Expansion", "Research", "Policy",
                   "Appointment", "General"]
    present = {_kind(s) for s in stories}
    kinds = [k for k in _kind_order if k in present]
    counts = {k: sum(1 for s in stories if _kind(s) == k) for k in kinds}
    dates = sorted(d for d in (when(s) for s in stories) if d)
    first_date, last_date = (dates[0], dates[-1]) if dates else ("", "")
    rounds = sum(1 for s in stories if _is_round(s))

    items = []
    for s in stories:
        date = when(s)
        title = (s.get("title") or "").strip() or "(untitled)"
        category = (s.get("category") or "").strip()
        company = (s.get("company") or "").strip()
        kind = _kind(s)
        marks = (f' <span class="tag kind k{kind.lower()}">{kind}</span>')
        if (s.get("score") or 0) >= SUBMITTED:
            marks += ' <span class="tag sent">sent in</span>'
        shown = dt.date.fromisoformat(date).strftime("%d %b %Y") if date else ""
        items.append(
            f'<li data-sector="{html.escape(category)}" '
            f'data-kind="{html.escape(kind)}" '
            f'data-date="{html.escape(date)}">'
            f'<a href="{html.escape(s.get("link", ""))}" target="_blank" '
            f'rel="noopener">{html.escape(title)}</a>{marks}'
            f'<div class="meta">{html.escape(shown)}'
            + (f' &middot; {html.escape(s.get("publisher") or "")}'
               if s.get("publisher") else "")
            + (f' &middot; <span class="cat">{html.escape(category)}</span>'
               if category else "")
            + (f' &middot; {html.escape(company)}' if company else "")
            + '</div></li>'
        )
    body = "\n".join(items) or (
        '<li class="nd">Nothing recorded yet. The next run will fill this in.</li>')
    options = "".join(f'<option value="{html.escape(v)}">{html.escape(v)}</option>'
                      for v in sectors)
    kind_options = "".join(
        f'<option value="{html.escape(k)}">{html.escape(k)} ({counts[k]})</option>'
        for k in kinds)
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Swiss DeepTech news</title><meta name="robots" content="noindex">
<style>
  :root {{ --green:#46b96a; --ink:#1b2430; --soft:#5b6472; --faint:#9aa3ad;
          --line:#e6eae8; --bg:#f6f8f7; }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
         background:var(--bg); color:var(--ink); line-height:1.5; }}
  .wrap {{ max-width:900px; margin:0 auto; padding:2rem 1rem 4rem; }}
  h1 {{ font-size:1.6rem; letter-spacing:-0.02em; }} h1 .dot {{ color:var(--green); }}
  .sub {{ color:var(--soft); margin:0.4rem 0 1rem; font-size:0.9rem; }}
  .refreshed {{ color:var(--soft); font-size:0.83rem; margin:0 0 1rem;
               background:#fff; border:1px solid var(--line); border-radius:12px;
               padding:0.6rem 0.9rem; }}
  .refreshed b {{ color:var(--ink); }}
  .controls {{ display:flex; gap:0.6rem; align-items:center; margin-bottom:1rem;
              flex-wrap:wrap; }}
  .controls input[type=text] {{ flex:1 1 14rem; min-width:11rem; padding:0.7rem 0.9rem;
    border:1px solid var(--line); border-radius:10px; font-size:1rem; }}
  .controls select, .controls input[type=date] {{ font-size:0.85rem;
    padding:0.55rem 0.6rem; border:1px solid var(--line); border-radius:10px;
    background:#fff; color:var(--ink); font-family:inherit; }}
  .dates {{ display:flex; align-items:center; gap:0.35rem; font-size:0.8rem;
           color:var(--soft); background:#fff; border:1px solid var(--line);
           border-radius:10px; padding:0 0 0 0.6rem; white-space:nowrap; }}
  .dates input[type=date] {{ border:none; padding:0.55rem 0.4rem; }}
  .clear {{ font-size:0.85rem; font-family:inherit; color:var(--soft);
           background:#fff; border:1px solid var(--line); border-radius:10px;
           padding:0.58rem 0.9rem; cursor:pointer; }}
  .clear:hover {{ color:var(--green); border-color:var(--green); }}
  .live {{ color:var(--soft); font-size:0.82rem; white-space:nowrap;
          margin-left:auto; padding-left:0.4rem; }}
  ul {{ list-style:none; background:#fff; border:1px solid var(--line);
       border-radius:14px; overflow:hidden; }}
  li {{ padding:0.8rem 1rem; border-bottom:1px solid var(--line); }}
  li:last-child {{ border-bottom:none; }}
  li a {{ color:var(--ink); text-decoration:none; font-weight:600; }}
  li a:hover {{ color:var(--green); }}
  .meta {{ color:var(--soft); font-size:0.82rem; margin-top:0.2rem; }}
  .cat {{ background:#eef4f0; color:#2f6b46; border-radius:6px;
         padding:0.05rem 0.4rem; font-size:0.74rem; font-weight:600; }}
  .tag {{ border-radius:6px; padding:0.05rem 0.4rem; font-size:0.68rem;
         font-weight:700; vertical-align:middle; margin-left:0.3rem; }}
  .tag.posted {{ background:var(--green); color:#fff; }}
  .tag.round {{ background:#eef3f8; color:#4a6b8a; border:1px solid #dde6ef; }}
  .tag.sent {{ background:#1b2430; color:#fff; }}
  /* One colour per kind of news, so the list can be skimmed rather than read. */
  .tag.kind {{ border:1px solid transparent; }}
  .kround {{ background:#e8f3ec; color:#2f6b46; border-color:#cfe5d8; }}
  .kgrant {{ background:#eef3f8; color:#3f6187; border-color:#dbe6f0; }}
  .kacquisition {{ background:#f6ecef; color:#8a4a5e; border-color:#ecd8de; }}
  .kpartnership {{ background:#f1eff8; color:#5b4b8a; border-color:#e0dbef; }}
  .kregulatory {{ background:#fdf3e3; color:#8a6d3b; border-color:#f0e2c8; }}
  .klaunch {{ background:#eaf4f6; color:#2f6a75; border-color:#d5e7ea; }}
  .kresearch {{ background:#f2f1ec; color:#6a6552; border-color:#e4e2d8; }}
  .kappointment {{ background:#f4f0ea; color:#7a5c3e; border-color:#e8ddcd; }}
  .kaward {{ background:#fdf1f3; color:#8a4a5e; border-color:#f2dde2; }}
  .kexpansion {{ background:#eef4f0; color:#3f6b53; border-color:#dbe8e0; }}
  .kpolicy {{ background:#eef1f6; color:#4a5878; border-color:#dde3ee; }}
  .kgeneral {{ background:#f1f3f2; color:#5b6472; border-color:#e3e7e5; }}
  .nd {{ color:var(--faint); }}
  .more {{ display:block; width:100%; margin-top:1rem; font-family:inherit;
          font-size:0.9rem; font-weight:600; color:var(--ink); background:#fff;
          border:1px solid var(--line); border-radius:12px; padding:0.8rem;
          cursor:pointer; }}
  .more:hover {{ border-color:var(--green); color:var(--green); }}
  a.back {{ color:var(--soft); }} a.back:hover {{ color:var(--green); }}
  @media (max-width: 760px) {{
    .wrap {{ padding:1.5rem 0.85rem 3rem; }}
    .controls select, .controls input, .dates, .clear {{ flex:1 1 45%; }}
  }}
</style></head><body>
<div class="wrap">
  <h1>Swiss DeepTech news<span class="dot">.</span></h1>
  <p class="sub">Everything the tracker has found and judged Swiss, newest first:
  rounds, grants, research results, spin-offs and launches alike. {rounds} of
  these {len(stories)} report a financing round; those are merged, one row per
  round, in <a href="/digest/archive.html">the database &rarr;</a></p>
  <p class="refreshed"><b>Refreshed {now.strftime('%d %B %Y at %H:%M')}</b>
  &middot; {len(stories)} stories on record, back to
  {dt.date.fromisoformat(first_date).strftime('%d %B %Y') if first_date else 'the first run'}.
  {merged} further write-ups of the same stories were folded in, keeping
  Startupticker's English version where there was one.</p>
  <div class="controls">
    <input type="text" id="q" placeholder="Search headline, company, outlet..." oninput="filter()">
    <select id="kind" onchange="filter()"><option value="">Every kind</option>{kind_options}</select>
    <select id="sector" onchange="filter()"><option value="">Every sector</option>{options}</select>
    <label class="dates">from <input type="date" id="from" value="" min="{first_date}" max="{last_date}" onchange="filter()"></label>
    <label class="dates">to <input type="date" id="to" value="" min="{first_date}" max="{last_date}" onchange="filter()"></label>
    <button type="button" class="clear" onclick="clearAll()">Clear</button>
    <span class="live" id="count"></span>
  </div>
  <ul id="rows">
{body}
  </ul>
  <button type="button" class="more" id="more" onclick="showMore()" hidden></button>
</div>
<script>
  function val(id) {{ return document.getElementById(id).value; }}
  var PAGE = 25, shown_upto = PAGE;

  function filter(reset) {{
    if (reset !== false) shown_upto = PAGE;
    var q = val('q').toLowerCase(), sector = val('sector'), kind = val('kind');
    var from = val('from'), to = val('to');
    var rows = document.querySelectorAll('#rows li');
    var shown = 0;
    for (var i = 0; i < rows.length; i++) {{
      var row = rows[i];
      var date = row.getAttribute('data-date') || '';
      var ok = row.innerText.toLowerCase().indexOf(q) > -1
        && (!sector || row.getAttribute('data-sector') === sector)
        && (!kind || row.getAttribute('data-kind') === kind)
        && (!from || (date && date >= from))
        && (!to || (date && date <= to));
      if (ok) shown++;
      row.style.display = (ok && shown <= shown_upto) ? '' : 'none';
    }}
    var more = document.getElementById('more');
    var left = shown - shown_upto;
    more.hidden = left <= 0;
    more.textContent = 'Show ' + Math.min(left, PAGE) + ' more of ' + shown;
    document.getElementById('count').textContent =
      shown + ' stor' + (shown === 1 ? 'y' : 'ies');
  }}

  function showMore() {{ shown_upto += PAGE; filter(false); return false; }}

  function clearAll() {{
    ['q', 'kind', 'sector', 'from', 'to'].forEach(function (id) {{
      document.getElementById(id).value = '';
    }});
    filter();
  }}

  filter();
</script>
</body></html>
"""


def _zurich_now() -> dt.datetime:
    """Now, in Max's time. The runner is on UTC, which is not where he reads."""
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("Europe/Zurich"))
    except Exception:
        return dt.datetime.now(dt.timezone.utc)


def render_archive_html(known: dict, now: dt.datetime | None = None,
                        only: str = "swiss") -> str:
    """A browsable page of the financing rounds found, newest first.

    Nine rigid columns left a hole wherever a fact was missing, and articles
    routinely withhold investors and founders, so most of the table read as
    blank. The columns here are the ones that are almost always known, and
    everything else sits under the company name and only appears when it is
    actually there, so a missing fact costs a phrase rather than a gap.

    The page also says when it last ran and what that run added, because a
    database you cannot date is one you cannot trust: without it there is no
    way to tell a quiet week from a broken job.
    """
    now = now or _zurich_now()
    everything = sorted(
        known.values(),
        key=lambda e: (e.get("published") or e.get("first_seen") or "",
                       e.get("score") or 0),
        reverse=True,
    )
    rounds = merge_deals([s for s in everything if _is_round(s)])
    # Sort the rounds, not the write-ups. GR3N closed on 5 June and sat second
    # on the page, because one of its two write-ups carried no date at all and
    # fell back to the day the tool found it. The round has one date; the
    # merged row is the only thing that knows it.
    rounds.sort(key=lambda e: (e.get("published") or e.get("first_seen") or "",
                               e.get("score") or 0),
                reverse=True)
    # Ruled out by hand: Swiss news, not a Swiss company. Off both pages, and
    # back on both the moment the name leaves corrections.json.
    import corrections as _corrections
    ruled_out = [s for s in rounds if _corrections.is_blocked(s.get("company", ""))]
    rounds = [s for s in rounds if s not in ruled_out]

    # The database is Swiss DeepTech and says so, so the main page carries only
    # Swiss rounds. The rest are not deleted: a seat abroad is sometimes a
    # Swiss company registered elsewhere, and that is Max's call to make. They
    # live on their own page with the same editing panel, one link away.
    swiss = [s for s in rounds if _is_swiss(s)]
    held = [s for s in rounds if not _is_swiss(s)]
    stories = held if only == "held" else swiss
    foreign = len(held)
    hidden = len(everything) - len(rounds) - len(ruled_out)
    posted = sum(1 for s in stories if s.get("posted"))
    with_investors = sum(1 for s in stories if _investor_line(s))
    with_founders = sum(1 for s in stories if (s.get("founders") or "").strip())
    placed = sum(1 for s in stories if (s.get("location") or "").strip())
    announced = sum(1 for s in stories if not is_closed(s))
    tracked = money.compact(
        sum(money.in_chf(s.get("amount", "")) for s in counted(stories)))

    # What the most recent run that found anything actually added. Keyed on the
    # newest first_seen present rather than on today, so a quiet run says "the
    # last additions were on the 2nd" instead of silently showing nothing new.
    refreshed = now.strftime("%d %B %Y at %H:%M")
    today = now.date()
    seen_dates = sorted({(s.get("first_seen") or "").strip()
                         for s in stories if s.get("first_seen")})
    # The day the record was created is not an addition. The archive was
    # rebuilt from scratch on 3 August, so every round in it carried that
    # morning's date and all 21 rows came up marked new. Nothing is new when
    # everything is. The earliest date present is the baseline load, and only
    # what arrived after it counts as added.
    baseline = seen_dates[0] if seen_dates else ""

    def entered(story) -> str:
        seen = (story.get("first_seen") or "").strip()
        return "" if not seen or seen == baseline else seen

    additions = [s for s in stories if entered(s)]
    newest = max((entered(s) for s in additions), default="")
    fresh = [s for s in additions if entered(s) == newest]
    week_ago = (today - dt.timedelta(days=7)).isoformat()
    month_ago = (today - dt.timedelta(days=30)).isoformat()
    added_week = sum(1 for s in additions if entered(s) >= week_ago)
    if newest == today.isoformat():
        added_line = (f"{len(fresh)} round{'' if len(fresh) == 1 else 's'} "
                      f"added today")
    elif newest:
        when = dt.date.fromisoformat(newest).strftime("%d %B")
        added_line = (f"last additions {when}: {len(fresh)} "
                      f"round{'' if len(fresh) == 1 else 's'}")
    elif baseline:
        when = dt.date.fromisoformat(baseline).strftime("%d %B")
        added_line = (f"all {len(stories)} rounds loaded together when the "
                      f"record was built on {when}, so nothing is marked new "
                      f"yet")
    else:
        added_line = "nothing added yet"

    if only == "held":
        heading = "Held back"
        blurb = (
            'Rounds kept off the database because the headquarters on record is '
            'not in Switzerland. A seat abroad is not always a foreign company, '
            'so nothing here is thrown away: correct the HQ with the '
            '<b>+</b> and the round joins the database on the next run. '
            f'{len(ruled_out)} more were ruled out by name in corrections.json. '
            '<a href="/digest/archive.html">&larr; Back to the database</a>'
        )
    else:
        heading = "Swiss DeepTech rounds"
        blurb = (
            'Swiss companies only, newest first. One row per round: where several '
            'outlets covered the same one, their facts are combined. '
            '<a href="/reports/">Monthly reports &rarr;</a> '
            f'<span title="Kept in archive.json, which is the raw record">{hidden} '
            'non-financing stories are held back.</span> '
            f'<a href="/digest/all.html">All Swiss news &rarr;</a> '
            f'<a href="/digest/held.html">{foreign} rounds held back for a '
            'foreign headquarters &rarr;</a>'
        )

    def options(field: str) -> str:
        """The values actually present, so no filter leads to an empty table."""
        seen = sorted({(s.get(field) or "").strip() for s in stories if s.get(field)})
        return "".join(f'<option value="{html.escape(v)}">{html.escape(v)}</option>'
                       for v in seen)

    # Stages read better in the order money arrives than alphabetically.
    _order = ["Pre-seed", "Seed", "Series A", "Series B", "Series C", "Series D",
              "Growth", "Grant", "IPO", "Acquisition"]
    present = {(s.get("stage") or "").strip() for s in stories if s.get("stage")}
    stage_options = "".join(
        f'<option value="{html.escape(v)}">{html.escape(v)}</option>'
        for v in ([v for v in _order if v in present]
                  + sorted(present - set(_order))))
    dates = sorted(d for d in ((s.get("published") or s.get("first_seen") or "")
                               for s in stories) if d)
    first_date, last_date = (dates[0], dates[-1]) if dates else ("", "")

    def cell(value: str, css: str = "", title: str = "", label: str = "") -> str:
        """One fact, one cell. An empty one is marked, not left blank.

        The label travels with the value because a phone stacks the row into a
        card, where a column heading three screens up is no help.
        """
        text = (value or "").strip()
        tag = f' data-label="{html.escape(label)}"' if label else ""
        if not text:
            return (f'<td class="{css} empty"{tag}>'
                    f'<span class="nd">&middot;</span></td>')
        attr = f' title="{html.escape(title)}"' if title else ""
        return f'<td class="{css}"{tag}{attr}>{html.escape(text)}</td>'

    # The corrections file as it stands, so the panel can hand back a complete
    # replacement rather than a fragment Max has to splice in by hand.
    import json as _json

    import corrections as _corrections
    try:
        with open(_corrections.PATH, encoding="utf-8") as f:
            current_fixes = _json.load(f)
    except Exception:
        current_fixes = {"companies": {}}
    current_fixes.setdefault("companies", {})
    fields_json = _json.dumps(_FIXABLE)

    rows = []
    for s in stories:
        # Whether a round became a LinkedIn post is a fact about the posting
        # side, not about the round. It has no place on the database page.
        tag = ""
        # How many outlets wrote this round up. Coverage, not verification:
        # three papers rewriting one press release is one source repeated, and
        # both Terra Quantum and MoonLake were wrong in every outlet at once.
        # Kept away from the verified badge so the two never read as the same
        # claim.
        if not _is_swiss(s):
            where = (s.get("location") or "").strip() or "not Switzerland"
            tag += (f' <span class="tag abroad" title="Headquarters recorded '
                    f'as {html.escape(where)}. Shown because a foreign seat '
                    f'does not always mean a foreign company.">foreign '
                    f'HQ</span>')
        outlets = [p for p in (s.get("sources") or []) if p]
        if len(outlets) > 1:
            tag += (f' <span class="tag sources" title="Covered by '
                    f'{html.escape(", ".join(outlets))}. Coverage, not a '
                    f'check against a primary source.">{len(outlets)} '
                    f'sources</span>')
        first_seen = entered(s)
        if newest and first_seen == newest:
            tag += (f' <span class="tag fresh" title="Added by the run of '
                    f'{html.escape(newest)}">new</span>')
        company = html.escape(s.get("company") or "") or html.escape(
            (s.get("title") or "")[:40])
        # Startupticker where there is one, whatever the round was found on.
        link = html.escape(s.get("startupticker_url") or s.get("link", ""))
        chf = money.in_chf(s.get("amount", ""))

        # What the row knows beyond its columns, kept on the company name so
        # the table stays one fact per column.
        extra = []
        for label, field in (("Founded", "founded"), ("Staff", "employees"),
                             ("Total raised", "total_raised"),
                             ("Valuation", "valuation"),
                             ("Use of funds", "use_of_funds"),
                             ("Registered in", "legal_seat")):
            if (s.get(field) or "").strip():
                extra.append(f"{label}: {s[field].strip()}")
        outlets = [p for p in (s.get("sources") or []) if p]
        if outlets:
            extra.append("Source: " + ", ".join(outlets))
        hover = html.escape(" · ".join(extra) or s.get("title", ""))

        stage_text = (s.get("stage") or "").strip()
        pending = ('<span class="pending" title="Announced, not closed. Its '
                   'figure is excluded from every total.">announced</span>'
                   if not is_closed(s) else "")
        checked = (s.get("verified") or "").strip()
        if checked:
            src = (s.get("verified_source") or "a primary source").strip()
            pending += (f'<span class="checked" title="Checked against '
                        f'{html.escape(src)} on {html.escape(checked)}">'
                        f'verified</span>')
        if stage_text == "Grant":
            pending += ('<span class="nondil" title="Public or foundation '
                        'money, not an equity round.">non-dilutive</span>')
        stage = (f'<td data-label="Stage"><span class="stage">'
                 f'{html.escape(stage_text)}</span>{pending}</td>'
                 if stage_text
                 else f'<td data-label="Stage" class="{"" if pending else "empty"}">'
                      f'<span class="nd">&middot;</span>{pending}</td>')
        category_text = (s.get("category") or "").strip()
        category = (f'<td data-label="Sector"><span class="cat">'
                    f'{html.escape(category_text)}</span></td>' if category_text
                    else '<td data-label="Sector" class="empty">'
                         '<span class="nd">&middot;</span></td>')

        amount_text = (s.get("amount") or "").strip()
        from extract import useful_note
        note = useful_note(s.get("amount_note") or "")
        if amount_text and note:
            # "up to USD 190M" is a different claim from "USD 190M".
            shown = (f'{html.escape(note.split(",")[0])} '
                     f'{html.escape(amount_text)}')
            title = f"{note}. Not counted in the total."
        else:
            shown, title = html.escape(amount_text), money.compact(chf)
        amount = (f'<td class="amt" data-label="Raised" '
                  f'title="{html.escape(title)}">{shown}</td>' if amount_text
                  else '<td class="amt" data-label="Raised">'
                       '<span class="nd">undisclosed</span></td>')

        location_text = (s.get("location") or "").strip()
        if location_text:
            where = _provenance(s, "location") or "as written in the coverage"
            location = (f'<td class="loc" data-label="HQ" '
                        f'title="Source: {html.escape(where)}">'
                        f'{html.escape(location_text)}</td>')
        else:
            location = ('<td class="loc" data-label="HQ"><span class="nd" '
                        'title="Swiss company, city not found yet">CH</span></td>')

        date_text = (s.get("published") or s.get("first_seen") or "").strip()
        rows.append(
            f'<tr data-chf="{chf if is_closed(s) else 0}" '
            f'data-sector="{html.escape(category_text)}" '
            f'data-stage="{html.escape(stage_text)}" '
            f'data-hq="{html.escape(location_text)}" '
            f'data-added="{html.escape(first_seen)}" '
            f'data-company="{html.escape(s.get("company") or "")}" '
            f'data-swiss="{"1" if _is_swiss(s) else "0"}" '
            f'data-facts="{html.escape(_json.dumps({k: (s.get(k) or "").strip() for k, _ in _FIXABLE}))}" '
            f'data-date="{html.escape(date_text)}">'
            f'<td class="co" data-label="Company">'
            f'<a href="{link}" target="_blank" rel="noopener" '
            f'title="{hover}">{company}</a>'
            f'<span class="marks">{tag}'
            f'<button type="button" class="fix" onclick="openFix(this)" '
            f'title="Add or correct a fact on this round">+</button></span></td>'
            + cell(s.get("description") or s.get("title", ""), "desc",
                   label="What it does")
            + category
            + stage
            + amount
            + cell(_investor_line(s), "inv", label="Investors")
            + cell(s.get("founders", ""), "fnd", label="Founders")
            + cell(s.get("spinoff_origin", ""), "org", label="Spin-off")
            + location
            + cell(s.get("published") or s.get("first_seen", ""), "d",
                   label="Date")
            + '</tr>'
        )
    body = "\n".join(rows) or (
        '<tr><td colspan="10" class="nd">No financing rounds recorded yet. '
        'The next run will fill this in.</td></tr>')
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{heading}</title><meta name="robots" content="noindex">
<style>
  :root {{ --green:#46b96a; --ink:#1b2430; --soft:#5b6472; --faint:#9aa3ad;
          --line:#e6eae8; --bg:#f6f8f7; }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
         background:var(--bg); color:var(--ink); line-height:1.5; }}
  .wrap {{ max-width:1500px; margin:0 auto; padding:2rem 1rem 4rem; }}
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
  /* Ten columns budgeted to fit a laptop. Before this the table was 1571px
     wide inside a 1406px page, so HQ and Date, the two columns a Swiss
     database exists for, sat off the right edge behind a scrollbar. */
  table {{ width:100%; border-collapse:collapse; font-size:0.85rem;
          table-layout:fixed; min-width:1120px; }}
  th, td {{ text-align:left; padding:0.55rem 0.6rem; border-bottom:1px solid var(--line);
           vertical-align:top; overflow-wrap:break-word; }}
  th {{ color:var(--soft); font-size:0.72rem; text-transform:uppercase;
       letter-spacing:0.04em; position:sticky; top:0;
       background:#fff; z-index:1; }}
  tr:last-child td {{ border-bottom:none; }}
  tbody tr:hover {{ background:var(--bg); }}
  /* Widths, in order: company, what it does, sector, stage, raised,
     investors, founders, spin-off, HQ, date. */
  col.c-co {{ width:12.5%; }}  col.c-desc {{ width:17.5%; }}
  col.c-sec {{ width:7%; }}    col.c-stage {{ width:8.5%; }}
  col.c-amt {{ width:8.5%; }}  col.c-inv {{ width:15.5%; }}
  col.c-fnd {{ width:11%; }}   col.c-org {{ width:6.5%; }}
  col.c-loc {{ width:6%; }}    col.c-date {{ width:7%; }}
  td.co {{ font-weight:600; }}
  td.desc, td.inv, td.fnd, td.org {{ color:var(--soft); }}
  td.amt {{ color:var(--ink); font-weight:600; }}
  td.loc, td.d {{ color:var(--soft); }}
  td.d {{ white-space:nowrap; font-variant-numeric:tabular-nums; }}
  a {{ color:var(--ink); text-decoration:none; }} a:hover {{ color:var(--green); }}
  .nd {{ color:var(--faint); font-weight:400; font-size:0.82rem; }}
  /* The marks sit on their own line under the name and never break a phrase:
     "2 sources" was wrapping to "2" and "sources". */
  td.co .marks {{ display:flex; flex-wrap:wrap; gap:0.25rem; align-items:center;
                 margin-top:0.25rem; }}
  td.co .marks > * {{ white-space:nowrap; }}
  .tag.posted {{ background:var(--green); color:#fff; border-radius:6px;
                padding:0.05rem 0.4rem; font-size:0.7rem; font-weight:700;
                vertical-align:middle; }}
  .tag.abroad {{ background:#f3f0ea; color:#8a6d3b; border:1px solid #e6ddcc;
                border-radius:6px; padding:0.05rem 0.4rem; font-size:0.7rem;
                font-weight:700; vertical-align:middle; }}
  .tag.sources {{ background:#eef3f8; color:#4a6b8a; border:1px solid #dde6ef;
                 border-radius:6px; padding:0.05rem 0.4rem; font-size:0.7rem;
                 font-weight:700; vertical-align:middle; }}
  .tag.fresh {{ background:#1b2430; color:#fff; border-radius:6px;
               padding:0.05rem 0.4rem; font-size:0.7rem; font-weight:700;
               vertical-align:middle; letter-spacing:0.02em; }}
  .refreshed {{ color:var(--soft); font-size:0.83rem; margin:0 0 1rem;
               background:#fff; border:1px solid var(--line); border-radius:12px;
               padding:0.6rem 0.9rem; }}
  .refreshed b {{ color:var(--ink); }}

  /* Typing in a fact the scraper could not find. */
  .fix {{ font-family:inherit; font-size:0.78rem; opacity:0.45;
         font-weight:700; line-height:1; color:var(--soft); background:#fff;
         border:1px solid var(--line); border-radius:6px; padding:0.15rem 0.4rem;
         cursor:pointer; vertical-align:middle; }}
  tr:hover .fix, .fix:focus-visible {{ opacity:1; }}
  .fix:hover {{ color:var(--green); border-color:var(--green); opacity:1; }}
  @media (max-width:760px) {{ .fix {{ opacity:1; }} }}
  .sheet {{ position:fixed; inset:0; background:rgba(27,36,48,0.45);
           display:flex; align-items:flex-end; justify-content:center;
           z-index:20; }}
  .sheet[hidden] {{ display:none; }}
  .sheetbox {{ background:var(--bg); width:100%; max-width:620px;
              max-height:92vh; overflow-y:auto; border-radius:18px 18px 0 0;
              padding:1.2rem 1.1rem 1.6rem; }}
  .sheetbox h2 {{ font-size:1.25rem; letter-spacing:-0.02em; }}
  .sheetnote {{ color:var(--soft); font-size:0.8rem; margin:0.4rem 0 0.9rem; }}
  .field {{ display:flex; align-items:center; gap:0.6rem; background:#fff;
           border:1px solid var(--line); border-radius:10px; padding:0.4rem 0.7rem;
           margin-bottom:0.4rem; }}
  .field span {{ flex:0 0 7.5rem; color:var(--soft); font-size:0.72rem;
                text-transform:uppercase; letter-spacing:0.04em; }}
  .field input {{ flex:1 1 auto; border:none; padding:0.3rem 0; margin:0;
                 font-size:0.92rem; background:none; }}
  .field input:focus {{ outline:none; }}
  .field.missing {{ border-style:dashed; }}
  .field.missing span {{ color:var(--faint); }}
  .sheetacts {{ display:flex; gap:0.5rem; flex-wrap:wrap; margin:0.9rem 0 0.6rem;
               position:sticky; bottom:0; background:var(--bg); padding:0.7rem 0;
               border-top:1px solid var(--line); z-index:2; }}
  .btn {{ font-family:inherit; font-size:0.88rem; font-weight:600; color:#fff;
         background:var(--ink); border:1px solid var(--ink); border-radius:10px;
         padding:0.6rem 0.9rem; cursor:pointer; text-decoration:none;
         display:inline-block; }}
  .btn:hover {{ background:var(--green); border-color:var(--green); color:#fff; }}
  .btn:disabled {{ background:#fff; color:var(--faint); border-color:var(--line);
                  cursor:default; }}
  .fallback {{ margin-top:0.5rem; }}
  .fallback summary {{ color:var(--soft); font-size:0.8rem; cursor:pointer;
                      padding:0.35rem 0; }}
  #out {{ width:100%; height:8rem; font-family:ui-monospace,Menlo,Consolas,monospace;
         font-size:0.72rem; color:var(--soft); border:1px solid var(--line);
         border-radius:10px; padding:0.6rem; background:#fff; }}
  .cat {{ background:#eef4f0; color:#2f6b46; border-radius:6px;
         padding:0.1rem 0.45rem; font-size:0.76rem; font-weight:600;
         white-space:nowrap; }}
  .stage {{ border:1px solid var(--line); border-radius:6px; padding:0.1rem 0.45rem;
           font-size:0.76rem; font-weight:600; white-space:nowrap; }}
  .total {{ display:block; color:var(--soft); font-size:0.72rem; font-weight:500; }}
  .pending {{ display:block; margin-top:0.2rem; background:#fdf3e3; color:#8a6d3b;
             border-radius:5px; padding:0.02rem 0.3rem; font-size:0.66rem;
             font-weight:700; text-transform:uppercase; letter-spacing:0.03em; }}
  .checked {{ display:block; margin-top:0.2rem; color:#2f6b46; background:#eef4f0;
             border-radius:5px; padding:0.02rem 0.3rem; font-size:0.66rem;
             font-weight:700; text-transform:uppercase; letter-spacing:0.03em; }}
  .nondil {{ display:block; margin-top:0.2rem; color:#4a6b8a; background:#eef3f8;
            border-radius:5px; padding:0.02rem 0.3rem; font-size:0.66rem;
            font-weight:700; text-transform:uppercase; letter-spacing:0.03em; }}
  .foreign {{ background:#f3f0ea; color:#8a6d3b; border-radius:5px;
             padding:0.02rem 0.3rem; font-size:0.68rem; font-weight:700; }}
  .controls {{ display:flex; gap:0.6rem; align-items:center; margin-bottom:1rem;
              flex-wrap:wrap; }}
  .controls input[type=text] {{ flex:1 1 14rem; margin:0; min-width:11rem; }}
  .controls select, .controls input[type=date] {{ font-size:0.85rem;
    padding:0.55rem 0.6rem; border:1px solid var(--line); border-radius:10px;
    background:#fff; color:var(--ink); font-family:inherit; }}
  .dates {{ display:flex; align-items:center; gap:0.35rem; font-size:0.8rem;
           color:var(--soft); background:#fff; border:1px solid var(--line);
           border-radius:10px; padding:0 0 0 0.6rem; white-space:nowrap; }}
  .dates input[type=date] {{ border:none; padding:0.55rem 0.4rem; }}
  .clear {{ font-size:0.85rem; font-family:inherit; color:var(--soft);
           background:#fff; border:1px solid var(--line); border-radius:10px;
           padding:0.58rem 0.9rem; cursor:pointer; }}
  .clear:hover {{ color:var(--green); border-color:var(--green); }}
  /* On a phone the tiles and six controls pushed the first round 900px down an
     844px screen: you landed on a database and saw no data. The filters fold
     behind one button, and the tiles scroll sideways instead of stacking. */
  .morefilters {{ display:none; }}
  .morefilters[aria-expanded="true"] {{ color:var(--green); border-color:var(--green); }}
  th {{ cursor:pointer; user-select:none; }}
  th:hover {{ color:var(--green); }}
  th.up::after {{ content:" \\2191"; color:var(--green); }}
  th.down::after {{ content:" \\2193"; color:var(--green); }}
  .note {{ color:var(--faint); font-size:0.76rem; margin-top:0.8rem; }}
  .live {{ color:var(--soft); font-size:0.82rem; white-space:nowrap; }}
  .more {{ display:block; width:100%; margin-top:1rem; font-family:inherit;
          font-size:0.9rem; font-weight:600; color:var(--ink); background:#fff;
          border:1px solid var(--line); border-radius:12px; padding:0.8rem;
          cursor:pointer; }}
  .more:hover {{ border-color:var(--green); color:var(--green); }}

  /* A ten column table does not fit a phone, so each round becomes a card and
     every value carries its own label. Empty facts are dropped rather than
     shown as a dot, which on a narrow screen is just a wasted line. */
  @media (max-width: 760px) {{
    .wrap {{ padding:1.5rem 0.85rem 3rem; }}
    .box {{ border:none; background:none; border-radius:0; }}
    table, tbody, tr, td {{ display:block; width:100%; }}
    table {{ min-width:0; }}
    thead {{ display:none; }}
    tr {{ background:#fff; border:1px solid var(--line); border-radius:14px;
         padding:0.85rem 1rem; margin-bottom:0.7rem; }}
    td {{ border:none; padding:0.12rem 0; display:flex; gap:0.6rem;
         align-items:baseline; }}
    td.empty {{ display:none; }}
    td::before {{ content:attr(data-label); flex:0 0 5.4rem; color:var(--faint);
                 font-size:0.68rem; text-transform:uppercase;
                 letter-spacing:0.04em; padding-top:0.15rem; }}
    td.co {{ font-size:1.05rem; margin-bottom:0.1rem; }}
    td.co::before, td.desc::before {{ display:none; }}
    td.desc {{ color:var(--soft); margin-bottom:0.5rem; }}
    td.amt {{ font-size:1rem; }}
    .stats {{ gap:0.4rem; }}
    .stat {{ min-width:0; flex:1 1 30%; padding:0.5rem 0.6rem; }}
    .stat b {{ font-size:1.1rem; }}
    .controls select, .controls input, .dates, .clear {{ flex:1 1 45%; }}
    .searchrow input[type=text] {{ flex:1 1 100%; margin-bottom:0; }}
    .morefilters {{ display:inline-block; flex:0 0 auto; }}
    #filterbits[hidden] {{ display:none; }}
    .stats {{ display:flex; flex-wrap:nowrap; overflow-x:auto; gap:0.4rem;
             scroll-snap-type:x mandatory; padding-bottom:0.25rem; }}
    .stat {{ flex:0 0 auto; min-width:8rem; scroll-snap-align:start; }}
  }}
</style></head><body>
<div class="wrap">
  <h1>{heading}<span class="dot">.</span></h1>
  <p class="sub">{blurb}</p>
  <p class="refreshed"><b>Refreshed {refreshed}</b> &middot; {added_line} &middot;
  {added_week} in the last 7 days. The database runs every morning, so a day with
  nothing new means the news was quiet, not that it stopped.</p>
  <div class="stats">
    <div class="stat"><b>{len(stories)}</b><span>rounds</span></div>
    <div class="stat"><b>{len(fresh) if newest == today.isoformat() else 0}</b><span>added today</span></div>
    <div class="stat"><b>{tracked or "&ndash;"}</b><span>tracked</span></div>
    <div class="stat"><b>{placed}</b><span>with a city</span></div>
    <div class="stat"><b>{announced}</b><span>announced, uncounted</span></div>
    <div class="stat"><b>{with_investors}</b><span>with investors</span></div>
    <div class="stat"><b>{with_founders}</b><span>with founders</span></div>
  </div>
  <div class="controls searchrow">
    <input type="text" id="q" placeholder="Search company, investor, founder..." oninput="filter()">
    <button type="button" class="clear morefilters" id="togglefilters"
            onclick="toggleFilters()" aria-expanded="false" aria-controls="filterbits">Filters</button>
    <span class="live" id="count"></span>
  </div>
  <div class="controls" id="filterbits">
    <select id="added" onchange="filter()">
      <option value="">Added any time</option>
      <option value="new">Just added ({len(fresh)})</option>
      <option value="week">Added in the last 7 days</option>
      <option value="month">Added in the last 30 days</option>
    </select>
    <select id="sector" onchange="filter()"><option value="">Every sector</option>{options("category")}</select>
    <select id="stage" onchange="filter()"><option value="">Every stage</option>{stage_options}</select>
    <select id="hq" onchange="filter()"><option value="">Everywhere</option>{options("location")}</select>
    <label class="dates">from <input type="date" id="from" value="" min="{first_date}" max="{last_date}" onchange="filter()"></label>
    <label class="dates">to <input type="date" id="to" value="" min="{first_date}" max="{last_date}" onchange="filter()"></label>
    <button type="button" class="clear" onclick="clearAll()">Clear</button>
  </div>
  <div class="box"><table>
    <colgroup>
      <col class="c-co"><col class="c-desc"><col class="c-sec"><col class="c-stage">
      <col class="c-amt"><col class="c-inv"><col class="c-fnd"><col class="c-org">
      <col class="c-loc"><col class="c-date">
    </colgroup>
    <thead><tr>
      <th onclick="sortBy(0,'text')">Company</th>
      <th onclick="sortBy(1,'text')">What it does</th>
      <th onclick="sortBy(2,'text')">Sector</th>
      <th onclick="sortBy(3,'text')">Stage</th>
      <th onclick="sortBy(4,'chf')">Raised</th>
      <th onclick="sortBy(5,'text')">Investors</th>
      <th onclick="sortBy(6,'text')">Founders</th>
      <th onclick="sortBy(7,'text')">Spin-off</th>
      <th onclick="sortBy(8,'text')">HQ</th>
      <th onclick="sortBy(9,'date')">Date</th>
    </tr></thead>
    <tbody id="rows">
{body}
    </tbody>
  </table></div>
  <button type="button" class="more" id="more" onclick="showMore()" hidden></button>
  <p class="note"><b>Missing a fact?</b> Tap the <b>+</b> beside a company to type it in
  yourself. What you write goes into corrections.json, which is applied after every
  automatic lookup and always wins, so it survives every future run rather than being
  overwritten the next morning.</p>
  <p class="note">An announced transaction is marked and its figure is excluded from
  every total: a ceiling on a deal that has not closed, quoted gross and before
  redemptions, is not capital raised. Amounts are shown as the article wrote them. The franc figure beside a
  foreign currency, and the total above, are converted at fixed indicative rates and are
  meant for scale rather than accounting. Hover a headquarters to see where it came from.</p>
</div>

<div class="sheet" id="sheet" hidden>
  <div class="sheetbox">
    <h2 id="sheettitle"></h2>
    <p class="sheetnote">Type what is missing, or correct what is wrong. Emptying a
    box that has a value clears it. Tap <b>Save</b> and the page shows it after the
    next run, tomorrow morning.</p>
    <div id="fields"></div>
    <p class="sheetnote">Built from corrections.json as it stood at {refreshed}.
    If you have edited it since, edit it on GitHub instead of pasting over it.</p>
    <div class="sheetacts">
      <button type="button" class="btn" id="savebtn" onclick="saveFix()">Save</button>
      <button type="button" class="clear" onclick="closeFix()">Close</button>
    </div>
    <p class="sheetnote" id="saidwhat">Saved straight to the corrections file. The
    page updates on the next run, tomorrow morning.</p>
    <details class="fallback">
      <summary>Save did not work?</summary>
      <p class="sheetnote">Copy the file and paste it into GitHub by hand. Select
      everything in the box there, paste, then <b>Commit changes</b>.</p>
      <div class="sheetacts">
        <button type="button" class="btn" id="copybtn" onclick="copyFile()">1. Copy the updated file</button>
        <a class="btn" href="{CORRECTIONS_EDIT_URL}" target="_blank" rel="noopener">2. Open the file on GitHub</a>
      </div>
      <textarea id="out" readonly></textarea>
    </details>
  </div>
</div>
<script type="application/json" id="corrections">{_json.dumps(current_fixes)}</script>
<script>
  function val(id) {{ return document.getElementById(id).value; }}

  var PAGE = 12, shown_upto = PAGE;

  // When each round entered the database, versus when the round happened. The
  // Date column is the news date; this is the "what changed since I last
  // looked" question, and the two are not the same.
  var NEWEST = "{newest}", WEEK_AGO = "{week_ago}", MONTH_AGO = "{month_ago}";

  // ------------------------------------------------ typing in a missing fact
  // The scraper will never get everything: GR3N's founder was in no article it
  // could read. Rather than leaving the gap, the row hands Max the file with
  // his answer already merged in, so the only manual step is a paste.
  var FIELDS = {fields_json};
  var CORRECTIONS = JSON.parse(document.getElementById('corrections').textContent);
  var editing = null;

  function openFix(btn) {{
    // closest, never a fixed number of parentNode hops: wrapping this button
    // in a span for the desktop layout moved it one level down and the panel
    // silently opened with no company and every field blank.
    var row = btn.closest('tr');
    if (!row) return;
    editing = {{
      company: row.getAttribute('data-company') || '',
      facts: JSON.parse(row.getAttribute('data-facts') || '{{}}')
    }};
    document.getElementById('sheettitle').textContent = editing.company;
    var box = document.getElementById('fields');
    box.innerHTML = '';
    for (var i = 0; i < FIELDS.length; i++) {{
      var key = FIELDS[i][0], label = FIELDS[i][1];
      var was = editing.facts[key] || '';
      var line = document.createElement('label');
      line.className = 'field' + (was ? '' : ' missing');
      var name = document.createElement('span');
      name.textContent = label;
      var input = document.createElement('input');
      input.type = 'text';
      input.id = 'f_' + key;
      input.value = was;
      input.placeholder = was ? '' : 'not known';
      input.oninput = build;
      line.appendChild(name);
      line.appendChild(input);
      box.appendChild(line);
    }}
    build();
    document.getElementById('sheet').hidden = false;
    document.body.style.overflow = 'hidden';
  }}

  function closeFix() {{
    document.getElementById('sheet').hidden = true;
    document.body.style.overflow = '';
    editing = null;
  }}

  function build() {{
    if (!editing) return '';
    var file = JSON.parse(JSON.stringify(CORRECTIONS));
    if (!file.companies) file.companies = {{}};
    var entry = {{}};
    var existing = file.companies[editing.company];
    if (existing) {{
      for (var k in existing) entry[k] = existing[k];
    }}
    var touched = 0;
    for (var i = 0; i < FIELDS.length; i++) {{
      var key = FIELDS[i][0];
      var input = document.getElementById('f_' + key);
      if (!input) continue;
      var now = input.value.trim(), was = editing.facts[key] || '';
      // Only what he actually changed. An empty box that was always empty is
      // not an instruction; one he cleared himself is, and clears the value.
      if (now !== was) {{ entry[key] = now; touched++; }}
    }}
    file.companies[editing.company] = entry;
    var text = JSON.stringify(file, null, 2);
    document.getElementById('out').value = text;
    var btn = document.getElementById('copybtn');
    btn.disabled = !touched;
    btn.textContent = touched
      ? '1. Copy the updated file (' + touched + ' change' + (touched === 1 ? '' : 's') + ')'
      : '1. Copy the updated file';
    var save = document.getElementById('savebtn');
    save.disabled = !touched;
    save.textContent = touched
      ? 'Save ' + touched + ' change' + (touched === 1 ? '' : 's')
      : 'Save';
    changed = {{}};
    for (var j = 0; j < FIELDS.length; j++) {{
      var f = FIELDS[j][0];
      var box = document.getElementById('f_' + f);
      if (box && box.value.trim() !== (editing.facts[f] || '')) {{
        changed[f] = box.value.trim();
      }}
    }}
    return text;
  }}

  // One tap instead of copy, open GitHub, paste, commit. The key lives in the
  // Worker, never on this page.
  var SAVE_URL = "{CORRECTIONS_SAVE_URL}";
  var changed = {{}};

  function saveFix() {{
    if (!editing || !Object.keys(changed).length) return;
    var btn = document.getElementById('savebtn');
    var said = document.getElementById('saidwhat');
    btn.disabled = true;
    btn.textContent = 'Saving...';
    fetch(SAVE_URL, {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ company: editing.company, fields: changed }})
    }})
      .then(function (r) {{ return r.json().catch(function () {{ return {{}}; }}); }})
      .then(function (out) {{
        if (out && out.ok) {{
          btn.textContent = 'Saved';
          said.textContent = 'Saved: ' + (out.fields || []).join(', ')
            + '. The page shows it after tomorrow morning\\u2019s run.';
        }} else {{
          btn.disabled = false;
          btn.textContent = 'Save failed, try again';
          said.textContent = 'Could not save'
            + (out && out.error ? ': ' + out.error : '')
            + '. Use the fallback below and nothing is lost.';
          var fb = document.querySelector('.fallback');
          if (fb) fb.open = true;
        }}
      }})
      .catch(function (err) {{
        btn.disabled = false;
        btn.textContent = 'Save failed, try again';
        said.textContent = 'Could not reach the saver (' + err + '). Use the '
          + 'fallback below and nothing is lost.';
        var fb = document.querySelector('.fallback');
        if (fb) fb.open = true;
      }});
  }}

  function copyFile() {{
    var out = document.getElementById('out');
    out.select();
    if (navigator.clipboard) {{
      navigator.clipboard.writeText(out.value);
    }} else {{
      document.execCommand('copy');
    }}
    var btn = document.getElementById('copybtn');
    var said = btn.textContent;
    btn.textContent = 'Copied';
    setTimeout(function () {{ btn.textContent = said; }}, 1500);
  }}

  function isAdded(seen, mode) {{
    if (!mode) return true;
    if (!seen) return false;
    if (mode === 'new') return seen === NEWEST;
    if (mode === 'week') return seen >= WEEK_AGO;
    if (mode === 'month') return seen >= MONTH_AGO;
    return true;
  }}

  function filter(reset) {{
    if (reset !== false) shown_upto = PAGE;
    var q = val('q').toLowerCase();
    var sector = val('sector'), stage = val('stage'), hq = val('hq');
    var from = val('from'), to = val('to'), added = val('added');
    var rows = document.querySelectorAll('#rows tr');
    var shown = 0, total = 0;
    for (var i = 0; i < rows.length; i++) {{
      var row = rows[i];
      var date = row.getAttribute('data-date') || '';
      var ok = row.innerText.toLowerCase().indexOf(q) > -1
        && (!sector || row.getAttribute('data-sector') === sector)
        && (!stage || row.getAttribute('data-stage') === stage)
        && (!hq || row.getAttribute('data-hq') === hq)
        && (!from || (date && date >= from))
        && (!to || (date && date <= to))
        && isAdded(row.getAttribute('data-added') || '', added);
      if (ok) {{
        shown++;
        total += parseInt(row.getAttribute('data-chf') || '0', 10);
      }}
      // Matching decides whether a round counts; paging decides whether it is
      // on screen yet. The count and the total always describe every match.
      row.style.display = (ok && shown <= shown_upto) ? '' : 'none';
    }}
    var more = document.getElementById('more');
    if (more) {{
      var left = shown - shown_upto;
      more.hidden = left <= 0;
      more.textContent = 'Show ' + Math.min(left, PAGE) + ' more of ' + shown;
    }}
    var box = document.getElementById('count');
    if (box) {{
      box.innerHTML = shown + ' round' + (shown === 1 ? '' : 's')
        + (total ? ' &middot; ' + (total >= 1e9 ? (total / 1e9).toFixed(1) + 'B'
                                                : Math.round(total / 1e6) + 'M') + ' CHF' : '');
    }}
  }}

  // Phone only: the filter block starts folded so the data is on screen.
  function toggleFilters() {{
    var bits=document.getElementById('filterbits');
    var btn=document.getElementById('togglefilters');
    var open=bits.hasAttribute('hidden');
    if (open) bits.removeAttribute('hidden'); else bits.setAttribute('hidden','');
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    btn.textContent = open ? 'Hide filters' : 'Filters';
  }}

  if (window.matchMedia('(max-width: 760px)').matches) {{
    document.getElementById('filterbits').setAttribute('hidden','');
  }}

  function showMore() {{
    shown_upto += PAGE;
    filter(false);
    return false;
  }}

  function clearAll() {{
    ['q', 'added', 'sector', 'stage', 'hq', 'from', 'to'].forEach(function (id) {{
      document.getElementById(id).value = '';
    }});
    filter();
  }}

  // Sorting keeps whatever is filtered: the two are independent.
  var sortState = {{ column: -1, descending: true }};
  function sortBy(index, kind) {{
    var body = document.getElementById('rows');
    var rows = Array.prototype.slice.call(body.querySelectorAll('tr'));
    sortState.descending = sortState.column === index ? !sortState.descending : true;
    sortState.column = index;
    var sign = sortState.descending ? -1 : 1;
    rows.sort(function (a, b) {{
      var x, y;
      if (kind === 'chf') {{
        x = parseInt(a.getAttribute('data-chf') || '0', 10);
        y = parseInt(b.getAttribute('data-chf') || '0', 10);
      }} else if (kind === 'date') {{
        x = a.getAttribute('data-date') || '';
        y = b.getAttribute('data-date') || '';
      }} else {{
        x = (a.cells[index].innerText || '').trim().toLowerCase();
        y = (b.cells[index].innerText || '').trim().toLowerCase();
        // An empty cell belongs at the bottom whichever way the sort runs.
        if (x === '\\u00b7') x = sign > 0 ? '\\uffff' : '';
        if (y === '\\u00b7') y = sign > 0 ? '\\uffff' : '';
      }}
      return x < y ? -sign : x > y ? sign : 0;
    }});
    rows.forEach(function (row) {{ body.appendChild(row); }});
    filter(false);
    var heads = document.querySelectorAll('thead th');
    for (var i = 0; i < heads.length; i++) {{
      heads[i].classList.remove('up', 'down');
    }}
    heads[index].classList.add(sortState.descending ? 'down' : 'up');
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
    ap.add_argument("--posts", type=int, default=15,
                    help="Length of the shortlist to draft (default 15). Not a "
                         "rota: nothing is assigned a day, Max picks from it.")
    ap.add_argument("--max-per-source", type=int, default=5,
                    help="Max drafts from any single outlet, for variety "
                         "(default 5)")
    ap.add_argument("--max-per-domain", type=int, default=5,
                    help="Max drafts linking to any one site, counted on the "
                         "link the draft carries (default 5)")
    ap.add_argument("--max-per-domain-hard", type=int, default=8,
                    help="What one site may reach when the shortlist would "
                         "otherwise be short (default 8). Startupticker writes "
                         "about two thirds of Swiss DeepTech news, so a list of "
                         "fifteen is not reachable on five links from it. The "
                         "soft cap still governs any run that can fill itself "
                         "without borrowing.")
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
    ap.add_argument("--skip-if-week-planned", action="store_true",
                    help="Do nothing when the plan on disk still has posts "
                         "dated today or later. The weekly schedule uses this "
                         "so a run cannot overwrite a week being posted.")
    ap.add_argument("--posts-only", action="store_true",
                    help="Only write the posts: do not read articles in full and "
                         "do not touch the archive.")
    ap.add_argument("--reread", action="store_true",
                    help="Read every story again, even ones the database has "
                         "already read. Use after changing how articles are read.")
    ap.add_argument("--backfill-months", type=int, default=0,
                    help="Also search the news archive month by month, this many "
                         "months back. Feeds carry only recent items, so this is "
                         "the only way to build history. Use with --archive-only.")
    args = ap.parse_args()
    if args.archive_only and args.posts_only:
        sys.exit("Pick one of --archive-only and --posts-only, not both.")

    # A weekly run that lands while the last week is still going does more harm
    # than nothing: it writes over a plan already being posted, and it marks
    # five fresh stories as used, so they can never be posted at all. The
    # schedule passes this flag; running it by hand never does.
    if args.skip_if_week_planned and week_still_running(args.outdir):
        sys.exit(0)

    print(f"Fetching Swiss DeepTech news (last {args.days} days)...", file=sys.stderr)
    articles = collect(args.days, args.min_score, args.backfill_months,
                       keep_all_coverage=args.archive_only)[: args.limit]

    # Anything Max supplied himself. Added after the cut, so a submission is
    # never the row that the limit drops.
    if not args.posts_only:
        import submissions
        articles += submissions.url_articles()
    print(f"Kept {len(articles)} relevant stories.", file=sys.stderr)

    import os
    os.makedirs(args.outdir, exist_ok=True)
    stamp = dt.date.today().isoformat()

    if args.format in ("digest", "both"):
        md_path = os.path.join(args.outdir, f"digest-{stamp}.md")
        html_path = os.path.join(args.outdir, f"digest-{stamp}.html")
        # The archive keeps every write-up of a round on purpose, because each
        # outlet knows something the others left out. A reading page does not:
        # the same story three times is not three stories.
        listing = deduplicate(list(articles)) if args.archive_only else articles
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(to_markdown(listing, args.days))
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(to_html(listing, args.days))
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
        from linkedin import (build_posts, for_cowork, render_markdown,
                              render_plan_html, COWORK_PROMPT)

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
        # enrich_articles goes looking for the company's own announcement, so
        # it needs to know which company. The headline names it in almost every
        # funding story, which is enough to find a newsroom.
        from extract import _company_from_headline
        for art in unused:
            if not art.get("company"):
                art["company"] = _company_from_headline(art.get("title", ""))

        print("Finding the image and primary source for each post...", file=sys.stderr)
        pool = diversify(unused, args.max_per_source)
        picks, cursor, dropped, paywalled, capped = [], 0, 0, 0, 0
        foreign = 0
        # Counted on the link the post will actually carry, after the swap to
        # the company's own announcement. The publisher field spells the same
        # outlet several ways, which is how four Startupticker links survived a
        # cap of two.
        from urllib.parse import urlsplit

        per_domain, overflow = {}, []
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
                if not plausibly_swiss(art):
                    foreign += 1
                    print(f"  not Swiss, skipped: "
                          f"{(art.get('title') or '')[:70]}", file=sys.stderr)
                    continue
                host = urlsplit(art.get("link", "")).netloc.lower()
                host = host[4:] if host.startswith("www.") else host
                if host and per_domain.get(host, 0) >= args.max_per_domain:
                    capped += 1
                    overflow.append((host, art))
                    continue
                per_domain[host] = per_domain.get(host, 0) + 1
                picks.append(art)

        # A short list is worse than one more link from a busy outlet. Only
        # what the list is actually missing is taken back, and never past the
        # hard limit.
        borrowed = 0
        for host, art in overflow:
            if len(picks) >= args.posts:
                break
            if per_domain.get(host, 0) >= args.max_per_domain_hard:
                continue
            per_domain[host] = per_domain.get(host, 0) + 1
            picks.append(art)
            borrowed += 1
        if borrowed:
            print(
                f"The shortlist was {borrowed} "
                f"{'stories' if borrowed > 1 else 'story'} short, so "
                f"{borrowed} went to a site already at "
                f"{args.max_per_domain}, up to {args.max_per_domain_hard}.",
                file=sys.stderr,
            )
        if capped:
            print(
                f"Skipped {capped} stories that would have put more than "
                f"{args.max_per_domain} posts on one site.",
                file=sys.stderr,
            )
        busiest = sorted(per_domain.items(), key=lambda kv: -kv[1])[:3]
        if busiest:
            print("  links by site: "
                  + ", ".join(f"{h} {n}" for h, n in busiest), file=sys.stderr)
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
        if foreign:
            print(
                f"Dropped {foreign} stories about companies that are not "
                f"Swiss.",
                file=sys.stderr,
            )
        if not picks:
            # A week with nothing in it is a broken run, not a quiet one: the
            # feeds carry Swiss DeepTech news every week. Failing here leaves
            # the published plan alone and raises the alarm, where writing an
            # empty file would wipe the page and look like silence.
            sys.exit(
                "Nothing to shortlist. Something upstream is wrong: the feeds "
                "returned nothing usable, or a filter is rejecting everything. "
                "The published plan is untouched. Check the log above for what "
                "was dropped and why."
            )
        if len(picks) < args.posts:
            print(
                f"Only {len(picks)} unused stories available for a shortlist "
                f"of {args.posts}"
                + (f", after skipping {capped} that would have exceeded "
                   f"{args.max_per_domain} links on one site" if capped else "")
                + ". The window stands: a short list means the news was thin, "
                  "not that the tool failed.",
                file=sys.stderr,
            )
        print(
            f"Shortlisted {len(picks)} stories across "
            f"{len({p['publisher'] for p in picks})} outlets "
            f"(max {args.max_per_source} each).",
            file=sys.stderr,
        )

        # What happened, in one word, so a list of fifteen can be read at a
        # glance: a round, a discovery and a grant do not look alike on the page
        # any more. Same labels as the news page.
        for art in picks:
            art["kind"] = _kind(art)
        seen_kinds = {}
        for art in picks:
            seen_kinds[art["kind"]] = seen_kinds.get(art["kind"], 0) + 1
        print("  shortlist: "
              + ", ".join(f"{k} {n}" for k, n in
                          sorted(seen_kinds.items(), key=lambda kv: -kv[1])),
              file=sys.stderr)

        # No outlet spacing any more. It existed so that three Startupticker
        # links did not land on three consecutive days; a shortlist ordered by
        # publication date has no days to land on, and reordering it by outlet
        # would fight the ordering Max asked for.

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
            # Only the fields a scheduling session uses. The rest of each
            # record belongs to the plan Max reads, and a browser session that
            # reads it is paying to skip it.
            "posts": for_cowork(records),
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

    # What the database already holds, loaded before any work, so a story it
    # has already read is not read again.
    #
    # The unit of "already done" is the article, never the round. A new piece
    # about a round we have is a new article, so it is always read, and what it
    # adds is merged into that round: the write-up that finally names the
    # investors completes the row rather than being skipped as old news. Only
    # the identical article, at the same address, is passed over.
    known = archive_mod.load(args.archive)
    if args.reread:
        fresh = list(articles)
        print("Re-reading every story, ignoring what the database holds.",
              file=sys.stderr)
    else:
        fresh = []
        for art in articles:
            entry = known.get(archive_mod._key(art.get("link", "")))
            if entry and entry.get("read"):
                # Carry the stored facts so this run still sees the round.
                for field, value in entry.items():
                    if field not in ("key", "runs", "first_seen", "last_seen"):
                        art.setdefault(field, value)
            else:
                fresh.append(art)
        if len(fresh) < len(articles):
            print(f"{len(articles) - len(fresh)} of {len(articles)} stories "
                  f"were read in an earlier run; reading the {len(fresh)} new ones.",
                  file=sys.stderr)

    # Only the seven picked posts had their Google News redirect resolved, so
    # every other story went into the archive as a news.google.com link. Asking
    # that URL for the article text returns Google's own redirect page, which
    # holds no facts, so those rows were extracted from the feed summary alone.
    # Resolve them all before reading.
    from google_news import is_google_news_url, resolve_url
    redirects = [a for a in fresh if is_google_news_url(a.get("link", ""))]
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
    print(f"Fetching {len(fresh)} articles in full...", file=sys.stderr)
    got = 0
    for art in fresh:
        art["fulltext"] = article_text(art.get("link", ""), limit=6000)
        if art["fulltext"]:
            got += 1
    print(f"  read {got}/{len(fresh)} in full", file=sys.stderr)

    # Some publishers refuse us outright, and those stories reached the archive
    # with nothing but a headline: two rounds sat there nameless because The
    # Quantum Insider and EU-Startups would not serve the page. The company is
    # usually named in the headline even so, and its own site will say the rest.
    from extract import _company_from_headline
    from hq_lookup import company_pages

    blocked = [a for a in fresh
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

    if fresh:
        print("Reading deal facts from each new story...", file=sys.stderr)
        for art, facts in zip(fresh, extract_fields(fresh)):
            art.update(facts)
            # Read once, and recorded as read, so tomorrow's run passes over it.
            art["read"] = True
        named = sum(1 for a in fresh if a.get("company"))
        print(f"  identified a company in {named}/{len(fresh)} stories",
              file=sys.stderr)

    # The lookups below are about the company rather than the article, and each
    # costs several page fetches, so they run only where the round still has a
    # gap they could fill. A round that is already complete is left alone; one
    # that a new write-up has just changed is looked at again, because the new
    # facts may be exactly what makes the rest findable.
    wanted = ("investors", "founders", "founded", "location", "website")
    incomplete = [a for a in articles
                  if _is_round(a) and any(not a.get(f) for f in wanted)]
    if incomplete:
        from extract import fill_from_company_sites
        fill_from_company_sites(incomplete)

        # The commercial register is authoritative for the registered seat.
        from registries import fill_from_registries
        fill_from_registries(incomplete)

    # Anything still without a location gets the address lookup.
    from hq_lookup import fill_missing
    blanks = sum(1 for a in articles if a.get("company") and not a.get("location"))
    if blanks:
        print(f"Looking up {blanks} missing headquarters...", file=sys.stderr)
        print(f"  found {fill_missing(articles)} of them", file=sys.stderr)

    # Rounds written out by hand, from a report or a dataset. They join the
    # others before the merge, so one already in the database gains the new
    # facts rather than appearing twice.
    import submissions
    articles = articles + submissions.rows()

    # Scrub before anything is stored, and again over the whole database, since
    # a value that reached it before this check will otherwise sit there for
    # good: the archive never replaces something with a blank on its own.
    from extract import clean_record
    for art in articles:
        clean_record(art)

    # The database links to Startupticker where there is a Startupticker piece.
    # Merging already prefers it among the write-ups collected; this looks for
    # the one that was never collected, once per round, and keeps it.
    from google_news import find_on

    rounds_now = [a for a in articles if _is_round(a)]
    missing = [a for a in rounds_now
               if a.get("company") and not a.get("startupticker_url")
               and "startupticker" not in (a.get("link") or "")]
    if missing:
        print(f"Looking for a Startupticker piece on {len(missing)} rounds...",
              file=sys.stderr)
        found = 0
        for art in missing:
            url = find_on("startupticker.ch", art["company"])
            if url:
                art["startupticker_url"] = url
                found += 1
        print(f"  found {found}/{len(missing)}", file=sys.stderr)

    # Anything Max ticked on the review page moves across first, so a
    # correction accepted this morning applies to this morning's run.
    import corrections
    import proposals as proposals_mod
    proposals_mod.promote(corrections.PATH)

    # Max's corrections go on last, over everything the lookups produced.
    corrections.apply(articles)

    before = len(known)
    known = archive_mod.record(known, articles, picks)
    # Again over the whole database, not just this run's stories. A correction
    # has to reach rows recorded weeks ago, and clearing a wrong value has to
    # work at all: the archive never replaces something with a blank on its own.
    stored = list(known.values())
    for entry in stored:
        clean_record(entry)
    corrections.apply(stored)
    archive_mod.save(args.archive, known)
    print(
        f"Archive: {len(known)} stories total ({len(known) - before} new "
        f"this run) in {args.archive}",
        file=sys.stderr,
    )
    _report_coverage(known)
    with open(os.path.join(args.outdir, "archive.html"), "w", encoding="utf-8") as f:
        f.write(render_archive_html(known))
    # What the database left out for a foreign headquarters, with the same
    # editing panel: a seat abroad is a judgement call, so it is reviewable
    # rather than invisible.
    with open(os.path.join(args.outdir, "held.html"), "w", encoding="utf-8") as f:
        f.write(render_archive_html(known, only="held"))
    # Everything Swiss, not only the financings: grants, research, launches.
    with open(os.path.join(args.outdir, "news.html"), "w", encoding="utf-8") as f:
        f.write(render_news_html(known))

    # A month's rounds are worth a page of their own: the table says what
    # happened, the report says what it amounts to.
    import report
    swiss_rounds = [r for r in merge_deals(
        [s for s in known.values() if _is_round(s)]) if _is_swiss(r)]
    report.write_all(swiss_rounds, os.path.join(args.outdir, "reports"))

    # What the scraper cannot check itself. Cowork reads the primary sources
    # and reports back as corrections, which win over everything.
    import verify
    verify.write(swiss_rounds, os.path.join(args.outdir, "verify.json"))

    # Anything the weekly check proposes, laid out to be read and accepted or
    # refused. It is not in the database and does not become so on its own.
    import corrections as corrections_mod
    import proposals
    proposals.write_page(os.path.join(args.outdir, "review.html"),
                         corrections_mod.load())


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
