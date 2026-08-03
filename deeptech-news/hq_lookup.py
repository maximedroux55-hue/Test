"""Find a company's headquarters when the article does not say.

Articles often skip the location: Hilo's round was covered without anyone
writing Neuchâtel. Rather than leave the column blank or trust recall, this
checks the company's own website, which is the authoritative source and, unlike
a search engine, does not block automated requests.

It looks for a Swiss postal address, since "2000 Neuchâtel" in a footer or
imprint is unambiguous in a way that a passing city mention is not.
"""

from __future__ import annotations

import re

from images import article_text

# Pages that carry a registered address, in the languages Swiss sites use.
_PATHS = (
    "", "/contact", "/en/contact", "/contact-us", "/kontakt", "/impressum",
    "/en/imprint", "/imprint", "/about", "/en/about", "/legal", "/mentions-legales",
)

# A Swiss address: four digit postcode then the town, optionally "CH-".
_SWISS_ADDRESS = re.compile(
    r"(?:CH[-\s])?\b([1-9]\d{3})\s+([A-ZÄÖÜ][\wÄÖÜäöüéèàêç'’\-]{2,24})"
)

# Addresses elsewhere, kept as "City, CC" so the column stays a city.
_COUNTRY_HINTS = {
    "germany": "DE", "deutschland": "DE", "france": "FR", "italy": "IT",
    "austria": "AT", "united kingdom": "GB", "netherlands": "NL",
    "united states": "US", "usa": "US",
}

_NOT_A_TOWN = {
    "Postfach", "Case", "Rue", "Route", "Avenue", "Strasse", "Street", "Chemin",
    "Via", "Piazza", "Platz", "Weg", "Allee", "Boulevard", "Impasse", "Zone",
    "Building", "Floor", "Suite", "Box", "Tel", "Fax", "Email", "VAT", "CHE",
}


def _city_from_address(text: str) -> str:
    """Return the town from the first plausible Swiss postal address."""
    for match in _SWISS_ADDRESS.finditer(text or ""):
        town = match.group(2).strip(" ,.")
        if town and town not in _NOT_A_TOWN and not town.isupper():
            return town
    return ""


def _candidate_domains(company: str, website: str) -> list:
    """Domains worth trying, the stated one first."""
    domains = []
    if website:
        d = website.strip().lower()
        d = re.sub(r"^https?://", "", d).split("/")[0]
        if d.startswith("www."):
            d = d[4:]
        if "." in d:
            domains.append(d)
    slug = re.sub(r"[^a-z0-9]", "", (company or "").lower())
    if 3 <= len(slug) <= 24:
        domains += [f"{slug}.com", f"{slug}.ch", f"{slug}.io", f"{slug}.swiss"]
    # Keep order, drop repeats.
    seen, out = set(), []
    for d in domains:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out[:4]


def find_hq(company: str, website: str = "", max_pages: int = 6) -> str:
    """Return the headquarters city from the company's own site, or ""."""
    if not company:
        return ""
    tried = 0
    for domain in _candidate_domains(company, website):
        for path in _PATHS:
            if tried >= max_pages:
                return ""
            text = article_text(f"https://{domain}{path}", limit=6000)
            tried += 1
            if not text:
                continue
            city = _city_from_address(text)
            if city:
                return city
            # Not Swiss: fall back to a stated country so the row is not blank.
            low = text.lower()
            for name, code in _COUNTRY_HINTS.items():
                if f"headquarters" in low and name in low:
                    return code
    return ""


def fill_missing(articles: list) -> int:
    """Look up the headquarters for articles that still have none. Returns count."""
    found = 0
    for art in articles:
        if art.get("location") or not art.get("company"):
            continue
        city = find_hq(art.get("company", ""), art.get("website", ""))
        if city:
            art["location"] = city
            found += 1
    return found


# Pages that describe the company rather than sell to visitors.
_PROFILE_PATHS = (
    "", "/about", "/en/about", "/about-us", "/team", "/en/team", "/company",
    "/news", "/en/news", "/press", "/blog", "/investors",
)


def company_pages(company: str, website: str = "", max_pages: int = 5):
    """Return (domain, text) from a company's own site, or ("", "").

    Used to fill what the news left out. A company's About or Press page names
    its founders and backers far more reliably than a funding write-up, which
    often says only that it "raised CHF 3.5 million".
    """
    if not company:
        return "", ""
    for domain in _candidate_domains(company, website):
        collected, hits = [], 0
        for path in _PROFILE_PATHS:
            if hits >= max_pages:
                break
            text = article_text(f"https://{domain}{path}", limit=4000)
            if text:
                collected.append(text)
                hits += 1
        # One reachable page is a coincidence; two means the domain is real.
        if len(collected) >= 2:
            return domain, "\n\n".join(collected)[:12000]
    return "", ""
