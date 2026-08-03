"""Turn a written amount into a number, so rounds can be sorted and summed.

The archive stores what the article said, "CHF 450,000" or "USD 70M", because
that is the fact. But text cannot be sorted by size or added up by quarter, so
each round also carries an approximate value in Swiss francs.

The rates are fixed and approximate on purpose. A round announced in July and
one announced in March were struck at different rates, and chasing the real one
for each would add a data source and a failure mode for a number whose only job
is to make "how much went into Swiss quantum this half" answerable to the right
order of magnitude. The written amount stays authoritative; this is for
arithmetic.
"""

from __future__ import annotations

import re

# Approximate, deliberately stable. Update them together when they drift.
RATES_TO_CHF = {
    "CHF": 1.00,
    "USD": 0.80,
    "EUR": 0.93,
    "GBP": 1.08,
    "SEK": 0.084,
    "DKK": 0.125,
    "NOK": 0.079,
}

_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "chf": "CHF", "fr.": "CHF"}

_AMOUNT = re.compile(
    r"(CHF|USD|EUR|GBP|SEK|DKK|NOK|\$|€|£)\s*"
    r"([\d]+(?:[.,'’\s]\d{3})*(?:[.,]\d+)?)\s*"
    r"(bn|b\b|billion|milliarde[n]?|m\b|million|mio\.?|k\b|thousand)?",
    re.IGNORECASE,
)

_MULTIPLIER = {
    "bn": 1e9, "b": 1e9, "billion": 1e9, "milliarde": 1e9, "milliarden": 1e9,
    "m": 1e6, "million": 1e6, "mio": 1e6, "mio.": 1e6,
    "k": 1e3, "thousand": 1e3,
}


def _to_number(digits: str) -> float:
    """Read 450,000 / 450'000 / 25.5 / 1 200 000 as a number."""
    text = digits.strip().replace("’", "'").replace(" ", "")
    # A comma or dot followed by exactly three digits is a thousands separator.
    text = re.sub(r"[,'](?=\d{3}\b)", "", text)
    text = re.sub(r"\.(?=\d{3}\b)", "", text)
    text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def parse(amount: str) -> tuple:
    """Return (currency, value) from a written amount, or ("", 0.0)."""
    m = _AMOUNT.search(amount or "")
    if not m:
        return "", 0.0
    raw = m.group(1)
    currency = _SYMBOLS.get(raw.lower(), _SYMBOLS.get(raw, raw.upper()))
    value = _to_number(m.group(2))
    unit = (m.group(3) or "").lower().rstrip(".")
    value *= _MULTIPLIER.get(unit, 1.0)
    return currency, value


def in_chf(amount: str) -> int:
    """Approximate value of a written amount in Swiss francs, or 0."""
    currency, value = parse(amount)
    if not value:
        return 0
    return int(round(value * RATES_TO_CHF.get(currency, 1.0)))


def compact(value: float) -> str:
    """A short readable figure: 70000000 -> 'CHF 56M'."""
    if not value:
        return ""
    if value >= 1e9:
        return f"CHF {value / 1e9:.1f}B".replace(".0B", "B")
    if value >= 1e6:
        return f"CHF {value / 1e6:.1f}M".replace(".0M", "M")
    if value >= 1e3:
        return f"CHF {value / 1e3:.0f}k"
    return f"CHF {value:.0f}"
