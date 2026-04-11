"""
scrapers/pnas.py — Scraper for PNAS (Proceedings of the National Academy of Sciences).

RSS: eTOC feed — gives the full current issue (~70 entries) once per week.
All entries share the same prism:coverDate (the issue date); individual
papers carry earlier updated/published dates (online-first). fetch_journals.py
uses the later of updated vs coverDate so the watermark advances to the
issue date after first scrape.

Abstract coverage: GOOD — Semantic Scholar (~80%+ estimated hit rate).
  - Semantic Scholar: free API, no key required. PNAS is open-access-friendly
    and well-indexed. Confirmed full abstract (907c) on first tested paper.
    Short commentaries and perspective pieces may not be indexed.
  - RSS fallback: PNAS RSS summaries are typically empty; Semantic Scholar
    is the sole abstract source.
  Tested on live feed 2026-04-11: 2/3 research articles returned full
  abstracts; 1 commentary had no Semantic Scholar entry.

Editorial filter: accepts 10.1073/pnas. DOIs only — excludes "In This Issue"
summaries (10.1073/iti...) and other non-paper content.

Subject tags: not available → always []
"""

import logging
import re

import requests

from .base import BaseScraper

log = logging.getLogger(__name__)

_PNAS_DOI_RE = re.compile(r"10\.1073/pnas\.")
_SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"


class PnasScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        doi = getattr(entry, "prism_doi", "") or getattr(entry, "id", "") or ""
        return bool(_PNAS_DOI_RE.search(doi))

    def scrape_article(self, url: str, entry=None) -> dict:
        doi = getattr(entry, "prism_doi", "") if entry is not None else ""
        if doi:
            abstract = self._fetch_abstract_semantic_scholar(doi)
            if abstract:
                return {"abstract": abstract, "subject_tags": []}
        return {"abstract": "", "subject_tags": []}

    def _fetch_abstract_semantic_scholar(self, doi: str) -> str:
        try:
            r = requests.get(
                _SEMANTIC_SCHOLAR_URL.format(doi=doi),
                params={"fields": "abstract"},
                timeout=15,
                headers={"User-Agent": "arxiv-grader/1.0 (mailto:contact@incomingscience.xyz)"},
            )
            if r.status_code == 200:
                return r.json().get("abstract") or ""
            log.debug("Semantic Scholar returned %d for DOI %s", r.status_code, doi)
        except Exception as e:
            log.warning("Semantic Scholar request failed for DOI %s: %s", doi, e)
        return ""
