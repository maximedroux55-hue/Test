"""Find the lead image for each article (the picture illustrating it).

Order of preference:
  1. An image the RSS feed already provides (cheap, no extra request).
  2. The article page's Open Graph image (og:image / twitter:image), which is
     the picture publishers designate for link previews, i.e. the one that
     illustrates the article.

Reading og:image is a light, standard operation (one request per post, only the
meta tag). It runs on a machine with open internet (GitHub Actions or your Mac),
and fails gracefully to "no image found" if a page blocks it or has none.

Note on usage: the returned URL points at the publisher's image. Use your own
judgment on rights and attribution before posting, as you already do.
"""

from __future__ import annotations

import html as _html_lib
import json
import re
import urllib.parse
import urllib.request

from relevance import is_excluded, is_paywalled

# A real browser user-agent. Sites behind a firewall (Startupticker among them)
# serve a 403 with no image to obvious bots, but let a normal browser through.
# The RSS fetch already uses a browser UA for the same reason.
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_META_PROPS = ("og:image", "og:image:url", "og:image:secure_url", "twitter:image")


def _og_image(html: str, base_url: str) -> str | None:
    for prop in _META_PROPS:
        p = re.escape(prop)
        # content after the property, or property after the content
        m = re.search(
            r'<meta[^>]+(?:property|name)=["\']' + p + r'["\'][^>]+content=["\']([^"\']+)["\']',
            html, re.IGNORECASE,
        ) or re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']' + p + r'["\']',
            html, re.IGNORECASE,
        )
        if m:
            return urllib.parse.urljoin(base_url, m.group(1).strip())
    return None


def _link_image_src(html: str, base_url: str) -> str | None:
    m = re.search(
        r'<link[^>]+rel=["\']image_src["\'][^>]+href=["\']([^"\']+)["\']',
        html, re.IGNORECASE,
    )
    return urllib.parse.urljoin(base_url, m.group(1).strip()) if m else None


def _jsonld_image(html: str, base_url: str) -> str | None:
    """Pull an image URL out of any JSON-LD block (schema.org 'image')."""
    for block in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.IGNORECASE | re.DOTALL,
    ):
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        for node in data if isinstance(data, list) else [data]:
            if not isinstance(node, dict):
                continue
            img = node.get("image")
            if isinstance(img, str):
                return urllib.parse.urljoin(base_url, img)
            if isinstance(img, dict) and img.get("url"):
                return urllib.parse.urljoin(base_url, img["url"])
            if isinstance(img, list) and img:
                first = img[0]
                if isinstance(first, str):
                    return urllib.parse.urljoin(base_url, first)
                if isinstance(first, dict) and first.get("url"):
                    return urllib.parse.urljoin(base_url, first["url"])
    return None


# Domains that are never the primary source of a story: social networks, the
# usual web infrastructure, and link shorteners.
_NOT_A_SOURCE = (
    "linkedin.com", "twitter.com", "x.com", "facebook.com", "instagram.com",
    "youtube.com", "youtu.be", "xing.com", "mastodon", "bsky.app", "tiktok.com",
    "whatsapp.com", "wa.me", "telegram.me", "t.me",
    "google.com", "googleapis.com", "gstatic.com", "doubleclick.net",
    "cookiebot.com", "addthis.com", "sharethis.com", "paypal.com",
    "apple.com", "adobe.com", "wordpress.org", "creativecommons.org",
    "bit.ly", "t.co", "lnkd.in",
)

_TITLE_STOP = {
    "raises", "raised", "million", "billion", "round", "seed", "series",
    "funding", "swiss", "switzerland", "startup", "company", "news", "with",
    "from", "that", "this", "into", "closes", "secures", "spin", "spinoff",
    "first", "opens", "markets", "outside", "growth", "capital", "chief",
}


def _domain(url: str) -> str:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


def _domain_root(host: str) -> str:
    """The distinctive part of a domain: 'medyria.com' -> 'medyria'."""
    parts = [p for p in host.split(".") if p]
    return parts[-2] if len(parts) >= 2 else (parts[0] if parts else "")


def _title_tokens(title: str) -> set:
    # Drop a trailing " - Publisher", which Google News appends. Without this
    # the outlet's own name counts as a name from the story, and a headline
    # ending "- TradingView" happily matches tradingviewstore.com.
    cleaned = re.sub(r"\s+[-|]\s+[^-|]+$", "", title or "")
    words = re.findall(r"[a-z0-9]+", cleaned.lower())
    return {w for w in words if len(w) >= 4 and w not in _TITLE_STOP}


def _primary_source(html: str, base_url: str, title: str):
    """Find the story's own source, and say how sure we are.

    Returns (url, confidence) where confidence is "high" or "none".

    High confidence means a linked domain carries a distinctive word from the
    headline, so "ZuriQ raises..." resolves to zuriq.com and "Ahead Health
    raises..." to aheadhealth.com. That test proved reliable in practice, and
    only those links are good enough to post.

    Anything weaker is deliberately dropped. A "most linked domain" guess
    produced a researcher's profile page, a lab page and, once, the covering
    outlet's own WhatsApp channel. A wrong link in a post is worse than no
    link, so we return nothing rather than guess.
    """
    publisher = _domain(base_url)
    publisher_root = _domain_root(publisher)
    tokens = _title_tokens(title)

    candidates = []
    for href in re.findall(r'<a[^>]+href=["\'](https?://[^"\'>\s]+)["\']', html, re.IGNORECASE):
        host = _domain(href)
        if not host:
            continue
        # Skip the publisher, including its other subdomains: when actu.epfl.ch
        # covers a story, epfl.ch and people.epfl.ch are not its source.
        if host == publisher or _domain_root(host) == publisher_root:
            continue
        if any(bad in host for bad in _NOT_A_SOURCE):
            continue
        # A market-research or directory page is never the story's source.
        if is_excluded(href):
            continue
        candidates.append((host, href))

    for host, href in candidates:
        root = _domain_root(host)
        if root and any(_name_matches(root, t) for t in tokens):
            return href, "high"

    return None, "none"


_ANNOUNCEMENT_HINTS = (
    "news", "press", "media", "blog", "article", "story", "release",
    "announcement", "newsroom", "post", "insights", "actualite", "aktuell",
)

# A path segment that is only a language or country code, e.g. /en, /de-ch.
_LOCALE = re.compile(r"^[a-z]{2}(-[a-z]{2})?$")


def _is_announcement_page(url: str) -> bool:
    """True when a URL points at a specific announcement rather than a homepage.

    Linking a post to "valuemize.io/en" tells the reader nothing: it is the
    company's front door, not the news. Only a page about the story itself is
    worth swapping the article link for, so require a real path once language
    and country segments are removed, and either a newsroom-style folder or a
    slug that looks like a headline.
    """
    try:
        path = urllib.parse.urlsplit(url).path
    except Exception:
        return False
    parts = [p for p in path.split("/") if p and not _LOCALE.match(p.lower())]
    if not parts:
        return False  # homepage, or just a language root
    lowered = [p.lower() for p in parts]
    if any(hint in seg for seg in lowered for hint in _ANNOUNCEMENT_HINTS):
        return True
    # A headline slug: long, hyphenated, and not a bare section name.
    return any(len(seg) >= 12 and "-" in seg for seg in lowered)


def _name_matches(root: str, token: str) -> bool:
    """Does a domain look like it belongs to a name from the headline?

    Matching is anchored at the start or end of the domain, never loose
    containment: "aheadhealth" matches "ahead", and "ai-infrastructure"
    matches "infrastructure", but "fortunebusinessinsights" must not match a
    headline that merely contains the word "business".
    """
    if root == token:
        return True
    if len(token) < 5:
        return False
    return (
        root.startswith(token) or root.endswith(token)
        or token.startswith(root) or token.endswith(root)
    )


# A picture inside the article, for pages that set no preview image. Small
# files are logos, spacers and tracking pixels rather than the photo.
_CONTENT_IMG = re.compile(
    r'<img\b([^>]*)\bsrc=["\']([^"\']+\.(?:jpe?g|png|webp))[^"\']*["\']([^>]*)>',
    re.IGNORECASE)

# Page furniture, sponsors and the widgets around a story. A wrong picture on a
# published post is worse than none, so anything that looks like chrome is
# refused rather than ranked.
_NOT_A_PHOTO = re.compile(
    r"logo|icon|avatar|sprite|placeholder|pixel|spacer|blank|1x1|badge|"
    r"favicon|banner|sponsor|advert|/ads?/|partner|newsletter|footer|header|"
    r"social|share|arrow|button|bullet|flag|emoji",
    re.IGNORECASE)

_DIMENSION = re.compile(r'\b(width|height)\s*=\s*["\']?(\d+)', re.IGNORECASE)


def _content_image(html_doc: str, base_url: str) -> str | None:
    """The article's own photograph, or None.

    Scanning the whole page took the first picture on it, which on
    Startupticker is the chrome around the story rather than the story. The
    search is confined to the block that holds the article, the same one the
    text is read from, and anything that looks like furniture or is declared
    small is refused. Where nothing qualifies this returns None: a post with no
    picture is fixable, a post with the wrong one is published.
    """
    if not html_doc:
        return None
    body = _STRIP_BLOCKS.sub(" ", html_doc)
    best = ""
    for pattern in _CONTENT_BLOCKS:
        for match in pattern.finditer(body):
            if len(match.group(1)) > len(best):
                best = match.group(1)
    if len(best) < 400:
        return None

    for before, src, after in _CONTENT_IMG.findall(best)[:12]:
        if _NOT_A_PHOTO.search(src):
            continue
        sizes = [int(v) for _, v in _DIMENSION.findall(f"{before} {after}")]
        if sizes and max(sizes) < 300:
            continue
        full = urllib.parse.urljoin(base_url, src)
        if "data:" in full or "base64" in full:
            continue
        return full
    return None


def article_page(url: str, timeout: int = 12):
    """Fetch an article once and return (html, final_url), or (None, url)."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                      "image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9,de;q=0.8,fr;q=0.7",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final_url = resp.geturl()
            raw = resp.read(600_000)  # the <head> plus a little body; cap the read
        return raw.decode("utf-8", "ignore"), final_url
    except Exception:
        return None, url


_STRIP_BLOCKS = re.compile(
    r"<(script|style|nav|header|footer|aside|form|noscript)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)

# Where a page keeps its actual story. Themes differ, so several are tried and
# the longest match wins.
_CONTENT_BLOCKS = (
    re.compile(r"<article\b[^>]*>(.*?)</article>", re.IGNORECASE | re.DOTALL),
    re.compile(r"<main\b[^>]*>(.*?)</main>", re.IGNORECASE | re.DOTALL),
    re.compile(r"<div\b[^>]*class=\"[^\"]*(?:entry-content|post-content|"
               r"article-body|articleBody|story-body|content-body|rich-text)"
               r"[^\"]*\"[^>]*>(.*?)</div>", re.IGNORECASE | re.DOTALL),
)


def article_text(url: str, limit: int = 4000, timeout: int = 12) -> str:
    """Return the readable text of an article, or "" when it cannot be fetched.

    Feed summaries are a sentence or two, which is why investors, founders and
    totals were so often missing. The article body carries them, so this pulls
    the page down and reduces it to plain text for the extractor to read.

    Which part of the page is used matters as much as fetching it. Taking the
    first <article> took a teaser on themes that mark up their related-post
    cards the same way, and falling back to the whole page spent the character
    budget on menus and cookie notices before reaching the paragraph naming the
    investors. The longest content block wins, and only then is the text cut.
    """
    html_doc, _ = article_page(url, timeout)
    if not html_doc:
        return ""
    return text_from_page(html_doc, limit)


def text_from_page(html_doc: str, limit: int = 4000) -> str:
    """Reduce an already-fetched page to its readable text.

    Split out from article_text because enrich_articles has the page in hand
    already: taking the text there costs nothing, where fetching it again is a
    second round trip for bytes we have downloaded once.
    """
    body = _STRIP_BLOCKS.sub(" ", html_doc or "")

    best = ""
    for pattern in _CONTENT_BLOCKS:
        for match in pattern.finditer(body):
            if len(match.group(1)) > len(best):
                best = match.group(1)
    if len(best) > 400:
        body = best

    text = re.sub(r"<[^>]+>", " ", body)
    text = _html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def article_image(url: str, timeout: int = 12) -> str | None:
    """Fetch the article page and return its lead image URL, or None.

    Tries, in order: Open Graph / Twitter image, <link rel="image_src">, and
    JSON-LD schema.org image. The first that hits wins.
    """
    html, final_url = article_page(url, timeout)
    if not html:
        return None
    return (
        _og_image(html, final_url)
        or _link_image_src(html, final_url)
        or _jsonld_image(html, final_url)
    )


def enrich_articles(articles: list) -> None:
    """Resolve each article's real URL, lead image, and primary source.

    For Google News items the link is a redirect, so we first resolve it back to
    the real publisher URL (and update article['link'] to it, since that is the
    page worth linking to). Then, from a single fetch of that page, we take the
    lead image (feed image wins if the feed gave one) and the story's primary
    source: the company's own site or release behind the coverage.
    """
    from google_news import is_google_news_url, resolve_url

    for a in articles:
        link = a.get("link", "")
        if is_google_news_url(link):
            real = resolve_url(link)
            if real:
                a["link"] = link = real

        html, final_url = article_page(link)
        # A gated article cannot be read by anyone who clicks the post, so mark
        # it for the caller to drop and replace.
        a["paywalled"] = bool(html) and is_paywalled(html)
        if html:
            # The page is already down the wire, so keep its text: it is what
            # settles a post's claims without a browser session opening the
            # article a second time.
            a["fulltext"] = a.get("fulltext") or text_from_page(html, 6000)
            if not a.get("image_feed"):
                a["image"] = (
                    _og_image(html, final_url)
                    or _link_image_src(html, final_url)
                    or _jsonld_image(html, final_url)
                    # Not every page declares a preview image. Startupticker
                    # and actu.epfl.ch do not, which left four posts of seven
                    # with no picture at all.
                    or _content_image(html, final_url)
                )
                a["image_note"] = ("" if a["image"]
                                   else f"no picture found on {_domain(final_url)}")
            else:
                a["image"] = a["image_feed"]

            source, confidence = _primary_source(html, final_url, a.get("title", ""))
            a["primary_source"] = source
            # Swap to the original source only when it is the announcement
            # itself. A company homepage says nothing about the news, so in
            # that case the article stays as the link.
            if source and confidence == "high" and _is_announcement_page(source):
                a["coverage_url"] = link
                a["link"] = source

        # Startupticker and the other outlets that write about a company rather
        # than for it rarely link to its announcement, so the article link
        # survives the test above and the post credits the outlet. Go and look
        # in the company's own newsroom instead.
        if any(agg in (a.get("link") or "") for agg in AGGREGATORS):
            # The write-up nearly always links to the company somewhere, even
            # when it links to the front page rather than the announcement.
            # That domain is worth far more than one guessed from the name.
            known_site = a.get("website") or ""
            if not known_site and a.get("primary_source"):
                known_site = _domain(a["primary_source"])
            # Why a post still credits an outlet is worth recording. Reading
            # it out of a run log means having the log; on the post it is
            # there whenever the question comes up.
            if not a.get("company"):
                a["link_note"] = "no company named in the headline"
            else:
                own = company_announcement(a.get("company", ""), known_site,
                                           a.get("amount", ""),
                                           a.get("title", ""))
                if own and _is_announcement_page(own):
                    a["coverage_url"] = a["link"]
                    a["link"] = own
                    a["link_note"] = "the company's own announcement"
                    # The post now points at the company, so its own picture
                    # belongs with it rather than the outlet's.
                    own_page, own_url = article_page(own)
                    if own_page:
                        picture = (_og_image(own_page, own_url)
                                   or _content_image(own_page, own_url))
                        if picture:
                            a["image"] = picture
                            a["image_note"] = ""
                elif own:
                    a["link_note"] = f"found {own}, not an announcement page"
                else:
                    a["link_note"] = (
                        f"no announcement found for {a['company']}"
                        + (f" at {known_site}" if known_site
                           else ", and no site known"))
        else:
            a["image"] = a.get("image_feed")
            a["primary_source"] = None
            # No note at all was worse than a bad one: two posts came back with
            # no picture and no reason, and the reason was that the page never
            # opened.
            a["image_note"] = (f"could not open {_domain(link)}"
                               if not a["image"] else "")


# Kept for compatibility with older callers.
resolve_images = enrich_articles


# Outlets that write about a company rather than for it. A post credits the
# company, so where one of these is the link, the company's own announcement is
# worth going and finding.
AGGREGATORS = (
    "startupticker.ch", "venturelab.swiss", "ggba.swiss", "techfundingnews.com",
    "eu-startups.com", "siliconcanals.com", "tech.eu", "swissinfo.ch",
    "fintechnews.ch", "thequantuminsider.com", "spacenews.com", "sifted.eu",
)

# Where a company keeps its own announcements.
_NEWSROOMS = (
    "/news", "/en/news", "/press", "/en/press", "/press-releases", "/newsroom",
    "/blog", "/en/blog", "/media", "/en/media", "/insights", "/updates",
)

# What an announcement of a round is called, in the languages Swiss sites use.
_ROUND_WORDS = re.compile(
    r"rais\w+|closes?|closing|secur\w+|funding|financing|round|seed|"
    r"series[\s-]?[a-e]\b|investment|finanzierung|runde|lev(?:é|e)e|"
    r"tour\s+de\s+table",
    re.IGNORECASE,
)


def company_announcement(company: str, website: str, amount: str = "",
                         title: str = "", limit: int = 6) -> str:
    """The company's own post about its round, or "".

    A post credits the company, so it should link to what the company itself
    published rather than to whoever wrote about it. The article does not
    always link there, so this goes to the company's newsroom and looks for the
    entry about this story.

    The entry is matched on the words of the headline rather than a fixed
    vocabulary. Looking only for funding language found nothing on a story
    about a launch, which is most of what a newsroom carries.
    """
    from hq_lookup import _candidate_domains, _is_the_company

    if not company:
        return ""
    digits = re.sub(r"[^\d.]", "", amount or "")[:4].rstrip(".")
    # Words from the headline that are not boilerplate, minus the company's
    # own name, which is on every entry in its newsroom.
    own_name = set(re.findall(r"[a-z0-9]+", (company or "").lower()))
    tokens = _title_tokens(title) - own_name
    # Funding language is only evidence when the story is about funding.
    # Otherwise a piece on an office opening matches last year's seed round.
    about_a_round = bool(digits) or bool(_ROUND_WORDS.search(title or ""))
    for domain in _candidate_domains(company, website):
        # One request settles whether this domain exists and belongs to the
        # company. Without it the budget went on newsroom paths of a domain
        # that was never there, and the real one was never reached.
        root, _ = article_page(f"https://{domain}")
        if not root or not _is_the_company(root, company):
            continue
        tried = 0
        for path in _NEWSROOMS:
            if tried >= limit:
                break
            page, final_url = article_page(f"https://{domain}{path}")
            tried += 1
            if not page or not _is_the_company(page, company):
                continue
            best = ""
            for href, text in re.findall(
                    r'<a\b[^>]*href="([^"]+)"[^>]*>(.{0,160}?)</a>',
                    page, re.IGNORECASE | re.DOTALL):
                label = re.sub(r"<[^>]+>", " ", text)
                label = _html_lib.unescape(re.sub(r"\s+", " ", label)).strip()
                blob = f"{label} {href}"
                # The headline's own distinctive words, or failing that the
                # language of a round.
                if not (tokens & set(re.findall(r"[a-z0-9]+", blob.lower()))
                        or (about_a_round and _ROUND_WORDS.search(blob))):
                    continue
                full = urllib.parse.urljoin(final_url, href)
                if domain not in full or full.rstrip("/") == final_url.rstrip("/"):
                    continue
                # An anchor on a newsroom page is not necessarily a news entry.
                # Matching on headline words alone returned
                # immitrabio.com/index.html#platform and
                # swissto12.com/products/satcom/, which are product pages that
                # happen to share a word with the story.
                if "#" in full or re.search(r"/index\.\w+$", full):
                    continue
                if not _is_announcement_page(full):
                    continue
                # An entry carrying the amount is the right entry, not merely a
                # plausible one.
                if digits and digits in f"{label} {href}":
                    return full
                best = best or full
            if best:
                return best
    return ""
