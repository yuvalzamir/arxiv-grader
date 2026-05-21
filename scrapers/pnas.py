"""
scrapers/pnas.py — Scraper for PNAS (Proceedings of the National Academy of Sciences).

RSS: eTOC feed — gives the full current issue (~70 entries) once per week.
All entries share the same prism:coverDate (the issue date); individual
papers carry earlier updated/published dates (online-first). fetch_journals.py
uses the later of updated vs coverDate so the watermark advances to the
issue date after first scrape.

Abstract coverage: GOOD — S2 batch enrichment (~80%+ estimated hit rate).
  - scrape_article returns empty abstract; S2 batch fills all PNAS papers
    at once after the full article loop (one request per journal).
  - RSS fallback: PNAS RSS summaries are typically empty.
  Tested on live feed 2026-04-11: 2/3 research articles returned full
  abstracts; 1 commentary had no Semantic Scholar entry.

Editorial filter: accepts 10.1073/pnas. DOIs only — excludes "In This Issue"
summaries (10.1073/iti...) and other non-paper content.

Subject tags: not available → always []
"""

import logging
import re

from .base import BaseScraper

log = logging.getLogger(__name__)

_PNAS_DOI_RE = re.compile(r"10\.1073/pnas\.")


class PnasScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        doi = getattr(entry, "prism_doi", "") or getattr(entry, "id", "") or ""
        return bool(_PNAS_DOI_RE.search(doi))

    def scrape_article(self, url: str, entry=None) -> dict:
        # S2 batch enrichment fills abstracts after the full article loop
        return {"abstract": "", "subject_tags": []}
