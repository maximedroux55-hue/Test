"""News sources for the Swiss DeepTech aggregator.

Direct publisher RSS feeds only. Google News search feeds are intentionally not
used: direct feeds give higher-quality items and, importantly, a usable lead
image for each article (Google News hides the article behind a redirect).

Feeds that are unreachable or empty are skipped automatically, so a wrong or
retired URL never breaks a run. After a run, prune any feed that the log marks
as "skipped (unreachable)".
"""

# ---- Direct institutional and media feeds (Swiss research and startups) -------
# (name, url). Verified-working feeds should stay near the top. Candidates that
# may need their URL corrected are grouped below and pruned after a test run.
DIRECT_FEEDS = [
    # Proven working:
    ("EPFL News", "https://actu.epfl.ch/feeds/rss/mediacom/en/"),

    # Candidates (kept only if a run shows they return items):
    ("SWI swissinfo (Business)", "https://www.swissinfo.ch/eng/business/rss"),
    ("SWI swissinfo (Sci-Tech)", "https://www.swissinfo.ch/eng/sci-tech/rss"),
    ("ETH Zurich News", "https://ethz.ch/en/news-and-events/eth-news.rss.xml"),
    ("Empa News", "https://www.empa.ch/web/empa/rss"),
    ("PSI News", "https://www.psi.ch/en/media/latest-news/rss.xml"),
    ("Startupticker", "https://www.startupticker.ch/en/rss"),
]


def all_feeds(days: int = 14):
    """Return a list of (source_label, feed_url) for every configured source.

    `days` is accepted for compatibility but not used now that the sources are
    direct feeds (the scraper filters by date after fetching).
    """
    return list(DIRECT_FEEDS)
