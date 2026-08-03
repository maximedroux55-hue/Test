"""Work the verification queue: find the primary source, compare, propose.

The queue says which rounds are worth checking. This goes and checks them,
weekly, without anyone asking. For each round it searches the news index for
the company and the round, reads the pages it finds, and asks whether they
confirm or contradict what the database holds.

What it produces is a proposal, never a correction. It writes to
proposals.json, which is inert, and every entry must carry the sentence it read
and the page it read it on. A machine checking a machine is worth something
only if its working can be inspected, so that evidence is required rather than
requested.

It says plainly when it cannot reach a source. A paywalled article is not
verification, and an unverifiable round stays unverified.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.parse

from images import article_text
from google_news import is_google_news_url, resolve_url

DEFAULT_MODEL = "claude-opus-5"

# Pages worth reading first: the company itself, then the filing, then the
# outlets that carry releases in full.
_PREFERRED = ("startupticker.ch", "globenewswire", "businesswire", "prnewswire",
              "sec.gov", "presseportal", "venturelab")

SYSTEM = (
    "You check a recorded financing round against the source that reported it. "
    "You are looking for four things that have actually been wrong before.\n\n"
    "1. Has the transaction closed? A round being assembled, a deal expected "
    "or targeted to close, or one subject to approval, is announced rather "
    "than closed. 'Is raising' is not 'raised'.\n"
    "2. Is the label right? A first listing is an IPO. An already listed "
    "company selling shares, off a shelf or as a secondary, is a Follow-on. A "
    "merger with a listed acquisition vehicle is a De-SPAC. A purchase is an "
    "Acquisition and not a round at all.\n"
    "3. Is the figure money received, or a ceiling, a gross, or a target? "
    "'Up to, assuming no redemptions' is not proceeds.\n"
    "4. Did the named investors take part in THIS round, or an earlier one?\n\n"
    "Answer only from the text you are given. If the text does not settle a "
    "question, say so: confirmed must mean the text says it, not that it "
    "sounds right. Where you propose a change, quote the sentence from the "
    "text that supports it, exactly as written. No quote, no change.\n\n"
    "Return verdict 'confirms' when the source supports what is recorded, "
    "'contradicts' when it says otherwise, and 'insufficient' when the text "
    "does not answer. Propose changes only for a contradiction."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string",
                    "enum": ["confirms", "contradicts", "insufficient"]},
        "quote": {"type": "string"},
        "reasoning": {"type": "string"},
        "changes": {
            "type": "object",
            "properties": {
                "stage": {"type": "string"},
                "status": {"type": "string"},
                "amount": {"type": "string"},
                "amount_note": {"type": "string"},
                "investors": {"type": "string"},
                "lead_investor": {"type": "string"},
                "location": {"type": "string"},
            },
            "required": ["stage", "status", "amount", "amount_note",
                         "investors", "lead_investor", "location"],
            "additionalProperties": False,
        },
    },
    "required": ["verdict", "quote", "reasoning", "changes"],
    "additionalProperties": False,
}


def candidate_sources(company: str, stage: str, limit: int = 4) -> list:
    """Addresses that might carry the primary account of this round."""
    import feedparser

    query = urllib.parse.quote(f'"{company}" {stage or "funding round"}')
    feed = (f"https://news.google.com/rss/search?q={query}"
            f"&hl=en-CH&gl=CH&ceid=CH:en")
    try:
        parsed = feedparser.parse(feed)
    except Exception:
        return []

    found = []
    for entry in parsed.entries[:12]:
        link = entry.get("link", "")
        if is_google_news_url(link):
            link = resolve_url(link) or link
        if link and link not in found:
            found.append(link)
    # A company release beats a write-up of one.
    found.sort(key=lambda u: 0 if any(p in u for p in _PREFERRED) else 1)
    return found[:limit]


def _is_about(company: str, text: str) -> bool:
    """Is this page about the company we asked about?

    The first pass searched for Prem and read QueryAI's release, because the
    check was a substring: "prem" sits inside "premier", "premises" and
    "premium". It then proposed moving a Swiss company to South Dakota. The
    name has to appear as a word, and near the top where a story names its
    subject, not once in passing halfway down.
    """
    import re

    name = (company or "").strip()
    if len(name) < 3:
        return False
    # Try the full name first, then the distinctive part of it.
    candidates = [name]
    first = name.split()[0]
    if len(first) >= 4:
        candidates.append(first)
    head = text[:800].lower()
    for candidate in candidates:
        pattern = re.compile(rf"\b{re.escape(candidate.lower())}\b")
        if pattern.search(head) and len(pattern.findall(text.lower())) >= 2:
            return True
    return False


def _ask(claim: dict, text: str, model: str | None = None):
    """One source, one verdict. None when the call fails."""
    try:
        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL),
            max_tokens=2000,
            system=SYSTEM,
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": _SCHEMA}},
            messages=[{"role": "user", "content":
                       f"Recorded: {json.dumps(claim, ensure_ascii=False)}\n\n"
                       f"Source text:\n{text[:9000]}"}],
        )
        if getattr(response, "stop_reason", "") == "refusal":
            return None
        body = "".join(b.text for b in response.content
                       if getattr(b, "type", "") == "text")
        return json.loads(body)
    except Exception as exc:
        print(f"    check failed: {type(exc).__name__}: {str(exc)[:120]}",
              file=sys.stderr)
        return None


def check(entry: dict, model: str | None = None) -> dict:
    """Check one queued round. Returns a proposal, or {} when nothing is settled."""
    company = entry.get("company", "")
    claim = entry.get("as_recorded", {})
    print(f"  {company}...", file=sys.stderr)

    for url in candidate_sources(company, claim.get("stage", "")):
        text = article_text(url, limit=9000)
        if not text or len(text) < 400:
            continue
        if not _is_about(company, text):
            continue  # somebody else's story
        answer = _ask(claim, text, model)
        if not answer:
            continue
        quote = (answer.get("quote") or "").strip()
        if answer["verdict"] == "insufficient" or not quote:
            continue
        # The quote has to be in the text. A sentence that is not there is not
        # evidence, whatever the verdict says.
        if quote[:60].lower() not in text.lower():
            print(f"    quote not found in the source, ignoring", file=sys.stderr)
            continue

        proposal = {
            "verified": dt.date.today().isoformat(),
            "verified_source": urllib.parse.urlsplit(url).netloc.replace("www.", ""),
            "verified_quote": quote[:400],
            "source_url": url,
            "verified_by": "automated weekly check",
        }
        if answer["verdict"] == "contradicts":
            from extract import STAGES

            for field, value in (answer.get("changes") or {}).items():
                value = (value or "").strip()
                if not value or value == (claim.get(field) or "").strip():
                    continue
                # An invented stage would fail the corrections tests later; it
                # is better refused here than proposed and rejected.
                if field == "stage" and value not in STAGES:
                    print(f"    ignoring an unknown stage {value!r}",
                          file=sys.stderr)
                    continue
                proposal[field] = value
        print(f"    {answer['verdict']} via {proposal['verified_source']}",
              file=sys.stderr)
        return proposal

    print(f"    no primary source reached", file=sys.stderr)
    return {}


def run(queue_path: str, out_path: str, limit: int = 8,
        model: str | None = None) -> dict:
    """Work the queue and write proposals. Returns a summary."""
    with open(queue_path, encoding="utf-8") as f:
        queue = json.load(f).get("rounds", [])

    try:
        with open(out_path, encoding="utf-8") as f:
            existing = json.load(f)
    except Exception:
        existing = {"proposals": {}}

    proposals = existing.get("proposals", {})
    checked, proposed, unreachable = 0, 0, []
    for entry in queue[:limit]:
        checked += 1
        found = check(entry, model)
        if found:
            proposals[entry["company"]] = found
            proposed += 1
        else:
            unreachable.append(entry["company"])

    existing["proposals"] = proposals
    existing["last_run"] = dt.date.today().isoformat()
    existing["could_not_verify"] = unreachable
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    print(f"\nChecked {checked}, proposed {proposed}, "
          f"could not reach a source for {len(unreachable)}: "
          f"{', '.join(unreachable) or 'none'}", file=sys.stderr)
    return {"checked": checked, "proposed": proposed, "unreachable": unreachable}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Work the verification queue")
    ap.add_argument("--queue", default="../digest/verify.json")
    ap.add_argument("--out", default="proposals.json")
    ap.add_argument("--limit", type=int, default=8)
    args = ap.parse_args()
    run(args.queue, args.out, args.limit)
