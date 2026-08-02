"""News sources for the Swiss DeepTech aggregator.

Direct publisher RSS feeds only. Google News search feeds are intentionally not
used: direct feeds give higher-quality items and, importantly, a usable lead
image for each article (Google News hides the article behind a redirect).

Feeds that are unreachable or empty are skipped automatically, so a wrong or
retired URL never breaks a run.

To add a source: append (name, url) below with the site's real RSS/Atom URL,
then run once and keep it only if the log does not mark it "skipped".
"""

# ---- Feeds (Swiss research, startups, and Europe-wide tech) --------------------
# (name, url). Two groups:
#   1. Swiss-specific direct feeds (research institutions and Swiss startup press).
#   2. Europe-wide tech feeds. These carry a lot of non-Swiss news, but the
#      relevance scorer keeps only stories with a Swiss + DeepTech signal, so
#      they act as extra Swiss deep-tech sources without the noise. Their
#      WordPress /feed/ endpoints are also the least likely to be blocked.
#
# Feeds that are unreachable or empty are skipped automatically at run time, so a
# wrong or retired URL never breaks a run. Keep an entry only if a run's log does
# not mark it "skipped".
DIRECT_FEEDS = [
    # --- Swiss research and institutions ---
    ("Startupticker", "https://www.startupticker.ch/en/rss/news.rss"),
    ("EPFL News", "https://actu.epfl.ch/feeds/rss/mediacom/en/"),
    ("ETH Zurich News", "https://ethz.ch/en/news-and-events/eth-news.rss.xml"),
    ("Empa Research", "https://www.empa.ch/web/empa/rss"),
    ("Idiap Research Institute", "https://www.idiap.ch/en/rss.xml"),

    # --- Swiss press ---
    ("SWI swissinfo (Business)", "https://www.swissinfo.ch/eng/business/rss"),
    ("Fintechnews Switzerland", "https://fintechnews.ch/feed/"),
    ("SwissCognitive (AI)", "https://swisscognitive.ch/feed/"),

    # --- Europe-wide tech (filtered to Swiss deep tech by the relevance scorer) ---
    ("Tech.eu", "https://tech.eu/feed/"),
    ("EU-Startups", "https://www.eu-startups.com/feed/"),
    ("Silicon Canals", "https://siliconcanals.com/feed/"),
    ("Tech Funding News", "https://techfundingnews.com/feed/"),
]


def all_feeds(days: int = 14):
    """Return (source_label, feed_url) for every configured direct feed.

    `days` is accepted for compatibility but unused (the scraper filters by
    date after fetching).
    """
    return list(DIRECT_FEEDS)
