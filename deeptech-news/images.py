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

import re
import urllib.parse
import urllib.request

_UA = "Mozilla/5.0 (compatible; ClimbNewsBot/1.0; +https://climbventures.com)"

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


def article_image(url: str, timeout: int = 12) -> str | None:
    """Fetch the article page and return its lead image URL, or None."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final_url = resp.geturl()
            raw = resp.read(300_000)  # only need the <head>; cap the read
        html = raw.decode("utf-8", "ignore")
        return _og_image(html, final_url)
    except Exception:
        return None


def resolve_images(articles: list) -> None:
    """Set article['image'] for each article (feed image, else og:image)."""
    for a in articles:
        img = a.get("image_feed")
        if not img:
            img = article_image(a.get("link", ""))
        a["image"] = img
