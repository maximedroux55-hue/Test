"""Remember where each fact came from.

A headquarters read off a company's registered address and one repeated from a
journalist's aside are not the same claim, and until now the database showed
them identically. Every filler records itself, so a row can be judged rather
than taken on trust, and so the source producing the errors can be found
instead of guessed at.
"""

from __future__ import annotations

ARTICLE = "the article"
COMPANY_SITE = "the company's own site"
REGISTER = "the commercial register"
IMPRINT = "a registered address"
CORRECTION = "Max"
KEYWORDS = "keyword matching, not read"


def note(article: dict, fields, source: str) -> None:
    """Record that `source` supplied these fields, for the ones that are set."""
    if isinstance(fields, str):
        fields = (fields,)
    seen = article.setdefault("provenance", {})
    for field in fields:
        value = article.get(field)
        if isinstance(value, str) and value.strip():
            seen[field] = source


def summary(stories: list) -> dict:
    """How many facts each source supplied, for the run log."""
    counts = {}
    for story in stories:
        for source in (story.get("provenance") or {}).values():
            counts[source] = counts.get(source, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
