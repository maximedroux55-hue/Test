"""Optional Claude-powered post writing for the Swiss DeepTech aggregator.

If an ANTHROPIC_API_KEY is available (and the `anthropic` package is installed),
this writes each LinkedIn draft in Max's voice using Claude, following his Climb
Ventures rules. If the key or package is missing, or anything goes wrong, it
returns None so the caller falls back to the template drafts. This keeps the
tool working with zero setup, and better with a key.

Set-up to enable it:
  1. Get an API key at https://console.anthropic.com  (this is separate from a
     Claude.ai subscription and is billed per use; a weekly digest is cheap).
  2. Export it:  export ANTHROPIC_API_KEY=sk-ant-...
     In GitHub Actions, add it as a repository secret named ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import json
import os
import re

# Default to the most capable model. Override with ANTHROPIC_MODEL if you want a
# cheaper one (e.g. claude-sonnet-5).
DEFAULT_MODEL = "claude-opus-5"

SYSTEM_PROMPT = """You write LinkedIn posts for Maxime Droux (Max), General \
Partner at Climb Ventures, a Geneva-based, FINMA-authorized venture capital firm \
backing Swiss DeepTech scale-ups. Style model: Charles-Henry Monchau. \
Journalistic, analytical, punchy, and data-driven. Confident and grounded, never \
hype.

Structure EVERY post exactly like this, with a blank line between each part:

1. Opening line: the Swiss flag emoji, then a headline of 5 to 8 words that names \
what happened. Most begin with "Swiss". Real examples: "🇨🇭 Swiss chips keep \
quantum computers cool", "🇨🇭 Swiss space firm raises $70M to build satellites", \
"🇨🇭 Swiss capsules reinvent alcohol-free perfume".
2. Body: 2 or 3 sentences, 35 to 50 words, and nothing more. Lead with the \
company, say where it came from ("an EPFL spin-off", "Neuchâtel-based"), then \
pack in the concrete facts you were given: the amount, the investor, revenue, \
customers, the technical specific. Exactly ONE @mention per post, on the \
company the post is about, the first time it appears. Every other organisation \
is named in plain text with no @: universities, investors, partners, customers, \
regulators. Each @ has to be typed into LinkedIn and picked from a dropdown, so \
a post with five of them is five chances to stall or tag the wrong entity. Real \
example: "@Rhonexum, an EPFL spin-off, is building electronics that run near \
absolute zero, right beside the qubits. Backed by Venture Kick and a $1M \
pre-seed, its cryo-CMOS control replaces today's tangle of cables, a key barrier \
to scaling quantum machines."
3. The exact label "Why it matters:" on its own line.
4. Exactly 3 bullets, one per line, no blank lines between them. Each starts with \
a single relevant emoji, then 7 to 12 words. One line only: a sharp claim, not a \
sentence of analysis. One of the three carries the Swiss flag and makes the Swiss \
point. Real examples: "⚛️ Tackles the cabling bottleneck blocking bigger quantum \
computers", "❄️ Cryogenic control chips cut complexity and heat load", "🇨🇭 Swiss \
deeptech targeting its first product in early 2027".
5. One closing line in Max's own voice: a single sentence of 12 to 20 words \
drawing out what the story says about Swiss DeepTech. One sentence only, never \
two, never a paragraph. A judgement, not a pitch, and never about Climb or "we". \
Examples: "Deep science reaching a first product on a lean budget is the Swiss \
pattern that keeps working." / "Another sign that Swiss deeptech scales quietly, \
then all at once." / "Precision manufacturing turns out to be the hardest moat to \
copy."
6. The source link on its own line.

Rules:
- Write every post in English. Swiss sources often report in German, French or \
Italian: translate the substance into natural English and never leave a foreign \
phrase, headline or quote untranslated. Keep company, institution and place \
names as they are (ETH Zurich, EPFL, Neuchâtel).
- Target 85 to 110 words total, not counting the link. These posts are short. \
Going long is the most common mistake: cut adjectives before you cut facts.
- Never name Climb, and never write "we", "our thesis" or what Max looks for. \
Not in the body, not in the closing line. The closing line observes what the \
story means for Swiss DeepTech; the positioning shows through story choice.
- Vary the closing line across the batch. Seven posts that all end on the same \
thought about capital efficiency read like a template.
- Prefer a concrete number to an adjective. Amounts, revenue, growth rates, unit \
counts, dates and named customers are what make these posts land.
- Name the company. Headlines often hide it ("how a Swiss company plans to ..."), \
so take the name from the summary. A post about an unnamed "Swiss startup" is a \
failed post. If neither headline nor summary names it, write about what is \
actually named instead, and never invent a name.
- Never use long dashes. Use commas, colons, parentheses, or separate sentences.
- Do not invent facts, numbers, or names beyond the headline. You have only a \
headline, its origin, and a date. You may add analysis of why it matters for \
Swiss DeepTech.
- Only credit a news outlet when a Publisher is given. When the source is the \
company's own announcement, mention no outlet at all.
- Vary phrasing across posts so a batch does not look templated.
- No hashtags. End with the source link.
- These are drafts Max reviews and lightly edits before posting."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "posts": {
            "type": "array",
            "items": {"type": "string"},
        }
    },
    "required": ["posts"],
    "additionalProperties": False,
}


def _clean_summary(raw: str, limit: int = 600) -> str:
    """Feed summaries as plain text, trimmed, for the writer to draw facts from."""
    import html as _html
    import re as _re

    text = _re.sub(r"<[^>]+>", " ", raw or "")
    text = _html.unescape(text)
    text = _re.sub(r"\s+", " ", text).strip()
    return text[:limit]


# Numbers only where somebody has checked them.
_FIGURE = __import__("re").compile(
    r"(?:CHF|USD|EUR|GBP)\s?[\d.,\']+\s?(?:m|bn|k|million|billion)?"
    r"|[$€£]\s?[\d.,\']+\s?(?:m|bn|k|million|billion)?"
    r"|\b(?:pre-?seed|seed|series\s+[a-e])\b",
    __import__("re").IGNORECASE)


def has_figure(text: str) -> bool:
    """Does this post state an amount or a round?"""
    return bool(_FIGURE.search(text or ""))


def _build_user_prompt(articles: list, days: int) -> str:
    lines = [
        f"Here are the top {len(articles)} Swiss DeepTech stories from the last "
        f"{days} days. Write one LinkedIn draft per story, in the same order.",
        "",
    ]
    for i, a in enumerate(articles, 1):
        date = a["date"].strftime("%d %b %Y") if a.get("date") else "n/a"
        # When the link is the company's own announcement, no outlet is named,
        # so the post credits the company rather than whoever covered it.
        origin = (
            "   Source: the company's own announcement, credit no news outlet\n"
            if a.get("coverage_url")
            else f"   Publisher: {a['publisher']}\n"
        )
        # The feed summary usually names the company and carries the numbers,
        # which the headline alone often omits ("how a Swiss company plans to
        # ..."). Without it the draft cannot name its own subject.
        summary = _clean_summary(a.get("summary", ""))
        # A figure nobody has checked does not go out under Max's name. The
        # database has carried a ceiling as proceeds, a follow-on as a
        # flotation and an unclosed round as closed; a wrong number in a post
        # tags the company and cannot be quietly corrected.
        import trust
        unchecked = ""
        if a.get("company") and not trust.is_verified(a["company"]):
            unchecked = (
                "   UNVERIFIED: this round has not been checked against a "
                "primary source. Write the post WITHOUT any funding figure, "
                "round name or investor names. Say what the company does and "
                "why it matters. Never write an amount here.\n")
        lines.append(
            f"{i}. Headline: {a['title']}\n"
            f"{origin}"
            f"{unchecked}"
            f"   Date: {date}\n"
            + (f"   Summary: {summary}\n" if summary else "")
            + f"   Link: {a['link']}"
        )
    return "\n".join(lines)


_MENTION = re.compile(r"@([A-Za-zÀ-ÿ0-9][\w\-.&']*)")


def one_mention(post: str, company: str = "") -> str:
    """Leave the @ on the subject company only, as plain text elsewhere.

    Every mention costs a type-wait-click cycle in LinkedIn, and a post with
    five of them is five chances to hang or tag the wrong entity. Two of them
    could not be tagged at all: "@University of St. Gallen" begins with a
    generic word, so typing the first word after the @ offers a list of
    universities, and "@FDA" is a US regulator nobody meant to tag.

    So one mention, the company the post is about. Everything else keeps its
    name and loses the @.
    """
    stem = re.sub(r"[^a-z0-9]", "", (company or "").lower())
    kept = [False]

    def decide(match):
        word = re.sub(r"[^a-z0-9]", "", match.group(1).lower())
        subject = bool(stem) and (word.startswith(stem[:len(word)] or "x")
                                  and stem.startswith(word[:len(stem)] or "x"))
        # A round-up names four companies and is about none of them; the first
        # is as good a choice as any, and it is only ever one.
        if (subject or not stem) and not kept[0]:
            kept[0] = True
            return match.group(0)
        return match.group(1)

    return _MENTION.sub(decide, post or "")


def _warn_missing_mentions(posts) -> None:
    """Flag drafts whose body names no organisation with an @.

    The writer occasionally states a company plainly ("AI Infrastructure Capital
    AG has launched") instead of mentioning it. Every story here has a company or
    institution behind it, so a draft with no @ at all is a miss worth seeing in
    the run log rather than discovering on LinkedIn.
    """
    import sys

    for i, post in enumerate(posts or [], 1):
        if "@" not in post:
            first = post.splitlines()[0][:60] if post else ""
            print(
                f"  ! post {i} has no @mention, add one before posting: {first}",
                file=sys.stderr,
            )


def generate_posts(articles: list, days: int, model: str | None = None):
    """Return a list of post strings from Claude, or None to trigger fallback."""
    if not articles:
        return None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None

    model = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            # Every post is written in one call, so the ceiling has to scale
            # with how many are asked for. A post runs about 350 tokens; at a
            # flat 8000 a shortlist of fifteen would have been cut off
            # mid-sentence and the whole run would have fallen back to
            # templates. 800 each, and never below the old figure.
            max_tokens=max(8000, 800 * len(articles)),
            system=SYSTEM_PROMPT,
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": _SCHEMA},
            },
            messages=[{"role": "user", "content": _build_user_prompt(articles, days)}],
        )
        if response.stop_reason == "refusal":
            return None
        text = next((b.text for b in response.content if b.type == "text"), "")
        posts = json.loads(text).get("posts", [])
        posts = [p.strip() for p in posts if isinstance(p, str) and p.strip()] or None
        _warn_missing_mentions(posts)
        return posts
    except Exception:
        # Any failure (network, auth, parsing) falls back to templates.
        return None
