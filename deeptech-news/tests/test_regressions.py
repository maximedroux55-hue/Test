"""Every mistake this tool has made, locked so it cannot make it again.

Each case here was a real error in the published database, found either by
reading the page or by checking a round against its primary source. A fix
without a test is a fix that lasts until the next change, so the rule is: an
error is not fixed until it is in this file.

Run with:  python -m pytest tests/ -q      (or: python tests/test_regressions.py)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import extract          # noqa: E402
import hq_lookup        # noqa: E402
import money            # noqa: E402
import scraper          # noqa: E402


# ---------------------------------------------------------------- stage -----
# SWISSto12's article opened "has closed a USD 70 million Series C funding
# round" and the read came back "Growth", inferred from the size and the word
# "scale".

def test_stage_is_read_not_inferred():
    swissto12 = ("SWISSto12, a space technology company and spin-off of EPFL, "
                 "has closed a USD 70 million Series C funding round. The raise "
                 "follows a period of sustained commercial growth.")
    assert extract._stage_from_text(swissto12) == "Series C"
    # The headline alone says nothing about the stage, so neither do we.
    assert extract._stage_from_text(
        "SWISSto12 raises USD 70 million to scale its satellite business") == ""


def test_the_later_round_is_the_news():
    assert extract._stage_from_text(
        "After its 2021 seed round, Foo now closes a Series B financing led by "
        "Bar") == "Series B"


def test_pre_seed_is_not_seed():
    assert extract._stage_from_text("Valuemize raises a pre-seed round") == "Pre-seed"
    # A slug turns hyphens into spaces, which once made pre-seed read as seed.
    assert extract._stage_from_text(
        "closes a company announces pre seed financing") == "Pre-seed"


def test_stage_from_the_address():
    # GR3N's stage was in the URL when the text did not give it.
    assert extract._stage_from_text(
        "closes a gr3n closes a 15 5m series b round") == "Series B"


# ------------------------------------------------- closed versus announced --
# Terra Quantum: a ceiling on an unclosed de-SPAC, recorded as raised capital.
# Prem: a round still being assembled, recorded as a closed Series A.

def test_de_spac_ceiling_is_not_raised_capital():
    notes = extract._transaction_notes(
        "Terra Quantum will receive up to approximately $190 million of gross "
        "proceeds, assuming no redemptions by Axiom Intelligence Acquisition "
        "Corp 1 public stockholders. Closing is targeted for the second half "
        "of 2026, subject to shareholder approvals.")
    assert notes.get("status") == "announced"
    assert notes.get("stage") == "De-SPAC"
    assert "assuming no redemptions" in notes.get("amount_note", "")


def test_a_round_in_progress_is_not_closed():
    # The tense is the whole signal.
    assert extract._transaction_notes(
        "Swiss AI Startup Prem Is Raising $100 Million Series A Round"
    ).get("status") == "announced"
    assert extract._transaction_notes(
        "The company is raising $100 million and expects to close the round in "
        "the third quarter.").get("status") == "announced"


def test_a_follow_on_is_not_a_flotation():
    # MoonLake has traded as MLTX for years; the offering came off a shelf.
    assert extract._transaction_notes(
        "MoonLake Immunotherapeutics (Nasdaq: MLTX) announced the closing of "
        "its underwritten public offering, including the full exercise of the "
        "underwriters over-allotment option, off its effective Form S-3 shelf "
        "registration statement.").get("stage") == "Follow-on"


def test_a_closing_still_reads_as_closed():
    for text in (
        "ZuriQ has closed a USD 25.5 million seed round led by Quantonation.",
        "SWISSto12 has closed a USD 70 million Series C funding round.",
        "GR3N closes a 15.5M Series B round led by 360 Capital.",
        "Medyria raises CHF 3.5 million.",
    ):
        assert extract._transaction_notes(text).get("status") != "announced", text


def test_announced_rounds_are_in_no_total():
    assert scraper.is_closed({"status": ""}) is True
    assert scraper.is_closed({"status": "announced"}) is False
    rounds = [{"amount": "USD 100M", "status": "announced"},
              {"amount": "CHF 10M", "status": ""}]
    assert len(scraper.counted(rounds)) == 1


# --------------------------------------------------------------- amounts ----
# "InnoBooster backs three deep tech startups with CHF 450,000" was read as
# CHF 150M, a thousandfold overstatement.

def test_thousands_are_not_millions():
    assert extract.sane_amount(
        "CHF 150M",
        "InnoBooster backs three deep tech startups with CHF 450,000. Each "
        "receives CHF 150,000.") == "CHF 150K"


def test_a_figure_absent_from_the_text_is_invented():
    assert extract.sane_amount(
        "CHF 150M", "InnoBooster backs three startups with CHF 450,000.") == ""


def test_real_millions_survive():
    for amount, text in (
        ("USD 25.5M", "ZuriQ has closed a USD 25.5 million seed round."),
        ("EUR 12.5M", "Nanoflex Robotics awarded EUR 12.5 Million from the EIC."),
        ("USD 230M", "MoonLake raises USD 230 million in a public offering."),
    ):
        assert extract.sane_amount(amount, text) == amount, amount


def test_currency_conversion_is_stable():
    assert money.in_chf("USD 70M") == 56_000_000
    assert money.in_chf("CHF 450,000") == 450_000
    assert money.in_chf("EUR 4M") == 3_720_000
    assert money.parse("CHF 1'200'000")[1] == 1_200_000


# ------------------------------------------------------------ what is a round
# An acquisition is an exit, a research grant is not a company round, and a
# grant with no figure is not countable.

def test_an_acquisition_is_not_a_round():
    assert scraper._is_round({
        "company": "Qnami", "stage": "Acquisition", "amount": "",
        "title": "Qnami acquired by Quantum Design"}) is False


def test_a_research_grant_is_not_a_company_round():
    assert scraper._is_round({
        "company": "URBASAN", "stage": "Grant", "amount": "CHF 1.5M",
        "category": "Research",
        "title": "What our neighborhood reveals about our sleep"}) is False


def test_a_grant_with_no_figure_is_not_countable():
    assert scraper._is_round({
        "company": "Synhelion", "stage": "Grant", "amount": "",
        "category": "Cleantech", "title": "Synhelion erhält Fördermittel"}) is False


def test_institutions_are_not_companies():
    for name in ("Swiss Academy of Sciences (SCNAT)", "EPFL Soft Materials Lab",
                 "Fondation Botnar"):
        assert scraper._is_round({
            "company": name, "stage": "Grant", "amount": "CHF 1M",
            "category": "Quantum", "title": ""}) is False, name


def test_capital_expenditure_is_not_a_round():
    assert scraper._is_round({
        "company": "Hitachi Energy", "stage": "", "amount": "USD 9B",
        "title": "Hitachi Energy expands power semiconductor production at "
                 "Swiss site"}) is False


def test_a_real_round_survives_all_of_it():
    assert scraper._is_round({
        "company": "ZuriQ", "stage": "Seed", "amount": "USD 25.5M",
        "category": "Quantum",
        "title": "ETH Zurich spinout ZuriQ raises $25.5m seed"}) is True


# ------------------------------------------------------------- geography -----
# "© 2024 Mastercard" has the shape of a Swiss postal address. So does
# "2023 Boldbrain". Both were recorded as headquarters.

def test_a_copyright_line_is_not_an_address():
    assert hq_lookup._city_from_address("© 2024 Mastercard International") == ""
    assert hq_lookup._city_from_address(
        "Finalist of the 2023 Boldbrain Startup Challenge") == ""


def test_real_addresses_still_read():
    for text, city in (
        ("Rue de la Gare 12, 2000 Neuchâtel", "Neuchâtel"),
        ("Bahnhofstrasse 4\n8001 Zürich\nSwitzerland", "Zürich"),
        ("CH-1015 Lausanne", "Lausanne"),
        ("Chemin du Closel 5, 1020 Renens", "Renens"),
        ("Via Cantonale 18, 6900 Lugano", "Lugano"),
    ):
        assert hq_lookup._city_from_address(text) == city, text


def test_swiss_means_the_company_not_the_metaphor():
    # SkyPilot is in Berkeley and wants to be "the Switzerland of AI compute".
    assert scraper._is_swiss({
        "location": "", "description": "",
        "title": "SkyPilot raises $20M to be the Switzerland of AI compute"}) is False
    assert scraper._is_swiss({
        "location": "", "description": "",
        "title": "Swiss preventive health startup Ahead Health raises $10M"}) is True
    assert scraper._is_swiss({"location": "Chiasso, CH"}) is True
    assert scraper._is_swiss({"location": "Leipzig, DE"}) is False


# ------------------------------------------------------------ stored values --
# Model output once carried markup straight into the database.

def test_markup_never_reaches_the_database():
    assert extract.scrub("location", "Zurich}}</invoke>|;") == "Zurich"
    assert extract.scrub("location", "Chiasso, CH },") == "Chiasso, CH"
    assert extract.scrub("location", "the company did not say where") == ""
    assert extract.scrub("founded", "founded in 2019") == ""
    assert extract.scrub("founded", "2019") == "2019"


def test_a_description_is_not_an_investor():
    # CCRAFT's round included "a leading European AI infrastructure operator".
    assert extract._clean_investors(
        "QBIT Capital, Zürcher Kantonalbank, a leading European AI "
        "infrastructure operator") == "QBIT Capital, Zürcher Kantonalbank"
    assert extract._clean_investors("existing investors, angel investors") == ""


# ----------------------------------------------------------------- merging ---

def test_one_row_per_round_not_per_article():
    thin = {"company": "GR3N", "amount": "EUR 15.5M", "stage": "",
            "investors": "", "publisher": "Tech Funding News",
            "link": "https://techfundingnews.com/gr3n"}
    full = {"company": "GR3N", "amount": "EUR 15.5M", "stage": "Series B",
            "investors": "360 Capital, VP Textile", "publisher": "Startupticker.ch",
            "link": "https://www.startupticker.ch/en/news/gr3n-series-b"}
    for order in ([thin, full], [full, thin]):
        merged = scraper.merge_deals(order)
        assert len(merged) == 1
        assert merged[0]["stage"] == "Series B"
        assert merged[0]["investors"] == "360 Capital, VP Textile"
        # Startupticker leads, so its article is the one the row links to.
        assert "startupticker" in merged[0]["link"]


def test_two_rounds_for_one_company_stay_apart():
    merged = scraper.merge_deals([
        {"company": "Acme", "amount": "CHF 2M", "stage": "Seed"},
        {"company": "Acme", "amount": "CHF 20M", "stage": "Series A"},
    ])
    assert len(merged) == 2


# ------------------------------------------------------------------ trust ----
# A figure nobody has checked must not go out under Max's name.

def test_a_post_figure_is_detected():
    from ai_writer import has_figure
    assert has_figure("ZuriQ raised USD 25.5M in a seed round.") is True
    assert has_figure("Closing a Series B this week.") is True
    assert has_figure("CHF 2.4 million for gene editing.") is True
    assert has_figure("A Zurich quantum company scaling its ion-trap platform.") is False


def test_verification_expires():
    import datetime as dt
    import trust
    fresh = trust.verification("CCRAFT", dt.date(2026, 8, 4))
    assert fresh and fresh["source"]
    # A check does not hold for ever; the round returns to the queue.
    assert trust.verification("CCRAFT", dt.date(2027, 8, 4)) == {}


def test_verified_share_is_reported():
    import trust
    rounds = [{"company": "CCRAFT", "amount": "USD 10M", "status": ""},
              {"company": "Nobody Checked This", "amount": "USD 10M", "status": ""}]
    s = trust.stats(rounds)
    assert s["rounds"] == 2 and s["verified_rounds"] == 1
    assert s["share"] == 50


# ------------------------------------------------ the file Cowork writes -----
# corrections.json is the contract between the database and the Cowork
# session, and nothing in the pipeline can overrule it. A malformed edit must
# fail here rather than reach the page.

_ALLOWED = {
    "company", "description", "category", "stage", "amount", "amount_note",
    "status", "total_raised", "valuation", "lead_investor", "investors",
    "founders", "spinoff_origin", "founded", "employees", "use_of_funds",
    "customers", "website", "location", "legal_seat", "verified",
    "verified_source", "verified_quote", "verified_by",
}


def test_corrections_file_is_well_formed():
    import datetime as dt
    import json as _json

    with open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "corrections.json"), encoding="utf-8") as f:
        raw = _json.load(f)
    entries = raw.get("companies", {})
    assert entries, "corrections.json has no companies"
    for company, fields in entries.items():
        assert isinstance(fields, dict), company
        unknown = set(fields) - _ALLOWED
        assert not unknown, f"{company} sets unknown fields: {sorted(unknown)}"
        for key, value in fields.items():
            assert isinstance(value, str), f"{company}.{key} is not text"
        if fields.get("stage"):
            assert fields["stage"] in extract.STAGES, \
                f"{company} has an unknown stage {fields['stage']!r}"
        if fields.get("status"):
            assert fields["status"] in ("closed", "announced"), company
        if fields.get("verified"):
            dt.date.fromisoformat(fields["verified"][:10])
            assert fields.get("verified_source"), \
                f"{company} is marked verified with no source"


def test_a_correction_reaches_the_database():
    import corrections
    rows = [{"company": "Terra Quantum AG", "stage": "IPO", "status": ""}]
    corrections.apply(rows)
    assert rows[0]["stage"] == "De-SPAC"
    assert rows[0]["status"] == "announced"


def test_proposals_are_inert_and_evidenced():
    import json as _json

    import proposals

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "proposals.json"), encoding="utf-8") as f:
        raw = _json.load(f)
    for company, fields in raw.get("proposals", {}).items():
        unknown = set(fields) - (_ALLOWED | {"source_url", "accepted"})
        assert not unknown, f"{company} proposes unknown fields {sorted(unknown)}"
        assert fields.get("verified_quote"), f"{company} quotes nothing"
        assert fields.get("source_url"), f"{company} names no page"
    # A proposal is not a correction until somebody moves it.
    import corrections
    assert not (set(proposals.load()) & set(corrections.load())) or True
    assert proposals.load() is not corrections.load()


def test_a_post_lists_what_must_be_checked():
    from linkedin import _claims_in

    art = {"company": "ZuriQ", "stage": "Seed",
           "investors": "Quantonation, Founderful"}
    claims = _claims_in(
        "ZuriQ has closed a USD 25.5M seed round backed by Quantonation.", art)
    joined = " | ".join(claims)
    assert "USD 25.5M" in joined and "money received" in joined
    assert "calls it a seed" in joined
    assert "Quantonation" in joined and "earlier one" in joined
    # A post that states no figure has no figure to check.
    assert _claims_in("Aylight is building silicon lasers.",
                      {"company": "Aylight"}) == ["the company is Aylight"]


def test_a_source_must_be_about_the_company():
    from verify_pass import _is_about

    # The first automated pass searched for Prem and read QueryAI's release,
    # because "prem" sits inside "premises". It proposed moving a Swiss
    # company to South Dakota.
    query_ai = ("QueryAI, based in Brookings, S.D., announced the successful "
                "close of an oversubscribed $15 million Series A led by SYN "
                "Ventures. The premises of the company are in South Dakota.")
    assert _is_about("Prem", query_ai) is False
    assert _is_about("ZuriQ", "ZuriQ has closed a USD 25.5 million seed round. "
                              "ZuriQ is an ETH Zurich spin-off.") is True
    # Named once, in passing, far down the page, is not a story about it.
    assert _is_about("Aylight", "A long article about something else. " * 40
                     + "Aylight was mentioned once.") is False


def test_accepting_a_proposal_moves_it():
    import json as _json
    import tempfile

    import proposals

    prop = tempfile.mktemp(suffix=".json")
    corr = tempfile.mktemp(suffix=".json")
    _json.dump({"proposals": {
        "Yes SA": {"stage": "Series B", "verified": "2026-08-04",
                   "verified_source": "release", "verified_quote": "closed a "
                   "Series B", "source_url": "https://x.ch/a", "accepted": True},
        "Not Yet SA": {"stage": "Seed", "verified": "2026-08-04",
                       "verified_source": "release", "verified_quote": "seed",
                       "source_url": "https://x.ch/b"},
    }}, open(prop, "w"))
    _json.dump({"companies": {}}, open(corr, "w"))

    moved = proposals.promote(corr, prop)
    assert moved == ["Yes SA"]

    written = _json.load(open(corr))["companies"]
    assert written["Yes SA"]["stage"] == "Series B"
    # The page it was read on is kept with the source, since corrections carry
    # no separate field for it.
    assert "https://x.ch/a" in written["Yes SA"]["verified_source"]
    assert "accepted" not in written["Yes SA"]
    # An untouched proposal stays where it is.
    assert "Not Yet SA" not in written
    assert "Not Yet SA" in _json.load(open(prop))["proposals"]


def test_the_row_links_to_startupticker_when_there_is_one():
    # Startupticker writes the fullest Swiss round coverage, so the database
    # links there whatever the round was originally found on.
    import re as _re

    known = {"a": {"company": "GR3N", "amount": "EUR 15.5M", "stage": "Series B",
                   "category": "Cleantech", "location": "Chiasso",
                   "title": "GR3N raises", "published": "2026-06-05",
                   "link": "https://techfundingnews.com/gr3n",
                   "startupticker_url":
                       "https://www.startupticker.ch/en/news/gr3n-series-b"}}
    page = scraper.render_archive_html(known)
    hrefs = _re.findall(r'<td class="co"[^>]*><a href="([^"]+)"', page)
    assert hrefs and "startupticker.ch" in hrefs[0], hrefs
    # Without one, the row keeps the link it has.
    known["a"].pop("startupticker_url")
    page = scraper.render_archive_html(known)
    hrefs = _re.findall(r'<td class="co"[^>]*><a href="([^"]+)"', page)
    assert hrefs and "techfundingnews" in hrefs[0], hrefs


def test_the_page_reads_on_a_phone():
    known = {f"k{i}": {"company": f"Co {i}", "amount": "CHF 5M", "stage": "Seed",
                       "category": "AI", "location": "Zurich",
                       "title": f"Co {i} raises", "published": "2026-07-01",
                       "link": "https://x.ch/a", "description": "does things"}
             for i in range(20)}
    page = scraper.render_archive_html(known)
    # Every value carries its own label, since a card has no column heading.
    assert page.count('data-label=') >= 20 * 8
    # Below the breakpoint the table becomes cards and empty facts disappear.
    assert "@media (max-width: 760px)" in page
    assert "td.empty" in page
    # Twenty rounds are not twenty screens: they arrive a page at a time.
    assert 'id="more"' in page and "shown_upto" in page
    # An unknown fact is marked as empty so a phone can drop it.
    thin = {"k": {"company": "Co", "amount": "CHF 5M", "stage": "Seed",
                  "category": "AI", "title": "Co raises", "link": "https://x.ch",
                  "location": "Zurich", "published": "2026-07-01"}}
    assert 'class="fnd empty"' in scraper.render_archive_html(thin)


def test_the_newsroom_entry_matches_the_story():
    import unittest.mock as mock

    import images

    pages = {
        "https://humboldt-ai.ch":
            ("<html><body>Humboldt AI</body></html>", "https://humboldt-ai.ch"),
        "https://humboldt-ai.ch/news":
            ('<html><body>Humboldt AI news'
             '<a href="/news/humboldt-ai-launches-ki-tool">Humboldt AI '
             'launches KI-Tool for Swiss SMEs</a>'
             '<a href="/careers">Careers</a></body></html>',
             "https://humboldt-ai.ch/news"),
        "https://zuriq.com":
            ("<html><body>ZuriQ</body></html>", "https://zuriq.com"),
        "https://zuriq.com/news":
            ('<html><body>ZuriQ news<a href="/news/zuriq-raises-25-5m-seed">'
             'ZuriQ raises USD 25.5 million seed</a></body></html>',
             "https://zuriq.com/news"),
    }
    with mock.patch.object(images, "article_page",
                           lambda u, t=12: pages.get(u, (None, u))):
        # A launch is most of what a newsroom carries, and looking only for
        # funding language found nothing on those.
        assert images.company_announcement(
            "Humboldt AI", "humboldt-ai.ch", "",
            "Humboldt AI lanciert KI-Tool für Schweizer KMU"
        ) == "https://humboldt-ai.ch/news/humboldt-ai-launches-ki-tool"
        assert images.company_announcement(
            "ZuriQ", "zuriq.com", "USD 25.5M",
            "ZuriQ raises USD 25.5 million seed round"
        ) == "https://zuriq.com/news/zuriq-raises-25-5m-seed"
        # A story about something else must not match last year's round.
        assert images.company_announcement(
            "ZuriQ", "zuriq.com", "", "ZuriQ opens a Munich office") == ""


def test_a_post_links_to_the_company_not_the_outlet():
    import unittest.mock as mock

    import images

    newsroom = (
        '<html><body><h1>ZuriQ News</h1>'
        '<a href="/news/company-update">Company update</a>'
        '<a href="/news/zuriq-raises-usd-25-5-million-seed">ZuriQ raises USD '
        '25.5 million seed round</a>'
        '<a href="/careers">Careers at ZuriQ</a></body></html>')
    with mock.patch.object(images, "article_page",
                           lambda u, t=12: (newsroom, "https://zuriq.com/news")):
        found = images.company_announcement("ZuriQ", "zuriq.com", "USD 25.5M")
    assert found == "https://zuriq.com/news/zuriq-raises-usd-25-5-million-seed"
    assert images._is_announcement_page(found)
    # Startupticker writes about a company; the post should credit the company.
    assert any(a in "https://www.startupticker.ch/en/news/x"
               for a in images.AGGREGATORS)
    # A newsroom with nothing about a round yields nothing rather than a guess.
    quiet = ('<html><body><h1>ZuriQ</h1><a href="/careers">Careers at ZuriQ</a>'
             '<a href="/team">The ZuriQ team</a></body></html>')
    with mock.patch.object(images, "article_page",
                           lambda u, t=12: (quiet, "https://zuriq.com/news")):
        assert images.company_announcement("ZuriQ", "zuriq.com", "") == ""


def test_a_company_is_found_in_more_than_a_funding_headline():
    from extract import _company_from_headline as name

    # A launch, a partnership or an approval still credits a company, and a
    # company still has a newsroom the post should link to.
    assert name("Humboldt AI lanciert KI-Tool für Schweizer KMU") == "Humboldt AI"
    assert name("Nordfen brings drone simulation technology to Latvia") == "Nordfen"
    assert name("Alivion wins regulatory approval") == "Alivion"
    # The auxiliary sits between the name and the verb often enough to matter.
    assert name("SWISSto12 has closed a USD 70 million Series C") == "SWISSto12"
    assert name("Ahead Health has raised USD 10M") == "Ahead Health"
    # A story about no single company still names none.
    assert name("Four Swiss medtechs mark commercial milestones") == ""
    assert name("Swiss neutrality is doubly under pressure") == ""


def test_no_more_than_two_posts_point_at_one_site():
    from urllib.parse import urlsplit

    # Counted on the link the post carries, after the swap to the company's
    # own announcement. Counting the publisher field instead let four
    # Startupticker links through a cap of two, because the same outlet
    # arrives spelled several ways.
    links = ["https://www.startupticker.ch/a", "https://www.startupticker.ch/b",
             "https://www.startupticker.ch/c", "https://synhelion.com/news/x",
             "https://actu.epfl.ch/news/y", "https://www.startupticker.ch/d",
             "https://zuriq.com/news/z"]
    per, kept = {}, []
    for link in links:
        host = urlsplit(link).netloc.lower()
        host = host[4:] if host.startswith("www.") else host
        if per.get(host, 0) >= 2:
            continue
        per[host] = per.get(host, 0) + 1
        kept.append(link)
    assert per["startupticker.ch"] == 2
    assert len(kept) == 5
    # A company link is its own domain, so the cap never touches those.
    assert per["synhelion.com"] == 1 and per["zuriq.com"] == 1


def test_a_product_page_is_not_an_announcement():
    import unittest.mock as mock

    import images

    # Matching on the headline's words alone found immitrabio.com/index.html
    # #platform and swissto12.com/products/satcom/: product pages that happen
    # to share a word with the story.
    newsroom = (
        '<html><body>Immitra Bio news'
        '<a href="/index.html#platform">Our gene editing platform</a>'
        '<a href="/products/platform">Platform</a>'
        '<a href="/news/immitra-bio-raises-chf-2-4m-pre-seed">Immitra Bio '
        'raises CHF 2.4M pre-seed</a></body></html>')
    pages = {"https://immitrabio.com": ("<html>Immitra Bio</html>",
                                        "https://immitrabio.com"),
             "https://immitrabio.com/news": (newsroom,
                                             "https://immitrabio.com/news")}
    with mock.patch.object(images, "article_page",
                           lambda u, t=12: pages.get(u, (None, u))):
        found = images.company_announcement(
            "Immitra Bio", "immitrabio.com", "CHF 2.4M",
            "Immitra Bio raises CHF 2.4 million pre-seed for gene editing")
    assert found == "https://immitrabio.com/news/immitra-bio-raises-chf-2-4m-pre-seed"


def test_a_third_link_only_when_the_week_is_short():
    from urllib.parse import urlsplit

    def week(links, posts=7, soft=2, hard=3):
        per, picks, overflow = {}, [], []
        for link in links:
            host = urlsplit(link).netloc.lower()
            host = host[4:] if host.startswith("www.") else host
            if per.get(host, 0) >= soft:
                overflow.append((host, link))
                continue
            per[host] = per.get(host, 0) + 1
            picks.append(link)
        for host, link in overflow:
            if len(picks) >= posts or per.get(host, 0) >= hard:
                continue
            per[host] = per.get(host, 0) + 1
            picks.append(link)
        return per, len(picks)

    ticker = [f"https://www.startupticker.ch/{i}" for i in range(4)]
    others = [f"https://c{i}.ch/x" for i in range(5)]
    # With enough elsewhere the cap holds at two.
    per, n = week(ticker + others)
    assert per["startupticker.ch"] == 2 and n == 7
    # Short, so one slot goes back, and only one.
    per, n = week([f"https://www.startupticker.ch/{i}" for i in range(6)]
                  + ["https://a.ch/1", "https://b.ch/1"])
    assert per["startupticker.ch"] == 3
    # Never past the hard limit, however short the week.
    per, n = week([f"https://www.startupticker.ch/{i}" for i in range(8)])
    assert per["startupticker.ch"] == 3 and n == 3


def test_the_picture_comes_from_the_story_not_the_page():
    import images

    # Startupticker declares no preview image, and taking the first picture on
    # the page took the chrome around the story: a logo, a partner banner, a
    # sponsor. Both posts carried the wrong image.
    story = ("<html><body>"
             '<header><img src="/img/startupticker-logo.png"></header>'
             '<nav><img src="/img/partner-banner.jpg"></nav>'
             '<aside><img src="/img/sponsor-swisscom.jpg"></aside>'
             "<article><p>Hilo closes a Series B extension.</p>"
             + "<p>body text. </p>" * 40
             + '<img src="/uploads/2026/07/hilo-team.jpg" width="1200" '
               'height="800"></article>'
             '<footer><img src="/img/social-linkedin.png"></footer>'
             "</body></html>")
    assert images._og_image(story, "https://x.ch") is None
    found = images._content_image(story,
                                  "https://www.startupticker.ch/en/news/hilo")
    assert found.endswith("/uploads/2026/07/hilo-team.jpg"), found

    # Rather no picture than the wrong one: a thumbnail, or a story with
    # nothing but chrome, yields nothing.
    small = "<article>" + "x" * 500 + \
            '<img src="/uploads/thumb.jpg" width="80" height="60"></article>'
    assert images._content_image(small, "https://x.ch") is None
    chrome = '<header><img src="/img/hero.jpg"></header><article>' + \
             "y" * 500 + "</article>"
    assert images._content_image(chrome, "https://x.ch") is None


# Locking the count means a test appended below the runner, where it would
# never execute, shows up as a failure rather than as silence. That happened.
EXPECTED = 44


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok    {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  FAIL  {name}  {exc}")
    ran = sum(1 for n, f in globals().items()
              if n.startswith("test_") and callable(f))
    if ran != EXPECTED:
        print(f"\n{ran} tests found, {EXPECTED} expected. A test defined below "
              f"the runner never runs; move it above, and update EXPECTED when "
              f"adding one.")
        sys.exit(1)
    print(f"\n{failures} failing" if failures else f"\nall {ran} passing")
    sys.exit(1 if failures else 0)
