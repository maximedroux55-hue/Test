"""News sources for the Swiss DeepTech aggregator.

Two layers of sources:

  1. Direct publisher RSS feeds (below). Reliable, and each already carries a
     lead image. But each covers only its own newsroom, so good Swiss deep-tech
     stories are spread thin across many of them.

  2. Google News search feeds (see google_news.py). A wide net across thousands
     of publishers at once, including company press releases and newswires. Its
     links are redirects, so for the stories we actually use we resolve each one
     back to the real publisher URL (that is also where the article image is).

Feeds that are unreachable or empty are skipped automatically, so a wrong or
retired URL never breaks a run.

To add a direct source: append (name, url) below with the site's real RSS/Atom
URL, then run once and keep it only if the log does not mark it "skipped". To
change what Google surfaces, edit GOOGLE_NEWS_QUERIES in google_news.py.
"""

from google_news import google_news_feeds

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

    # --- Swiss press ---
    ("Fintechnews Switzerland", "https://fintechnews.ch/feed/"),

    # --- Europe-wide tech (filtered to Swiss deep tech by the relevance scorer) ---
    ("Tech.eu", "https://tech.eu/feed/"),
    ("EU-Startups", "https://www.eu-startups.com/feed/"),
    ("Silicon Canals", "https://siliconcanals.com/feed/"),
]

# Feeds removed on 11 August 2026, with what --check-feeds found. Kept here so
# nobody adds them back from memory, and so the next person can try a corrected
# URL knowing what the old one did.
#
# Seventeen of the twenty three direct feeds returned nothing. Fourteen of them
# had never contributed a single story in the whole life of the database: not
# one of 115 rows came from ETH, Empa, PSI, CSEM, IDIAP or any of the three
# universities. This was never rot. The URLs were wrong from the day they were
# added, and the run reported it as one word, "unreachable", in a log nobody
# reads line by line.
#
# They are covered by Google News queries instead, which is the transport that
# demonstrably works here and cannot 404 when an institution redesigns its site.
RETIRED_FEEDS = [
    # 404: the address does not exist.
    ("ETH Zurich News", "https://ethz.ch/en/news-and-events/eth-news.rss.xml"),
    ("Empa Research", "https://www.empa.ch/web/empa/rss"),
    ("Idiap Research Institute", "https://www.idiap.ch/en/rss.xml"),
    ("Venturelab", "https://www.venturelab.swiss/feed"),
    ("CSEM", "https://www.csem.ch/en/feed/"),
    ("PSI (Paul Scherrer Institute)", "https://www.psi.ch/en/media-corner/rss.xml"),
    ("University of Basel", "https://www.unibas.ch/en/News.rss"),
    ("University of Zurich", "https://www.news.uzh.ch/en.rss.xml"),
    ("University of Geneva", "https://www.unige.ch/campus/rss/"),
    ("Presseportal Switzerland", "https://www.presseportal.ch/rss/index.rss2"),
    # 410: retired by the publisher, and not coming back.
    ("SWI swissinfo (Business)", "https://www.swissinfo.ch/eng/business/rss"),
    # 403: the server refuses us specifically.
    ("Swiss Biotech Association", "https://www.swissbiotech.org/feed/"),
    # 520: their server errors on every request.
    ("Tech Funding News", "https://techfundingnews.com/feed/"),
    # Never answers at all.
    ("GlobeNewswire (technology)", "https://www.globenewswire.com/RssFeed/subjectcode/22-Technology/feedTitle/GlobeNewswire%20-%20Technology"),
    # 200 with an empty feed: the address is alive and carries no items.
    ("IBM Research Zurich", "https://www.zurich.ibm.com/rss/news.xml"),
    ("SwissCognitive (AI)", "https://swisscognitive.ch/feed/"),
    ("Business Wire (technology)", "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeEFpRWQ4="),
]


def all_feeds(days: int = 14):
    """Return (source_label, feed_url) for every source: direct feeds first,
    then the Google News discovery feeds.

    `days` is accepted for compatibility but unused (the scraper filters by
    date after fetching).
    """
    return list(DIRECT_FEEDS) + google_news_feeds()
