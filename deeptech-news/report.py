"""A month of Swiss DeepTech financing, written up from the database.

The table answers "what happened". A report answers "what does it amount to",
and the answers that matter are the ones a total hides: whether the month's
capital was two deals or twenty, whether the busy end and the expensive end are
the same end, and how much of the deal flow came out of a laboratory.

Everything here is computed from the rounds themselves. Where the data cannot
support a claim the report says so rather than reaching, which is why the
caveats are on the page and not in a footnote.
"""

from __future__ import annotations

import calendar
import collections
import datetime as dt
import html
import statistics

import money

# Stages that are venture capital, as opposed to a listing or a public grant.
_VENTURE = {"Pre-seed", "Seed", "Series A", "Series B", "Series C", "Series D",
            "Growth"}
_EARLY = {"Pre-seed", "Seed"}


def _month_name(month: str) -> str:
    year, mon = int(month[:4]), int(month[5:7])
    return f"{calendar.month_name[mon]} {year}"


def analyse(rounds: list, month: str) -> dict:
    """Everything the report states, worked out once."""
    from scraper import _investor_line

    inside = [r for r in rounds
              if (r.get("published") or r.get("first_seen") or "").startswith(month)]
    inside.sort(key=lambda r: money.in_chf(r.get("amount", "")), reverse=True)

    amounts = [money.in_chf(r.get("amount", "")) for r in inside
               if money.in_chf(r.get("amount", ""))]
    total = sum(amounts)

    # A total carried by one or two deals says something different from the
    # same total spread across twenty.
    top_two = sum(amounts[:2]) if len(amounts) >= 2 else total
    concentration = round(100 * top_two / total) if total else 0

    venture = [r for r in inside if (r.get("stage") or "") in _VENTURE]
    venture_total = sum(money.in_chf(r.get("amount", "")) for r in venture)
    early = [r for r in inside if (r.get("stage") or "") in _EARLY]
    early_total = sum(money.in_chf(r.get("amount", "")) for r in early)

    def tally(field):
        counts = collections.Counter()
        sums = collections.Counter()
        for r in inside:
            key = (r.get(field) or "not stated").strip() or "not stated"
            counts[key] += 1
            sums[key] += money.in_chf(r.get("amount", ""))
        return [(k, counts[k], sums[k])
                for k in sorted(counts, key=lambda k: (-counts[k], -sums[k]))]

    investors = collections.Counter()
    for r in inside:
        for name in _investor_line(r).split(","):
            name = name.strip()
            if name:
                investors[name] += 1

    spinoffs = collections.Counter(
        (r.get("spinoff_origin") or "").strip() for r in inside
        if (r.get("spinoff_origin") or "").strip())

    return {
        "month": month,
        "label": _month_name(month),
        "rounds": inside,
        "count": len(inside),
        "priced": len(amounts),
        "total": total,
        "median": statistics.median(amounts) if amounts else 0,
        "mean": sum(amounts) / len(amounts) if amounts else 0,
        "largest": inside[0] if inside else None,
        "concentration": concentration,
        "venture_count": len(venture),
        "venture_total": venture_total,
        "early_count": len(early),
        "early_total": early_total,
        "early_share": round(100 * early_total / total) if total else 0,
        "by_sector": tally("category"),
        "by_stage": tally("stage"),
        "by_city": tally("location"),
        "investors": investors,
        "repeat": [(k, v) for k, v in investors.most_common() if v > 1],
        "spinoffs": spinoffs,
        "spinoff_count": sum(spinoffs.values()),
        "with_investors": sum(1 for r in inside if _investor_line(r)),
        "with_founders": sum(1 for r in inside
                             if (r.get("founders") or "").strip()),
    }


def _table(rows: list, heading: str) -> str:
    if not rows:
        return ""
    out = [f'<h3>{heading}</h3><table class="mini">']
    for name, count, amount in rows:
        out.append(
            f'<tr><td>{html.escape(name)}</td>'
            f'<td class="n">{count}</td>'
            f'<td class="a">{money.compact(amount) or "&ndash;"}</td></tr>')
    out.append("</table>")
    return "".join(out)


def render(stats: dict) -> str:
    """The month as a page."""
    from scraper import _investor_line

    if not stats["count"]:
        return ""

    rows = []
    for r in stats["rounds"]:
        rows.append(
            f'<tr><td class="co"><a href="{html.escape(r.get("link",""))}" '
            f'target="_blank" rel="noopener">'
            f'{html.escape(r.get("company") or "?")}</a></td>'
            f'<td>{html.escape(r.get("category") or "")}</td>'
            f'<td>{html.escape(r.get("stage") or "&ndash;")}</td>'
            f'<td class="a">{html.escape(r.get("amount") or "undisclosed")}</td>'
            f'<td>{html.escape((_investor_line(r) or "&ndash;")[:60])}</td>'
            f'<td>{html.escape(r.get("location") or "CH")}</td></tr>')

    largest = stats["largest"]
    lead = ""
    if largest and money.in_chf(largest.get("amount", "")):
        lead = (f'{html.escape(largest.get("company",""))}\'s '
                f'{html.escape((largest.get("stage") or "round").lower())} of '
                f'{html.escape(largest.get("amount",""))}')

    # The sentences that follow are the ones the numbers actually support.
    notes = []
    if stats["concentration"] >= 60 and stats["priced"] >= 3:
        notes.append(
            f"The two largest deals are {stats['concentration']}% of the "
            f"month's capital, so the total describes a handful of companies "
            f"rather than the market.")
    if stats["median"] and stats["mean"] > stats["median"] * 2:
        notes.append(
            f"The median round is {money.compact(stats['median'])} against a "
            f"mean of {money.compact(stats['mean'])}. The gap is the month in "
            f"one line: a long tail of small rounds under a few large ones.")
    if stats["early_count"] and stats["total"]:
        notes.append(
            f"{stats['early_count']} of {stats['count']} rounds were pre-seed "
            f"or seed, and together they drew {stats['early_share']}% of the "
            f"capital. The formation end is busy and cheap.")
    if stats["spinoff_count"]:
        origins = ", ".join(f"{k} {v}" for k, v in stats["spinoffs"].most_common())
        notes.append(
            f"{stats['spinoff_count']} of {stats['count']} rounds came out of "
            f"an institution ({origins}), which is the structural feature of "
            f"this market rather than a feature of the month.")
    if stats["repeat"]:
        names = ", ".join(f"<b>{html.escape(k)}</b>" for k, _ in stats["repeat"])
        notes.append(
            f"{len(stats['investors'])} distinct investors were named across "
            f"{stats['with_investors']} rounds. Only {len(stats['repeat'])} "
            f"appear more than once: {names}.")
    elif stats["with_investors"]:
        notes.append(
            f"{len(stats['investors'])} distinct investors were named across "
            f"{stats['with_investors']} rounds, none of them twice. No fund "
            f"built a visible position this month.")

    unpriced = stats["count"] - stats["priced"]
    caveat = (
        f"{unpriced} of {stats['count']} rounds have no stated amount, so "
        f"{money.compact(stats['total'])} is a floor rather than a total. "
        if unpriced else "")
    caveat += (
        f"The database records what the press carried, so undisclosed rounds "
        f"and quiet extensions do not reach it, and "
        f"{stats['with_investors']} of {stats['count']} rounds name their "
        f"investors. This is reported activity, not a market census, and one "
        f"month is too short to read as a trend.")

    body = "".join(f"<p>{n}</p>" for n in notes)
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Swiss DeepTech, {stats['label']}</title><meta name="robots" content="noindex">
<style>
  :root {{ --green:#46b96a; --ink:#1b2430; --soft:#5b6472; --faint:#9aa3ad;
          --line:#e6eae8; --bg:#f6f8f7; }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
         background:var(--bg); color:var(--ink); line-height:1.6; }}
  .wrap {{ max-width:780px; margin:0 auto; padding:2.5rem 1.25rem 4rem; }}
  h1 {{ font-size:1.9rem; letter-spacing:-0.02em; }} h1 .dot {{ color:var(--green); }}
  h2 {{ font-size:1.05rem; margin:2.2rem 0 0.6rem; letter-spacing:-0.01em; }}
  h3 {{ font-size:0.8rem; color:var(--soft); text-transform:uppercase;
       letter-spacing:0.05em; margin:1.4rem 0 0.5rem; }}
  .sub {{ color:var(--soft); margin:0.4rem 0 1.5rem; font-size:0.92rem; }}
  p {{ margin:0 0 0.9rem; }}
  .stats {{ display:flex; flex-wrap:wrap; gap:0.6rem; margin:0 0 1.5rem; }}
  .stat {{ background:#fff; border:1px solid var(--line); border-radius:12px;
          padding:0.7rem 1rem; flex:1 1 auto; min-width:8rem; }}
  .stat b {{ display:block; font-size:1.4rem; letter-spacing:-0.02em; }}
  .stat span {{ color:var(--soft); font-size:0.72rem; text-transform:uppercase;
               letter-spacing:0.04em; }}
  .box {{ background:#fff; border:1px solid var(--line); border-radius:14px;
         overflow-x:auto; margin:0.8rem 0 1.4rem; }}
  table {{ width:100%; border-collapse:collapse; font-size:0.86rem; }}
  td, th {{ text-align:left; padding:0.55rem 0.75rem;
           border-bottom:1px solid var(--line); vertical-align:top; }}
  tr:last-child td {{ border-bottom:none; }}
  td.co {{ font-weight:600; white-space:nowrap; }}
  td.a {{ white-space:nowrap; font-weight:600; }}
  td.n {{ width:3rem; color:var(--soft); }}
  table.mini {{ background:#fff; border:1px solid var(--line); border-radius:12px; }}
  table.mini td.a {{ text-align:right; color:var(--soft); font-weight:500; }}
  a {{ color:var(--ink); }} a:hover {{ color:var(--green); }}
  .caveat {{ background:#fff; border:1px solid var(--line); border-left:3px solid var(--faint);
            border-radius:10px; padding:0.9rem 1.1rem; color:var(--soft);
            font-size:0.86rem; margin-top:2rem; }}
  .back {{ display:inline-block; margin-top:2rem; font-size:0.86rem;
          color:var(--soft); text-decoration:none; }}
</style></head><body>
<div class="wrap">
  <h1>Swiss DeepTech, {stats['label']}<span class="dot">.</span></h1>
  <p class="sub">{stats['count']} financing rounds recorded.
  {"Largest: " + lead + "." if lead else ""}</p>
  <div class="stats">
    <div class="stat"><b>{stats['count']}</b><span>rounds</span></div>
    <div class="stat"><b>{money.compact(stats['total']) or "&ndash;"}</b><span>capital</span></div>
    <div class="stat"><b>{money.compact(stats['median']) or "&ndash;"}</b><span>median</span></div>
    <div class="stat"><b>{stats['venture_count']}</b><span>venture rounds</span></div>
    <div class="stat"><b>{stats['spinoff_count']}</b><span>spin-offs</span></div>
  </div>

  <h2>What the numbers say</h2>
  {body}

  <h2>The rounds</h2>
  <div class="box"><table>
    <thead><tr><th>Company</th><th>Sector</th><th>Stage</th><th>Raised</th>
      <th>Investors</th><th>HQ</th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table></div>

  {_table(stats['by_stage'], 'By stage')}
  {_table(stats['by_sector'], 'By sector')}
  {_table(stats['by_city'], 'By city')}

  <div class="caveat">{caveat}</div>
  <a class="back" href="/digest/archive.html">&larr; the full database</a>
</div></body></html>
"""


def render_index(months: list) -> str:
    """A list of the months that have a report."""
    items = "".join(
        f'<li><a href="/reports/{m["month"]}.html">{m["label"]}</a>'
        f'<span> {m["count"]} rounds &middot; '
        f'{money.compact(m["total"]) or "&ndash;"}</span></li>'
        for m in months)
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Swiss DeepTech monthly reports</title><meta name="robots" content="noindex">
<style>
  :root {{ --green:#46b96a; --ink:#1b2430; --soft:#5b6472; --line:#e6eae8; --bg:#f6f8f7; }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
         background:var(--bg); color:var(--ink); line-height:1.6; }}
  .wrap {{ max-width:640px; margin:0 auto; padding:2.5rem 1.25rem 4rem; }}
  h1 {{ font-size:1.7rem; letter-spacing:-0.02em; }} h1 .dot {{ color:var(--green); }}
  .sub {{ color:var(--soft); margin:0.4rem 0 1.5rem; font-size:0.92rem; }}
  ul {{ list-style:none; background:#fff; border:1px solid var(--line);
       border-radius:14px; overflow:hidden; }}
  li {{ border-bottom:1px solid var(--line); padding:0.9rem 1.1rem;
       display:flex; justify-content:space-between; gap:1rem; align-items:baseline; }}
  li:last-child {{ border-bottom:none; }}
  li span {{ color:var(--soft); font-size:0.84rem; white-space:nowrap; }}
  a {{ color:var(--ink); text-decoration:none; font-weight:600; }}
  a:hover {{ color:var(--green); }}
  .back {{ display:inline-block; margin-top:2rem; font-size:0.86rem;
          color:var(--soft); font-weight:400; }}
</style></head><body>
<div class="wrap">
  <h1>Swiss DeepTech monthly<span class="dot">.</span></h1>
  <p class="sub">One report per month, written from the deal database.</p>
  <ul>{items or '<li>No month has enough rounds yet.</li>'}</ul>
  <a class="back" href="/digest/archive.html">&larr; the full database</a>
</div></body></html>
"""


def write_all(rounds: list, outdir: str) -> list:
    """Write a report for every month with rounds. Returns what was written."""
    import os
    import sys

    months = sorted({(r.get("published") or r.get("first_seen") or "")[:7]
                     for r in rounds if (r.get("published") or r.get("first_seen"))},
                    reverse=True)
    os.makedirs(outdir, exist_ok=True)
    written = []
    today = dt.date.today().strftime("%Y-%m")
    for month in months:
        stats = analyse(rounds, month)
        # A month still running is reported too, but a report is only worth a
        # page once there is something to compare within it.
        if stats["count"] < 2:
            continue
        page = render(stats)
        if not page:
            continue
        with open(os.path.join(outdir, f"{month}.html"), "w",
                  encoding="utf-8") as f:
            f.write(page)
        written.append({"month": month, "label": stats["label"],
                        "count": stats["count"], "total": stats["total"],
                        "running": month == today})
    with open(os.path.join(outdir, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_index(written))
    if written:
        print(f"Wrote {len(written)} monthly reports to {outdir}",
              file=sys.stderr)
    return written
