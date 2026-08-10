"""Remember which stories have already been turned into posts.

Without this, a story covered again next week (or simply still sitting in the
feeds) could be posted a second time. Every run records the stories it used in
digest/history.json, which is committed to the repo, so the memory survives
between runs.

Two rules, deliberately different in reach:

  * The exact same article URL is never reused, however long ago it appeared.
  * A story that merely looks like an earlier one (same headline wording, or
    the same rare name such as a company) is blocked for HISTORY_DAYS. After
    that the company is fair game again, because a genuinely new round from the
    same company is real news, not a duplicate.

Re-running on the same day is not treated as a duplicate: entries recorded
today are ignored when filtering, so tapping "Generate now" twice rebuilds the
same week's plan instead of emptying it.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import urllib.parse

from relevance import _keywords, _normalize, _same_story

# How long a look-alike story stays blocked. Exact URLs are blocked forever.
HISTORY_DAYS = 180
# Cap the file so it cannot grow without bound.
MAX_ENTRIES = 1000


def _canonical(url: str) -> str:
    """A stable form of a URL for comparison: no query, fragment or trailing slash."""
    try:
        p = urllib.parse.urlsplit(url or "")
    except Exception:
        return (url or "").strip().lower()
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = p.path.rstrip("/")
    return f"{host}{path}".lower()


def load(path: str) -> list:
    """Return past entries, or an empty list when there is no history yet."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("used", [])
    except Exception:
        return []


def _as_story(entry: dict) -> dict:
    """Shape a history entry so it can be compared with a fresh article."""
    return {
        "_norm": entry.get("norm", ""),
        "_kw": set(entry.get("kw", [])),
        "_rare": set(entry.get("rare", [])),
        # Entries written before the looser band existed fall back to the
        # strict one, which can only under-match, never merge two companies.
        "_uncommon": set(entry.get("uncommon") or entry.get("rare", [])),
    }


def filter_seen(articles: list, history: list, today: dt.date | None = None) -> list:
    """Drop articles that an earlier run already used."""
    today = today or dt.date.today()
    cutoff = (today - dt.timedelta(days=HISTORY_DAYS)).isoformat()
    today_str = today.isoformat()

    seen_urls = set()
    lookalikes = []
    for entry in history:
        used = entry.get("used", "")
        # Today's own entries are this week's plan being rebuilt, not history.
        if used == today_str:
            continue
        for key in ("link", "coverage_url"):
            if entry.get(key):
                seen_urls.add(_canonical(entry[key]))
        if used >= cutoff:
            lookalikes.append(_as_story(entry))

    fresh = []
    for art in articles:
        urls = {_canonical(art.get(k, "")) for k in ("link", "coverage_url") if art.get(k)}
        if urls & seen_urls:
            continue
        probe = {
            "_norm": art.get("_norm") or _normalize(art.get("title", "")),
            "_kw": art.get("_kw") or _keywords(art.get("title", "")),
            "_rare": art.get("_rare") or set(),
            "_uncommon": art.get("_uncommon") or set(),
        }
        if any(_same_story(probe, old) for old in lookalikes):
            continue
        fresh.append(art)
    return fresh


def record(history: list, articles: list, today: dt.date | None = None) -> list:
    """Add the stories just used, replacing any entry already made today."""
    today_str = (today or dt.date.today()).isoformat()
    kept = [e for e in history if e.get("used") != today_str]
    for art in articles:
        kept.append({
            "used": today_str,
            "title": art.get("title", ""),
            "link": art.get("link", ""),
            "coverage_url": art.get("coverage_url"),
            "norm": art.get("_norm") or _normalize(art.get("title", "")),
            "kw": sorted(art.get("_kw") or _keywords(art.get("title", ""))),
            "rare": sorted(art.get("_rare") or set()),
            "uncommon": sorted(art.get("_uncommon") or set()),
        })
    return kept[-MAX_ENTRIES:]


def save(path: str, history: list) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {"note": "Stories already posted. Prevents repeats between runs.",
             "used": history},
            f, ensure_ascii=False, indent=2,
        )
