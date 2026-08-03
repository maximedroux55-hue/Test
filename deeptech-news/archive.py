"""An append-only record of every story the tool has ever seen.

The digest files are rewritten on each run, so until now only the seven posted
stories survived and the rest were lost. This keeps them all: what was found,
when, how it scored, and whether it became a post.

Stored at digest/archive.json and committed with the digest, so it builds up
week after week into a record of Swiss DeepTech news rather than a snapshot.

Entries are keyed on the story's link, so re-running the same day updates a
story in place instead of duplicating it. A story first seen in July and
covered again in August keeps its original first_seen date and gains the later
run in `runs`.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import urllib.parse

# Plenty for years of weekly runs, while keeping the file quick to load.
MAX_ENTRIES = 20000


def _key(url: str) -> str:
    """Canonical form of a link, so the same story is one entry."""
    try:
        p = urllib.parse.urlsplit(url or "")
    except Exception:
        return (url or "").strip().lower()
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return f"{host}{p.path.rstrip('/')}".lower()


def load(path: str) -> dict:
    """Return {key: entry} for everything seen so far."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {e["key"]: e for e in data.get("stories", []) if e.get("key")}
    except Exception:
        return {}


def record(
    known: dict,
    found: list,
    posted: list,
    today: dt.date | None = None,
) -> dict:
    """Add or update this run's stories. `found` is everything, `posted` the picks."""
    stamp = (today or dt.date.today()).isoformat()
    posted_keys = {_key(a.get("link", "")) for a in posted}
    # A posted story may have had its link swapped to the company announcement,
    # so match on where it was found as well.
    posted_keys |= {_key(a["coverage_url"]) for a in posted if a.get("coverage_url")}

    for art in found:
        link = art.get("link", "")
        key = _key(link)
        if not key:
            continue
        date = art.get("date")
        entry = known.get(key) or {
            "key": key,
            "first_seen": stamp,
            "runs": [],
        }
        entry.update({
            "title": art.get("title", ""),
            "link": link,
            "publisher": art.get("publisher", ""),
            "published": date.date().isoformat() if hasattr(date, "date") else None,
            "score": art.get("score"),
            "last_seen": stamp,
            "posted": entry.get("posted", False) or key in posted_keys,
        })
        # Deal facts read out of the article, see extract.py. Only overwrite
        # with something, so a later thinner mention cannot blank a good value.
        for field in (
            "company", "description", "category", "stage", "amount",
            "total_raised", "valuation", "lead_investor", "investors",
            "founders", "spinoff_origin", "founded", "employees",
            "use_of_funds", "customers", "website", "location", "legal_seat",
        ):
            value = art.get(field, "")
            if value or not entry.get(field):
                entry[field] = value
        if stamp not in entry["runs"]:
            entry["runs"].append(stamp)
        known[key] = entry

    if len(known) > MAX_ENTRIES:
        # Drop the oldest first, keeping anything that was actually posted.
        ordered = sorted(
            known.values(),
            key=lambda e: (e.get("posted", False), e.get("last_seen", "")),
        )
        for entry in ordered[: len(known) - MAX_ENTRIES]:
            known.pop(entry["key"], None)
    return known


def save(path: str, known: dict) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    stories = sorted(
        known.values(),
        key=lambda e: (e.get("last_seen", ""), e.get("score") or 0),
        reverse=True,
    )
    posted = sum(1 for e in stories if e.get("posted"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "note": "Every story this tool has seen. Appended to on each run.",
                "total": len(stories),
                "posted": posted,
                "stories": stories,
            },
            f, ensure_ascii=False, indent=2,
        )
