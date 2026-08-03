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


# Locking the count means a test appended below the runner, where it would
# never execute, shows up as a failure rather than as silence. That happened.
EXPECTED = 29


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
