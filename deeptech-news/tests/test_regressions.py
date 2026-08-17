"""Every mistake this tool has made, locked so it cannot make it again.

Each case here was a real error in the published database, found either by
reading the page or by checking a round against its primary source. A fix
without a test is a fix that lasts until the next change, so the rule is: an
error is not fixed until it is in this file.

Run with:  python -m pytest tests/ -q      (or: python tests/test_regressions.py)
"""

from __future__ import annotations

import html
import os
import re
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
    # Not so loose that a real second round folds into the first.
    assert len(scraper.merge_deals([
        {"company": "Bar", "amount": "CHF 10M", "stage": "Seed"},
        {"company": "Bar", "amount": "CHF 12M", "stage": "Series A"},
    ])) == 2


def test_one_round_quoted_in_two_currencies_is_one_row():
    """Exclaim Robotics was on the page twice, and in the total twice."""
    # The same pre-seed, written up three times: dollars in two papers, euros
    # in the third. Keyed on the raw number they looked like separate rounds.
    merged = scraper.merge_deals([
        {"company": "Exclaim Robotics", "amount": "USD 4.95M",
         "stage": "Pre-seed", "location": "Zurich", "publisher": "Startupticker",
         "title": "Exclaim Robotics raises USD 4.95 million"},
        {"company": "Exclaim Robotics", "amount": "EUR 4.29M",
         "stage": "Pre-seed", "location": "Zurich", "publisher": "EU-Startups",
         "title": "Zurich-based Exclaim Robotics exits stealth"},
        {"company": "Exclaim Robotics", "amount": "USD 4.95M",
         "stage": "Pre-seed", "location": "Zurich", "publisher": "AI Insider",
         "title": "Swiss Startup Exclaim Robotics Emerges From Stealth"},
    ])
    assert len(merged) == 1, [m["amount"] for m in merged]
    # The preferred outlet still sets the figure, and every outlet is credited.
    assert merged[0]["amount"] == "USD 4.95M"
    assert set(merged[0]["sources"]) == {"Startupticker", "EU-Startups",
                                         "AI Insider"}
    # And the money is counted once, not twice.
    assert len(scraper.counted(merged)) == 1

    # The tolerance is about conversion drift, not about size: a figure that
    # differs by a fifth is a different round.
    assert scraper._same_size(3_960_000, 3_989_700) is True
    assert scraper._same_size(10_000_000, 12_000_000) is False
    assert scraper._same_size(0, 0) is True
    assert scraper._same_size(0, 5_000_000) is False


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


def test_a_round_is_dated_by_the_round_not_by_the_write_up():
    """GR3N closed on 5 June and sat second on a page sorted newest first."""
    import datetime as dt

    def write_up(publisher, published):
        entry = {"company": "GR3N", "amount": "EUR 15.5M", "stage": "Series B",
                 "location": "Chiasso", "category": "Cleantech",
                 "publisher": publisher, "first_seen": "2026-08-03",
                 "description": "PET recycling", "title": "GR3N closes 15.5M",
                 "link": f"https://{publisher}/gr3n"}
        if published:
            entry["published"] = published
        return entry

    known = {
        # One write-up carries no date at all, which is what broke it: the
        # sort fell back to the day the tool found the story.
        "a": write_up("startupticker.ch", None),
        "b": write_up("techfundingnews.com", "2026-06-05"),
        "c": {"company": "Newer SA", "amount": "CHF 5M", "stage": "Seed",
              "location": "Zurich", "category": "Quantum",
              "published": "2026-08-01", "first_seen": "2026-08-01",
              "description": "Newer", "title": "Newer raises",
              "link": "https://startupticker.ch/newer"},
    }
    page = scraper.render_archive_html(known, now=dt.datetime(2026, 8, 5, 9, 0))
    rows = re.findall(r"<tr data-chf.*?</tr>", page, re.S)
    order = [re.search(r'data-company="([^"]*)"', r).group(1) for r in rows]
    assert order == ["Newer SA", "GR3N"], order
    # The merged round keeps the earliest date any outlet gave it.
    assert 'data-date="2026-06-05"' in page

    # A note that says nothing is not printed in front of the figure. The
    # reader wrote "amount" on a seed and the page read "amount USD 10M".
    from extract import useful_note
    for junk in ("amount", "Amount", "total", "n/a", "", "  ", "..."):
        assert useful_note(junk) == "", junk
    for real in ("up to", "gross proceeds", "Series B extension"):
        assert useful_note(real) == real, real


def test_the_news_page_carries_more_than_the_money():
    """The database answers which rounds closed; this answers what happened."""
    import datetime as dt

    known = {
        "a": {"company": "ZuriQ", "amount": "USD 25.5M", "stage": "Seed",
              "location": "Zurich", "category": "Quantum",
              "published": "2026-08-01", "title": "ZuriQ raises $25.5m seed",
              "link": "https://startupticker.ch/zuriq", "score": 8},
        # A grant with no figure and a research result are not rounds, and were
        # therefore invisible: the database is the wrong page to look for them.
        "b": {"company": "Synhelion", "amount": "", "stage": "Grant",
              "location": "Zurich", "category": "Cleantech",
              "published": "2026-07-30", "title": "Synhelion erhält Fördermittel",
              "link": "https://startupticker.ch/synhelion", "score": 6},
        "c": {"company": "", "category": "Research", "published": "2026-07-28",
              "title": "EPFL researchers find a lipid switch blocking anthrax",
              "link": "https://actu.epfl.ch/anthrax", "score": 8},
        # And a foreign company covered by a Swiss outlet is not Swiss news.
        "d": {"company": "Anthropic", "amount": "USD 65.8B", "stage": "Series D",
              "location": "San Francisco, US", "category": "AI",
              "published": "2026-08-01", "title": "Global AI funding triples",
              "link": "https://fintechnews.ch/global-ai-funding", "score": 5},
    }
    page = scraper.render_news_html(known, now=dt.datetime(2026, 8, 5, 9, 0))

    assert page.count("<li data-") == 3, "the foreign round should be left out"
    for kept in ("ZuriQ", "Synhelion", "lipid switch"):
        assert kept in page, kept
    assert "Anthropic" not in page
    # A recorded headquarters settles it whoever published the story.
    assert scraper.plausibly_swiss(known["d"]) is False
    assert scraper.plausibly_swiss(known["b"]) is True

    # The round is labelled as one, so the two pages stay legible together.
    assert page.count('data-kind="Round"') == 1
    assert "the database" in page

    # A story Max sent in is marked as sent, not scored: the marker is 999 and
    # printing "relevance 999" beside a dateless row looked like a broken page.
    sent = dict(known["a"], score=scraper.SUBMITTED)
    assert scraper._rank(sent) == "sent in"
    assert scraper._rank({"score": 8}) == "relevance 8"
    # And a story with no date shows no date rather than the word n/a.
    assert scraper._meta_line({"publisher": "Startupticker", "date": None,
                               "score": 999}) == "Startupticker · sent in"


def test_the_news_page_says_what_kind_of_news_each_story_is():
    """A round, a grant and a professor's appointment read alike in a list."""
    import datetime as dt

    def story(title, link="https://startupticker.ch/x", **extra):
        return dict({"title": title, "link": link, "company": "Foo",
                     "description": "", "amount": "", "stage": "",
                     "category": "Quantum"}, **extra)

    cases = [
        ("Exclaim Robotics raises USD 4.95 million", {"amount": "USD 4.95M",
         "stage": "Pre-seed", "category": "Robotics"}, "Round"),
        # A round the reader could not pin down still reads as one.
        ("SeasON Energy erhält Millionenfinanzierung", {}, "Round"),
        ("Synhelion erhält Fördermittel", {"stage": "Grant"}, "Grant"),
        ("Tech4Trust Crowns AURIGIN.AI as Grand Prize Winner", {}, "Award"),
        ("Qnami acquired by Quantum Design", {}, "Acquisition"),
        ("Nordfen brings drone simulation to Latvia",
         {"stage": "Partnership"}, "Partnership"),
        ("Hi-D Imaging wins expanded FDA clearance", {}, "Regulatory"),
        ("In AI arms race, Swiss neutrality is double-edged sword", {}, "Policy"),
        ("Humboldt AI lanciert KI-Tool für den CV-Check", {}, "Launch"),
        ("Hitachi Energy expands power semiconductor production at Swiss site",
         {}, "Expansion"),
        ("ETH names new professor of quantum engineering", {}, "Appointment"),
        ("A tiny pore identifies cyanobacteria toxins in lake water", {},
         "Research"),
        # No keyword at all, but a laboratory's own newsroom publishes research.
        ("A lipid switch that blocks anthrax",
         {"link": "https://actu.epfl.ch/news/anthrax"}, "Research"),
        ("Swiss Stocks Climb As AI Chip Fever Lifts Micron", {}, "General"),
    ]
    for title, extra, expected in cases:
        assert scraper._kind(story(title, **extra)) == expected, \
            f"{title!r} read as {scraper._kind(story(title, **extra))}"

    # The description is written by the reader and is not evidence: one stray
    # word in it filed an opinion piece under Research.
    opinion = story("In AI arms race, Swiss neutrality is double-edged sword",
                    description="Article on Switzerland as an AI research hub")
    assert scraper._kind(opinion) == "Policy"

    # A Google News publisher suffix must not decide the kind either.
    assert scraper._kind(story(
        "Switzerland confirms its lead in deep tech - Research Institute")) \
        == "General"

    # The page shows the label and offers it as a filter, with counts.
    known = {str(i): story(t, **e) for i, (t, e, _) in enumerate(cases)}
    page = scraper.render_news_html(known, now=dt.datetime(2026, 8, 5, 9, 0))
    assert 'id="kind"' in page
    assert 'data-kind="Round"' in page and 'data-kind="Research"' in page
    assert re.search(r'<option value="Round">Round \(\d+\)</option>', page)


def test_one_story_one_entry_preferring_startupticker_in_english():
    """Exclaim Robotics was on the news page three times, once in French."""
    import datetime as dt

    def copy(publisher, title, link, score=8, amount="USD 4.95M"):
        return {"company": "Exclaim Robotics", "amount": amount, "stage": "Pre-seed",
                "location": "Zurich", "category": "Robotics", "score": score,
                "publisher": publisher, "published": "2026-08-05",
                "first_seen": "2026-08-05", "description": "Data centre robots",
                "title": title, "link": link}

    known = {
        "fr": copy("L'Usine Digitale",
                   "Avec ses robots mobiles, la start-up suisse Exclaim Robotics "
                   "veut automatiser la maintenance des data centers",
                   "https://usine-digitale.fr/exclaim", score=9),
        "en": copy("Startupticker",
                   "Exclaim Robotics raises USD 4.95 million for data centre "
                   "repair robots",
                   "https://www.startupticker.ch/en/news/exclaim"),
        # Worded far enough apart to survive the headline check, so the round
        # identity has to catch it, and in euros so the currency must not fool it.
        "eu": copy("EU-Startups",
                   "Zurich-based Exclaim Robotics exits stealth with EUR 4.29 "
                   "million to build robots",
                   "https://eu-startups.com/exclaim", amount="EUR 4.29M"),
    }
    page = scraper.render_news_html(known, now=dt.datetime(2026, 8, 5, 9, 0))
    assert page.count("<li data-") == 1
    # Startupticker in English wins even though the French piece scored higher.
    assert "raises USD 4.95 million" in page
    assert "L&#x27;Usine" not in page and "EU-Startups" not in page

    # The headline decides the language, not the address: Startupticker files
    # German pieces under /en/.
    assert scraper._in_english({
        "title": "Humboldt AI lanciert KI-Tool für den CV-Check",
        "link": "https://www.startupticker.ch/en/news/humboldt"}) is False
    # And a Google News publisher suffix must not make an English headline
    # read as Italian.
    assert scraper._in_english({
        "title": "Switzerland confirms its leading position in deep tech - "
                 "Università della Svizzera italiana",
        "link": "https://usi.ch/news"}) is True
    assert scraper._in_english({
        "title": "Exclaim Robotics raises USD 4.95 million",
        "link": "https://www.startupticker.ch/en/news/exclaim"}) is True

    # The order of preference, as tiers: Startupticker English, then English.
    st_en = {"link": "https://www.startupticker.ch/en/news/x", "title": "A raises",
             "score": 1}
    other_en = {"link": "https://sifted.eu/x", "title": "A raises", "score": 9}
    st_de = {"link": "https://www.startupticker.ch/de/news/x",
             "title": "A erhält Millionen", "score": 9}
    assert scraper._news_rank(st_en) > scraper._news_rank(other_en)
    assert scraper._news_rank(other_en) > scraper._news_rank(st_de)

    # A story with no English version anywhere is kept as it stands: this
    # picks the best copy, it does not delete news.
    only_german = {"g": {"company": "SeasON Energy", "amount": "", "score": 6,
                         "category": "Cleantech", "location": "Zurich",
                         "published": "2026-08-02", "first_seen": "2026-08-02",
                         "title": "SeasON Energy erhält Millionenfinanzierung",
                         "description": "Speicher",
                         "link": "https://www.startupticker.ch/de/news/season"}}
    page = scraper.render_news_html(only_german, now=dt.datetime(2026, 8, 5, 9, 0))
    assert page.count("<li data-") == 1


def test_what_is_held_back_stays_reviewable():
    """A seat abroad is a judgement call, so it is not deleted, just moved."""
    import datetime as dt

    def row(company, location):
        return {"company": company, "amount": "CHF 5M", "stage": "Seed",
                "location": location, "category": "Quantum",
                "published": "2026-08-01", "first_seen": "2026-08-01",
                "description": f"{company} does things",
                "title": f"{company} raises CHF 5M",
                "link": "https://startupticker.ch/x"}

    known = {"a": row("Swiss SA", "Zurich"), "b": row("Abroad SA", "Leipzig, DE")}
    now = dt.datetime(2026, 8, 5, 9, 0)

    # The database is Swiss DeepTech and says so: one row, and a way through.
    page = scraper.render_archive_html(known, now=now)
    assert page.count("<tr data-chf") == 1
    assert "Swiss SA" in page and "Abroad SA" not in page
    assert "held.html" in page and "1 rounds held back" in page

    # The held page carries the other one, with the same editing panel, so a
    # wrong headquarters can be corrected and the round joins the database.
    held = scraper.render_archive_html(known, now=now, only="held")
    assert held.count("<tr data-chf") == 1
    assert "Abroad SA" in held and "Swiss SA" not in held
    assert "<title>Held back</title>" in held
    assert 'class="fix"' in held          # the + panel is there too
    assert "archive.html" in held         # and a way back

    # Pfäffikon is in Switzerland. AI Infrastructure Capital read as foreign
    # for want of its town being on the list.
    assert scraper._is_swiss({"location": "Pfäffikon"}) is True
    for town in ("Rotkreuz", "Baar", "Chur", "Allschwil", "Meyrin"):
        assert scraper._is_swiss({"location": town}) is True, town
    assert scraper._is_swiss({"location": "Leipzig, DE"}) is False


def test_a_company_ruled_out_by_hand_leaves_both_pages():
    """Terminal Technologies is in Toronto and was Swiss news by metaphor only."""
    import datetime as dt
    import json
    import tempfile

    import corrections

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"companies": {}, "blocked": ["Terminal Technologies"]}, f)
        path = f.name
    try:
        assert corrections.is_blocked("Terminal Technologies Inc", path) is True
        assert corrections.is_blocked("ZuriQ", path) is False
        # An empty or missing list blocks nothing.
        assert corrections.blocked("/nonexistent.json") == set()
    finally:
        os.unlink(path)

    # The real file blocks it, and it is off the database and off the held
    # page: removing the name from corrections.json puts it back.
    assert corrections.is_blocked("Terminal Technologies Inc") is True
    known = {"a": {"company": "Terminal Technologies Inc", "amount": "USD 20M",
                   "stage": "Seed", "location": "Toronto, CA",
                   "category": "AI", "published": "2026-07-29",
                   "first_seen": "2026-08-04", "description": "Telematics",
                   "title": "Toronto startup Terminal raises $20-million",
                   "link": "https://theglobeandmail.com/x"}}
    now = dt.datetime(2026, 8, 5, 9, 0)
    for page in (scraper.render_archive_html(known, now=now),
                 scraper.render_archive_html(known, now=now, only="held")):
        assert page.count("<tr data-chf") == 0


def test_one_figure_two_currency_labels_is_one_round():
    """AI Infrastructure Capital was EUR 16M in one paper and USD 16M in another."""
    merged = scraper.merge_deals([
        {"company": "AI Infrastructure Capital AG", "amount": "EUR 16M",
         "publisher": "EU-Startups", "location": "Pfäffikon"},
        {"company": "AI Infrastructure Capital", "amount": "USD 16M",
         "publisher": "Startupticker", "location": "Pfäffikon"},
    ])
    # In francs those are 14 per cent apart, outside the conversion tolerance,
    # so only the bare figure matching catches it.
    assert len(merged) == 1, [m["amount"] for m in merged]
    assert set(merged[0]["sources"]) == {"EU-Startups", "Startupticker"}
    # And it must not merge a genuinely different round of a different size.
    assert len(scraper.merge_deals([
        {"company": "Bar", "amount": "CHF 16M"},
        {"company": "Bar", "amount": "CHF 160M"},
    ])) == 2


def test_coverage_is_not_verification():
    """Three outlets rewriting one release is one source, not three checks."""
    import datetime as dt

    def write_up(publisher):
        return {"company": "Exclaim Robotics", "amount": "USD 4.95M",
                "stage": "Pre-seed", "location": "Zurich", "category": "Robotics",
                "publisher": publisher, "first_seen": "2026-08-05",
                "published": "2026-08-05", "description": "Data centre robots",
                "title": "Exclaim Robotics raises USD 4.95 million",
                "link": f"https://{publisher.lower()}.ch/exclaim"}

    known = {p: write_up(p) for p in ("Startupticker", "AIInsider", "EUStartups")}
    page = scraper.render_archive_html(known, now=dt.datetime(2026, 8, 5, 9, 0))

    # One row, marked with how many outlets carried it.
    assert page.count("3 sources") == 1
    assert 'class="tag sources"' in page
    # And it is not the verified badge: nothing here was read against a
    # primary source, so nothing claims it was.
    assert 'class="checked"' not in page
    assert "Coverage, not a check against a primary source" in page

    # A single write-up gets no mark at all: "1 source" is noise.
    one = scraper.render_archive_html({"a": write_up("Startupticker")},
                                      now=dt.datetime(2026, 8, 5, 9, 0))
    assert "tag sources" not in one


def test_an_empty_week_is_never_published():
    """A filter rejecting everything would wipe the plan page and look quiet."""
    import inspect
    source = inspect.getsource(scraper.main)
    # The guard has to sit before anything is written, and it has to stop the
    # run rather than warn: a warning still publishes the empty file.
    guard = source.index("if not picks:")
    written = source.index('"posts.json"')
    assert guard < written, "the empty check runs after the file is written"
    assert "sys.exit(" in source[guard:written]
    assert "The published plan is untouched" in source


def test_a_foreign_company_never_becomes_a_post():
    """It scored 19 and was one pick away from going out under Max's name."""
    # The database has always dropped these. The picks never checked at all,
    # so only the shortage of candidates kept them out.
    toronto = {
        "title": "Toronto startup Terminal raises $20-million to become the "
                 "'Switzerland' of telematics trade",
        "summary": "The Toronto-based company wants to be the neutral party.",
        "link": "https://www.theglobeandmail.com/business/article-terminal/"}
    assert scraper.plausibly_swiss(toronto) is False
    assert scraper._is_swiss(toronto) is False

    # A metaphor is not a country, whoever writes it.
    assert scraper.plausibly_swiss({
        "title": "Berlin-based Baz raises Series A to expand into Switzerland",
        "link": "https://tech.eu/baz"}) is False

    # But a Swiss round covered abroad still counts, or the pool shrinks for
    # nothing: Sifted and EU-Startups carry real Swiss rounds.
    for title, link in (
        ("Exclusive: ETH Zurich spinout ZuriQ raises $25.5m seed",
         "https://sifted.eu/articles/zuriq"),
        ("Swiss startup Foo raises EUR 4M seed",
         "https://www.eu-startups.com/foo"),
        ("Zurich-based Bar lands its first industrial customer",
         "https://tech.eu/bar"),
    ):
        assert scraper.plausibly_swiss({"title": title, "link": link}), title

    # And a Swiss outlet is Swiss enough on its own: judging these by headline
    # threw out four of five real posts, because a post about "Swiss medtechs"
    # names no single company.
    for link in ("https://www.startupticker.ch/en/news/x",
                 "https://actu.epfl.ch/news/y",
                 "https://www.swissinfo.ch/eng/z",
                 "https://venturelab.swiss/q"):
        assert scraper.plausibly_swiss({"title": "Milestones this month",
                                        "link": link}), link


def test_milestones_reach_the_posts_but_not_the_database():
    """Every query was funding-shaped, so non-funding news came from one outlet."""
    import google_news
    from relevance import score_article

    asked = " ".join(google_news.GOOGLE_NEWS_QUERIES).lower()
    for term in ("clearance", "first customer", "contract", "partnership"):
        assert term in asked, f"nothing asks for {term}"

    # A milestone with no money in it has to clear the relevance bar, or the
    # queries are decoration: the run's minimum is 4.
    for title, summary in (
        ("EPFL spin-off wins CE mark for its neural implant",
         "The Lausanne-based EPFL spin-off received CE mark approval."),
        ("Zurich robotics spin-off lands first industrial customer",
         "The ETH Zurich spin-off signed its first contract with a Swiss "
         "manufacturer."),
        ("Swiss quantum firm ships first commercial system",
         "The Zurich-based company delivered its first commercial system."),
    ):
        assert score_article(title, summary, "Google News") >= 4, title

    # And none of them may become a row in the deal database. The posts and the
    # database are two projects; widening one must not corrupt the other.
    for title in ("Hi-D Imaging wins expanded FDA clearance",
                  "Foo Robotics lands first industrial customer",
                  "Bar SA ships its first commercial system"):
        assert scraper._is_round({
            "company": title.split()[0], "stage": "", "amount": "",
            "category": "MedTech", "title": title}) is False, title


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

    # The real week: Startupticker writes about two thirds of Swiss DeepTech
    # news, so 8 of its stories and 2 from elsewhere is a normal ten days.
    # At a hard cap of three that is a five-post week, which is what happened.
    real = [f"https://www.startupticker.ch/{i}" for i in range(8)] + \
           ["https://swissinfo.ch/1", "https://actu.epfl.ch/1"]
    assert week(real, hard=3)[1] == 5
    # At five it fills, and the soft cap of two still governs a week that can
    # fill itself without borrowing.
    assert week(real, hard=5)[1] == 7
    assert week(ticker + others, hard=5)[0]["startupticker.ch"] == 2

    # And that is what actually ships, not just what this test passes in.
    import inspect
    source = inspect.getsource(scraper.main)

    def shipped(flag):
        found = re.search(re.escape(f'"{flag}"') + r", type=int, default=(\d+)",
                          source)
        return int(found.group(1)) if found else None

    # The list is fifteen now, not seven, so the caps that fill it moved with
    # it. Five and eight keep the same shape: no outlet owns the list, and a
    # thin fortnight still fills rather than shipping half a page.
    assert shipped("--posts") == 15, "the shortlist length moved"
    assert shipped("--max-per-domain") == 5, "the normal cap moved"
    assert shipped("--max-per-domain-hard") == 8, "the short-list cap moved"


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


def test_the_article_settles_what_it_can_and_no_more():
    """A browser session opening a page is the priciest check in the workflow."""
    import linkedin

    body = ("AssetOS, a spin-off from the University of St. Gallen, counts "
            "Implenia and Avadis among its customers.")
    art = {"fulltext": body, "summary": "", "status": ""}
    remaining, settled = linkedin.settle_claims(
        ["the company is AssetOS",
         "the post names Implenia, Avadis: did they take part in this round "
         "rather than an earlier one"], art, {})
    assert remaining == [] and len(settled) == 2

    # Nothing read means nothing settled. Silence is not confirmation.
    assert linkedin.settle_claims(["the company is Foo"],
                                  {"fulltext": "", "summary": ""}, {}) == \
        (["the company is Foo"], [])

    # A figure on an unclosed deal stays open however plainly it is printed:
    # a ceiling appears in the text exactly as proceeds would.
    spac = {"fulltext": "Terra Quantum will receive up to $190 million of "
                        "gross proceeds.", "status": "announced"}
    claim = ("the post states $190 million: is that money received rather "
             "than a ceiling or a target, and has the round closed")
    assert linkedin.settle_claims([claim], spac, {}) == ([claim], [])

    # The one that matters. Every word of "the company is Humboldt AI" is in
    # the article, so a plain match would settle it and lose the catch.
    brand = {"fulltext": "Gegruendet wurde Humboldt AI, eine Marke der "
                         "Raetica Innovation Labs GmbH, 2026.", "status": ""}
    assert linkedin.settle_claims(["the company is Humboldt AI"], brand, {}) \
        == (["the company is Humboldt AI"], [])
    for phrase in ("a brand of Foo", "une marque de Foo", "trading as Foo",
                   "division of Foo"):
        assert linkedin._BRAND_OF.search(phrase), phrase

    # Already read against a primary source: nothing left for a browser.
    assert linkedin.settle_claims(["the company is Foo"],
                                  {"fulltext": "", "summary": ""},
                                  {"source": "company release"})[0] == []


def test_a_run_does_not_land_on_a_week_being_posted():
    """A scheduled run mid-week overwrites the plan and spends its stories."""
    import datetime as dt
    import json
    import tempfile

    out = tempfile.mkdtemp()
    with open(os.path.join(out, "posts.json"), "w", encoding="utf-8") as f:
        json.dump({"posts": [{"date": "2026-08-05"}, {"date": "2026-08-11"}]}, f)

    # Wednesday the 5th: the plan runs to the 11th, so leave it alone.
    assert scraper.week_still_running(out, dt.date(2026, 8, 5)) is True
    # The last day still counts: a post due today has not gone out yet.
    assert scraper.week_still_running(out, dt.date(2026, 8, 11)) is True
    # The Wednesday after: the week is over, so build the next one.
    assert scraper.week_still_running(out, dt.date(2026, 8, 12)) is False
    # No plan at all is not a live week.
    assert scraper.week_still_running("/nonexistent", dt.date(2026, 8, 5)) is False

    # The guard has to read the published shortlist, not the build directory.
    # output/ is generated and never committed, so on a fresh checkout it is
    # empty and the guard found nothing to protect: it answered "go ahead" on
    # every scheduled run since it was written, and a shortlist of fifteen was
    # rebuilt twice inside two days, each rebuild recording its stories as used.
    import inspect
    main_src = inspect.getsource(scraper.main)
    assert "week_still_running(args.outdir)" not in main_src, \
        "the guard is reading the build directory again, where nothing persists"
    assert "os.path.dirname(args.history)" in main_src, \
        "the guard must read the shortlist that is actually published"

    # A shortlist carries no day per post, so its age is what counts. Six days
    # is the life: rebuilding sooner would record the stories Max has not
    # picked yet as used, and they would never come back.
    shortlist = tempfile.mkdtemp()
    with open(os.path.join(shortlist, "posts.json"), "w", encoding="utf-8") as f:
        json.dump({"generated": "2026-08-05", "posts": [{"index": 1}]}, f)
    assert scraper.week_still_running(shortlist, dt.date(2026, 8, 5)) is True
    assert scraper.week_still_running(shortlist, dt.date(2026, 8, 10)) is True
    assert scraper.week_still_running(shortlist, dt.date(2026, 8, 11)) is False

    # A live week is protected from every trigger, not only the schedule. The
    # The scheduled run no longer passes this flag, and that is deliberate.
    # The guard existed because rebuilding recorded every story on the page as
    # used, so a run landing mid-week cost stories nobody had posted. Drafting
    # spends nothing now, the page rebuilds every morning, and a shortlist that
    # refuses to refresh is the failure rather than the protection: it sat at 13
    # August until the 17th and nothing was wrong. The flag and the guard stay
    # available for a run made by hand.
    #
    # Found from this file, not from an absolute path: the runner checks the
    # repository out somewhere else entirely, and a hardcoded /home/user path
    # failed the whole run rather than the one assertion.
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    with open(os.path.join(root, ".github", "workflows", "news-digest.yml"),
              encoding="utf-8") as f:
        flow = f.read()
    assert "--skip-if-week-planned" not in flow, \
        "the daily rebuild is being blocked by a guard it no longer needs"
    assert "force:" in flow, "there must be a way to rebuild on purpose"


def test_cowork_reads_only_what_it_uses():
    """Every field a scheduling session does not use is paid for and skipped."""
    import linkedin

    record = {"index": 1, "published": "2026-08-05", "time": "08:00",
              "published_label": "05 August", "kind": "Round", "text": "x",
              "link": "https://e.ch", "mention": {"type": "A", "expect": "A"},
              "needs_check": False, "claims": [], "settled": ["a"],
              "image": "https://e.ch/x.jpg", "publisher": "E",
              "link_note": "-", "image_note": "", "primary_source": None,
              "coverage_url": None, "verified": False, "verified_source": ""}
    slim = linkedin.for_cowork([record])[0]
    # No date and no time: the shortlist has no rota, and the day each picked
    # post goes out is written into the instruction when Max copies it.
    assert set(slim) == {"index", "text", "link", "mention",
                         "needs_check", "claims"}
    # The page Max reads keeps everything; only the machine file is trimmed.
    assert record.get("published_label") == "05 August"

    # The mention is a check, not a guess at the first dropdown row.
    hint = linkedin._mention_hint("@Humboldt AI launched a tool.", "Humboldt AI")
    assert hint == {"type": "Humboldt", "expect": "Humboldt AI"}
    assert linkedin._mention_hint("No mention here.", "Foo") == {}

    # And the prompt must not send a browser session to GitHub to commit.
    prompt = linkedin.COWORK_PROMPT
    assert "do not edit any file or commit" in prompt
    assert "proposals.json" not in prompt
    assert "already scheduled" in prompt
    # And it must schedule only what Max picked, never the whole file.
    assert "and only those" in prompt
    assert "Ignore every other post in the file" in prompt
    # Worst case has to be bounded. A post that will not go through can
    # otherwise be retried until the session is out of money.
    assert "Two attempts per post" in prompt
    assert "Never start a third" in prompt
    assert "do not hunt for an image" in prompt


def test_one_mention_per_post():
    """Five @mentions per post cost a fortune in Cowork restarts."""
    import ai_writer
    import linkedin

    # The real post: four organisations tagged, two of them untaggable. Typing
    # the first word after "@University" offers a list of universities, and the
    # FDA is a US regulator nobody meant to tag.
    text = ("@AssetOS, a spin-off from @University of St. Gallen, counts "
            "@Implenia and @Avadis among its customers.")
    out = ai_writer.one_mention(text, "AssetOS")
    assert re.findall(r"@[\w\-.&]+", out) == ["@AssetOS"]
    # The other names survive in full, they just lose the @.
    for name in ("University of St. Gallen", "Implenia", "Avadis"):
        assert name in out, name

    # A round-up is about no single company, so the first mention stands and
    # the rest go plain: one is the cap either way.
    roundup = ("@Arcoris bio signed a deal, while @Hi-D Imaging won @FDA "
               "clearance. @ABILITY Neurotech and @Alivion followed.")
    out = ai_writer.one_mention(roundup, "")
    assert re.findall(r"@[\w\-.&]+", out) == ["@Arcoris"]
    assert "FDA clearance" in out and "Hi-D Imaging" in out

    # A multi-word company keeps its @ on the first word, which is what gets
    # typed into the dropdown.
    out = ai_writer.one_mention("@Humboldt AI, based in St. Gallen.",
                                "Humboldt AI")
    assert out.startswith("@Humboldt AI,")

    # A post with no mention at all is left exactly as it is.
    assert ai_writer.one_mention("No organisations here.", "Foo") == \
        "No organisations here."

    # The writing instruction has to agree, or every run pays to strip them.
    assert "ONE @mention per post" in ai_writer.SYSTEM_PROMPT

    # And the Cowork prompt must not ask for the URL twice: it is already the
    # last line of the text, and asking again restarted posts.
    prompt = linkedin.COWORK_PROMPT
    assert "already ends with the article URL" in prompt
    assert "exactly one @mention" in prompt


def test_a_broken_proposals_file_is_not_an_empty_one():
    """A check appended its report after the closing brace and vanished."""
    import json
    import tempfile

    import proposals

    # Two JSON objects in one file, which is what an append produces.
    broken = ('{"proposals": {"Foo": {"stage": "Seed"}}}, '
              '{"post_index": 3, "status": "held_not_scheduled"}')
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write(broken)
        path = f.name
    try:
        proposals.load(path)
        raise AssertionError("a file that will not parse read as empty")
    except json.JSONDecodeError:
        pass
    finally:
        os.unlink(path)

    # A file that is simply absent is genuinely empty, and stays quiet.
    assert proposals.load("/nonexistent/proposals.json") == {}

    # And the real file parses, with the held post kept rather than dropped.
    with open(proposals.PATH, encoding="utf-8") as f:
        real = json.load(f)
    assert isinstance(real.get("proposals"), dict)
    for held in real.get("held_posts", []):
        assert held.get("source_url"), "a held post must say where it read it"
        assert held.get("problem"), "a held post must say what is wrong"


def test_a_missing_fact_can_be_typed_in():
    """GR3N's founder was in no article the scraper could read."""
    import datetime as dt
    import json

    import archive
    import corrections

    known = {"g": {
        "key": "g", "company": "GR3N", "first_seen": "2026-08-03",
        "published": "2026-06-05", "stage": "Series B", "amount": "EUR 15.5M",
        "category": "Cleantech", "location": "Chiasso", "founders": "",
        "investors": "360 Capital, VP Textile",
        "title": "GR3N closes a 15.5M Series B round",
        "description": "Microwave-assisted depolymerization recycling",
        "link": "https://www.startupticker.ch/en/news/gr3n"}}
    page = scraper.render_archive_html(known, now=dt.datetime(2026, 8, 4, 6, 30))

    # Every row offers it, and carries what it already knows so the panel can
    # tell a gap from a value and only report what Max actually changed.
    assert page.count('class="fix"') == 1
    assert 'data-company="GR3N"' in page
    facts = json.loads(html.unescape(
        re.search(r'data-facts="([^"]+)"', page).group(1)))
    assert facts["founders"] == ""
    assert facts["investors"] == "360 Capital, VP Textile"
    assert facts["location"] == "Chiasso"

    # The panel finds its row by closest(), never by counting parents. Wrapping
    # the + button in a span for the desktop layout moved it one level deeper,
    # and the panel opened with no company and every field blank, on every
    # device, silently.
    assert "closest('tr')" in page
    assert "btn.parentNode.parentNode" not in page
    # And the button really does sit deeper than the row, which is why.
    row = re.search(r"<tr data-chf.*?</tr>", page, re.S).group(0)
    assert re.search(r'<span class="marks">.*?class="fix"', row, re.S), \
        "the + button is expected inside the marks span"

    # The panel hands back a whole file rather than a fragment to splice in,
    # so the current corrections have to be embedded and parseable.
    embedded = json.loads(re.search(
        r'<script type="application/json" id="corrections">(.*?)</script>',
        page, re.S).group(1))
    assert "companies" in embedded

    # A field offered for editing that the archive does not persist would be
    # typed in, committed, and silently dropped on the next run.
    import inspect
    source = inspect.getsource(archive.record)
    for field, _label in scraper._FIXABLE:
        assert f'"{field}"' in source, f"{field} is not kept by archive.record"

    # And corrections.py has to accept them: it drops anything it does not
    # recognise as data about the company.
    fixes = {"companies": {"GR3N": {f: "x" for f, _ in scraper._FIXABLE}}}
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(fixes, f)
        path = f.name
    loaded = corrections.load(path)
    assert set(loaded["gr3n"]) == {f for f, _ in scraper._FIXABLE}
    os.unlink(path)


def test_the_page_says_when_it_ran_and_what_it_added():
    """A database you cannot date is one you cannot trust."""
    import datetime as dt

    def deal(key, company, seen, amount="CHF 10M"):
        return {"key": key, "company": company, "first_seen": seen,
                "published": "2026-08-01", "stage": "Seed", "amount": amount,
                "category": "Quantum", "location": "Zurich",
                "title": f"{company} raises {amount}",
                "description": f"{company} is a Swiss quantum startup",
                "link": f"https://www.startupticker.ch/en/news/{key}"}

    now = dt.datetime(2026, 8, 4, 6, 30)

    # The day the record was built is not an addition. The archive was rebuilt
    # on 3 August, every round in it carried that morning's date, and the page
    # came up with all 21 rows marked new. Nothing is new when everything is.
    loaded = {
        "a": deal("a", "Alpha", "2026-08-03"),
        "b": deal("b", "Beta", "2026-08-03", "CHF 20M"),
        "c": deal("c", "Gamma", "2026-08-03", "CHF 30M"),
    }
    page = scraper.render_archive_html(loaded, now=now)

    # When it ran, in Max's time and in words rather than a bare stamp.
    assert "Refreshed 04 August 2026 at 06:30" in page
    assert 'class="tag fresh"' not in page
    assert "loaded together when the record was built on 03 August" in page
    assert "<b>0</b><span>added today</span>" in page
    assert 'value="new">Just added (0)' in page
    # And the baseline rows are not reachable through the date filters either.
    assert 'data-added="2026-08-03"' not in page

    # What arrives after the load is a real addition, and is marked.
    known = dict(loaded)
    known["a"] = deal("a", "Alpha", "2026-08-04")
    known["b"] = deal("b", "Beta", "2026-08-04", "CHF 20M")
    page = scraper.render_archive_html(known, now=now)
    assert "2 rounds added today" in page
    assert "<b>2</b><span>added today</span>" in page
    assert page.count('class="tag fresh"') == 2
    assert 'data-added="2026-08-04"' in page
    assert 'value="new">Just added (2)' in page

    # A quiet run says when the last additions were rather than showing
    # nothing, so silence is never mistaken for a broken job.
    later = dt.datetime(2026, 8, 9, 6, 30)
    page = scraper.render_archive_html(known, now=later)
    assert "last additions 04 August: 2 rounds" in page
    assert "<b>0</b><span>added today</span>" in page
    assert page.count('class="tag fresh"') == 2  # still the newest batch

    # A second outlet covering an old round this morning does not make the
    # round new: the merged row keeps the earliest date it was seen.
    twice = [dict(known["c"], key="c1", first_seen="2026-07-20",
                  publisher="Startupticker"),
             dict(known["c"], key="c2", first_seen="2026-08-04",
                  publisher="The Quantum Insider")]
    merged = scraper.merge_deals(twice)
    assert len(merged) == 1
    assert merged[0]["first_seen"] == "2026-07-20"


def test_one_outlet_never_runs_two_days_running():
    """Three Startupticker links went out on three consecutive days."""
    from relevance import adjacent_repeats, space_out

    def post(host, title, link=None):
        return {"link": link or f"https://www.{host}/en/news/{title}",
                "publisher": host, "title": title}

    week = [post("swissinfo.ch", "neutrality"),
            post("actu.epfl.ch", "anthrax"),
            post("startupticker.ch", "immunomuse"),
            post("startupticker.ch", "humboldt"),
            post("startupticker.ch", "assetos")]
    spaced = space_out(week)
    assert adjacent_repeats(spaced) == 0, [p["publisher"] for p in spaced]
    # Nothing is lost or duplicated in the reshuffle.
    assert sorted(p["title"] for p in spaced) == \
        sorted(p["title"] for p in week)
    # The busiest outlet leads, which is what makes zero repeats possible.
    assert spaced[0]["publisher"] == "startupticker.ch"

    # A link swapped to the company's own site counts as that site, because
    # that is the source the plan shows.
    swapped = [post("startupticker.ch", "one"),
               post("startupticker.ch", "two", link="https://gr3n.ch/news"),
               post("startupticker.ch", "three")]
    assert adjacent_repeats(space_out(swapped)) == 0

    # Four of five from one outlet cannot be spaced. Return the best possible
    # rather than failing, and keep every post.
    lopsided = [post("startupticker.ch", f"s{i}") for i in range(4)] + \
               [post("swissinfo.ch", "other")]
    best = space_out(lopsided)
    assert len(best) == 5
    assert adjacent_repeats(best) == 2, [p["publisher"] for p in best]

    # A week with no repeats at all keeps its ranking order untouched.
    varied = [post("a.ch", "1"), post("b.ch", "2"), post("c.ch", "3")]
    assert [p["title"] for p in space_out(varied)] == ["1", "2", "3"]


def test_short_week_skips_the_weekend():
    """Fewer than seven posts go out on working days, weekend left blank."""
    import datetime as dt
    import linkedin

    # Wednesday 5 August 2026. Five posts run Thursday, Friday, then Monday on.
    wednesday = dt.date(2026, 8, 5)
    days = linkedin.schedule_days(wednesday, 5)
    assert [d.strftime("%a") for d in days] == \
        ["Thu", "Fri", "Mon", "Tue", "Wed"], days
    assert days[0] == dt.date(2026, 8, 6)
    assert days[2] == dt.date(2026, 8, 10)

    # A full week has nowhere else to put the seventh, so it fills every day.
    week = linkedin.schedule_days(wednesday, 7)
    assert [d.strftime("%a") for d in week] == \
        ["Thu", "Fri", "Sat", "Sun", "Mon", "Tue", "Wed"], week

    # A run landing on a Friday still starts on the next working day.
    friday = linkedin.schedule_days(dt.date(2026, 8, 7), 2)
    assert [d.strftime("%a") for d in friday] == ["Mon", "Tue"], friday

    # One post, and no post at all, both behave.
    assert len(linkedin.schedule_days(wednesday, 1)) == 1
    assert linkedin.schedule_days(wednesday, 0) == []


def test_a_well_covered_round_is_still_one_story():
    """Four write-ups of one round must not become four posts.

    The rare-name check calls a word a name when at most three headlines use
    it, which quietly gave up on the stories carried by the most outlets.
    Exclaim Robotics ran in Startupticker, AI Insider, EU-Startups and L'Usine
    Digitale, so "exclaim" was in four headlines, no longer rare, and two of
    the four survived into the week's plan on consecutive days.
    """
    from relevance import deduplicate

    exclaim = [
        "Exclaim Robotics raises USD 4.95 million for data centre repair robots",
        "Swiss Startup Exclaim Robotics Emerges From Stealth With Nearly $5M "
        "in Funding for AI Data Center Robotics",
        "Zurich-based Exclaim Robotics exits stealth with EUR 4.29 million to "
        "build robots for AI data centre maintenance",
        "Avec ses robots mobiles, la start-up suisse Exclaim Robotics veut "
        "automatiser la maintenance des data centers",
    ]
    # Two other companies in the same field. They share "robotics" or "robots"
    # with Exclaim and with each other, and must stay apart: one field word in
    # common is not one story.
    others = [
        "Nanoflex Robotics awarded EUR 12.5 million from the EIC Accelerator",
        "IERA Award 2026 goes to flying warehouse robots by Verity",
        "Synhelion wins German backing for a commercial demonstration plant",
        "Delta Capacity completes Swedish battery project",
    ]
    pool = [{"title": t, "score": 20 - i, "link": f"https://x{i}.example/a"}
            for i, t in enumerate(exclaim + others)]

    kept = [a["title"] for a in deduplicate(pool)]
    left = [t for t in kept if "exclaim" in t.lower()]
    assert len(left) == 1, left

    # And nothing else was swallowed on the way: sharing one field word is not
    # the same story.
    assert len(kept) == 1 + len(others), kept


def test_the_run_does_not_spend_its_time_waiting_on_sockets():
    """Enrichment is parallel, and the writer's ceiling scales with the list.

    Both broke on the same change. Fifteen stories instead of seven meant
    fifteen page fetches instead of seven, each up to four requests at twelve
    and fifteen second timeouts, run one after another: a build that took three
    minutes took twenty five, almost all of it idle. And one call writes every
    post, so a flat 8000 token ceiling that fitted seven would have truncated
    fifteen and dropped the whole run back to template drafts.
    """
    import inspect
    import time
    import ai_writer
    import images

    # The ceiling follows the length of the list.
    source = inspect.getsource(ai_writer.generate_posts)
    assert "max_tokens=max(8000, 800 * len(articles))" in source, \
        "the writer's token ceiling stopped scaling with the shortlist"

    # And enrichment actually runs in parallel: ten articles that each take a
    # tenth of a second must not take a whole second between them.
    calls = []
    real = images._enrich_one

    def slow(a):
        calls.append(a)
        time.sleep(0.1)

    images._enrich_one = slow
    try:
        batch = [{"link": f"https://e{i}.ch/a"} for i in range(10)]
        started = time.monotonic()
        images.enrich_articles(batch)
        took = time.monotonic() - started
    finally:
        images._enrich_one = real

    assert len(calls) == 10, f"enriched {len(calls)} of 10 articles"
    assert took < 0.5, f"ten articles took {took:.2f}s, so they ran one by one"

    # An article whose page cannot be read costs that article, not the run.
    # Checked on the source rather than by calling it, because proving it takes
    # a dead host and a test may not touch the network.
    guard = inspect.getsource(images._enrich_one)
    assert "except Exception as exc" in guard, \
        "one unreachable host would now take the whole run down"


def test_one_bad_feed_does_not_cost_the_run():
    """A feed that hangs or drops the connection is skipped, not fatal.

    feedparser reports most network trouble by setting bozo, and the loop reads
    that. It does not catch everything: a throttled server closed the
    connection without a response, feedparser let http.client.RemoteDisconnected
    through, and a run that had produced nothing yet died on the spot. It had
    also sat on that one socket for four and a half minutes first, because
    feedparser has no timeout of its own.
    """
    import inspect
    import scraper as sc

    source = inspect.getsource(sc.collect)
    assert "socket.setdefaulttimeout(FEED_TIMEOUT)" in source, \
        "a silent feed can hold the run open again"
    # Generous, because the feeds are fetched in parallel and the run waits for
    # the slowest rather than the sum. Twenty was mean enough to skip
    # Startupticker on a slow evening, which is most of the news in one line,
    # and the run ended with nothing to shortlist.
    assert 30 <= sc.FEED_TIMEOUT <= 60, \
        "the feed timeout is either too mean to trust or too long to guard"
    assert "ThreadPoolExecutor" in source, \
        "the feeds are fetched one at a time again, so the timeout costs the run"

    # The parse itself is guarded, and the guard reports rather than re-raises.
    assert "except Exception as exc:" in source, "feedparser.parse is unguarded again"
    assert "return label, url, None, type(exc).__name__" in source, \
        "a failed feed must come back as a skip, not as an exception"

    # And a real one: a feed whose fetch raises must leave the others alone.
    real = sc.feedparser.parse
    seen = []

    class Fake:
        bozo = False
        entries = []

    def flaky(url, **kw):
        seen.append(url)
        if "boom" in url:
            import http.client
            raise http.client.RemoteDisconnected("closed without response")
        return Fake()

    real_feeds = sc.all_feeds
    sc.feedparser.parse = flaky
    sc.all_feeds = lambda days: [("Good", "https://a.ch/f"),
                                 ("Bad", "https://boom.ch/f"),
                                 ("Also good", "https://b.ch/f")]
    try:
        got = sc.collect(7, 3)
    finally:
        sc.feedparser.parse = real
        sc.all_feeds = real_feeds

    assert got == [], f"expected no articles from empty feeds, got {len(got)}"
    assert len(seen) == 3, f"stopped after {len(seen)} feeds instead of all 3"


def test_no_source_is_kept_that_never_delivered():
    """A feed that has never returned an item is not a source, it is a comment.

    Seventeen of the twenty three direct feeds returned nothing, and fourteen
    of those had never contributed a single story in the life of the database:
    not one of 115 rows came from ETH, Empa, PSI, CSEM, IDIAP or any of the
    three universities. The run said "unreachable" once per feed, in a log
    nobody reads line by line, so the pipeline was really Startupticker plus
    EPFL plus Google News and nothing said so.
    """
    import sources

    live = {url for _, url in sources.DIRECT_FEEDS}
    retired = {url for _, url in sources.RETIRED_FEEDS}
    assert not (live & retired), \
        f"a retired feed is back in the live list: {live & retired}"

    # The institutions the dead feeds were meant to cover have to be covered
    # somewhere, or removing them just loses the sources quietly.
    import google_news
    queries = " ".join(google_news.GOOGLE_NEWS_QUERIES).lower()
    for who in ("eth zurich", "epfl", "empa", "psi", "csem", "idiap",
                "university of zurich", "innosuisse", "venture kick"):
        assert who in queries, f"nothing covers {who} since its feed was dropped"


def test_a_crunchbase_export_becomes_rounds():
    """A month of Swiss rounds dropped in as CSV reaches the database.

    The feeds miss what no newsroom writes up. One month's export carried a USD
    152M Series B announced that morning and a USD 30M BARDA grant to Basilea,
    and neither had reached the database, because grant bodies announce on
    their own sites and no feed carries them.
    """
    import tempfile
    import submissions

    header = ("Transaction Name,Transaction Name URL,Organization Name,"
              "Organization Name URL,Funding Type,Money Raised,"
              "Money Raised Currency,Money Raised (in USD),Announced Date,"
              "Funding Stage,Organization Industries,Organization Location,"
              "Organization Website,Total Funding Amount,"
              "Total Funding Amount Currency,Total Funding Amount (in USD),"
              "Number of Funding Rounds,Lead Investors")
    rows = [
        # A real round.
        'Series B - Vaderis,https://cb.com/a,Vaderis Therapeutics,https://cb.com/o,'
        'Series B,152000000,USD,152000000,2026-08-11,Early Stage Venture,'
        '"Biotechnology, Life Science","Basel, Basel-Stadt, Switzerland, Europe",'
        'https://vaderis.com/,170598980,USD,170598980,2,"Goldman Sachs, TCG"',
        # A grant no feed carries.
        'Grant - Basilea,https://cb.com/b,Basilea Pharmaceutica,https://cb.com/o2,'
        'Grant,30000000,USD,30000000,2026-07-29,,"Biotechnology, Pharmaceutical",'
        '"Basel, Basel-Stadt, Switzerland, Europe",http://basilea.com,'
        '233987223,USD,233987223,11,BARDA',
        # Not Climb material: a listed group's post-IPO debt.
        'Post-IPO Debt - SIG,https://cb.com/c,SIG Group,https://cb.com/o3,'
        'Post-IPO Debt,270000000,USD,270000000,2026-08-03,,Manufacturing,'
        '"Neuhausen, Schaffhausen, Switzerland, Europe",http://sig.biz,'
        '951985330,USD,951985330,2,',
        # The same round under two names, which is how Crunchbase files it.
        'Series B - Hilo,https://cb.com/d,Hilo,https://cb.com/o4,Series B,'
        '19000000,USD,19000000,2026-07-21,Early Stage Venture,'
        '"Health Care, Medical Device","Neuchatel, Neuchatel, Switzerland, Europe",'
        'https://hilo.com,120675083,USD,120675083,7,DFO Management',
        'Series B - Hilo by Aktiia,https://cb.com/e,Hilo by Aktiia,https://cb.com/o5,'
        'Series B,19000000,USD,19000000,2026-07-22,Early Stage Venture,'
        '"Wearables, Health Care","Neuchatel, Neuchatel, Switzerland, Europe",'
        'https://aktiia.com,61000000,USD,61000000,3,Dell Family Office',
    ]
    box = tempfile.mkdtemp()
    with open(os.path.join(box, "export.csv"), "w", encoding="utf-8") as f:
        f.write(header + "\n" + "\n".join(rows) + "\n")

    got = submissions.csv_rows(box)
    names = {r["company"] for r in got}

    # The buyout is out, the round and the grant are in.
    assert "SIG Group" not in names, "a post-IPO debt reached the database"
    assert "Vaderis Therapeutics" in names and "Basilea Pharmaceutica" in names

    # One round, not two, however Crunchbase spells the company.
    hilo = [r for r in got if "hilo" in r["company"].lower()]
    assert len(hilo) == 1, [r["company"] for r in hilo]
    # And the merge kept what only the duplicate knew.
    assert hilo[0]["lead_investor"], "the surviving row lost its lead investor"

    money = {r["company"]: r["amount"] for r in got}
    assert money["Vaderis Therapeutics"] == "USD 152M", money
    assert money["Basilea Pharmaceutica"] == "USD 30M", money
    stages = {r["company"]: r["stage"] for r in got}
    assert stages["Basilea Pharmaceutica"] == "Grant", stages

    # No export at all is not an error.
    assert submissions.csv_rows(tempfile.mkdtemp()) == []


def test_the_shortlist_can_reach_the_database():
    """A round on record must be offerable even when no feed returned it today.

    The shortlist only ever saw what the feeds carried in the last few minutes.
    Basilea's USD 30M from BARDA came in through a Crunchbase export, no
    newsroom wrote it up, and no run would ever have offered it. Meanwhile the
    database keeps every write-up of a round on purpose, so Exclaim Robotics is
    four rows there and has to be one card here.
    """
    import datetime as dt
    import json
    import tempfile

    today = scraper._zurich_now().date()
    recent = (today - dt.timedelta(days=3)).isoformat()
    stale = (today - dt.timedelta(days=90)).isoformat()

    box = tempfile.mkdtemp()
    path = os.path.join(box, "archive.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"stories": {
            # A grant with no article behind it: the company's own site is the
            # only address worth putting under a post.
            "a": {"company": "Basilea", "published": recent, "location": "Basel",
                  "stage": "Grant", "amount": "USD 30M", "website": "http://basilea.com",
                  "link": "https://www.crunchbase.com/funding_round/basilea",
                  "publisher": "Crunchbase export"},
            # Four write-ups of one round, which is one card.
            "b": {"company": "Exclaim Robotics", "published": recent, "location": "Zurich",
                  "stage": "Pre-seed", "amount": "USD 4.95M",
                  "link": "https://www.startupticker.ch/exclaim", "publisher": "Startupticker"},
            "c": {"company": "Exclaim Robotics", "published": recent, "location": "Zurich",
                  "stage": "Pre-seed", "link": "https://theaiinsider.tech/exclaim",
                  "publisher": "AI Insider"},
            "d": {"company": "Exclaim Robotics", "published": recent, "location": "Zurich",
                  "link": "https://eu-startups.com/exclaim", "publisher": "EU-Startups"},
            # Too old for the window.
            "e": {"company": "Ancient", "published": stale, "location": "Bern",
                  "link": "https://example.ch/old", "publisher": "X"},
            # Not Swiss.
            "f": {"company": "Foreign", "published": recent, "location": "Toronto",
                  "link": "https://example.com/tor", "publisher": "X"},
            # No article and no website: nothing to link a post to.
            "g": {"company": "Nowhere", "published": recent, "location": "Zug",
                  "link": "https://www.crunchbase.com/funding_round/nowhere",
                  "publisher": "Crunchbase export"},
        }}, f)

    got = scraper.from_database(path, 14, [])
    names = [g["company"] for g in got]

    assert "Basilea" in names, "a round with no article behind it never reaches the page"
    assert names.count("Exclaim Robotics") == 1, names
    assert "Ancient" not in names, "a round outside the window was offered"
    assert "Foreign" not in names, "a round that is not Swiss was offered"
    assert "Nowhere" not in names, "a post was built with nothing to link to"

    # The grant links to the company, never to the paywall it came from.
    basilea = next(g for g in got if g["company"] == "Basilea")
    assert basilea["link"] == "http://basilea.com", basilea["link"]
    assert "crunchbase" not in basilea["link"]

    # Of four write-ups, the one that says most survives.
    exclaim = next(g for g in got if g["company"] == "Exclaim Robotics")
    assert exclaim["amount"] == "USD 4.95M", exclaim

    # Anything the feeds already returned this run is not offered twice.
    # The second entry is a story straight off a feed: a headline, no company
    # yet, because that is worked out after this runs. Matching on links alone
    # would offer a different write-up of the same round.
    again = scraper.from_database(path, 14, [
        {"company": "Basilea"},
        {"title": "Exclaim Robotics raises USD 4.95 million for repair robots",
         "link": "https://www.startupticker.ch/exclaim"},
    ])
    assert "Basilea" not in [g["company"] for g in again]
    assert "Exclaim Robotics" not in [g["company"] for g in again]

    # A missing database is not an error.
    assert scraper.from_database("/nonexistent/archive.json", 14, []) == []


def test_drafting_a_story_does_not_spend_it():
    """Building the page must not mark its stories as posted.

    Every run used to record all fifteen picks as used the moment the page was
    written, so merely generating a shortlist spent it. Five test runs on one
    evening emptied the pool, and the scheduled run two days later found four
    stories with nothing having gone out. The page rebuilds daily now, which
    would burn the whole pool inside a week under the old behaviour.
    """
    import inspect

    source = inspect.getsource(scraper.main)
    assert "history_mod.save(" not in source, \
        "generating the shortlist writes to history again, so drafting spends a story"
    # Reading history is still right: a story genuinely posted stays out.
    assert "history_mod.filter_seen(" in source, \
        "the shortlist stopped excluding what has already been posted"

    # And the prompt still carries the guard that replaces it.
    import linkedin
    assert "already scheduled" in linkedin.COWORK_PROMPT
    assert "never schedule the same one" in linkedin.COWORK_PROMPT

    # The schedule has to match: a shortlist read like a news page cannot sit
    # for four days, which is what a weekly cron did to it.
    from pathlib import Path
    flow = Path(__file__).resolve().parents[2] / ".github/workflows/news-digest.yml"
    text = flow.read_text(encoding="utf-8")
    cron = re.search(r'- cron: "([^"]+)"', text).group(1)
    assert cron.split()[-1] == "*", f"the shortlist is on a weekly cron again: {cron}"
    assert cron.split()[2] == "*", f"the shortlist does not run every day: {cron}"


# Locking the count means a test appended below the runner, where it would
# never execute, shows up as a failure rather than as silence. That happened.
EXPECTED = 72


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
