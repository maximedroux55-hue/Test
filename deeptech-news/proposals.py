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


def _read(path: str) -> dict:
    """Parse the file, loudly. A broken file is not an empty one.

    A check once appended its report after the closing brace, leaving two JSON
    objects in the file. Every reader here caught the parse error and returned
    nothing, so the review page said "nothing waiting" and the finding was
    invisible. Silence is the one answer this file must never give.
    """
    import sys

    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        print(f"proposals.json will not parse ({exc}). Findings in it are "
              f"being ignored until it is valid JSON again.", file=sys.stderr)
        raise


def load(path: str = PATH) -> dict:
    """Return {company: {field: value, ...}} of pending proposals."""
    raw = _read(path)
    entries = raw.get("proposals", {})
    return entries if isinstance(entries, dict) else {}


def promote(corrections_path: str, path: str = PATH) -> list:
    """Move accepted proposals into corrections. Returns the names moved.

    A proposal is accepted by setting "accepted": true on it, either by Max on
    the review page or by asking. Nothing moves on its own: an untouched
    proposal stays where it is however long it sits there.
    """
    import sys

    raw = _read(path)
    try:
        with open(corrections_path, encoding="utf-8") as f:
            corrections = json.load(f)
    except Exception:
        return []

    pending = raw.get("proposals", {})
    accepted = [c for c, fields in pending.items()
                if isinstance(fields, dict) and fields.get("accepted") is True]
    if not accepted:
        return []

    for company in accepted:
        fields = pending.pop(company)
        entry = corrections["companies"].get(company, {})
        url = (fields.get("source_url") or "").strip()
        for key, value in fields.items():
            if key in ("source_url", "accepted"):
                continue
            entry[key] = value
        if url:
            entry["verified_source"] = (
                f"{fields.get('verified_source', '')} — {url}".strip(" —"))
        corrections["companies"][company] = entry

    raw["proposals"] = pending
    raw.setdefault("accepted_log", {})
    import datetime as _dt
    raw["accepted_log"][_dt.date.today().isoformat()] = sorted(accepted)

    with open(corrections_path, "w", encoding="utf-8") as f:
        json.dump(corrections, f, ensure_ascii=False, indent=2)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
    print(f"Accepted {len(accepted)} proposals: {', '.join(sorted(accepted))}",
          file=sys.stderr)
    return sorted(accepted)


# Editing the file straight from a phone, for when asking is more trouble.
EDIT_URL = ("https://github.com/maximedroux55-hue/Test/edit/"
            "claude/questions-9a5egd/deeptech-news/proposals.json")


def render(pending: dict, current: dict) -> str:
    """A page to read the proposals on, with what each would change."""
    if not pending:
        rows = ('<tr><td colspan="5" class="nd">Nothing waiting. The queue is '
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
                f'<tr><td class="pick"><label>'
                f'<input type="checkbox" value="{html.escape(company)}" '
                f'onchange="pick()"> accept</label></td>'
                f'<td class="co">{html.escape(company)}</td>'
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
  td.pick {{ white-space:nowrap; }}
  td.pick label {{ display:flex; gap:0.35rem; align-items:center;
                  font-size:0.78rem; color:var(--soft); cursor:pointer; }}
  .accept {{ background:#fff; border:1px solid var(--line); border-radius:14px;
            padding:1rem 1.1rem; margin-top:1.2rem; }}
  .acc-head {{ font-size:0.9rem; color:var(--soft); margin-bottom:0.5rem; }}
  textarea {{ width:100%; border:1px solid var(--line); border-radius:10px;
             padding:0.6rem 0.7rem; font-family:inherit; font-size:0.88rem;
             color:var(--ink); resize:vertical; }}
  .acc-row {{ display:flex; gap:0.5rem; margin-top:0.6rem; flex-wrap:wrap; }}
  button, .btn {{ font-family:inherit; font-size:0.85rem; font-weight:600;
                 border:1px solid var(--line); background:var(--bg);
                 color:var(--ink); border-radius:10px; padding:0.5rem 0.9rem;
                 cursor:pointer; text-decoration:none; }}
  button:hover, .btn:hover {{ border-color:var(--green); color:var(--green); }}
  code {{ background:var(--bg); padding:0.05rem 0.3rem; border-radius:4px; }}
</style></head><body>
<div class="wrap">
  <h1>Proposed corrections<span class="dot">.</span></h1>
  <p class="sub">Found by the weekly check, waiting to be accepted. Nothing here
  is in the database yet.</p>
  <div class="box"><table>
    <thead><tr><th></th><th>Company</th><th>Would change</th><th>Because it read</th>
      <th>Source</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
  <div class="accept" id="accept" hidden>
    <div class="acc-head">Accepting <b id="count">0</b></div>
    <textarea id="out" readonly rows="3"></textarea>
    <div class="acc-row">
      <button type="button" onclick="copyIt()">Copy</button>
      <a class="btn" href="{EDIT_URL}" target="_blank" rel="noopener">Edit the file on GitHub</a>
    </div>
    <p class="note">Send the copied line to Claude or to Cowork, or open the file
    and set <code>"accepted": true</code> on the ones you want. Either way the
    next run moves them into corrections.json, where they apply to the whole
    database and cannot be overruled.</p>
  </div>
  <p class="note">A proposal with nothing quoted, or no source, should be
  refused: the evidence is the only reason to believe a check that a machine
  ran on itself.</p>
  <p class="note"><a href="/digest/archive.html">&larr; the database</a></p>
</div>
<script>
  function picked() {{
    return Array.prototype.slice
      .call(document.querySelectorAll('input[type=checkbox]:checked'))
      .map(function (b) {{ return b.value; }});
  }}
  function pick() {{
    var names = picked();
    var box = document.getElementById('accept');
    box.hidden = names.length === 0;
    document.getElementById('count').textContent = names.length;
    document.getElementById('out').value =
      'Accept the proposed corrections for: ' + names.join(', ') + '.';
  }}
  function copyIt() {{
    var out = document.getElementById('out');
    out.select();
    navigator.clipboard.writeText(out.value);
  }}
</script>
</body></html>
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
