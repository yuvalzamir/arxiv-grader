"""
scrapers/edp.py — Scraper for EDP Sciences journals.

Covers: Astronomy & Astrophysics (A&A, aanda.org) and the European
Physical Journal C (EPJC, epjc.epj.org), both delivered via Feedburner
RSS. Any future EDP journal added to fields.json with publisher="edp"
will also use this scraper.

Abstract coverage: GOOD — scraped from open-access article pages.
  - Both A&A and EPJC are fully open access; article pages are publicly
    accessible without authentication.
  - A&A full-HTML page structure: <p class="bold">Abstract</p> followed
    by the abstract <p> sibling. No wrapper div/section.
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

        # A&A full-HTML structure: <p class="bold">Abstract</p> followed by
        # the abstract text in the next <p> sibling.
        for bold_p in soup.find_all("p", class_="bold"):
            if "abstract" in bold_p.get_text(strip=True).lower():
                sibling = bold_p.find_next_sibling("p")
                if sibling:
                    text = sibling.get_text(separator=" ", strip=True)
                    if len(text) > 50:
                        return {"abstract": text, "subject_tags": []}

        # Generic fallback selectors (EPJC and other EDP journals)
        for selector in ("div.abstract", "section.abstract", "div#abstract"):
            el = soup.select_one(selector)
            if el:
                text = el.get_text(separator=" ", strip=True)
                text = _LABEL_RE.sub("", text).strip()
                if len(text) > 50:
                    return {"abstract": text, "subject_tags": []}

        return {"abstract": "", "subject_tags": []}
