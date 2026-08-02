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


def article_image(url: str, timeout: int = 12) -> str | None:
    """Fetch the article page and return its lead image URL, or None.

    Tries, in order: Open Graph / Twitter image, <link rel="image_src">, and
    JSON-LD schema.org image. The first that hits wins.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final_url = resp.geturl()
            raw = resp.read(600_000)  # the <head> plus a little body; cap the read
        html = raw.decode("utf-8", "ignore")
        return (
            _og_image(html, final_url)
            or _link_image_src(html, final_url)
            or _jsonld_image(html, final_url)
        )
    except Exception:
        return None


def resolve_images(articles: list) -> None:
    """Resolve each article's real source URL and lead image.

    For Google News items the link is a redirect, so we first resolve it back to
    the real publisher URL (and update article['link'] to it, since that is the
    page worth linking to). Then the image is the feed image if the feed gave
    one, otherwise the source page's og:image.
    """
    from google_news import is_google_news_url, resolve_url

    for a in articles:
        link = a.get("link", "")
        if is_google_news_url(link):
            real = resolve_url(link)
            if real:
                a["link"] = link = real

        img = a.get("image_feed")
        if not img:
            img = article_image(link)
        a["image"] = img
