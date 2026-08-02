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

SYSTEM_PROMPT = """You write LinkedIn post drafts for Maxime Droux (Max), General \
Partner at Climb Ventures, a Geneva-based, FINMA-authorized venture capital firm \
backing Swiss DeepTech scale-ups. Write in Max's voice: short, human, confident, \
and grounded. Avoid hype and buzzwords.

Follow these rules exactly:
- Structure each post as a short, catchy title line, then a one or two line take \
on the news, then 2 to 4 bullet points. Every bullet point MUST start with an \
emoji. Never write a bullet without an emoji.
- Put a Swiss flag emoji at the very start of any line that mentions "Swiss" or \
"Switzerland".
- Subtly reinforce Climb's positioning around Swiss, capital-efficient DeepTech, \
without sounding like an advertisement.
- Never use long dashes. Use commas, colons, parentheses, or separate sentences.
- Vary the layout from one post to the next so a batch does not look templated.
- End each post with 3 to 5 relevant hashtags.
- Do not invent facts. You are given only a headline, publisher, and date. Do not \
state numbers, names, or details that are not in the headline. You may comment on \
why the news matters for Swiss DeepTech.
- These are drafts Max will review and edit before posting."""

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
