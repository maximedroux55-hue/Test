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
    "Growth", "Grant", "IPO", "Follow-on", "De-SPAC", "Acquisition",
    "Partnership", "None",
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
    "status is 'announced' when the transaction has not completed: subject to "
    "shareholder or regulatory approval, expected or targeted to close, or a "
    "signed agreement rather than a closing. Otherwise 'closed'. A merger with "
    "a listed acquisition vehicle is 'De-SPAC', never 'IPO'.\n"
    "'IPO' means a company reaching the public market for the first time. A "
    "company that is already listed raising more shares, off a shelf "
    "registration or as a secondary or follow-on offering, is 'Follow-on'. "
    "The presence of a ticker, a shelf, a Form S-3 or an over-allotment "
    "exercised by underwriters all point to a company that is already public.\n"
    "amount_note carries any condition attached to the figure, in a few words: "
    "'up to, assuming no redemptions', 'gross proceeds before expenses', "
    "'including debt'. An amount written as a ceiling is not an amount raised, "
    "and the condition is the difference.\n\n"
    "Stage must be written in the text: 'Series C', 'a seed round', "
    "'pre-seed'. Never infer it. The size of the cheque, the maturity of the "
    "company and words such as 'to scale' or 'to expand' say nothing about "
    "the stage, and 'Growth' is only correct where the text calls it a growth "
    "round. When the text says only that a company raised an amount, leave "
    "stage empty.\n\n"
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
                    "status": {"type": "string", "enum": ["closed", "announced"]},
                    "amount_note": {"type": "string"},
                },
                "required": [
                    "index", "company", "description", "category", "stage",
                    "amount", "total_raised", "valuation", "lead_investor",
                    "investors", "founders", "spinoff_origin", "founded",
                    "employees", "use_of_funds", "customers", "website",
                    "location", "status", "amount_note",
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


# Model output occasionally carries stray markup into a field: two rows were
# stored with a city of "Zurich}}</invoke>|;". Nothing we extract is markup, so
# anything from the first bracket or brace onwards is cut.
_STRAY_MARKUP = re.compile(r"[<>{}|\[\]].*$", re.DOTALL)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")

# A city is a name, optionally with a country code. Anything else is not one.
_CITY = re.compile(
    r"^[A-ZÄÖÜÉÈÀ][\w\s.'’\-]{1,28}(?:,\s?[A-Z]{2})?$", re.UNICODE)

_MAX_LENGTH = {
    "company": 60, "location": 40, "stage": 20, "amount": 30, "category": 20,
    "founded": 4, "description": 160, "use_of_funds": 90,
}


def scrub(field: str, value: str) -> str:
    """Return a value fit to store, or "" when it is not.

    A wrong value is worse than a blank, and a value carrying markup is not a
    fact at all.
    """
    if not isinstance(value, str):
        return ""
    text = _CONTROL.sub(" ", _STRAY_MARKUP.sub("", value))
    text = re.sub(r"\s+", " ", text).strip(" ,;.|-")
    limit = _MAX_LENGTH.get(field)
    if limit and len(text) > limit:
        # Truncating a name invents one, so drop it instead.
        return "" if field in ("company", "location", "stage", "founded") else text[:limit]
    if field == "location" and text and not _CITY.match(text):
        return ""
    if field == "founded" and not re.fullmatch(r"(19|20)\d{2}", text):
        return ""
    return text


def clean_record(facts: dict) -> dict:
    """Scrub every field of an extracted record in place."""
    for field, value in list(facts.items()):
        if isinstance(value, str):
            facts[field] = scrub(field, value)
    return facts


def _is_a_name(text: str) -> bool:
    """Is this an investor's name rather than a description of one?

    CCRAFT's round included "a leading European AI infrastructure operator",
    which is a fact about the round and not a name, so it is not an entry in a
    list of investors.
    """
    words = text.split()
    if not words or len(words) > 6:
        return False
    if re.match(r"^(a|an|the|another|several|various|two|three)\b", text,
                re.IGNORECASE) and not text[0].isupper():
        return False
    if re.match(r"^(a|an|the)\s+[a-z]", text, re.IGNORECASE):
        return False
    # A name carries a capital. "european ai operator" does not.
    return any(w[:1].isupper() for w in words)


def _clean_investors(value: str) -> str:
    """Drop generic descriptions, keep actual names."""
    names = [n.strip(" .;") for n in (value or "").split(",")]
    kept = [n for n in names
            if n and not _GENERIC_INVESTORS.match(n) and _is_a_name(n)]
    return ", ".join(kept)


# Words that sit in front of a company name in a headline and are not part of
# it: "Swiss AI startup Prem is raising" is Prem, not "Swiss AI startup Prem".
_LEAD_NOISE = {
    "swiss", "swiss-based", "ai", "startup", "start-up", "scaleup", "spinout",
    "spin-off", "spinoff", "company", "firm", "tech", "deeptech", "biotech",
    "medtech", "fintech", "quantum", "the", "a", "exclusive", "eth", "epfl",
    "zurich", "geneva", "lausanne", "basel", "bern", "swiss-french",
}

# The verbs a funding headline uses, in the order they appear after the name.
# German and French too, since the Swiss feeds carry all three.
_RAISE_VERBS = (
    r"raises|raised|is\s+raising|has\s+raised|closes|closed|secures|secured|"
    r"lands|landed|nets|netted|completes|completed|announces|announced|"
    r"bags|picks\s+up|receives|received|gets|attracts|banks|launches|launched|"
    r"erh(?:ä|ae)lt|sammelt|sichert|schliesst|holt|"
    r"l(?:è|e)ve|boucle|d(?:é|e)croche|obtient"
)

# A name ending in a legal form is complete as written, so the leading-word
# clean-up must leave it alone: "AI Infrastructure Capital AG" is the company.
_LEGAL_SUFFIX = re.compile(
    r"\b(AG|SA|SÀRL|SARL|GmbH|Ltd|Inc|BV|NV|Holding|Group)\.?$", re.IGNORECASE)


def _company_from_headline(title: str) -> str:
    """The company named in a funding headline, or "".

    Used when the article could not be read. The name is not always first:
    "Exclusive: ETH Zurich spinout ZuriQ raises $25.5m seed - Sifted" and
    "Swiss preventive health startup Ahead Health raises $10M" both name the
    company in the middle, which an anchored match missed entirely.
    """
    head = re.sub(r"\s+[-–|]\s+[^-–|]{2,30}$", "", title or "").strip()
    head = re.sub(r"^(exclusive|breaking|update|opinion|news)\s*:\s*", "", head,
                  flags=re.IGNORECASE)
    # The name must stay case sensitive, the verb must not: headlines write
    # both "raises" and "Raises". The optional clause between them absorbs an
    # aside, as in "SkyPilot, from Databricks' cofounder, raises $20M".
    m = re.search(
        rf"\b([A-Z][\w&.\-]*(?:\s+[A-Z0-9][\w&.\-]*){{0,3}})"
        rf"(?:,[^,]{{0,50}},)?\s+(?i:{_RAISE_VERBS})\b",
        head,
    )
    if not m:
        return ""
    name = m.group(1).strip(" ,.")
    if _LEGAL_SUFFIX.search(name):
        return name
    words = name.split()
    while len(words) > 1 and words[0].lower().strip(",.") in _LEAD_NOISE:
        words.pop(0)
    if words and words[0].lower().strip(",.") in _LEAD_NOISE:
        return ""
    return " ".join(words).strip(" ,.")


# A stage the text states outright. SWISSto12's article said Series C and the
# read came back "Growth", inferred from "raises USD 70 million to scale", so
# what the text actually says is checked separately and wins.
_STATED_STAGE = (
    (re.compile(r"\bpre[\s\-]?seed\b", re.IGNORECASE), None),
    (re.compile(r"\bseries[\s\-]?([A-E])\b", re.IGNORECASE), None),
    # Not the "seed" inside "pre-seed" or "pre seed", a different round.
    (re.compile(r"(?<!pre )(?<![\w\-])seed\s+(?:round|financing|funding|investment)\b"
                r"|\brais\w+\s+(?:a\s+|its\s+)?(?<!pre )(?<![\w\-])seed\b",
                re.IGNORECASE),
     "Seed"),
    (re.compile(r"\bgrowth\s+(?:round|financing|funding|equity)\b", re.IGNORECASE),
     "Growth"),
    (re.compile(r"\bbridge\s+(?:round|financing)\b", re.IGNORECASE), "Seed"),
)

# Words that mark the raise this story is about, as opposed to funding history
# mentioned in passing.
_RAISE_NEARBY = re.compile(
    r"rais\w+|clos\w+|secur\w+|round|financing|funding|led\s+by|oversubscribed",
    re.IGNORECASE,
)

# Where a story names more than one round, the later one is the news and the
# earlier is the company's history: "after its 2021 seed, it closes a Series B"
# is a Series B story.
_SENIORITY = {
    "Pre-seed": 1, "Seed": 2, "Series A": 3, "Series B": 4, "Series C": 5,
    "Series D": 6, "Growth": 7, "IPO": 8,
}


# Wording that means the article names who put the money in. If this is in the
# text and the read came back with no investors, the read is wrong, not the
# article: CCRAFT's write-up said "led by QBIT Capital, with participation from
# Zürcher Kantonalbank, Apprecia Capital, Spacewalk, Blue Wonder Ventures" and
# the row was stored empty.
_NAMES_INVESTORS = re.compile(
    r"led\s+by|co-?led\s+by|participation\s+(?:from|of)|backed\s+by|"
    r"investors?\s+include|joined\s+by|with\s+support\s+from|"
    r"angef(?:ü|ue)hrt\s+von|unter\s+(?:der\s+)?F(?:ü|ue)hrung|"
    r"beteiligt\s+(?:sich|waren)|men(?:é|e)\s+par|avec\s+la\s+participation",
    re.IGNORECASE,
)


# A transaction that has not closed. Terra Quantum's USD 190M was recorded as
# capital raised when it was a ceiling on an unclosed de-SPAC: "up to
# approximately $190 million of gross proceeds, assuming no redemptions",
# targeted to close in the second half of the year subject to approvals. On
# those deals redemptions routinely run above 80%, so the headline can be a
# multiple of what arrives.
_NOT_CLOSED = re.compile(
    r"expected\s+to\s+close|targeted\s+(?:for|to\s+close)|subject\s+to\s+"
    r"(?:\w+\s+){0,3}approval|shareholder\s+approval|pending\s+approval|"
    r"upon\s+(?:the\s+)?clos|once\s+(?:the\s+deal\s+)?closes|"
    r"(?:definitive|merger|business\s+combination)\s+agreement|"
    r"has\s+agreed\s+to\s+merge|plans\s+to\s+(?:list|go\s+public)|"
    r"ahead\s+of\s+(?:its\s+)?(?:listing|merger)|would\s+(?:raise|receive)",
    re.IGNORECASE,
)

# A figure that is a ceiling or a gross, not money in the bank.
_CONTINGENT = re.compile(
    r"up\s+to\s+(?:approximately\s+|around\s+|about\s+)?(?:USD|EUR|CHF|\$|€|£)|"
    r"assuming\s+no\s+redemption|before\s+(?:transaction\s+)?expenses|"
    r"gross\s+proceeds|excluding\s+(?:transaction\s+)?(?:costs|expenses)|"
    r"could\s+raise|potential(?:ly)?\s+(?:raise|receive)",
    re.IGNORECASE,
)

# A merger with a listed shell is not a flotation, whatever the headline says.
_DE_SPAC = re.compile(
    r"\bde-?SPAC\b|special\s+purpose\s+acquisition|business\s+combination|"
    r"acquisition\s+corp\b|blank[-\s]cheque\s+company",
    re.IGNORECASE,
)

# A company that is already public raising more shares is not floating. Read as
# an IPO it says a Swiss company reached the public market, which is a
# different event from MoonLake, listed on Nasdaq since 2022, selling stock off
# a shelf.
_ALREADY_LISTED = re.compile(
    r"follow[-\s]?on\s+offering|secondary\s+(?:public\s+)?offering|"
    r"shelf\s+registration|form\s+s-3|\bs-3\b|at[-\s]the[-\s]market\s+offering|"
    r"over[-\s]?allot(?:ment)?\s+option|underwriters?\s*.{0,20}\boption\b|"
    r"already\s+(?:listed|public)|\b(?:NASDAQ|NYSE|SIX|Euronext)\s*:\s*[A-Z]{2,6}\b|"
    r"existing\s+shareholders?\s+sold|its\s+shares\s+(?:trade|are\s+traded)",
    re.IGNORECASE,
)


def _transaction_notes(text: str) -> dict:
    """Whether a deal has closed and whether its figure is conditional."""
    out = {}
    if _NOT_CLOSED.search(text or ""):
        out["status"] = "announced"
    note = []
    if re.search(r"up\s+to\b", text or "", re.IGNORECASE):
        note.append("up to")
    if re.search(r"assuming\s+no\s+redemption", text or "", re.IGNORECASE):
        note.append("assuming no redemptions")
    if re.search(r"gross\s+proceeds", text or "", re.IGNORECASE):
        note.append("gross proceeds")
    if note and _CONTINGENT.search(text or ""):
        out["amount_note"] = ", ".join(note)
    if _DE_SPAC.search(text or ""):
        out["stage"] = "De-SPAC"
    elif _ALREADY_LISTED.search(text or ""):
        out["stage"] = "Follow-on"
    return out


def _stage_from_text(text: str) -> str:
    """The stage the text states, or "".

    Where several are named ("after its 2021 seed, it now closes a Series C")
    the one nearest a word about raising wins, which is the round being
    reported rather than the company's history.
    """
    text = (text or "")[:4000]
    reported, mentioned = [], []
    for pattern, fixed in _STATED_STAGE:
        for m in pattern.finditer(text):
            if fixed:
                stage = fixed
            elif m.lastindex:
                stage = f"Series {m.group(1).upper()}"
            else:
                stage = "Pre-seed"
            window = text[max(0, m.start() - 60): m.end() + 60]
            (reported if _RAISE_NEARBY.search(window) else mentioned).append(
                (stage, m.start()))

    candidates = reported or mentioned
    if not candidates:
        return ""
    # The most senior round wins, and position only breaks a tie.
    return min(candidates,
               key=lambda c: (-_SENIORITY.get(c[0], 0), c[1]))[0]


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

    company = _company_from_headline(title)

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
        "location": location, "status": "", "amount_note": "",
    }


# Eighteen fields for thirty stories overruns a single reply, and a truncated
# reply is unparseable, which silently costs every field. Ask in small batches.
BATCH = 8


# How the last extraction went, so the caller can tell a thin archive caused by
# quiet reporting apart from one caused by the API being unavailable.
LAST_RUN_OK = 0
LAST_RUN_ERROR = ""


def extract_fields(articles: list, model: str | None = None) -> list:
    """Return one facts dict per article, in the same order."""
    import sys

    global LAST_RUN_OK
    LAST_RUN_OK = 0
    fallback = [_fallback(a) for a in articles]
    if not articles or not os.environ.get("ANTHROPIC_API_KEY"):
        return fallback

    out = list(fallback)
    ok = 0
    for start in range(0, len(articles), BATCH):
        chunk = articles[start: start + BATCH]
        got = _extract_batch(chunk, model)
        if got is None and len(chunk) > 1:
            # One awkward story should not cost the other seven. A batch that
            # fails is retried a story at a time, which is how six rounds ended
            # up in the archive with no company name against a headline that
            # said it plainly.
            print(f"  batch {start + 1}-{start + len(chunk)} failed, "
                  f"retrying one story at a time", file=sys.stderr)
            got = []
            for art in chunk:
                got.extend(_extract_batch([art], model) or [None])
        if got is None:
            print(f"  ! extraction failed for stories {start + 1}-{start + len(chunk)}, "
                  f"used keywords instead", file=sys.stderr)
            continue
        import provenance

        for offset, facts in enumerate(got):
            if facts:
                art = articles[start + offset]
                facts["provenance"] = {
                    f: provenance.ARTICLE for f, v in facts.items()
                    if isinstance(v, str) and v.strip()
                }
                body = art.get("fulltext") or art.get("summary", "")
                # The address often states the round outright, as in
                # ".../gr3n-closes-a-15-5m-series-b-round", and a slug cannot
                # be a passing mention of somebody else's raise.
                slug = re.sub(r"[-_/]+", " ", art.get("link", "").rsplit("/", 1)[-1])
                stated = (_stage_from_text(f"{art.get('title', '')}. {body}")
                          or _stage_from_text(f"closes a {slug}"))
                if stated:
                    facts["stage"] = stated
                # Whether it closed, and whether the figure is a ceiling. Read
                # from the text rather than left to be noticed, because the
                # difference between "raised" and "up to, if nobody redeems"
                # is the difference between a fact and a press release.
                for field, value in _transaction_notes(
                        f"{art.get('title', '')}. {body}").items():
                    facts[field] = value
                # The article names the backers and we came back with none: read
                # that one again on its own, where the whole reply is about it.
                if (not facts.get("investors") and not facts.get("lead_investor")
                        and _NAMES_INVESTORS.search(body)):
                    retry = (_extract_batch([art], model) or [None])[0]
                    if retry and (retry.get("investors")
                                  or retry.get("lead_investor")):
                        for field in ("investors", "lead_investor", "founders"):
                            if retry.get(field) and not facts.get(field):
                                facts[field] = retry[field]
                        print(f"  re-read '{art.get('title', '')[:44]}' for its "
                              f"investors", file=sys.stderr)
                out[start + offset] = facts
                ok += 1
    print(f"  read the facts from {ok}/{len(articles)} stories", file=sys.stderr)
    LAST_RUN_OK = ok
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
        # Only fill gaps. What the article said stands, with one exception:
        # the headquarters. A company's own imprint is authoritative and a
        # journalist's shorthand is not, which is how SWISSto12 in Renens was
        # recorded in Geneva and Hilo in Neuchâtel was recorded in Sion.
        import provenance

        changed = False
        for field in wanted:
            authoritative = field == "location" and facts.get(field)
            if (not art.get(field) or authoritative) and facts.get(field):
                if art.get(field) != facts[field]:
                    changed = True
                art[field] = facts[field]
                provenance.note(art, field, provenance.COMPANY_SITE)
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
                    "status": item.get("status", "").strip(),
                    "amount_note": item.get("amount_note", "").strip(),
                }
                clean_record(out[i])
        return out
    except Exception as exc:
        import sys
        global LAST_RUN_ERROR
        LAST_RUN_ERROR = f"{type(exc).__name__}: {str(exc)[:200]}"
        print(f"    extraction error: {LAST_RUN_ERROR}", file=sys.stderr)
        return None
