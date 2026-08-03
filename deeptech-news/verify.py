"""The rounds worth checking against a primary source, and why.

The scraper is good at finding rounds and bad at verifying them. It reads what
publishers put in a feed, cannot get past a paywall, and takes a headline at
its word. Every error found so far came from reading the primary source: a
de-SPAC ceiling recorded as raised capital, a follow-on by a listed company
recorded as an IPO, a round still being assembled recorded as closed.

Cowork can read those sources. So this writes the queue rather than guessing:
the rounds where an error would move the numbers, in the places errors have
actually been, with the claim as recorded and what to check about it. What
comes back goes into corrections.json, which wins over everything and is
applied to the whole database on every run.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys

import money

# Where a mistake moves the totals. Below this a wrong figure is noise.
MATERIAL_CHF = 10_000_000

# The end of the lifecycle where the labels have been wrong: a price is not
# capital, a follow-on is not a flotation, a ceiling is not proceeds.
_EXIT_OR_PUBLIC = {"IPO", "Follow-on", "De-SPAC", "Acquisition"}

# Outlets we cannot read, so the row rests on a headline alone.
PAYWALLED = (
    "bloomberg.com", "ft.com", "wsj.com", "nzz.ch", "handelszeitung.ch",
    "finanzundwirtschaft.ch", "letemps.ch", "sifted.eu", "theinformation.com",
    "economist.com", "reuters.com/business",
)

# How long a check holds before it is worth repeating.
FRESH_DAYS = 180


def _stale(verified: str, today: dt.date) -> bool:
    try:
        when = dt.date.fromisoformat((verified or "").strip()[:10])
    except Exception:
        return True
    return (today - when).days > FRESH_DAYS


def reasons(story: dict, today: dt.date) -> list:
    """Why this round is worth a look. Empty means it is not."""
    from scraper import is_closed, _investor_line

    out = []
    if not is_closed(story):
        out.append("recorded as announced rather than closed: has it closed "
                   "since, and on what terms")
    if (story.get("stage") or "") in _EXIT_OR_PUBLIC:
        out.append("an exit or a public market transaction, where the label "
                   "and the figure mean different things")
    if money.in_chf(story.get("amount", "")) >= MATERIAL_CHF:
        out.append(f"{money.compact(money.in_chf(story.get('amount','')))} is "
                   f"large enough that an error moves the totals")
    link = (story.get("link") or "").lower()
    if any(p in link for p in PAYWALLED):
        out.append("the only source is behind a paywall, so this rests on a "
                   "headline")
    if (story.get("amount_note") or "").strip():
        out.append(f"the figure carries a condition "
                   f"({story['amount_note']}): is it the amount actually "
                   f"raised")
    if (story.get("stage") or "").strip() and not _investor_line(story) \
            and money.in_chf(story.get("amount", "")) >= MATERIAL_CHF:
        out.append("a round this size with no investor named is usually a "
                   "reading failure rather than an undisclosed syndicate")
    return out


def build(rounds: list, today: dt.date | None = None) -> dict:
    """The queue, newest and largest first."""
    from scraper import _investor_line

    today = today or dt.date.today()
    queue = []
    for story in rounds:
        why = reasons(story, today)
        if not why:
            continue
        if (story.get("verified") or "").strip() and not _stale(
                story.get("verified", ""), today):
            # Checked recently, and nothing about it has changed since.
            if "recorded as announced" not in " ".join(why):
                continue
        queue.append({
            "company": story.get("company", ""),
            "as_recorded": {
                "stage": story.get("stage", ""),
                "amount": story.get("amount", ""),
                "amount_note": story.get("amount_note", ""),
                "status": story.get("status") or "closed",
                "investors": _investor_line(story),
                "date": story.get("published") or story.get("first_seen", ""),
                "hq": story.get("location", ""),
            },
            "check": why,
            "sources": story.get("sources", []),
            "link": story.get("link", ""),
            "last_verified": story.get("verified", ""),
        })
    queue.sort(key=lambda q: (money.in_chf(q["as_recorded"]["amount"]),
                              q["as_recorded"]["date"]), reverse=True)
    return {
        "generated": today.isoformat(),
        "note": "Rounds worth checking against a primary source.",
        "how_to_report": HOW_TO_REPORT,
        "corrections_file": "deeptech-news/corrections.json",
        "count": len(queue),
        "rounds": queue,
    }


HOW_TO_REPORT = (
    "For each round below, find the primary source: the company's own release, "
    "the filing, or the outlet that reported it first. Check the four things "
    "that have actually been wrong. Has the transaction closed, or is it "
    "announced, in progress, or subject to approval? Is the label right, where "
    "a first listing is an IPO, an already listed company selling shares is a "
    "Follow-on, a merger with a listed shell is a De-SPAC, and a purchase is "
    "an Acquisition rather than a round? Is the figure money received, or a "
    "ceiling, a gross, or a target? And did the named investors take part in "
    "THIS round, rather than an earlier one?\n\n"
    "Report back as entries for corrections.json, keyed on the company name, "
    "setting only the fields that are wrong. Add \"verified\" with today's "
    "date and \"verified_source\" naming what you read. An empty string clears "
    "a wrong value. For example:\n\n"
    "  \"Prem\": {\n"
    "    \"status\": \"announced\",\n"
    "    \"amount_note\": \"raising, expected to close in Q3\",\n"
    "    \"investors\": \"\",\n"
    "    \"verified\": \"2026-08-03\",\n"
    "    \"verified_source\": \"Bloomberg, 18 June 2026\"\n"
    "  }\n\n"
    "Where a round checks out, still send back \"verified\" and "
    "\"verified_source\" so it is not queued again. Say plainly when a primary "
    "source cannot be found: an unverifiable round should stay unverified "
    "rather than be marked correct."
)


def write(rounds: list, path: str) -> int:
    """Write the queue. Returns how many rounds need checking."""
    payload = build(rounds)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"{payload['count']} rounds queued for checking in {path}",
          file=sys.stderr)
    return payload["count"]
