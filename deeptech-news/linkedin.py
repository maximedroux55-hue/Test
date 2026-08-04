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
    elif article.get("coverage_url"):
        # Linking to the company's own announcement, so name no outlet.
        body = f"{_FLAG} The announcement lands{where}. {bucket['sig']}{deal}"
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


# A standing instruction to paste into Claude Cowork. It drives the existing
# Cowork + Chrome workflow off the structured posts.json, so the whole week gets
# scheduled from one prompt.
COWORK_PROMPT = (
    "Open https://maxime-droux.com/digest/posts.json and schedule this week's "
    "posts.\n\n"
    "For each post, in order:\n"
    "- Type the `text` straight through, once, with real keystrokes. Never "
    "insert\n"
    "  text via JavaScript. It already ends with the article URL on its own "
    "line,\n"
    "  so do not add, move or retype the URL separately: typing it last is what "
    "makes\n"
    "  the link preview load the article photo.\n"
    "- Each post has exactly one @mention. Type `mention.type`, wait for the\n"
    "  dropdown, click the row matching `mention.expect`. If no row matches, "
    "post\n"
    "  it without the mention rather than tagging the wrong company. LinkedIn "
    "will\n"
    "  render the official name: that is expected and fine, do not fight it, "
    "do not\n"
    "  restart the post, do not rewrite it.\n"
    "- Schedule at `time` on `date`. If no link preview appears, schedule it "
    "anyway:\n"
    "  do not hunt for an image.\n\n"
    "Two attempts per post, then stop. If a post is not scheduled after two "
    "tries,\n"
    "leave it, move to the next one, and list it at the end. Never start a "
    "third.\n\n"
    "Before you start, open the scheduled-posts list once and note what is "
    "already\n"
    "there. Skip any post already scheduled: never schedule the same one "
    "twice.\n\n"
    "Verification:\n"
    "- Claims already settled against the article are not in the file. Check "
    "only\n"
    "  what `claims` still lists, and posts with needs_check: true (a figure "
    "nobody\n"
    "  has verified: confirm round closed / round name / amount received / "
    "investors\n"
    "  in THIS round). Both empty and false means schedule it, no research.\n\n"
    "Anything that fails: do not schedule it, and do not edit any file or "
    "commit\n"
    "anything. List the held posts at the end with the sentence you read and "
    "the\n"
    "page you read it on, and I will record them.\n\n"
    "Report what was scheduled and what was held."
)

# Post scheduling time (local). Kept here so the JSON, the Markdown, and the
# Cowork prompt always agree.
POST_TIME = "08:00"

# The Cloudflare Worker that triggers a fresh run when the page button is tapped.
# It holds the GitHub token; the page only pings this URL.
RUN_URL = "https://md-news-button.maxime-droux55.workers.dev/"


def _claims_in(text: str, art: dict) -> list:
    """The factual assertions a post makes, so they can be checked one by one.

    Written from the post rather than from the database, because what needs
    checking is what the post says, not what we meant it to say.
    """
    import re

    amounts = re.compile(
        r"(?:CHF|USD|EUR|GBP)\s?[\d.,\']+\s?(?:m|bn|k|million|billion)?"
        r"|[$€£]\s?[\d.,\']+\s?(?:m|bn|k|million|billion)?", re.IGNORECASE)
    rounds = re.compile(r"\b(pre-?seed|seed|series\s+[a-e])\b", re.IGNORECASE)

    claims = []
    company = (art.get("company") or "").strip()
    if company:
        claims.append(f"the company is {company}")
    for found in dict.fromkeys(m.group(0).strip() for m in amounts.finditer(text or "")):
        claims.append(f"the post states {found}: is that money received rather "
                      f"than a ceiling or a target, and has the round closed")
    for found in dict.fromkeys(m.group(0).strip().lower()
                               for m in rounds.finditer(text or "")):
        claims.append(f"the post calls it a {found}: is that the right name "
                      f"for this transaction")
    investors = (art.get("investors") or "").strip()
    if investors:
        named = [n.strip() for n in investors.split(",") if n.strip()]
        mentioned = [n for n in named if n.lower() in (text or "").lower()]
        if mentioned:
            claims.append(f"the post names {', '.join(mentioned)}: did they "
                          f"take part in this round rather than an earlier one")
    return claims


# A brand, a trading name or a division is not the company, and tagging it
# points the @mention at the wrong entity. Where the article says so, the
# question of who the company is stays open for someone to read.
_BRAND_OF = re.compile(
    r"\b(?:eine\s+marke\s+(?:der|von)|marke\s+der|a\s+brand\s+of|"
    r"brand\s+(?:of|owned\s+by)|une\s+marque\s+de|un\s+marchio\s+di|"
    r"trading\s+as|division\s+of|dba)\b", re.IGNORECASE)


def settle_claims(claims: list, art: dict, checked: dict) -> tuple:
    """Split a post's claims into what the article already settles and what not.

    Every claim Cowork checks means opening a page in a browser session, which
    is the most expensive way this workflow spends a token. The article text is
    already downloaded by then, so a claim whose words are plainly in it does
    not need a second reading.

    What stays is what a machine reading one page cannot settle: an amount on a
    round nobody has verified, a stage the article never names, an investor it
    does not mention. Those are exactly the ones that have gone wrong before,
    and they still get an independent read.
    """
    if checked:
        # Already read against a primary source, so there is nothing left for a
        # browser session to add, whatever the article does or does not say.
        return [], list(claims)

    text = ((art.get("fulltext") or "") + " "
            + (art.get("summary") or "")).lower()
    if not text.strip():
        # Nothing was read, so nothing is settled. Silence is not confirmation.
        return list(claims), []

    settled, remaining = [], []
    for claim in claims:
        # A name appearing in the article does not make it the company. The
        # Humboldt AI post tagged a brand: "Humboldt AI, eine Marke der Raetica
        # Innovation Labs GmbH". The words were all there, so a plain text
        # match would have settled it and lost the catch that mattered.
        if claim.startswith("the company is ") and _BRAND_OF.search(text):
            remaining.append(claim)
            continue
        subject = claim.split(":")[0]
        # The quoted fact sits after "the company is" / "the post states" /
        # "the post calls it a" / "the post names".
        for lead in ("the company is ", "the post states ",
                     "the post calls it a ", "the post names "):
            if subject.startswith(lead):
                facts = subject[len(lead):]
                break
        else:
            remaining.append(claim)
            continue

        # An amount is only settled when the round has closed as well: the
        # figure appearing in the text is what a ceiling on an unclosed deal
        # does too, which is how Terra Quantum got counted.
        if claim.startswith("the post states ") and \
                (art.get("status") or "").strip().lower() == "announced":
            remaining.append(claim)
            continue

        parts = [p.strip().lower() for p in facts.split(",") if p.strip()]
        if parts and all(re.search(r"\b" + re.escape(p) + r"\b", text)
                         for p in parts):
            settled.append(claim)
        else:
            remaining.append(claim)

    return remaining, settled


def schedule_days(today, count: int, full_week: int = 7) -> list:
    """Dates to post on, one per post, starting the day after the run.

    A full week of posts fills every day, weekend included, because there is
    nowhere else to put the seventh. A short week is spread over working days
    only and the weekend is left blank: a quiet Saturday reads as a pause, a
    thin Saturday reads as a thin week.
    """
    import datetime as dt

    days, day = [], today
    while len(days) < count:
        day += dt.timedelta(days=1)
        if count < full_week and day.weekday() >= 5:
            continue
        days.append(day)
    return days


def build_posts(articles: list, days: int, top: int = 7):
    """Build the week's posts once. Returns (records, mode).

    Each record is a self-contained dict ready for both the human-readable
    Markdown and the machine-readable posts.json, so the AI writer runs only
    once per digest. Posts are dated one per day starting the day after the run
    (a Wednesday run plans Thursday through the next Wednesday). Short weeks
    skip the weekend, see schedule_days.
    """
    import datetime as dt
    from ai_writer import generate_posts

    today = dt.date.today()
    picks = articles[:top]

    ai_posts = generate_posts(picks, days)
    if ai_posts:
        texts = ai_posts
        mode = "Written by Claude in Max's voice."
    else:
        texts = [build_post(art, i) for i, art in enumerate(picks)]
        mode = "Template drafts (set ANTHROPIC_API_KEY for AI-written posts)."

    # A post is the one output that cannot be quietly corrected: it goes out
    # under Max's name and tags the company. So every draft is checked against
    # what has actually been verified, and an unchecked figure is flagged for
    # him rather than published on trust.
    import sys
    import trust
    from ai_writer import has_figure, one_mention

    records = []
    settled_total = 0
    when = schedule_days(today, len(picks), full_week=top)
    for i, (text, art) in enumerate(zip(texts, picks)):
        day = when[i]
        company = art.get("company", "")
        # One @ per post, on the subject company. Five mentions meant five
        # dropdowns to fight in LinkedIn, and two of them could not be tagged.
        text = one_mention(text, company)
        checked = trust.verification(company) if company else {}
        risky = bool(has_figure(text)) and not checked
        claims, settled = settle_claims(_claims_in(text, art), art, checked)
        settled_total += len(settled)
        if risky:
            print(f"  ! post {i + 1} ({company or art.get('title','')[:40]}) "
                  f"states a figure for a round nobody has verified",
                  file=sys.stderr)
        records.append({
            # What a browser session still has to read a page to confirm.
            # Everything the article already settled is gone from here.
            "claims": claims,
            "settled": settled,
            "verified": bool(checked),
            "verified_source": checked.get("source", ""),
            "needs_check": risky,
            "index": i + 1,
            "date": day.isoformat(),
            "time": POST_TIME,
            "text": text,
            "link": art.get("link"),
            "publisher": art.get("publisher"),
            # The one @mention in the text: what to type into LinkedIn's
            # dropdown, and the name the right row should carry. A guess at
            # the first row is what tagged the wrong entity and cost a restart.
            "mention": _mention_hint(text, company),
            # For the plan Max reads, not for the browser session.
            "link_note": art.get("link_note", ""),
            "image_note": art.get("image_note", ""),
            "weekday": day.strftime("%A"),
            "schedule_for": day.strftime("%A %d %B"),
            "image": art.get("image"),
            "primary_source": art.get("primary_source"),
            "coverage_url": art.get("coverage_url"),
        })
    if settled_total:
        print(f"Settled {settled_total} claims against the article text; "
              f"only what is left needs an outside read.", file=sys.stderr)
    return records, mode


# What a browser session actually uses. Everything else on a record is for the
# plan Max reads, and reading it in Cowork is paying to skip it.
_FOR_COWORK = ("index", "date", "time", "text", "link", "mention",
               "needs_check", "claims")


def for_cowork(records: list) -> list:
    """The posts, stripped to the fields a scheduling session needs."""
    return [{k: r[k] for k in _FOR_COWORK if k in r} for r in records]


def _mention_hint(text: str, company: str) -> dict:
    """The single @mention in a post: what to type, and what to expect."""
    found = re.search(r"@([A-Za-zÀ-ÿ0-9][\w\-.&']*)", text or "")
    if not found:
        return {}
    return {"type": found.group(1), "expect": (company or found.group(1)).strip()}


def render_markdown(records: list, mode: str, days: int) -> str:
    """Render the human-readable weekly plan, with the Cowork handoff on top."""
    import datetime as dt

    today = dt.date.today()
    spread = ("one per day" if len(records) >= 7
              else "one per working day, weekend left blank")
    parts = [
        "# Climb Ventures LinkedIn plan for the week",
        f"_Generated {today.strftime('%d %B %Y')}. {len(records)} posts, {spread}, "
        f"from Swiss DeepTech news of the last {days} days. {mode} "
        f"Schedule each for {POST_TIME} on its day. Review and edit before posting._",
        "",
        "## Publish with Claude Cowork",
        "Paste this into Cowork to schedule the whole week in one go (it reads the "
        "structured file `digest/posts.json` next to this one):",
        "",
        "```",
        COWORK_PROMPT,
        "```",
        "",
        "The posts themselves are below, for review before you run it.",
        "",
    ]
    for r in records:
        parts.append(
            f"## Post {r['index']} — schedule for {r['schedule_for']} at {r['time']}\n"
        )
        parts.append("```")
        parts.append(r["text"])
        parts.append("```")
        if r["image"]:
            parts.append(f"🖼️ **Article image:** {r['image']}")
        else:
            parts.append("🖼️ **Article image:** none found, grab one from the article page.")
        if r.get("coverage_url"):
            parts.append("🔗 **Links to the original source.**")
        parts.append("")
    if not records:
        parts.append("_No stories to turn into posts this run._")
    return "\n".join(parts) + "\n"


def render_plan_html(records: list, mode: str, days: int) -> str:
    """Render the weekly plan as a phone-friendly web page (for GitHub Pages).

    Each post is a card with a one-tap Copy button, its image, the schedule
    slot, and the source link. The Cowork prompt sits at the top with its own
    Copy button. This is the page served at maxime-droux.com/plan so it opens on
    any device with no GitHub login.
    """
    import datetime as dt

    today = dt.date.today().strftime("%d %B %Y")

    def esc(s: str) -> str:
        return html.escape(s or "")

    cards = []
    for r in records:
        if r.get("image"):
            img = (
                f'<img class="shot" src="{esc(r["image"])}" '
                f'alt="Article image" loading="lazy" '
                f'onerror="this.replaceWith(Object.assign(document.createElement(\'p\'),'
                f'{{className:\'noimg\',textContent:\'Image preview blocked. Cowork will '
                f'grab it from the article page.\'}}))">'
            )
        else:
            img = (
                '<p class="noimg">No preview image. Cowork will grab one from the '
                "article page when scheduling.</p>"
            )
        # When the link is the original source, that is the only source shown.
        # The outlet we happened to find the story through is not credited.
        primary = ""
        if r.get("coverage_url"):
            host = r["link"].split("//", 1)[-1].split("/", 1)[0].replace("www.", "")
            main_label = f"Original source: {host}"
        else:
            main_label = f"Article: {r['publisher'] or 'link'}"
        cards.append(
            f"""      <article class="card">
        <div class="cardhead">
          <span class="num">Post {r['index']}</span>
          <span class="when">{esc(r['schedule_for'])} &middot; {esc(r['time'])}</span>
          {'<span class="flag">check this figure</span>' if r.get('needs_check') else ('<span class="ok">verified</span>' if r.get('verified') else '')}
        </div>
        <div class="posttext">
          <button class="copy" onclick="copyText(this)">Copy</button>
          <pre class="post">{esc(r['text'])}</pre>
        </div>
        {img}
        <a class="src" href="{esc(r['link'])}" target="_blank" rel="noopener">{esc(main_label)}</a>
        {primary}
      </article>"""
        )
    body = "\n".join(cards) or "<p>No stories to turn into posts this week.</p>"

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Climb LinkedIn plan for the week</title>
<meta name="robots" content="noindex">
<style>
  :root {{ --green:#46b96a; --ink:#1b2430; --soft:#5b6472; --line:#e6eae8; --bg:#f6f8f7; }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
         background:var(--bg); color:var(--ink); line-height:1.55; }}
  .wrap {{ max-width:720px; margin:0 auto; padding:2rem 1rem 4rem; }}
  h1 {{ font-size:1.6rem; letter-spacing:-0.02em; }}
  h1 .dot {{ color:var(--green); }}
  .sub {{ color:var(--soft); margin:0.4rem 0 1.5rem; font-size:0.9rem; }}
  .runbox {{ margin-bottom:1.5rem; }}
  .runbtn {{ width:100%; background:var(--green); color:#fff; border:0;
            border-radius:12px; padding:0.9rem 1rem; font-size:1rem; font-weight:700;
            cursor:pointer; }}
  .runbtn:active {{ transform:scale(0.99); }}
  .runbtn:disabled {{ opacity:0.55; cursor:default; }}
  .runstatus {{ margin-top:0.5rem; font-size:0.85rem; color:var(--soft);
               text-align:center; }}
  .cowork {{ background:#fff; border:1px solid var(--line); border-radius:14px;
            padding:1rem; margin-bottom:1.8rem; }}
  .cowork h2 {{ font-size:1rem; margin-bottom:0.5rem; }}
  .cowork p {{ font-size:0.85rem; color:var(--soft); margin-bottom:0.6rem; }}
  .card {{ background:#fff; border:1px solid var(--line); border-radius:14px;
          padding:1rem; margin-bottom:1rem; }}
  .cardhead {{ display:flex; justify-content:space-between; align-items:baseline;
              gap:0.5rem; margin-bottom:0.6rem; }}
  .num {{ color:var(--green); font-weight:800; }}
  .flag {{ background:#fdf3e3; color:#8a6d3b; border-radius:6px;
          padding:0.05rem 0.45rem; font-size:0.7rem; font-weight:700;
          text-transform:uppercase; letter-spacing:0.03em; }}
  .ok {{ background:#eef4f0; color:#2f6b46; border-radius:6px;
        padding:0.05rem 0.45rem; font-size:0.7rem; font-weight:700;
        text-transform:uppercase; letter-spacing:0.03em; }}
  .when {{ color:var(--soft); font-size:0.82rem; text-align:right; }}
  .posttext {{ position:relative; }}
  pre.post {{ white-space:pre-wrap; word-wrap:break-word; font:inherit;
             background:var(--bg); border:1px solid var(--line); border-radius:10px;
             padding:0.9rem; padding-top:2.4rem; }}
  .copy {{ position:absolute; top:0.5rem; right:0.5rem; z-index:2;
          background:var(--green); color:#fff; border:0; border-radius:8px;
          padding:0.35rem 0.7rem; font-size:0.8rem; font-weight:600; cursor:pointer; }}
  .copy:active {{ transform:scale(0.97); }}
  .shot {{ display:block; width:100%; height:auto; border-radius:10px;
          margin-top:0.8rem; border:1px solid var(--line); }}
  .noimg {{ margin-top:0.8rem; font-size:0.82rem; color:var(--soft); font-style:italic; }}
  .src {{ display:inline-block; margin-top:0.7rem; margin-right:0.9rem;
         color:var(--green); font-size:0.82rem; text-decoration:none;
         font-weight:600; }}
  .src.primary {{ color:var(--soft); }}
  .src:hover {{ text-decoration:underline; }}
  footer {{ color:var(--soft); font-size:0.78rem; margin-top:2rem; }}
</style></head><body>
<div class="wrap">
  <h1>This week on LinkedIn<span class="dot">.</span></h1>
  <p class="sub">Generated {today} &middot; {len(records)} posts, one per day &middot; {esc(mode)}</p>

  <div class="runbox">
    <button id="runbtn" class="runbtn">&#8635; Generate this week's posts now</button>
    <p id="runstatus" class="runstatus"></p>
  </div>

  <div class="cowork">
    <h2>Publish with Claude Cowork</h2>
    <p>Copy this into Cowork to schedule the whole week in one go:</p>
    <div class="posttext">
      <button class="copy" onclick="copyText(this)">Copy</button>
      <pre class="post">{esc(COWORK_PROMPT)}</pre>
    </div>
  </div>

{body}

  <footer>Review each post before publishing. Times are Swiss local.</footer>
</div>
<script>
  function copyText(btn) {{
    var pre = btn.parentElement.querySelector('pre.post');
    navigator.clipboard.writeText(pre.innerText).then(function() {{
      var old = btn.textContent; btn.textContent = 'Copied';
      setTimeout(function() {{ btn.textContent = old; }}, 1500);
    }});
  }}

  var RUN_URL = "{RUN_URL}";
  var runBtn = document.getElementById('runbtn');
  if (runBtn) {{
    runBtn.addEventListener('click', function() {{
      var s = document.getElementById('runstatus');
      runBtn.disabled = true;
      s.textContent = 'Starting...';
      fetch(RUN_URL, {{ method: 'POST' }})
        .then(function(r) {{ return r.json(); }})
        .then(function(d) {{
          if (d && d.ok) {{
            s.textContent = 'Started. Your new posts will be ready here in about 3 minutes. Refresh this page then.';
          }} else {{
            var why = (d && (d.error || d.detail)) ? (': ' + (d.error || d.detail)) : '';
            var code = (d && d.status) ? (' ' + d.status) : '';
            s.textContent = 'Could not start (error' + code + ')' + why + '. Try again in a moment.';
            runBtn.disabled = false;
          }}
        }})
        .catch(function() {{
          s.textContent = 'Network error. Try again in a moment.';
          runBtn.disabled = false;
        }});
    }});
  }}
</script>
</body></html>
"""


def to_linkedin(articles: list, days: int, top: int = 7) -> str:
    """Convenience: build and render the weekly plan in one call."""
    records, mode = build_posts(articles, days, top)
    return render_markdown(records, mode, days)
