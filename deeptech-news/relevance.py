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
    "appointment of": 4, "appointments": 3, "professors": 3,
    "obituary": 4, "anniversary": 2, "open day": 3, "campus": 2,
    "semester": 3, "graduation": 3, "rector": 3, "lecture series": 3,
}


def _count(text: str, terms: dict) -> int:
    score = 0
    for term, weight in terms.items():
        if term in text:
            score += weight
    return score


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
    text = f" {title} {summary} {source} ".lower()
    title_text = f" {title} ".lower()
    swiss = _count(text, SWISS_TERMS)
    deep = _count(text, DEEPTECH_TERMS)

    # Institutional sources are inherently Swiss and research-heavy, so give
    # them a small Swiss floor even if the headline omits the country name.
    if any(s in source.lower() for s in _SWISS_SOURCES):
        swiss = max(swiss, 2)

    if swiss == 0 or deep == 0:
        return 0

    score = swiss + deep
    # Deal language counts double in the title, where it is most meaningful.
    score += _count(title_text, DEAL_TERMS) + _count(text, DEAL_TERMS)
    score -= _count(title_text, NOISE_TERMS)
    return max(score, 0)


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
