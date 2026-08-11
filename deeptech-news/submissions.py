"""Rounds Max supplies himself, alongside the ones the feeds find.

The scraper only knows what the feeds carry. Plenty does not reach them: a
round covered only in a paywalled piece, an annual report, a PDF from an
investor, something a founder mentions directly. This is the way in.

Two files, both committed, so a submission is re-applied on every run rather
than being a one-off edit somebody later overwrites.

  submissions/urls.txt   one article address per line. Each is fetched and
                         read exactly like a story from a feed, but it skips
                         the relevance scoring and the date window, because it
                         was chosen deliberately rather than found.

  submissions/rows.json  rounds written out directly, for what has no article
                         behind it: a report, a dataset, a conversation. Same
                         field names as the database.

  submissions/*.csv      a Crunchbase funding-rounds export, dropped in as it
                         downloads. Buyouts, debt and crowdfunding are left
                         out; everything else becomes a round. This is how the
                         grants get in: no newsroom writes up an Innosuisse or
                         Venture Kick award, and Crunchbase records them.

Anything submitted goes through the same merge as everything else, so a round
already in the database gains the new facts instead of appearing twice.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "submissions")
URLS = os.path.join(DIR, "urls.txt")
ROWS = os.path.join(DIR, "rows.json")

# Fields a submitted round may set. Anything else is ignored rather than
# stored, so a typo cannot invent a column.
FIELDS = (
    "company", "description", "category", "stage", "amount", "total_raised",
    "valuation", "lead_investor", "investors", "founders", "spinoff_origin",
    "founded", "employees", "use_of_funds", "customers", "website",
    "location", "legal_seat", "published", "link", "title",
)


def _read_lines(path: str) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception:
        return []
    return [l.strip() for l in lines
            if l.strip() and not l.strip().startswith("#")]


def url_articles(path: str = URLS) -> list:
    """Fetch each submitted address and shape it like a story from a feed."""
    from images import article_page

    urls = [u for u in _read_lines(path) if u.startswith("http")]
    if not urls:
        return []
    print(f"Reading {len(urls)} submitted articles...", file=sys.stderr)

    out = []
    for url in urls:
        html_doc, final_url = article_page(url)
        title = ""
        if html_doc:
            m = re.search(r"<title[^>]*>(.*?)</title>", html_doc,
                          re.IGNORECASE | re.DOTALL)
            if m:
                import html as html_lib
                title = html_lib.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
        if not html_doc:
            print(f"  ! could not fetch {url[:70]}", file=sys.stderr)
        out.append({
            "title": title or url.rsplit("/", 1)[-1].replace("-", " "),
            "link": final_url,
            "publisher": urllib.parse.urlsplit(final_url).netloc.replace("www.", ""),
            "date": None,
            # Above any threshold: it is here because Max put it here.
            "score": 999,
            "summary": "",
            "image_feed": None,
            "submitted": True,
        })
    print(f"  read {sum(1 for a in out if a['title'])}/{len(urls)}", file=sys.stderr)
    return out


# Funding types in a Crunchbase export that are not venture DeepTech news for a
# seed-stage Swiss fund. A packaging group's post-IPO debt and a dental clinic
# roll-up are Swiss transactions, not Climb material, and one month's export
# carried eight of them against twelve real rounds.
_NOT_VENTURE = {
    "post-ipo debt", "post-ipo equity", "private equity", "debt financing",
    "equity crowdfunding", "secondary market",
}

# Crunchbase's funding type, in the database's own vocabulary.
_STAGE = {
    "pre-seed": "Pre-seed", "seed": "Seed",
    "series a": "Series A", "series b": "Series B", "series c": "Series C",
    "series d": "Series D", "grant": "Grant",
    "venture - series unknown": "Venture", "corporate round": "Corporate",
    "funding round": "Venture", "convertible note": "Venture",
}


def _money(amount: str, currency: str) -> str:
    """'25500000', 'USD' -> 'USD 25.5M'. Blank when the export has no figure."""
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""
    cur = (currency or "").strip().upper() or "USD"
    if value >= 1_000_000:
        return f"{cur} {value / 1_000_000:.2f}".rstrip("0").rstrip(".") + "M"
    return f"{cur} {value / 1000:.0f}k"


def csv_rows(directory: str = DIR) -> list:
    """Rounds from a Crunchbase export dropped into submissions/.

    A month of Swiss rounds exported from Crunchbase carried twelve the feeds
    had never found, including a USD 152M Series B announced that morning and a
    USD 30M BARDA grant. No feed carries a grant body's announcement, and
    Crunchbase does, so this is the way in for both.

    Every row goes through the same merge as everything else, so a round already
    known gains the export's facts rather than appearing twice.
    """
    import csv
    import glob

    files = sorted(glob.glob(os.path.join(directory, "*.csv")))
    if not files:
        return []

    out, skipped = [], 0
    for path in files:
        try:
            with open(path, encoding="utf-8-sig", newline="") as f:
                entries = list(csv.DictReader(f))
        except Exception as exc:
            print(f"  ! could not read {os.path.basename(path)}: {exc}",
                  file=sys.stderr)
            continue
        for entry in entries:
            company = (entry.get("Organization Name") or "").strip()
            kind = (entry.get("Funding Type") or "").strip()
            if not company:
                continue
            if kind.lower() in _NOT_VENTURE:
                skipped += 1
                continue
            amount = _money(entry.get("Money Raised"),
                            entry.get("Money Raised Currency"))
            row = {
                "company": company,
                "stage": _STAGE.get(kind.lower(), kind or "Venture"),
                "amount": amount,
                "total_raised": _money(entry.get("Total Funding Amount"),
                                       entry.get("Total Funding Amount Currency")),
                "lead_investor": (entry.get("Lead Investors") or "").strip(),
                # The industry list runs to nine entries on some rows, which is
                # a paragraph, not a category.
                "category": ", ".join(
                    p.strip() for p in
                    (entry.get("Organization Industries") or "").split(",")[:2]
                    if p.strip()),
                "location": ", ".join(
                    p.strip() for p in
                    (entry.get("Organization Location") or "").split(",")[:2]
                    if p.strip()),
                "website": (entry.get("Organization Website") or "").strip(),
                "published": (entry.get("Announced Date") or "").strip(),
                "link": (entry.get("Transaction Name URL") or "").strip(),
                "title": f"{company} raises {amount}" if amount
                         else f"{company} raises an undisclosed round",
                "source": "Crunchbase export",
                # Sorted by USD so the same round under two names can be found.
                "_usd": (entry.get("Money Raised (in USD)") or "").strip(),
            }
            out.append(row)

    out = _one_round_per_deal(out)
    if out or skipped:
        print(f"Read {len(out)} rounds from {len(files)} Crunchbase export"
              f"{'s' if len(files) > 1 else ''}"
              + (f", skipping {skipped} buyouts, debt and crowdfunding"
                 if skipped else ""),
              file=sys.stderr)
    return out


def _one_round_per_deal(entries: list) -> list:
    """Collapse the same round filed under two company names.

    The export carried "Hilo" and "Hilo by Aktiia" as separate rounds, both
    USD 19M Series B in Neuchâtel, a day apart. Crunchbase holds the company
    under both names and reports the round twice. Same money, and one name
    contains the other, so it is one deal.
    """
    kept = []
    for entry in sorted(entries, key=lambda e: len(e["company"])):
        short = re.sub(r"[^a-z0-9]", "", entry["company"].lower())
        twin = next(
            (k for k in kept
             if entry["_usd"] and k["_usd"] == entry["_usd"]
             and (short in re.sub(r"[^a-z0-9]", "", k["company"].lower())
                  or re.sub(r"[^a-z0-9]", "", k["company"].lower()) in short)),
            None)
        if twin:
            # Keep whichever row says more, since the duplicate is rarely equal.
            for field, value in entry.items():
                if value and not twin.get(field):
                    twin[field] = value
            continue
        kept.append(entry)
    for entry in kept:
        entry.pop("_usd", None)
    return kept


def rows(path: str = ROWS) -> list:
    """Rounds written out by hand, from a report or a dataset."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    entries = data.get("rounds", data) if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return []

    out = []
    for entry in list(entries) + csv_rows():
        if not isinstance(entry, dict) or not (entry.get("company") or "").strip():
            continue
        row = {k: str(v).strip() for k, v in entry.items()
               if k in FIELDS and v is not None}
        source = (entry.get("source") or "supplied by Max").strip()
        row["publisher"] = source
        row["provenance"] = {k: source for k, v in row.items() if v}
        row.setdefault("title", f"{row['company']} round, {source}")
        # A row keyed on nothing cannot be stored or updated later, so one
        # taken from a report gets a stable key of its own.
        if not row.get("link"):
            stem = re.sub(r"[^a-z0-9]", "", row["company"].lower())
            digits = re.sub(r"[^0-9]", "", row.get("amount", "")) or "0"
            row["link"] = f"supplied:{stem}-{digits}"
        row["submitted"] = True
        out.append(row)
    if out:
        by_hand = sum(1 for r in out if r.get("publisher") != "Crunchbase export")
        print(f"Adding {len(out)} submitted rounds "
              f"({by_hand} written by hand, {len(out) - by_hand} from an export)",
              file=sys.stderr)
    return out
