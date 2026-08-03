"""What has actually been checked, as opposed to merely reported.

A figure read out of a press write-up and a figure checked against a filing are
not the same claim, and until now the tool presented them identically. Five
errors this session were figures or labels that a primary source contradicted:
a ceiling counted as proceeds, a follow-on called a flotation, a round still
being assembled recorded as closed.

Verification lives in corrections.json, where a round carries the date it was
checked and what was read. This reads that back, so a report can say how much
of its total has been checked and a post can decline to state a figure nobody
has confirmed.
"""

from __future__ import annotations

import datetime as dt

import corrections

# A check holds for this long before the round is worth looking at again.
FRESH_DAYS = 180


def _entries() -> dict:
    """Company stem to what was recorded about it."""
    return corrections.load()


def verification(company: str, today: dt.date | None = None) -> dict:
    """Return {'date', 'source'} for a checked company, or {}."""
    fixes = _entries()
    found = corrections._match(corrections._stem(company or ""), fixes)
    when = (found.get("verified") or "").strip()
    if not when:
        return {}
    try:
        checked = dt.date.fromisoformat(when[:10])
    except ValueError:
        return {}
    if ((today or dt.date.today()) - checked).days > FRESH_DAYS:
        return {}
    return {"date": when, "source": (found.get("verified_source") or "").strip()}


def is_verified(company: str, today: dt.date | None = None) -> bool:
    return bool(verification(company, today))


def stats(rounds: list, today: dt.date | None = None) -> dict:
    """How much of a set of rounds has been checked, by count and by value."""
    import money
    from scraper import is_closed

    counted = [r for r in rounds if is_closed(r)]
    checked = [r for r in counted if is_verified(r.get("company", ""), today)]
    total = sum(money.in_chf(r.get("amount", "")) for r in counted)
    seen = sum(money.in_chf(r.get("amount", "")) for r in checked)
    return {
        "rounds": len(counted),
        "verified_rounds": len(checked),
        "total": total,
        "verified_total": seen,
        "share": round(100 * seen / total) if total else 0,
    }
