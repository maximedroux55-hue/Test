"""Max's corrections, applied last and always winning.

Some facts a scraper will keep getting wrong. A company's registered seat is
not where it works, an article repeats a city the company left years ago, and
no amount of parsing fixes either. When Max says Synhelion is run out of
Zurich, that is the answer, and it should stay the answer through every future
run rather than being quietly overwritten the next morning.

Corrections live in corrections.json next to this file so they can be edited
without touching code. They are keyed on the company name, matched loosely
enough that "SWISSto12" and "Swissto12 SA" are the same company.
"""

from __future__ import annotations

import json
import os
import re
import sys

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corrections.json")


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


# Legal forms sit on the end of a registered name and never on the end of the
# name a journalist uses, so they are dropped before matching.
_SUFFIX = re.compile(r"(ag|sa|sarl|sàrl|gmbh|ltd|inc|bv|nv|holding|group)$")


def _stem(name: str) -> str:
    return _SUFFIX.sub("", _key(name))


def load(path: str = PATH) -> dict:
    """Return {company stem: {field: value}}, or {} when there are none."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}
    entries = raw.get("companies", raw) if isinstance(raw, dict) else {}
    out = {}
    for company, fields in entries.items():
        if isinstance(fields, dict):
            # An empty value is meaningful: it clears a wrong one, which is
            # better than a blank being silently refilled with the same error.
            out[_stem(company)] = {k: v for k, v in fields.items()
                                   if isinstance(v, str)}
    return out


def _match(stem: str, fixes: dict) -> dict:
    """Find the correction for a company name, allowing for how names vary."""
    if stem in fixes:
        return fixes[stem]
    # "Hilo" should still match the story that called it "Hilo (Aktiia)".
    for key, fields in fixes.items():
        if len(key) >= 4 and (stem.startswith(key) or key.startswith(stem)):
            return fields
    return {}


def apply(articles: list, path: str = PATH) -> int:
    """Overwrite fields on any article whose company has a correction."""
    fixes = load(path)
    if not fixes:
        return 0
    changed = 0
    for art in articles:
        wanted = _match(_stem(art.get("company", "")), fixes)
        if not wanted:
            continue
        if any(art.get(k) != v for k, v in wanted.items()):
            changed += 1
        art.update(wanted)
        seen = art.setdefault("provenance", {})
        for field, value in wanted.items():
            if value:
                seen[field] = "Max"
            else:
                seen.pop(field, None)
    if changed:
        print(f"Applied {changed} corrections from corrections.json", file=sys.stderr)
    return changed
