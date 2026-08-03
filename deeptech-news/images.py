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


def _primary_source(html: str, base_url: str, title: str) -> str | None:
    """Find the story's own source: usually the company's site or its release.

    Strategy: look at the outbound links on the article page, drop the
    publisher's own domain plus social and infrastructure links, then prefer a
    domain that matches a distinctive word from the headline (so "Medyria
    raises CHF 3.5 million" picks medyria.com). If nothing matches by name,
    fall back to the most frequently linked outside domain, which is normally
    the subject of the piece.
    """
    publisher = _domain(base_url)
    tokens = _title_tokens(title)

    candidates = []
    for href in re.findall(r'<a[^>]+href=["\'](https?://[^"\'>\s]+)["\']', html, re.IGNORECASE):
        host = _domain(href)
        if not host or host == publisher or host.endswith("." + publisher):
            continue
        if any(bad in host for bad in _NOT_A_SOURCE):
            continue
        candidates.append((host, href))

    if not candidates:
        return None

    # Best case: a linked domain carries a distinctive word from the headline.
    for host, href in candidates:
        root = _domain_root(host)
        if root and any(root == t or (len(root) >= 5 and root in t) or
                        (len(t) >= 5 and t in root) for t in tokens):
            return href

    # Otherwise the most-linked outside domain is usually the story's subject.
    counts = {}
    for host, _ in candidates:
        counts[host] = counts.get(host, 0) + 1
    top_host = max(counts, key=counts.get)
    for host, href in candidates:
        if host == top_host:
            return href
    return None


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
            a["primary_source"] = _primary_source(html, final_url, a.get("title", ""))
        else:
            a["image"] = a.get("image_feed")
            a["primary_source"] = None


# Kept for compatibility with older callers.
resolve_images = enrich_articles
