"""
scrapers/cambridge.py — Scraper for Cambridge University Press journals.

Covers: Journal of Fluid Mechanics and any future Cambridge journal added
to fields.json with publisher="cambridge".

Abstract coverage: FULL — Cambridge RSS <summary> includes the full article
abstract as HTML. Stripped with BeautifulSoup; no HTTP page fetches needed.

DOI: available in prism_doi and dc_identifier fields.
Subject tags: not available → always []
"""

import logging
import re

from bs4 import BeautifulSoup

from .base import BaseScraper

log = logging.getLogger(__name__)

_ERRATA_TITLES = ("erratum", "corrigendum", "correction", "retraction", "publisher's note")
_CAMBRIDGE_DOI_RE = re.compile(r"10\.1017/")


class CambridgeScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        title = getattr(entry, "title", "").lower()
        if any(t in title for t in _ERRATA_TITLES):
            return False
        doi = getattr(entry, "prism_doi", "") or getattr(entry, "dc_identifier", "")
        return bool(_CAMBRIDGE_DOI_RE.search(str(doi)))

    def scrape_article(self, url: str, entry=None) -> dict:
        # Try OpenAlex first using the DOI from RSS metadata fields.
        if entry is not None:
            doi = getattr(entry, "prism_doi", "") or getattr(entry, "dc_identifier", "")
            if doi:
                abstract = self._fetch_abstract_openalex(doi)
                if abstract:
                    return {"abstract": abstract, "subject_tags": []}
        # Fall back to RSS <summary> (Cambridge includes full abstract as HTML CDATA).
        if entry is not None:
            raw = getattr(entry, "summary", "") or getattr(entry, "description", "")
            if raw:
                text = BeautifulSoup(raw, "lxml").get_text(separator=" ", strip=True)
                if text:
                    return {"abstract": text, "subject_tags": []}
        return {"abstract": "", "subject_tags": []}
