"""Relevance scoring and de-duplication for the Swiss DeepTech aggregator.

The idea is simple: an article is interesting to us when it is both about
Switzerland AND about deep technology. We score each of those two dimensions
from keyword hits, then combine them. An article with zero Swiss signal or zero
DeepTech signal is dropped.
"""

import re
from difflib import SequenceMatcher

# Weighted keyword sets. Higher weight = stronger signal.
SWISS_TERMS = {
    "switzerland": 3, "swiss": 3, "suisse": 3, "schweiz": 3,
    "zurich": 2, "geneva": 2, "genève": 2, "lausanne": 2, "basel": 2,
    "bern": 2, "lugano": 2, "vaud": 2, "neuchâtel": 2, "neuchatel": 2,
    "epfl": 3, "eth zurich": 3, "eth zürich": 3, "empa": 3, "psi": 2,
    "csem": 3, "idiap": 3, "unibas": 2, "chf": 2, "finma": 2,
}

DEEPTECH_TERMS = {
    "deep tech": 4, "deeptech": 4, "deep-tech": 4,
    "quantum": 3, "semiconductor": 3, "photonics": 3, "chip": 2,
    "robotics": 3, "biotech": 2, "medtech": 2, "cleantech": 2,
    "nanotech": 3, "materials": 2, "fusion": 3,
    "longevity": 3, "battery": 2, "sensor": 2, "microtech": 3,
    "spin-off": 2, "spinoff": 2, "spin off": 2,
    "artificial intelligence": 2, "machine learning": 2, "ai ": 1,
    "series a": 2, "series b": 2,
    "funding round": 2, "raises": 2, "raised": 2, "seed round": 2,
    "research": 1, "laboratory": 1, "patent": 1,
    # Models and compute
    "llm": 3, "large language model": 3, "foundation model": 3,
    "language model": 2, "supercomputer": 3, "compute": 2, "sovereign": 2,
    "algorithm": 2, "simulation": 2, "digital twin": 3, "open source": 2,
    # Hardware, optics, materials
    "qubit": 3, "laser": 2, "optics": 2, "wafer": 3, "silicon": 2,
    "microscopy": 2, "spectroscopy": 2, "catalyst": 2, "membrane": 2,
    "sensing": 2, "sensor": 2, "biosensor": 3, "nanopore": 3,
    # Life sciences
    "gene editing": 3, "crispr": 3, "in vivo": 2, "in-vivo": 2,
    "therapeutic": 2, "protein": 2, "molecule": 2, "vaccine": 2,
    "diagnostic": 2, "imaging": 2, "implant": 2,
    # Energy and climate hardware
    "hydrogen": 2, "solar": 2, "carbon capture": 3, "grid": 1,
    # Motion
    "drone": 2, "satellite": 2, "autonomous": 2,
}

# A story is far more postable when it is a deal or a spinout, which is what
# Climb Ventures comments on. These add a bonus on top of the base score so
# funding news outranks routine institutional updates (appointments, campus
# stories) that would otherwise score similarly.
DEAL_TERMS = {
    "raises": 3, "raised": 3, "funding round": 3, "seed round": 3,
    "series a": 3, "series b": 3, "series c": 3, "pre-seed": 3,
    "closes": 2, "secures": 2, "led by": 2, "investment": 2,
    "spin-off": 3, "spinoff": 3, "spin off": 3, "spinout": 3,
    "acquisition": 2, "acquired": 2, "ipo": 2, "venture kick": 3,
}

# Routine institutional items that are Swiss and research-adjacent but not
# postable as DeepTech news. These pull the score down.
NOISE_TERMS = {
    # Academic appointments and honours, in every phrasing they arrive in.
    "appointment of": 4, "appointments": 3, "professor": 3,
    "appoints": 4, "appointed": 3, "professorship": 4, "professorial": 4,
    "nomination of": 4, "emeritus": 4, "honorary": 4, "doctorate": 4,
    "names new": 3, "steps down": 3, "joins as": 3, "hires": 3,
    "promoted to": 3,
    "obituary": 4, "anniversary": 2, "open day": 3, "campus": 2,
    "semester": 3, "graduation": 3, "rector": 3, "lecture series": 3,
    # Evergreen listicles and market-research filler, not news.
    "vendor guide": 5, "complete guide": 5, "market size": 5,
    "market report": 5, "market share": 4, "forecast to": 4,
    "top 10": 4, "best of": 3, "everything you need": 4,
    # Crime and courts. Swiss and occasionally technical, never a Climb post.
    # Listed in the three languages Swiss outlets publish in.
    "fraud": 5, "scandal": 5, "lawsuit": 4, "court": 4, "trial of": 4,
    "convicted": 5, "prosecutor": 5, "arrested": 5, "money laundering": 5,
    "escroquerie": 5, "fraude": 5, "accusé": 5, "accusée": 5,
    "procès": 5, "condamné": 5, "justice": 3, "plainte": 4,
    "betrug": 5, "verurteilt": 5, "prozess": 4, "festgenommen": 5,
    "staatsanwalt": 5, "skandal": 5, "anklage": 5,
    # Campus showcases rather than commercial deep tech.
    "students": 4, "student project": 5, "semester project": 5,
}

# No outlet is barred for being general-interest: a mainstream Swiss title
# reporting a photonics milestone is as welcome as a trade publication. What
# gets filtered is the content, through the noise and opinion rules below.
EXCLUDED_PUBLISHERS = ()

# Opinion, analysis and interviews. The digest reports what happened, so
# commentary about what it means is left out however relevant the topic.
OPINION_TERMS = {
    "opinion": 5, "commentary": 5, "editorial": 5, "op-ed": 5,
    "viewpoint": 5, "interview": 5, "q&a": 5, "in conversation": 5,
    "the case for": 5, "lessons from": 4, "here's why": 5, "heres why": 5,
    "why we": 4, "my take": 5, "we need to": 5, "should we": 5,
    "predictions": 4, "outlook": 4, "trends to watch": 5,
    "what to expect": 5, "the future of": 4, "is the future": 5,
    "emerges as": 4, "powerhouse": 4, "rethinking": 4, "reimagining": 4,
    "can become": 4, "could become": 4, "must ": 3,
    # The same, as Swiss outlets phrase it in German and French.
    "kommentar": 5, "meinung": 5, "gastbeitrag": 5, "standpunkt": 5,
    "kann werden": 4, "sollte": 3, "warum ": 3,
    "tribune": 4, "édito": 5, "edito": 5, "pourquoi ": 3, "entretien": 5,
    "analyse": 3, "chronique": 5,
}


def _is_quoted_headline(title: str) -> bool:
    """A headline wrapped in quotation marks is someone's view, not an event.

    The trailing " - Publisher" that Google News appends is removed first,
    otherwise a quoted headline ending "» - Watson" looks unquoted.
    """
    t = re.sub(r"\s+[-|]\s+[^-|]+$", "", (title or "")).strip()
    if len(t) < 2:
        return False
    return (t[0], t[-1]) in {
        ("«", "»"), ('"', '"'), ("“", "”"), ("'", "'"), ("‘", "’"),
    }

# Sites that publish market-research summaries, stock chatter or directory
# pages. They mention the right words but never carry the news itself.
EXCLUDED_DOMAINS = (
    "fortunebusinessinsights.com", "marketscreener.com", "tradingview.com",
    "globenewswire.com/newsroom", "researchandmarkets.com", "grandviewresearch.com",
    "marketsandmarkets.com", "prnewswire.com/news-releases/global",
    "quantumzeitgeist.com", "wko.at", "simplywall.st", "investing.com",
)


def _squash(text: str) -> str:
    """Lowercase, letters and digits only, so 'Simply Wall St' meets simplywall.st."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


# The distinctive part of each excluded domain, long enough to be safe to look
# for inside other strings. This catches the outlet's display name ("TradingView")
# and copycat domains (tradingviewstore.com) as well as the domain itself.
_EXCLUDED_NAMES = tuple(
    sorted({
        name for name in (
            _squash(d.split("/")[0].rsplit(".", 1)[0]) for d in EXCLUDED_DOMAINS
        ) if len(name) >= 6
    })
)


def is_excluded(text: str) -> bool:
    """True for a link or publisher we never want a story from."""
    squashed = _squash(text)
    if not squashed:
        return False
    if any(_squash(d) in squashed for d in EXCLUDED_DOMAINS):
        return True
    if any(_squash(p) in squashed for p in EXCLUDED_PUBLISHERS):
        return True
    return any(name in squashed for name in _EXCLUDED_NAMES)


def _count(text: str, terms: dict) -> int:
    score = 0
    for term, weight in terms.items():
        if term in text:
            score += weight
    return score


# Most a summary can contribute to any one signal, so headline relevance leads.
_SUMMARY_CAP = 3

_SWISS_SOURCES = (
    "epfl", "eth", "empa", "startupticker", "swissinfo", "csem", "idiap",
    "venturelab", "psi", "unibas", "uzh", "unige", "swissbiotech", "ibm research",
)


def score_article(title: str, summary: str, source: str = "") -> int:
    """Return a relevance score. 0 means 'not relevant, drop it'.

    Base score is Swiss signal + DeepTech signal. On top of that, funding and
    spinout news gets a bonus (that is the news worth posting about), while
    routine institutional items (appointments, campus notices) are penalised.
    The title carries more weight than the summary, so the bonus and penalty
    are measured on the title first.
    """
    # Score the story itself, never the outlet's name. "Fintechnews
    # Switzerland" contains "Switzerland", which otherwise handed a Swiss score
    # to every story it runs, including its London desk's UK banking news.
    title_text = f" {title} ".lower()
    summary_text = f" {summary} ".lower()

    # The headline states what the story is. When it announces an appointment
    # or a student showcase, no amount of technical vocabulary further down
    # makes it a DeepTech story. Deal language in the same headline overrides
    # this, so "EPFL professor's spin-off raises CHF 5 million" still counts.
    if _count(title_text, NOISE_TERMS) and not _count(title_text, DEAL_TERMS):
        return 0

    # Opinion and interviews are dropped outright. Unlike the noise rules, deal
    # language does not rescue these: "why we should back quantum" is still a
    # view, not a fact to report.
    if _is_quoted_headline(title) or _count(title_text, OPINION_TERMS):
        return 0

    # The headline carries full weight; the summary is capped. A long research
    # write-up can otherwise brush past a dozen keywords and outscore an actual
    # funding round, which is how a piece on rivers and cities came to rank
    # above a quantum seed round.
    swiss = _count(title_text, SWISS_TERMS) + min(_count(summary_text, SWISS_TERMS), _SUMMARY_CAP)
    deep = _count(title_text, DEEPTECH_TERMS) + min(_count(summary_text, DEEPTECH_TERMS), _SUMMARY_CAP)

    # Institutional sources are inherently Swiss and research-heavy, so give
    # them a small Swiss floor even if the headline omits the country name.
    if any(s in source.lower() for s in _SWISS_SOURCES):
        swiss = max(swiss, 2)

    # A single weight-1 mention is not evidence of deep tech. A passing "AI" in
    # a consumer subscription story, or the bare word "research", would
    # otherwise clear the bar. Require either one substantial signal (quantum,
    # semiconductor, spin-off, a funding round) or two weak ones.
    if swiss == 0 or deep < 2:
        return 0

    # Deal language counts double in the headline, where it is most meaningful.
    return (
        swiss + deep
        + _count(title_text, DEAL_TERMS) * 2
        + min(_count(summary_text, DEAL_TERMS), _SUMMARY_CAP)
    )


# Words too generic to help tell two stories apart. Overlap on these does not
# mean two headlines describe the same event, so we ignore them when comparing.
_STOP = {
    "the", "and", "for", "with", "from", "that", "this", "into", "over",
    "startup", "startups", "company", "raises", "raised", "raise", "round",
    "seed", "series", "funding", "million", "billion", "francs", "franc",
    "chf", "usd", "eur", "swiss", "switzerland", "lands", "secures", "closes",
    "gets", "wins", "news", "technology", "tech", "new", "its", "after",
}


def _normalize(title: str) -> str:
    t = title.lower()
    t = re.sub(r"\s+[-|]\s+[^-|]+$", "", t)  # drop trailing " - Publisher"
    t = re.sub(r"[^a-z0-9 ]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _keywords(title: str) -> set:
    """Distinctive words from a title: length >= 4, not a stopword, not a pure number."""
    words = _normalize(title).split()
    return {w for w in words if len(w) >= 4 and w not in _STOP and not w.isdigit()}


def _same_story(a: dict, b: dict) -> bool:
    # Three signals, any one is enough: near-identical text, a strong overlap
    # of distinctive keywords, or a shared rare name.
    if SequenceMatcher(None, a["_norm"], b["_norm"]).ratio() > 0.80:
        return True
    # A rare name shared by two headlines is almost always the same company,
    # and so the same event. This catches the same round written up very
    # differently, e.g. "Quantonation leads USD 25.5 million seed round for ETH
    # spin-off ZuriQ" and "ETH Zurich spinout ZuriQ raises $25.5m seed", which
    # share too few words to look alike but are plainly one story.
    if a["_rare"] & b["_rare"]:
        return True
    ka, kb = a["_kw"], b["_kw"]
    if not ka or not kb:
        return False
    jaccard = len(ka & kb) / len(ka | kb)
    return jaccard >= 0.5


def diversify(articles: list, max_per_publisher: int = 2) -> list:
    """Re-order so no single outlet dominates, keeping the ranking otherwise.

    Startupticker covers most Swiss rounds, so a purely score-ranked list tends
    to be mostly Startupticker. This takes at most `max_per_publisher` stories
    from any one outlet first, then appends the rest in score order, so the top
    of the list spans several outlets without losing any story.
    """
    picked, overflow, seen = [], [], {}
    for art in articles:
        pub = (art.get("publisher") or "").strip().lower()
        seen[pub] = seen.get(pub, 0) + 1
        (picked if seen[pub] <= max_per_publisher else overflow).append(art)
    return picked + overflow


def deduplicate(articles: list) -> list:
    """Remove near-duplicate stories (same event reported by several outlets).

    Keeps the highest-scoring version of each story. `articles` is a list of
    dicts with at least 'title' and 'score'.
    """
    # How many headlines each word appears in. A word used by only one or two
    # stories is a name (a company, a product), not general vocabulary.
    freq = {}
    for art in articles:
        for word in _keywords(art["title"]):
            freq[word] = freq.get(word, 0) + 1

    for art in articles:
        art["_norm"] = _normalize(art["title"])
        art["_kw"] = _keywords(art["title"])
        art["_rare"] = {
            w for w in art["_kw"] if len(w) >= 5 and freq.get(w, 0) <= 3
        }

    kept = []
    for art in sorted(articles, key=lambda a: a["score"], reverse=True):
        if not any(_same_story(art, existing) for existing in kept):
            kept.append(art)
    return kept
