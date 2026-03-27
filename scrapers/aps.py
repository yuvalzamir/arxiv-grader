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

from bs4 import BeautifulSoup

from .base import BaseScraper

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
        response = self.get(url)
        if response is None:
            return {"abstract": "", "subject_tags": []}
        soup = BeautifulSoup(response.text, "lxml")
        section = soup.find("section", {"id": "abstract-section"})
        abstract = section.get_text(separator=" ", strip=True).removeprefix("Abstract").strip() if section else ""
        return {"abstract": abstract, "subject_tags": []}
