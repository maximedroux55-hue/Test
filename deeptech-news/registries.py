"""Official and licensed registries, for the facts a news article omits.

Zefix is the Swiss federal commercial register. Its public API is free and
authoritative for a company's registered seat, legal name, legal form and
registration date, which is exactly what a funding write-up leaves out. It
carries nothing about investors or rounds.

Crunchbase covers investors and funding history, but only through its paid API
tier: the consumer subscription gives a website login and no programmatic
access, and scraping it either way breaches the terms. The hook is written and
stays dormant until a CRUNCHBASE_API_KEY is present, so it can be switched on
by adding the secret and nothing else.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request

ZEFIX_SEARCH = "https://www.zefix.admin.ch/ZefixPublicREST/api/v1/firm/search.json"
CRUNCHBASE_SEARCH = "https://api.crunchbase.com/api/v4/searches/organizations"

_UA = "Mozilla/5.0 (compatible; ClimbNewsBot/1.0; +https://climbventures.com)"


def _post_json(url: str, payload: dict, headers: dict, timeout: int = 12):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def zefix_lookup(company: str, timeout: int = 12) -> dict:
    """Return {'location', 'legal_name', 'legal_form', 'founded', 'uid'} or {}.

    Matches on the company name. A name that returns several unrelated firms is
    treated as no match, since a wrong registration is worse than a blank.
    """
    name = (company or "").strip()
    if len(name) < 3:
        return {}
    try:
        data = _post_json(
            ZEFIX_SEARCH,
            {"name": name, "languageKey": "en", "maxEntries": 5, "offset": 0,
             "activeOnly": True},
            {"Content-Type": "application/json", "Accept": "application/json",
             "User-Agent": _UA},
            timeout,
        )
    except Exception:
        return {}

    entries = data if isinstance(data, list) else data.get("list", []) or []
    target = re.sub(r"[^a-z0-9]", "", name.lower())
    for entry in entries:
        registered = entry.get("name", "")
        squashed = re.sub(r"[^a-z0-9]", "", registered.lower())
        # Registered names carry a legal suffix, so match on the stem.
        if not (squashed.startswith(target) or target in squashed):
            continue
        seat = entry.get("legalSeat") or ""
        out = {
            "legal_name": registered,
            "location": seat,
            "legal_form": (entry.get("legalFormId") and str(entry["legalFormId"])) or "",
            "uid": entry.get("uid") or entry.get("uidFormatted") or "",
        }
        date = entry.get("sogcDate") or entry.get("registryOfCommerceDate") or ""
        m = re.search(r"(19|20)\d{2}", str(date))
        if m:
            out["founded"] = m.group(0)
        return {k: v for k, v in out.items() if v}
    return {}


def crunchbase_lookup(company: str, timeout: int = 12) -> dict:
    """Investors, founders and funding history. Needs CRUNCHBASE_API_KEY.

    Returns {} when no key is configured, so the pipeline runs unchanged until
    a paid API licence is added.
    """
    key = os.environ.get("CRUNCHBASE_API_KEY")
    if not key or not company:
        return {}
    try:
        data = _post_json(
            CRUNCHBASE_SEARCH,
            {
                "field_ids": [
                    "identifier", "short_description", "location_identifiers",
                    "founded_on", "num_employees_enum", "website",
                ],
                "query": [{
                    "type": "predicate", "field_id": "identifier",
                    "operator_id": "contains", "values": [company],
                }],
                "limit": 1,
            },
            {"Content-Type": "application/json", "X-cb-user-key": key,
             "User-Agent": _UA},
            timeout,
        )
        entities = data.get("entities") or []
        if not entities:
            return {}
        props = entities[0].get("properties", {})
        out = {}
        if props.get("website", {}).get("value"):
            out["website"] = urllib.parse.urlsplit(
                props["website"]["value"]).netloc.replace("www.", "")
        if props.get("founded_on", {}).get("value"):
            out["founded"] = str(props["founded_on"]["value"])[:4]
        locs = [l.get("value") for l in props.get("location_identifiers", [])]
        if locs:
            out["location"] = locs[0]
        if props.get("short_description"):
            out["description"] = props["short_description"][:120]
        return out
    except Exception:
        return {}


def fill_from_registries(articles: list) -> int:
    """Fill blanks from Zefix, then Crunchbase when it is configured."""
    import sys

    fields = ("location", "founded", "website", "description")
    todo = [a for a in articles
            if a.get("company") and any(not a.get(f) for f in fields)]
    if not todo:
        return 0

    have_cb = bool(os.environ.get("CRUNCHBASE_API_KEY"))
    print(f"Checking the commercial register for {len(todo)} companies"
          f"{' and Crunchbase' if have_cb else ''}...", file=sys.stderr)

    improved = 0
    for art in todo:
        facts = zefix_lookup(art["company"])
        if have_cb:
            for k, v in crunchbase_lookup(art["company"]).items():
                facts.setdefault(k, v)
        if not facts:
            continue
        changed = False
        for field in fields + ("legal_name", "uid"):
            if not art.get(field) and facts.get(field):
                art[field] = facts[field]
                changed = True
        improved += bool(changed)
    print(f"  filled {improved} companies", file=sys.stderr)
    return improved
