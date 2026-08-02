"""Google News as a wide discovery net, resolved back to the real source.

Direct RSS feeds (EPFL, ETH, Startupticker, ...) are reliable but each covers
only its own newsroom, so good Swiss deep-tech stories are spread thin. Google
News indexes thousands of publishers at once, including company press releases
and newswires (Business Wire, GlobeNewswire, Presseportal), which is exactly
where "direct press releases by companies" show up.

The catch: a Google News link is a redirect (news.google.com/rss/articles/...),
not the article. So for the stories we actually use we resolve that redirect
back to the original publisher URL. That real URL is what we link to, and it is
where the article's lead image (og:image) lives. This is the "use Google, then
go to the source" idea.

Resolution can fail (Google changes its internals now and then). It fails
gracefully: if a link cannot be resolved, the original Google link is kept (it
still redirects fine in a browser) and the image simply falls back to "none
found". So a broken resolver degrades quality, it never breaks a run.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

# Search phrases, each already scoped to Switzerland by the query text and by
# the Swiss edition parameters below. They mix research/company angles with
# funding/announcement language so that company press releases get surfaced too.
GOOGLE_NEWS_QUERIES = [
    "Swiss deeptech startup",
    "Switzerland quantum technology",
    "Switzerland semiconductor OR photonics",
    "Swiss biotech OR medtech funding",
    "EPFL OR ETH spin-off",
    "Swiss startup raises round",
    "Switzerland robotics OR AI startup",
    "Swiss cleantech OR energy startup",
]

# Swiss editions of Google News. English is primary; adding the German and
# French editions catches Swiss press (NZZ, Handelszeitung, Le Temps) and their
# company announcements that never appear in English.
_EDITIONS = [
    ("en", "CH", "CH:en"),
    ("de", "CH", "CH:de"),
    ("fr", "CH", "CH:fr"),
]

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def google_news_feeds() -> list[tuple[str, str]]:
    """Return (label, url) Google News RSS search feeds for every query/edition."""
    feeds = []
    for query in GOOGLE_NEWS_QUERIES:
        q = urllib.parse.quote(query)
        for hl, gl, ceid in _EDITIONS:
            url = (
                f"https://news.google.com/rss/search?q={q}"
                f"&hl={hl}-{gl}&gl={gl}&ceid={ceid}"
            )
            feeds.append(("Google News", url))
    return feeds


def is_google_news_url(url: str) -> bool:
    return "news.google.com" in (url or "")


def _article_id(url: str) -> str | None:
    path = urllib.parse.urlparse(url).path
    m = re.search(r"/(?:rss/)?articles/([^/?]+)", path)
    return m.group(1) if m else None


def resolve_url(google_url: str, timeout: int = 15) -> str | None:
    """Resolve a Google News redirect to the real publisher URL, or None.

    Uses Google's own batchexecute endpoint (the same call the Google News page
    makes) to turn an article id into its destination link. Wrapped so any
    failure returns None and the caller keeps the original link.
    """
    article_id = _article_id(google_url)
    if not article_id:
        return None
    try:
        # Step 1: load the article stub to read its signature and timestamp.
        stub_url = f"https://news.google.com/rss/articles/{article_id}"
        req = urllib.request.Request(stub_url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", "ignore")
        sig = re.search(r'data-n-a-sg="([^"]+)"', html)
        ts = re.search(r'data-n-a-ts="([^"]+)"', html)
        if not (sig and ts):
            return None

        # Step 2: ask batchexecute to expand the id into the real URL.
        inner = json.dumps(
            [
                "garturlreq",
                [
                    ["X", "X", ["X", "X"], None, None, 1, 1, "US:en",
                     None, 1, None, None, None, None, None, 0, 1],
                    "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0,
                ],
                article_id, int(ts.group(1)), sig.group(1),
            ]
        )
        f_req = json.dumps([[["Fbv4je", inner, None, "generic"]]])
        body = urllib.parse.urlencode({"f.req": f_req}).encode("utf-8")
        post = urllib.request.Request(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            data=body,
            headers={
                "User-Agent": _UA,
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            },
        )
        with urllib.request.urlopen(post, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "ignore")
        # Response is anti-JSON-prefixed lines; find the payload line.
        for line in raw.splitlines():
            if "garturlres" in line:
                arr = json.loads(line)
                real = json.loads(arr[0][2])[1]
                if real and real.startswith("http"):
                    return real
        return None
    except Exception:
        return None
