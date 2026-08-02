"""Turn ranked articles into Climb Ventures LinkedIn post drafts.

Each draft follows Max's real posting structure (Monchau style):

    🇨🇭 punchy headline (about 6 to 8 words)

    A 1 to 2 sentence body giving context and the news, with @mentions.

    Why it matters:
    <emoji> market or ecosystem impact
    🇨🇭 the Swiss advantage or competitive angle
    <emoji> the broader implication or what it enables

    source link

Rules honored: Swiss flag emoji on the headline and the Swiss bullet, emoji on
every bullet, no long dashes, a subtle nod to Climb's capital-efficient Swiss
DeepTech positioning, no hashtags.

These are drafts to review. Because the tool reads RSS feeds (not full article
text), the template posts are structured scaffolds. With an ANTHROPIC_API_KEY
set, the posts are instead written in Max's voice by Claude (see ai_writer.py).
"""

import html
import re

# Topic detection: keyword -> (label, emoji)
_TOPICS = [
    ("quantum", ("Quantum", "⚛️")),
    ("semiconductor", ("Semiconductors", "\U0001f50c")),
    ("photonics", ("Photonics", "\U0001f4a1")),
    ("chip", ("Chips", "\U0001f50c")),
    ("robot", ("Robotics", "\U0001f916")),
    ("biotech", ("Biotech", "\U0001f9ec")),
    ("medtech", ("MedTech", "\U0001fa7a")),
    ("cleantech", ("Cleantech", "\U0001f331")),
    ("climate", ("Climate tech", "\U0001f331")),
    ("energy", ("Energy", "⚡")),
    ("nanotech", ("Nanotech", "\U0001f52c")),
    ("fusion", ("Fusion", "☀️")),
    ("artificial intelligence", ("AI", "\U0001f9e0")),
    ("machine learning", ("AI", "\U0001f9e0")),
    (" ai ", ("AI", "\U0001f9e0")),
]

_SWISS_CITIES = [
    "Zurich", "Zürich", "Geneva", "Genève", "Lausanne", "Basel", "Bern",
    "Lugano", "Sion", "Fribourg", "Neuchâtel", "St. Gallen", "Winterthur",
]

_FLAG = "\U0001f1e8\U0001f1ed"  # Swiss flag

# "Why it matters" content, grouped by topic bucket. Each bucket gives a body
# significance line and three bullets: market impact, Swiss advantage (leads
# with the flag), and broader implication.
_BUCKETS = {
    "quantum": {
        "sig": "It is another sign that Swiss quantum and photonics research is edging toward commercial products.",
        "market": "\U0001f4c8 Photonics is one of the rare quantum fields with a credible near-term path to revenue.",
        "swiss": f"{_FLAG} Switzerland's strength in precision engineering and optics gives its quantum spinouts a real head start.",
        "broader": "\U0001f9ed Deep science on a lean capital plan is exactly the Swiss DeepTech we look for at Climb.",
    },
    "chips": {
        "sig": "Swiss semiconductor work keeps turning academic research into industrial capability.",
        "market": "\U0001f4c8 Semiconductors sit under almost every growth market, from AI to defense to mobility.",
        "swiss": f"{_FLAG} Switzerland punches above its weight in specialised chips and advanced materials.",
        "broader": "\U0001f9ed Capital-efficient hardware built on Swiss research is core to the Climb thesis.",
    },
    "bio": {
        "sig": "Mechanism-level biology is where tomorrow's therapeutics quietly begin.",
        "market": "\U0001f4c8 Early biological insight compounds into products years before anyone names a company.",
        "swiss": f"{_FLAG} Swiss academic biology remains one of Europe's most underrated sources of DeepTech company creation.",
        "broader": "\U0001f9ed Patient capital behind rigorous science is what turns Swiss labs into global businesses.",
    },
    "robotics": {
        "sig": "Swiss robotics and applied AI keep moving from demo to deployment.",
        "market": "\U0001f4c8 Automation is shifting from pilots to real commercial operations.",
        "swiss": f"{_FLAG} Switzerland's robotics ecosystem, anchored by ETH and EPFL, is world class.",
        "broader": "\U0001f9ed Hard engineering with a clear path to revenue is the Swiss DeepTech we back at Climb.",
    },
    "clean": {
        "sig": "Swiss cleantech keeps pairing serious science with real-world deployment.",
        "market": "\U0001f4c8 Energy and climate hardware is moving from subsidy toward genuine demand.",
        "swiss": f"{_FLAG} Switzerland combines deep materials science with disciplined engineering.",
        "broader": "\U0001f9ed Capital-efficient climate hardware fits squarely in the Climb thesis.",
    },
    "generic": {
        "sig": "It is another data point in Switzerland's steady deep-tech build-out.",
        "market": "\U0001f4c8 Deep technology is where durable, defensible companies get built.",
        "swiss": f"{_FLAG} Switzerland turns world-class research into companies with unusual consistency.",
        "broader": "\U0001f9ed Backing that research early and capital-efficiently is what we do at Climb.",
    },
}


def _bucket_for(label: str) -> str:
    label = label.lower()
    if label in ("quantum", "photonics"):
        return "quantum"
    if label in ("chips", "semiconductors"):
        return "chips"
    if label in ("biotech", "medtech"):
        return "bio"
    if label in ("robotics", "ai"):
        return "robotics"
    if label in ("cleantech", "climate tech", "energy", "fusion", "nanotech"):
        return "clean"
    return "generic"


def _topic(text: str):
    low = f" {text.lower()} "
    for key, val in _TOPICS:
        if key in low:
            return val
    return ("DeepTech", "\U0001f680")


def _city(text: str):
    for city in _SWISS_CITIES:
        if city.lower() in text.lower():
            return city
    return None


def _funding(text: str):
    m = re.search(r"(chf|usd|eur|\$|€)\s?\d[\d'.,]*\s?(m|million|bn|billion)?",
                  text, re.IGNORECASE)
    if m:
        return m.group(0).strip()
    m = re.search(r"\d[\d'.,]*\s?(million|billion)\s?(francs|dollars|euros)?",
                  text, re.IGNORECASE)
    return m.group(0).strip() if m else None


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _first_sentences(text: str, max_len: int = 300) -> str:
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
    """Return a clean summary, or '' when the feed gives only boilerplate."""
    if not raw:
        return ""
    if "<ol" in raw or "<li" in raw or raw.count("<a ") > 1:
        return ""  # Google News related-coverage boilerplate
    summary = _first_sentences(raw)
    if not summary:
        return ""
    if _norm(summary)[:60] == _norm(title)[:60]:
        return ""
    return summary


def _headline(clean_title: str) -> str:
    """A short, punchy headline for the opening line (kept from the real title)."""
    h = clean_title.strip()
    if len(h) > 72:
        h = h[:69].rsplit(" ", 1)[0] + "..."
    return h


def build_post(article: dict, index: int) -> str:
    """Build one structured LinkedIn draft (template fallback)."""
    title = article["title"]
    clean_title = re.sub(r"\s+[-|]\s+[^-|]+$", "", title).strip() or title
    combined = f"{title} {article.get('summary', '')}"

    label, _emoji = _topic(combined)
    bucket = _BUCKETS[_bucket_for(label)]
    city = _city(combined)
    funding = _funding(combined)

    # 1. Opening line: Swiss flag + punchy headline.
    opening = f"{_FLAG} {_headline(clean_title)}"

    # 2. Body: prefer a real summary; otherwise a grounded templated sentence.
    where = f" in {city}" if city else ""
    deal = f" The round is reported at {funding}." if funding else ""
    summary = _usable_summary(article.get("summary", ""), clean_title)
    if summary:
        body = f"{summary}{deal}"
        # Swiss flag at the start of a real summary that names Switzerland
        # (the opening headline already carries the flag on templated bodies).
        if re.search(r"swiss|switzerland", body, re.IGNORECASE) and not body.startswith(_FLAG):
            body = f"{_FLAG} {body}"
    else:
        body = (
            f"{article['publisher']} covers the story{where}. {bucket['sig']}{deal}"
        )

    # 3 and 4. Why it matters, three bullets, no blank lines between them.
    market = bucket["market"]
    if funding:
        market = f"\U0001f4b0 Capital keeps following Swiss deep science, this time at {funding}."

    parts = [
        opening,
        "",
        body,
        "",
        "Why it matters:",
        market,
        bucket["swiss"],
        bucket["broader"],
        "",
        article["link"],
    ]
    return "\n".join(parts)


def to_linkedin(articles: list, days: int, top: int = 7) -> str:
    """Return a Markdown file of the week's LinkedIn post drafts, one per day.

    Uses Claude to write the posts in Max's voice when an ANTHROPIC_API_KEY is
    available; otherwise falls back to the built-in structured templates. Each
    draft is labeled with the day it is meant to be scheduled for, starting the
    day after the run (so a Wednesday run plans Thursday through the next
    Wednesday).
    """
    import datetime as dt
    from ai_writer import generate_posts

    today = dt.date.today()
    picks = articles[:top]

    ai_posts = generate_posts(picks, days)
    if ai_posts:
        posts = ai_posts
        mode = "Written by Claude in Max's voice."
    else:
        posts = [build_post(art, i) for i, art in enumerate(picks)]
        mode = "Template drafts (set ANTHROPIC_API_KEY for AI-written posts)."

    parts = [
        "# Climb Ventures LinkedIn plan for the week",
        f"_Generated {today.strftime('%d %B %Y')}. {len(picks)} posts, one per "
        f"day, from Swiss DeepTech news of the last {days} days. {mode} "
        f"Schedule each for 8:00 AM on its day. Review and edit before posting._",
        "",
    ]
    for i, post in enumerate(posts):
        day = (today + dt.timedelta(days=i + 1)).strftime("%A %d %B")
        parts.append(f"## Post {i + 1} — schedule for {day}\n")
        parts.append("```")
        parts.append(post)
        parts.append("```")
        parts.append("")
    if not picks:
        parts.append("_No stories to turn into posts this run._")
    return "\n".join(parts) + "\n"
