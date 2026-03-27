"""
scrapers/aps.py — Scraper for APS journals (journals.aps.org).

Covers: PRL, PRB, PRX, PRX Quantum, and any future APS journal
added to fields.json with publisher="aps".

Editorial filter: keep URLs matching the abstract pattern; drop errata and publisher's notes.
Abstract selector: section.abstract p
Subject tags: not available → always []
"""

import logging
import re

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper

_S2_API = "https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=abstract"

log = logging.getLogger(__name__)

# APS uses two URL formats:
#   legacy:  http://journals.aps.org/prl/abstract/10.1103/PhysRevLett.XXX.XXXXXX
#   current: http://link.aps.org/doi/10.1103/fgh1-gq8p
_ABSTRACT_URL_RE = re.compile(
    r"(journals\.aps\.org/.*/abstract/10\.\d{4}/|link\.aps\.org/doi/10\.\d{4}/)"
)
_ERRATA_TITLES = ("erratum", "publisher's note")


class APSScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        url = getattr(entry, "link", "")
        if not _ABSTRACT_URL_RE.search(url):
            return False
        title = getattr(entry, "title", "").lower()
        if any(t in title for t in _ERRATA_TITLES):
            return False
        return True

    def scrape_article(self, url: str) -> dict:
        # Try Semantic Scholar first — reliable, no IP blocking issues.
        doi_match = re.search(r"10\.\d{4}/\S+", url)
        if doi_match:
            try:
                resp = requests.get(_S2_API.format(doi=doi_match.group()), timeout=10)
                if resp.status_code == 200:
                    abstract = resp.json().get("abstract") or ""
                    if abstract:
                        return {"abstract": abstract, "subject_tags": []}
            except Exception:
                pass

        # Fallback: direct APS page scrape.
        response = self.get(url)
        if response is not None:
            soup = BeautifulSoup(response.text, "lxml")
            section = soup.find("section", {"id": "abstract-section"})
            abstract = section.get_text(separator=" ", strip=True).removeprefix("Abstract").strip() if section else ""
            if abstract:
                return {"abstract": abstract, "subject_tags": []}

        return {"abstract": "", "subject_tags": []}
