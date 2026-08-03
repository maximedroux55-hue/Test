"""Pull structured deal facts out of each story.

The archive is more useful as a table of companies and rounds than as a list of
headlines, so every story is reduced to: company, category, stage, amount,
investors and location.

Claude does the reading when an ANTHROPIC_API_KEY is present, because the facts
sit in ordinary prose ("has closed a USD 25.5 million seed round led by
Quantonation") and patterns alone read that badly. Without a key, or if the call
fails, a keyword fallback fills in what it can and leaves the rest blank, so the
archive still builds.
"""

from __future__ import annotations

import os
import re

DEFAULT_MODEL = "claude-opus-5"

CATEGORIES = [
    "AI", "Quantum", "Semiconductors", "Photonics", "Robotics", "Space",
    "Biotech", "Pharma", "MedTech", "Cleantech", "Energy", "Materials",
    "Software", "FinTech", "AgriTech", "Logistics", "Research", "Other",
]

STAGES = [
    "Pre-seed", "Seed", "Series A", "Series B", "Series C", "Series D",
    "Growth", "Grant", "IPO", "Acquisition", "Partnership", "None",
]

SYSTEM = (
    "You read Swiss deep tech news and return the facts as structured data. "
    "Extract only what the text states. Never guess, never infer a number that "
    "is not written, and leave a field empty when the text does not say. That "
    "holds absolutely for the deal itself: amount, stage, investors, valuation "
    "and totals come from the text alone. Headquarters is the single exception, "
    "explained below. "
    "Company is the subject of the story, not the investor and not the "
    "publication. Amount is written compactly with its currency, for example "
    "'CHF 3.5M', 'USD 25.5M', 'EUR 700M'.\n\n"
    "Location is the company's headquarters, as a city, written as "
    "'Lausanne' or, when the company is not Swiss, 'Munich, DE'. Take it from "
    "wording such as 'Zurich-based', 'the Renens company' or 'headquartered "
    "in Basel'. It is never a market the company is expanding into, never an "
    "investor's home city, never where an event or conference took place, and "
    "never the country alone. The outlet's own name is not evidence: a story "
    "carried by 'Greater Geneva Bern area' says nothing about the company "
    "being in Geneva.\n"
    "Headquarters is the one field you may fill from your own knowledge of the "
    "company when the article does not state it, because it is a standing fact "
    "about the company rather than a detail of this news. Do so only when you "
    "actually know the company and are confident, for instance Hilo in "
    "Neuchâtel. If you are unsure, leave it empty. Never take another city from "
    "the text as a substitute.\n\n"
    "Investors: list only named funds, corporates or people, comma separated, "
    "for example 'Quantonation' or 'Swisscom Ventures, Venture Kick'. A "
    "headline of the form 'X leads a round for Y' names X as an investor of Y. "
    "Never write a generic description such as 'angel investors', 'VC firms', "
    "'existing investors' or 'undisclosed': leave the field empty instead. "
    "lead_investor is the one said to lead or co-lead; leave empty if none is.\n\n"
    "Category is the sector the company works in, judged from what it makes, "
    "never from the funding stage. 'Seed' is a stage, not a category. Use "
    "'Other' only when the text genuinely does not say what the company does: "
    "a drug delivery company is Pharma, a sensor maker is MedTech or "
    "Materials, a chip designer is Semiconductors.\n\n"
    "The other fields:\n"
    "- description: what the company does, at most 12 words, no marketing.\n"
    "- total_raised: cumulative funding when stated ('brings the total to').\n"
    "- valuation: only when the text gives one.\n"
    "- founders: names of founders or the CEO when named.\n"
    "- spinoff_origin: the institution it spun out of, such as 'ETH Zurich', "
    "'EPFL', 'CSEM', 'Empa', 'University of Basel'. Empty if not a spin-off.\n"
    "- founded: year of founding, four digits.\n"
    "- employees: headcount when stated.\n"
    "- use_of_funds: what the money is for, at most 10 words.\n"
    "- customers: named customers or partners, comma separated.\n"
    "- website: the company's own domain when the text gives it."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "company": {"type": "string"},
                    "description": {"type": "string"},
                    "category": {"type": "string", "enum": CATEGORIES},
                    "stage": {"type": "string", "enum": STAGES},
                    "amount": {"type": "string"},
                    "total_raised": {"type": "string"},
                    "valuation": {"type": "string"},
                    "lead_investor": {"type": "string"},
                    "investors": {"type": "string"},
                    "founders": {"type": "string"},
                    "spinoff_origin": {"type": "string"},
                    "founded": {"type": "string"},
                    "employees": {"type": "string"},
                    "use_of_funds": {"type": "string"},
                    "customers": {"type": "string"},
                    "website": {"type": "string"},
                    "location": {"type": "string"},
                },
                "required": [
                    "index", "company", "description", "category", "stage",
                    "amount", "total_raised", "valuation", "lead_investor",
                    "investors", "founders", "spinoff_origin", "founded",
                    "employees", "use_of_funds", "customers", "website",
                    "location",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

_SWISS_PLACES = [
    "Zurich", "Zürich", "Geneva", "Genève", "Lausanne", "Basel", "Bern",
    "Lugano", "Sion", "Fribourg", "Neuchâtel", "Neuchatel", "Winterthur",
    "St. Gallen", "Zug", "Vaud", "Valais", "Ticino", "Renens", "Schlieren",
    "Yverdon", "Villigen", "Dübendorf", "Biel", "Lucerne", "Thun",
]

_STAGE_PATTERNS = [
    (r"pre-?seed", "Pre-seed"),
    (r"series\s*a", "Series A"),
    (r"series\s*b", "Series B"),
    (r"series\s*c", "Series C"),
    (r"series\s*d", "Series D"),
    (r"\bseed\b", "Seed"),
    (r"\bipo\b|public offering", "IPO"),
    (r"acquir|acquisition|takeover", "Acquisition"),
    (r"grant|funding initiative|foerdermittel|fördermittel|venture kick", "Grant"),
    (r"partnership|collaborat|strategic investment", "Partnership"),
]

_CATEGORY_PATTERNS = [
    (r"quantum|qubit|ion trap", "Quantum"),
    (r"photonic|laser|optic", "Photonics"),
    (r"semiconductor|chip|wafer|silicon", "Semiconductors"),
    (r"satellite|space|orbit", "Space"),
    (r"robot|autonomous|drone", "Robotics"),
    (r"gene|biotech|antibody|therapeut|molecul|protein", "Biotech"),
    (r"pharma|drug|clinical", "Pharma"),
    (r"medtech|medical device|implant|diagnos|health", "MedTech"),
    (r"battery|solar|hydrogen|energy|grid", "Energy"),
    (r"cleantech|carbon|recycl|emission", "Cleantech"),
    (r"material|nano|coating|membrane", "Materials"),
    (r"fintech|bank|payment|insur", "FinTech"),
    (r"logistic|shipping|freight|container", "Logistics"),
    (r"agri|food|farm", "AgriTech"),
    (r"\bai\b|machine learning|language model|llm|compute", "AI"),
    (r"software|platform|saas", "Software"),
]


# Descriptions of investors rather than names. An empty cell is more honest.
_GENERIC_INVESTORS = re.compile(
    r"^\s*(and\s+)?("
    r"angel|angels|investor|investors|vc|vcs|venture capital|"
    r"venture capitalists?|business angels?|family offices?|funds?|"
    r"existing|undisclosed|private|institutional|strategic|various|"
    r"several|multiple|unnamed|others?|offices?"
    r")\b[\s\w]*$",
    re.IGNORECASE,
)


def _clean_investors(value: str) -> str:
    """Drop generic descriptions, keep actual names."""
    names = [n.strip(" .;") for n in (value or "").split(",")]
    kept = [n for n in names if n and not _GENERIC_INVESTORS.match(n)]
    return ", ".join(kept)


def _fallback(article: dict) -> dict:
    """Best effort from the text alone, leaving unknowns blank."""
    title = article.get("title", "") or ""
    text = f"{title} {article.get('summary', '')}".lower()

    amount = ""
    m = re.search(
        r"(chf|usd|eur|£|€|\$)\s?([\d][\d'’.,]*)\s?(million|billion|bn|m\b)?",
        text, re.IGNORECASE,
    )
    if m:
        cur = {"$": "USD", "€": "EUR", "£": "GBP"}.get(m.group(1), m.group(1).upper())
        num = m.group(2).rstrip(".,")
        unit = (m.group(3) or "").lower()
        suffix = "B" if unit in ("billion", "bn") else ("M" if unit else "")
        amount = f"{cur} {num}{suffix}".strip()

    stage = ""
    for pattern, label in _STAGE_PATTERNS:
        if re.search(pattern, text):
            stage = label
            break

    category = "Other"
    for pattern, label in _CATEGORY_PATTERNS:
        if re.search(pattern, text):
            category = label
            break

    # Prefer a place the text ties to the company, so an expansion market or an
    # investor's city is not mistaken for the headquarters.
    location = ""
    for place in _SWISS_PLACES:
        p = re.escape(place.lower())
        if re.search(rf"{p}[\s-]based|based in {p}|the {p} (company|startup|firm)"
                     rf"|headquartered in {p}", text):
            location = place
            break
    if not location:
        location = next((p for p in _SWISS_PLACES if p.lower() in text), "")

    # The company usually opens the headline: "Medyria raises CHF 3.5 million".
    company = ""
    m = re.match(r"([A-Z][\w&.\-]*(?:\s+[A-Z][\w&.\-]*){0,2})\s+(raises|closes|secures|lands|announces|has)", title)
    if m:
        company = m.group(1).strip()

    origin = ""
    for name in ("ETH Zurich", "EPFL", "CSEM", "Empa", "PSI", "Idiap"):
        if name.lower() in text and re.search(r"spin[\s-]?o(ff|ut)", text):
            origin = name
            break

    return {
        "company": company, "description": "", "category": category,
        "stage": stage, "amount": amount, "total_raised": "", "valuation": "",
        "lead_investor": "", "investors": "", "founders": "",
        "spinoff_origin": origin, "founded": "", "employees": "",
        "use_of_funds": "", "customers": "", "website": "",
        "location": location,
    }


# Eighteen fields for thirty stories overruns a single reply, and a truncated
# reply is unparseable, which silently costs every field. Ask in small batches.
BATCH = 8


def extract_fields(articles: list, model: str | None = None) -> list:
    """Return one facts dict per article, in the same order."""
    import sys

    fallback = [_fallback(a) for a in articles]
    if not articles or not os.environ.get("ANTHROPIC_API_KEY"):
        return fallback

    out = list(fallback)
    ok = 0
    for start in range(0, len(articles), BATCH):
        chunk = articles[start: start + BATCH]
        got = _extract_batch(chunk, model)
        if got is None:
            print(f"  ! extraction failed for stories {start + 1}-{start + len(chunk)}, "
                  f"used keywords instead", file=sys.stderr)
            continue
        for offset, facts in enumerate(got):
            if facts:
                out[start + offset] = facts
                ok += 1
    print(f"  read the facts from {ok}/{len(articles)} stories", file=sys.stderr)
    return out


def fill_from_company_sites(articles: list, model: str | None = None) -> int:
    """Fill blanks from each company's own site. Returns how many rows improved.

    News write-ups name the amount and skip the rest, so investors, founders and
    the founding year are usually missing. The company's own About and Press
    pages carry them. Only empty fields are filled, so the article always wins
    where the two disagree, and only rows with something missing are looked up.
    """
    import sys

    from hq_lookup import company_pages

    wanted = ("investors", "lead_investor", "founders", "founded",
              "employees", "website", "spinoff_origin", "location")
    todo = [
        a for a in articles
        if a.get("company") and any(not a.get(f) for f in wanted)
    ]
    if not todo:
        return 0

    print(f"Checking {len(todo)} company websites for the missing details...",
          file=sys.stderr)
    improved = 0
    for art in todo:
        domain, text = company_pages(art.get("company", ""), art.get("website", ""))
        if not text:
            continue
        if not art.get("website"):
            art["website"] = domain
        probe = dict(art)
        probe["fulltext"] = text
        got = _extract_batch([probe], model)
        facts = (got or [None])[0]
        if not facts:
            continue
        # Only fill gaps. What the article said stands.
        changed = False
        for field in wanted:
            if not art.get(field) and facts.get(field):
                art[field] = facts[field]
                changed = True
        improved += bool(changed)
    print(f"  filled gaps on {improved} companies", file=sys.stderr)
    return improved


def _extract_batch(articles: list, model: str | None = None):
    """One request for a handful of stories. None when it could not be read."""
    try:
        import anthropic

        from ai_writer import _clean_summary

        lines = []
        for i, a in enumerate(articles, 1):
            # The full article when we could fetch it, else the feed summary.
            body = a.get("fulltext") or _clean_summary(a.get("summary", ""), 500)
            lines.append(
                f"{i}. Headline: {a.get('title','')}\n"
                f"   Link: {a.get('link','')}\n"
                + (f"   Article: {body}\n" if body else "")
            )
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL),
            max_tokens=8000,
            system=SYSTEM,
            messages=[{
                "role": "user",
                "content": "Extract the facts for each story.\n\n" + "\n".join(lines),
            }],
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": _SCHEMA},
            },
        )
        if getattr(resp, "stop_reason", "") == "refusal":
            return None

        import json
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        items = json.loads(text).get("items", [])
        out = [None] * len(articles)
        for item in items:
            i = item.get("index", 0) - 1
            if 0 <= i < len(out):
                out[i] = {
                    "company": item.get("company", "").strip(),
                    "description": item.get("description", "").strip(),
                    "category": item.get("category", "Other"),
                    "stage": "" if item.get("stage") == "None" else item.get("stage", ""),
                    "amount": item.get("amount", "").strip(),
                    "total_raised": item.get("total_raised", "").strip(),
                    "valuation": item.get("valuation", "").strip(),
                    "lead_investor": _clean_investors(item.get("lead_investor", "")),
                    "investors": _clean_investors(item.get("investors", "")),
                    "founders": item.get("founders", "").strip(),
                    "spinoff_origin": item.get("spinoff_origin", "").strip(),
                    "founded": item.get("founded", "").strip(),
                    "employees": item.get("employees", "").strip(),
                    "use_of_funds": item.get("use_of_funds", "").strip(),
                    "customers": item.get("customers", "").strip(),
                    "website": item.get("website", "").strip(),
                    "location": item.get("location", "").strip(),
                }
        return out
    except Exception as exc:
        import sys
        print(f"    extraction error: {type(exc).__name__}: {str(exc)[:160]}",
              file=sys.stderr)
        return None
