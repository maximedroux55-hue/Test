"""News sources for the Swiss DeepTech aggregator.

Everything here is a public RSS feed, so no API keys are needed. Two kinds:

1. Google News search feeds. Each query is scoped to Switzerland and to deep
   technology topics. Google News turns any search into an RSS feed, which is a
   reliable, layout-proof way to collect news (far sturdier than scraping raw
   web pages). Edit GOOGLE_NEWS_QUERIES to change what we look for.

2. Direct feeds from Swiss research institutions and startup media. Feeds that
   are unreachable or empty are skipped automatically, so it is safe to leave a
   URL here even if it occasionally changes.
"""

import urllib.parse

# ---- 1. Google News search queries -------------------------------------------
# Keep each query focused. "when:14d" limits Google News to the last 14 days.
GOOGLE_NEWS_QUERIES = [
    '"deep tech" Switzerland',
    'Swiss deeptech startup',
    'Switzerland startup funding round',
    'EPFL spin-off OR spinoff',
    'ETH Zurich spin-off OR spinoff',
    'Switzerland quantum OR semiconductor OR photonics',
    'Swiss robotics OR AI hardware startup',
    'Switzerland biotech OR medtech financing',
    'Swiss cleantech OR climate tech startup',
]


def google_news_feed(query: str, days: int = 14) -> str:
    """Build a Google News RSS URL for a query, scoped to Switzerland."""
    q = urllib.parse.quote(f"{query} when:{days}d")
    return f"https://news.google.com/rss/search?q={q}&hl=en-CH&gl=CH&ceid=CH:en"


# ---- 2. Direct institutional / media feeds -----------------------------------
# (name, url). If one breaks, the scraper logs it and moves on.
DIRECT_FEEDS = [
    ("Startupticker", "https://www.startupticker.ch/en/rss"),
    ("EPFL News", "https://actu.epfl.ch/feeds/rss/mediacom/en/"),
    ("ETH Zurich News", "https://ethz.ch/en/news-and-events/eth-news/_jcr_content/rightpar/textimage.rss.xml"),
    ("SWI swissinfo (Business)", "https://www.swissinfo.ch/eng/business/rss"),
]


def all_feeds(days: int = 14):
    """Return a list of (source_label, feed_url) for every configured source."""
    feeds = [("Google News", google_news_feed(q, days)) for q in GOOGLE_NEWS_QUERIES]
    feeds += DIRECT_FEEDS
    return feeds
