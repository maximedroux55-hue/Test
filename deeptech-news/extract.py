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
    "is not written, and leave a field empty when the text does not say. "
    "Company is the subject of the story, not the investor and not the "
    "publication. Amount is written compactly with its currency, for example "
    "'CHF 3.5M', 'USD 25.5M', 'EUR 700M'. Investors is a comma separated list "
    "of the funds or corporates putting money in. Location is the Swiss city or "
    "canton when stated."
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
                    "category": {"type": "string", "enum": CATEGORIES},
                    "stage": {"type": "string", "enum": STAGES},
                    "amount": {"type": "string"},
                    "investors": {"type": "string"},
                    "location": {"type": "string"},
                },
                "required": ["index", "company", "category", "stage",
                             "amount", "investors", "location"],
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

    location = next((p for p in _SWISS_PLACES if p.lower() in text), "")

    # The company usually opens the headline: "Medyria raises CHF 3.5 million".
    company = ""
    m = re.match(r"([A-Z][\w&.\-]*(?:\s+[A-Z][\w&.\-]*){0,2})\s+(raises|closes|secures|lands|announces|has)", title)
    if m:
        company = m.group(1).strip()

    return {
        "company": company, "category": category, "stage": stage,
        "amount": amount, "investors": "", "location": location,
    }


def extract_fields(articles: list, model: str | None = None) -> list:
    """Return one facts dict per article, in the same order."""
    fallback = [_fallback(a) for a in articles]
    if not articles or not os.environ.get("ANTHROPIC_API_KEY"):
        return fallback

    try:
        import anthropic

        from ai_writer import _clean_summary

        lines = []
        for i, a in enumerate(articles, 1):
            summary = _clean_summary(a.get("summary", ""), 500)
            lines.append(
                f"{i}. Headline: {a.get('title','')}\n"
                f"   Publisher: {a.get('publisher','')}\n"
                + (f"   Summary: {summary}\n" if summary else "")
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
            return fallback

        import json
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        items = json.loads(text).get("items", [])
        out = list(fallback)
        for item in items:
            i = item.get("index", 0) - 1
            if 0 <= i < len(out):
                out[i] = {
                    "company": item.get("company", "").strip(),
                    "category": item.get("category", "Other"),
                    "stage": "" if item.get("stage") == "None" else item.get("stage", ""),
                    "amount": item.get("amount", "").strip(),
                    "investors": item.get("investors", "").strip(),
                    "location": item.get("location", "").strip(),
                }
        return out
    except Exception:
        return fallback
