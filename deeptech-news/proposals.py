"""What an automated check found, waiting for Max to accept it.

corrections.json overrules the whole pipeline, so nothing writes to it without
being read first. An automated verification pass writes here instead: what it
believes is wrong, the sentence it read, and where it read it. The file is
inert. Nothing in it reaches the database until it is moved across.

That keeps the useful part of automation, which is doing the reading every
week without anyone asking, and keeps the part that needs a person, which is
deciding whether a source actually says what a machine thinks it says.
"""

from __future__ import annotations

import html
import json
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proposals.json")


def load(path: str = PATH) -> dict:
    """Return {company: {field: value, ...}} of pending proposals."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}
    entries = raw.get("proposals", {})
    return entries if isinstance(entries, dict) else {}


def render(pending: dict, current: dict) -> str:
    """A page to read the proposals on, with what each would change."""
    if not pending:
        rows = ('<tr><td colspan="4" class="nd">Nothing waiting. The queue is '
                'either empty or the last pass found nothing to change.</td></tr>')
    else:
        rows = []
        for company, fields in sorted(pending.items()):
            now = current.get(company, {})
            changes = []
            for key, value in fields.items():
                if key in ("verified_quote", "verified_by", "verified_source",
                           "verified", "source_url"):
                    continue
                was = (now.get(key) or "").strip() or "&mdash;"
                changes.append(
                    f'<div class="ch"><b>{html.escape(key)}</b>: '
                    f'<span class="was">{html.escape(was) if was != "&mdash;" else was}</span> '
                    f'&rarr; <span class="now">{html.escape(value) or "<em>cleared</em>"}</span></div>')
            quote = (fields.get("verified_quote") or "").strip()
            source = (fields.get("verified_source") or "").strip()
            url = (fields.get("source_url") or "").strip()
            link = (f'<a href="{html.escape(url)}" target="_blank" '
                    f'rel="noopener">{html.escape(source or url)}</a>'
                    if url else html.escape(source))
            rows.append(
                f'<tr><td class="co">{html.escape(company)}</td>'
                f'<td>{"".join(changes) or "<span class=nd>verification only</span>"}</td>'
                f'<td class="q">{html.escape(quote) or "<span class=nd>nothing quoted</span>"}</td>'
                f'<td class="s">{link or "<span class=nd>no source</span>"}</td></tr>')
        rows = "\n".join(rows)

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Proposed corrections</title><meta name="robots" content="noindex">
<style>
  :root {{ --green:#46b96a; --ink:#1b2430; --soft:#5b6472; --faint:#9aa3ad;
          --line:#e6eae8; --bg:#f6f8f7; }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
         background:var(--bg); color:var(--ink); line-height:1.6; }}
  .wrap {{ max-width:1100px; margin:0 auto; padding:2.5rem 1.25rem 4rem; }}
  h1 {{ font-size:1.7rem; letter-spacing:-0.02em; }} h1 .dot {{ color:var(--green); }}
  .sub {{ color:var(--soft); margin:0.4rem 0 1.5rem; font-size:0.92rem; }}
  .box {{ background:#fff; border:1px solid var(--line); border-radius:14px;
         overflow-x:auto; }}
  table {{ width:100%; border-collapse:collapse; font-size:0.86rem; }}
  th, td {{ text-align:left; padding:0.7rem 0.8rem; border-bottom:1px solid var(--line);
           vertical-align:top; }}
  th {{ color:var(--soft); font-size:0.72rem; text-transform:uppercase;
       letter-spacing:0.04em; }}
  tr:last-child td {{ border-bottom:none; }}
  td.co {{ font-weight:600; white-space:nowrap; }}
  td.q {{ color:var(--soft); font-style:italic; max-width:30rem; }}
  td.s {{ white-space:nowrap; }}
  .ch {{ margin-bottom:0.2rem; }}
  .was {{ color:var(--faint); text-decoration:line-through; }}
  .now {{ color:var(--ink); font-weight:600; }}
  .nd {{ color:var(--faint); }}
  a {{ color:var(--ink); }} a:hover {{ color:var(--green); }}
  .note {{ color:var(--faint); font-size:0.8rem; margin-top:1.2rem; }}
</style></head><body>
<div class="wrap">
  <h1>Proposed corrections<span class="dot">.</span></h1>
  <p class="sub">Found by the weekly check, waiting to be accepted. Nothing here
  is in the database yet.</p>
  <div class="box"><table>
    <thead><tr><th>Company</th><th>Would change</th><th>Because it read</th>
      <th>Source</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
  <p class="note">Tell Claude which to accept and they move into
  corrections.json, where they apply to the whole database and cannot be
  overruled. A proposal with nothing quoted, or no source, should be refused:
  the evidence is the only reason to believe an automated check.</p>
  <p class="note"><a href="/digest/archive.html">&larr; the database</a></p>
</div></body></html>
"""


def write_page(path: str, current: dict) -> int:
    """Write the review page. Returns how many proposals are waiting."""
    import sys

    pending = load()
    with open(path, "w", encoding="utf-8") as f:
        f.write(render(pending, current))
    if pending:
        print(f"{len(pending)} proposed corrections waiting at {path}",
              file=sys.stderr)
    return len(pending)
