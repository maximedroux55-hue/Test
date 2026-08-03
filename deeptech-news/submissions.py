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
    for entry in entries:
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
        print(f"Adding {len(out)} rounds from submissions/rows.json",
              file=sys.stderr)
    return out
