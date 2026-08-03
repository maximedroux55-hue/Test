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

import json
import re
import urllib.parse
import urllib.request

from relevance import is_excluded

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
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
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


def article_page(url: str, timeout: int = 12):
    """Fetch an article once and return (html, final_url), or (None, url)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final_url = resp.geturl()
            raw = resp.read(600_000)  # the <head> plus a little body; cap the read
        return raw.decode("utf-8", "ignore"), final_url
    except Exception:
        return None, url


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
        if html:
            if not a.get("image_feed"):
                a["image"] = (
                    _og_image(html, final_url)
                    or _link_image_src(html, final_url)
                    or _jsonld_image(html, final_url)
                )
            else:
                a["image"] = a["image_feed"]

            source, confidence = _primary_source(html, final_url, a.get("title", ""))
            a["primary_source"] = source
            # When we are confident, the post links to the original source
            # rather than the coverage. The outlet that reported it is kept so
            # it can still be credited in the text.
            if source and confidence == "high":
                a["coverage_url"] = link
                a["link"] = source
        else:
            a["image"] = a.get("image_feed")
            a["primary_source"] = None


# Kept for compatibility with older callers.
resolve_images = enrich_articles
