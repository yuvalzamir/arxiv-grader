"""
scrapers/iop.py — Scraper for IOP Science journals (iopscience.iop.org).

Covers: The Astrophysical Journal (ApJ), ApJ Letters (ApJL),
The Astronomical Journal (AJ), Journal of Cosmology and Astroparticle
Physics (JCAP), and any future IOP journal added to fields.json
with publisher="iop".

Abstract coverage: FULL — IOP RSS <description> elements include the
full article abstract. No HTTP page fetches are required.
  - feedparser exposes this as entry.summary
  - May contain HTML tags (stripped with BeautifulSoup)

Subject tags: not available → always []
"""

import logging
import re

from bs4 import BeautifulSoup

from .base import BaseScraper

log = logging.getLogger(__name__)

_ERRATA_TITLES = ("erratum", "corrigendum", "correction", "publisher's note", "retraction")
_DOI_RE = re.compile(r"10\.\d{4}/")


class IOPScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        title = getattr(entry, "title", "").lower()
        if any(t in title for t in _ERRATA_TITLES):
            return False
        link = getattr(entry, "link", "")
        doi = getattr(entry, "prism_doi", "") or getattr(entry, "dc_identifier", "")
        return bool(_DOI_RE.search(link) or _DOI_RE.search(str(doi)))

    def scrape_article(self, url: str, entry=None) -> dict:
        # IOP RSS feeds include the full abstract in <description> (feedparser:
        # entry.summary). Strip any HTML tags that may be present.
        if entry is not None:
            raw = getattr(entry, "summary", "") or getattr(entry, "description", "")
            if raw:
                text = BeautifulSoup(raw, "lxml").get_text(separator=" ", strip=True)
                if text:
                    return {"abstract": text, "subject_tags": []}
        return {"abstract": "", "subject_tags": []}
