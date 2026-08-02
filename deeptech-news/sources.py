"""News sources for the Swiss DeepTech aggregator.

Direct publisher RSS feeds only. Google News search feeds are intentionally not
used: direct feeds give higher-quality items and, importantly, a usable lead
image for each article (Google News hides the article behind a redirect).

Feeds that are unreachable or empty are skipped automatically, so a wrong or
retired URL never breaks a run.

To add a source: append (name, url) below with the site's real RSS/Atom URL,
then run once and keep it only if the log does not mark it "skipped".
Startupticker is a wanted source but its public feed URL is not yet confirmed;
add it here once you have the exact RSS link from their site.
"""

# ---- Direct institutional and media feeds (Swiss research and startups) -------
# (name, url). Confirmed reachable in test runs.
DIRECT_FEEDS = [
    ("EPFL News", "https://actu.epfl.ch/feeds/rss/mediacom/en/"),
    ("ETH Zurich News", "https://ethz.ch/en/news-and-events/eth-news.rss.xml"),
    ("SWI swissinfo (Business)", "https://www.swissinfo.ch/eng/business/rss"),
]


def all_feeds(days: int = 14):
    """Return (source_label, feed_url) for every configured direct feed.

    `days` is accepted for compatibility but unused (the scraper filters by
    date after fetching).
    """
    return list(DIRECT_FEEDS)
