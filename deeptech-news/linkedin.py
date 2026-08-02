"""Turn ranked articles into Climb Ventures LinkedIn post drafts.

These follow Max's Climb LinkedIn rules: a catchy title, emoji-formatted
bullet points (never a bullet without an emoji), a Swiss flag on any summary
that mentions Switzerland, a subtle nod to Climb's capital-efficient Swiss
DeepTech positioning, a short and grounded tone, and no long dashes. Three
layouts are rotated so a batch of posts does not look templated.

Important: these are *drafts to review*, not finished posts. Because the tool
reads RSS feeds (not full article text), summaries are kept short and factual.
For richer, fully written summaries, wire in the Claude API (see README).
"""

import html
import re

# Topic detection: keyword -> (label, emoji, hashtag)
_TOPICS = [
    ("quantum", ("Quantum", "⚛️", "#Quantum")),
    ("semiconductor", ("Semiconductors", "\U0001f50c", "#Semiconductors")),
    ("photonics", ("Photonics", "\U0001f4a1", "#Photonics")),
    ("chip", ("Chips", "\U0001f50c", "#Semiconductors")),
    ("robot", ("Robotics", "\U0001f916", "#Robotics")),
    ("biotech", ("Biotech", "\U0001f9ec", "#Biotech")),
    ("medtech", ("MedTech", "\U0001fa7a", "#MedTech")),
    ("cleantech", ("Cleantech", "\U0001f331", "#Cleantech")),
    ("climate", ("Climate tech", "\U0001f331", "#ClimateTech")),
    ("energy", ("Energy", "⚡", "#Energy")),
    ("nanotech", ("Nanotech", "\U0001f52c", "#Nanotech")),
    ("fusion", ("Fusion", "☀️", "#Fusion")),
    ("artificial intelligence", ("AI", "\U0001f9e0", "#AI")),
    ("machine learning", ("AI", "\U0001f9e0", "#AI")),
    (" ai ", ("AI", "\U0001f9e0", "#AI")),
]

_SWISS_CITIES = [
    "Zurich", "Zürich", "Geneva", "Genève", "Lausanne", "Basel", "Bern",
    "Lugano", "Sion", "Fribourg", "Neuchâtel", "St. Gallen", "Winterthur",
]

# Rotating closing lines that reinforce Climb's positioning without hype.
_CLOSERS = [
    "At Climb, this is the Swiss DeepTech we back: world-class research, built to scale globally and capital-efficiently.",
    "Exactly the capital-efficient Swiss DeepTech thesis we are building at Climb.",
    "Another data point for the Swiss DeepTech story we back at Climb.",
    "This is why we invest in Swiss DeepTech at Climb: deep science, lean capital, global ambition.",
]

# Topic-driven catchy headlines (pooled so a batch varies).
_HEADLINES = {
    "funding": [
        "Swiss deep tech keeps drawing serious capital.",
        "Another Swiss deep-tech raise worth watching.",
        "Capital is following Swiss deep science.",
    ],
    "quantum": [
        "Switzerland's quantum bench keeps getting deeper.",
        "Swiss quantum is quietly compounding.",
    ],
    "chip": [
        "Swiss silicon is having a moment.",
        "The Swiss semiconductor story keeps building.",
    ],
    "research": [
        "Swiss labs keep turning research into companies.",
        "From the lab bench to a business, the Swiss way.",
    ],
    "generic": [
        "Swiss deep tech, quietly building the future.",
        "Another sign of Switzerland's deep-tech momentum.",
        "Swiss DeepTech is compounding, one breakthrough at a time.",
    ],
}


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _first_sentences(text: str, max_len: int = 240) -> str:
    text = _clean(text)
    if not text:
        return ""
    out = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if len(out) + len(sentence) > max_len and out:
            break
        out = (out + " " + sentence).strip()
    return out


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _usable_summary(raw: str, title: str) -> str:
    """Return a clean summary, or '' when the feed gives only boilerplate.

    Google News descriptions are usually HTML lists of related links rather
    than a real summary. We detect that and skip the summary line, leaving a
    clean draft built from the headline and structured bullets.
    """
    if not raw:
        return ""
    if "<ol" in raw or "<li" in raw or raw.count("<a ") > 1:
        return ""  # Google News related-coverage boilerplate
    summary = _first_sentences(raw)
    if not summary:
        return ""
    # If the "summary" is really just the headline again, drop it.
    if _norm(summary)[:60] == _norm(title)[:60]:
        return ""
    return summary


def _topic(text: str):
    low = f" {text.lower()} "
    for key, val in _TOPICS:
        if key in low:
            return val
    return ("DeepTech", "\U0001f680", "#DeepTech")


def _city(text: str):
    for city in _SWISS_CITIES:
        if city.lower() in text.lower():
            return city
    return None


def _funding(text: str):
    m = re.search(r"(chf|usd|eur|\$|€)\s?\d[\d'.,]*\s?(m|million|bn|billion)?",
                  text, re.IGNORECASE)
    if m:
        return m.group(0).strip().upper().replace("MILLION", "million")
    m = re.search(r"\d[\d'.,]*\s?(million|billion)\s?(francs|dollars|euros)?",
                  text, re.IGNORECASE)
    return m.group(0).strip() if m else None


def _headline_pool(text: str) -> list:
    low = text.lower()
    if any(w in low for w in ("raise", "raised", "funding", "round", "seed", "series", "million")):
        return _HEADLINES["funding"]
    if "quantum" in low:
        return _HEADLINES["quantum"]
    if "chip" in low or "semiconductor" in low:
        return _HEADLINES["chip"]
    if any(w in low for w in ("epfl", "eth", "empa", "research", "spin")):
        return _HEADLINES["research"]
    return _HEADLINES["generic"]


def build_post(article: dict, index: int) -> str:
    """Build one LinkedIn draft. `index` rotates headline and layout choices."""
    title = article["title"]
    # Google News appends " - Publisher" to titles; drop it for cleanliness.
    clean_title = re.sub(r"\s+[-|]\s+[^-|]+$", "", title).strip() or title
    combined = f"{title} {article.get('summary', '')}"

    label, emoji, hashtag = _topic(combined)
    city = _city(combined)
    funding = _funding(combined)
    pool = _headline_pool(combined)
    headline = pool[index % len(pool)]
    closer = _CLOSERS[index % len(_CLOSERS)]

    summary = _usable_summary(article.get("summary", ""), clean_title)
    flag = "\U0001f1e8\U0001f1ed "
    mentions_swiss = bool(re.search(r"swiss|switzerland", f"{combined} {summary}", re.IGNORECASE))
    # Swiss flag at the start of a summary that mentions Switzerland.
    summary_line = (f"{flag}{summary}" if (summary and mentions_swiss) else summary)

    # Emoji bullets (rule: never a bullet without an emoji).
    bullets = [f"{emoji} Focus: {label}"]
    if city:
        bullets.append(f"\U0001f4cd Where: {city}")
    if funding:
        bullets.append(f"\U0001f4b0 Deal: {funding}")
    bullets.append(f"\U0001f517 Source: {article['publisher']}")
    bullets_block = "\n".join(bullets)

    tags = f"#DeepTech #Switzerland #VentureCapital #ClimbVentures {hashtag}"

    # Three rotating layouts so a batch does not look templated. Each omits the
    # summary line cleanly when the feed gave no usable summary.
    layout = index % 3
    if layout == 0:
        s = f"{summary_line}\n\n" if summary_line else ""
        body = (
            f"\U0001f680 {headline}\n\n"
            f"{clean_title}\n\n"
            f"{s}"
            f"{bullets_block}\n\n"
            f"{closer}\n\n"
            f"Read more: {article['link']}\n\n{tags}"
        )
    elif layout == 1:
        s = f"{summary_line}\n\n" if summary_line else ""
        body = (
            f"{headline} {flag}\n\n"
            f"{bullets_block}\n\n"
            f"{s}"
            f"{clean_title}\n{article['link']}\n\n"
            f"{closer}\n\n{tags}"
        )
    else:
        s = f"{summary_line}\n\n" if summary_line else ""
        body = (
            f"{s}"
            f"\U0001f4cc {clean_title}\n\n"
            f"Why it matters:\n"
            f"{bullets_block}\n\n"
            f"{closer}\n\n"
            f"\U0001f517 {article['link']}\n\n{tags}"
        )
    return body


def to_linkedin(articles: list, days: int, top: int = 6) -> str:
    """Return a Markdown file of the top LinkedIn post drafts."""
    import datetime as dt
    today = dt.date.today().strftime("%d %B %Y")
    picks = articles[:top]
    parts = [
        f"# Climb Ventures LinkedIn drafts",
        f"_Generated {today} from the top {len(picks)} Swiss DeepTech stories "
        f"of the last {days} days. Review and edit before posting._",
        "",
    ]
    for i, art in enumerate(picks):
        parts.append(f"## Draft {i + 1}\n")
        parts.append("```")
        parts.append(build_post(art, i))
        parts.append("```")
        parts.append("")
    if not picks:
        parts.append("_No stories to turn into posts this run._")
    return "\n".join(parts) + "\n"
