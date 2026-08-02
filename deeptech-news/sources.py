"""News sources for the Swiss DeepTech aggregator.

Direct publisher RSS feeds only. Google News search feeds are intentionally not
used: direct feeds give higher-quality items and, importantly, a usable lead
image for each article (Google News hides the article behind a redirect).

Feeds that are unreachable or empty are skipped automatically, so a wrong or
retired URL never breaks a run. After a run, prune any feed the log marks as
"skipped (unreachable)".
"""

# ---- Direct institutional and media feeds (Swiss research and startups) -------
# (name, url).
DIRECT_FEEDS = [
    # Confirmed working (returned items in a test run):
    ("EPFL News", "https://actu.epfl.ch/feeds/rss/mediacom/en/"),
    ("ETH Zurich News", "https://ethz.ch/en/news-and-events/eth-news.rss.xml"),
    ("SWI swissinfo (Business)", "https://www.swissinfo.ch/eng/business/rss"),

    # Startupticker candidates (Max's primary startup source). The exact RSS URL
    # is unconfirmed; these are likely patterns. Unreachable ones are skipped,
    # and the working one (if any) should be kept and the rest removed.
    ("Startupticker", "https://www.startupticker.ch/en/rss.xml"),
    ("Startupticker (feed)", "https://www.startupticker.ch/feed"),
    ("Startupticker (rss)", "https://www.startupticker.ch/rss"),
]


def all_feeds(days: int = 14):
    """Return (source_label, feed_url) for every configured direct feed.

    `days` is accepted for compatibility but unused (the scraper filters by
    date after fetching).
    """
    return list(DIRECT_FEEDS)
