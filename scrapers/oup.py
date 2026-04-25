"""
scrapers/oup.py — Scraper for Oxford University Press / Oxford Academic journals.

Covers: Monthly Notices of the Royal Astronomical Society (MNRAS) and any
future OUP journal added to fields.json with publisher="oup".

Abstract coverage: GOOD — scraped from open-access article pages.
  - MNRAS has been fully open access since 2024; article pages at
    academic.oup.com are publicly accessible.
  - Abstract selector: <section class="abstract">, <div class="abstract-block">,
    <div class="abstract">, tried in order.
  - Inner heading elements ("Abstract") are removed before extracting text.
  - Fallback: empty string (RSS summary used by caller) when page fetch fails.

Subject tags: not available → always []
"""

import logging
import re

from bs4 import BeautifulSoup

from .base import BaseScraper

log = logging.getLogger(__name__)

_ERRATA_TITLES = ("erratum", "corrigendum", "correction", "retraction")
_DOI_RE = re.compile(r"10\.\d{4}/")

_ABSTRACT_SELECTORS = [
    "section.abstract",
    "div.abstract-block",
    "div.abstract",
    "div#abstract",
]


class OUPScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        title = getattr(entry, "title", "").lower()
        if any(t in title for t in _ERRATA_TITLES):
            return False
        link = getattr(entry, "link", "")
        doi = getattr(entry, "dc_identifier", "")
        return bool(_DOI_RE.search(link) or _DOI_RE.search(str(doi)))

    def scrape_article(self, url: str, entry=None) -> dict:
        response = self.get(url)
        if response is None:
            return {"abstract": "", "subject_tags": []}

        soup = BeautifulSoup(response.text, "lxml")
        for selector in _ABSTRACT_SELECTORS:
            el = soup.select_one(selector)
            if el:
                # Remove "Abstract" heading elements before extracting text.
                for heading in el.select("h2, h3, h4, strong.abstract-title"):
                    heading.decompose()
                text = el.get_text(separator=" ", strip=True)
                if len(text) > 50:
                    return {"abstract": text, "subject_tags": []}

        return {"abstract": "", "subject_tags": []}
