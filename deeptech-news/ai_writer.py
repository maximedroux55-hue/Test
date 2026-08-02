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

# Default to the most capable model. Override with ANTHROPIC_MODEL if you want a
# cheaper one (e.g. claude-sonnet-5).
DEFAULT_MODEL = "claude-opus-5"

SYSTEM_PROMPT = """You write LinkedIn posts for Maxime Droux (Max), General \
Partner at Climb Ventures, a Geneva-based, FINMA-authorized venture capital firm \
backing Swiss DeepTech scale-ups. Style model: Charles-Henry Monchau. \
Journalistic, analytical, punchy, and data-driven. Confident and grounded, never \
hype.

Structure EVERY post exactly like this, with a blank line between each part:

1. Opening line: the Swiss flag emoji, then a short punchy headline of about 6 to \
8 words. Example: "🇨🇭 Swiss quantum moves to commercial scale".
2. Body: 1 or 2 sentences of context and the news. Where a company, university, \
or institution is named, add an @mention for it (for example @EPFL, @ETH Zurich, \
@Startupticker). Max verifies the exact handles before posting.
3. The exact label "Why it matters:" on its own line.
4. Exactly 3 bullet points, one per line, with NO blank lines between them. Each \
bullet MUST start with a single relevant emoji, then the point. Cover, in order: \
(a) market or ecosystem impact, (b) the Swiss advantage or competitive angle \
(start this bullet with the Swiss flag emoji), (c) the broader implication or \
what it enables.
5. The source link on its own line.

Rules:
- Target 150 to 200 words total, not counting the link. Do not be terse.
- Subtly reinforce Climb's positioning around Swiss, capital-efficient DeepTech, \
without sounding like an advertisement.
- Never use long dashes. Use commas, colons, parentheses, or separate sentences.
- Do not invent facts, numbers, or names beyond the headline. You have only a \
headline, publisher, and date. You may add analysis of why it matters for Swiss \
DeepTech.
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


def _build_user_prompt(articles: list, days: int) -> str:
    lines = [
        f"Here are the top {len(articles)} Swiss DeepTech stories from the last "
        f"{days} days. Write one LinkedIn draft per story, in the same order.",
        "",
    ]
    for i, a in enumerate(articles, 1):
        date = a["date"].strftime("%d %b %Y") if a.get("date") else "n/a"
        lines.append(
            f"{i}. Headline: {a['title']}\n"
            f"   Publisher: {a['publisher']}\n"
            f"   Date: {date}\n"
            f"   Link: {a['link']}"
        )
    return "\n".join(lines)


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
            max_tokens=8000,
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
        return [p.strip() for p in posts if isinstance(p, str) and p.strip()] or None
    except Exception:
        # Any failure (network, auth, parsing) falls back to templates.
        return None
