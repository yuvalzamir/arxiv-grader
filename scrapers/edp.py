"""
scrapers/edp.py — Scraper for EDP Sciences journals.

Covers: Astronomy & Astrophysics (A&A, aanda.org) and the European
Physical Journal C (EPJC, epjc.epj.org), both delivered via Feedburner
RSS. Any future EDP journal added to fields.json with publisher="edp"
will also use this scraper.

Abstract coverage: GOOD — scraped from open-access article pages.
  - Both A&A and EPJC are fully open access; article pages are publicly
    accessible without authentication.
  - Abstract selector: <div class="abstract">, <section class="abstract">,
    or <p class="a-plus-plus"> (A&A-specific), tried in order.
  - Fallback: truncated RSS summary when the page fetch fails or the
    abstract element is not found.

Subject tags: not available → always []
"""

import logging
import re

from bs4 import BeautifulSoup

from .base import BaseScraper

log = logging.getLogger(__name__)

_ERRATA_TITLES = ("erratum", "corrigendum", "correction", "comment on", "reply to", "retraction")
_DOI_RE = re.compile(r"10\.\d{4}/")

# Try these CSS selectors in order; take the first non-empty match.
_ABSTRACT_SELECTORS = [
    "div.abstract",
    "section.abstract",
    "div#abstract",
    "div.Abs",
    "section.Abs",
]

# Prefix labels to strip from the extracted text.
_LABEL_RE = re.compile(r"^(Abstract[:\s]*|ABSTRACT[:\s]*)", re.IGNORECASE)


class EDPScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        title = getattr(entry, "title", "").lower()
        if any(t in title for t in _ERRATA_TITLES):
            return False
        link = getattr(entry, "link", "")
        return bool(_DOI_RE.search(link))

    def scrape_article(self, url: str, entry=None) -> dict:
        response = self.get(url)
        if response is None:
            return {"abstract": "", "subject_tags": []}

        soup = BeautifulSoup(response.text, "lxml")
        for selector in _ABSTRACT_SELECTORS:
            el = soup.select_one(selector)
            if el:
                text = el.get_text(separator=" ", strip=True)
                text = _LABEL_RE.sub("", text).strip()
                if len(text) > 50:
                    return {"abstract": text, "subject_tags": []}

        return {"abstract": "", "subject_tags": []}
