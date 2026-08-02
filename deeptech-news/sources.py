"""News sources for the Swiss DeepTech aggregator.

Direct publisher RSS feeds only. Google News search feeds are intentionally not
used: direct feeds give higher-quality items and, importantly, a usable lead
image for each article (Google News hides the article behind a redirect).

Feeds that are unreachable or empty are skipped automatically, so a wrong or
retired URL never breaks a run.

To add a source: append (name, url) below with the site's real RSS/Atom URL,
then run once and keep it only if the log does not mark it "skipped".
"""

# ---- Direct institutional and media feeds (Swiss research and startups) -------
# (name, url). All confirmed reachable in test runs. Startupticker is the
# primary startup source; EPFL and ETH provide research and spinout news.
DIRECT_FEEDS = [
    # Confirmed working:
    ("Startupticker", "https://www.startupticker.ch/en/rss/news.rss"),
    ("EPFL News", "https://actu.epfl.ch/feeds/rss/mediacom/en/"),
    ("ETH Zurich News", "https://ethz.ch/en/news-and-events/eth-news.rss.xml"),
    ("SWI swissinfo (Business)", "https://www.swissinfo.ch/eng/business/rss"),

    # New candidates (kept only if a test run shows they return items):
    ("Fintechnews Switzerland", "https://fintechnews.ch/feed/"),
    ("EU-Startups (Switzerland)", "https://www.eu-startups.com/tag/switzerland/feed/"),
    ("Handelszeitung", "https://www.handelszeitung.ch/rss.xml"),
    ("Cash", "https://www.cash.ch/rss"),
    ("finews", "https://www.finews.ch/rss"),
    ("CERN News", "https://home.cern/api/news/news/feed.rss"),
    ("PSI News", "https://www.psi.ch/en/media/rss"),
    ("University of Zurich", "https://www.news.uzh.ch/en.rss.html"),
]


def all_feeds(days: int = 14):
    """Return (source_label, feed_url) for every configured direct feed.

    `days` is accepted for compatibility but unused (the scraper filters by
    date after fetching).
    """
    return list(DIRECT_FEEDS)
