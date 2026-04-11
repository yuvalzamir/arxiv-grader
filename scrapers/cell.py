"""
scrapers/cell.py — Scraper for Cell Press journals (cell.com).

Covers: Cell, Cell Systems, iScience, Immunity, and any future Cell Press
journal added to fields.json with publisher="cell".

cell.com article pages are Cloudflare-protected (403) from server IPs.
Semantic Scholar has no Cell Press abstracts (Elsevier licensing).

Abstract strategy (in order):
  1. Europe PMC REST API — good coverage for Cell, Cell Systems, Immunity
     (~67–83% hit rate on inpress articles). Free, no key required.
  2. RSS summary fallback — the caller (fetch_journals.py) uses entry.summary
     when scrape_article returns an empty abstract. Cell Press RSS summaries
     are 200–600c teasers, sufficient for triage. iScience RSS has full
     abstracts (~575c) and relies entirely on this fallback.

Editorial filter: prism:section = "Correction" is excluded. All other
section types (Article, Review, Perspective, Methods, etc.) are kept.
When no section tag is present the entry is included by default.

DOI: stored in dc:identifier on Cell Press RSS entries. fetch_journals.py
_extract_doi() reads dc_identifier so Cell papers get their DOI as
arxiv_id rather than the PII-based article URL.
"""

import logging

import requests

from .base import BaseScraper

log = logging.getLogger(__name__)

_EUROPE_PMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_SKIP_SECTIONS = {"correction", "erratum", "retraction", "expression of concern"}


class CellScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        section = (getattr(entry, "prism_section", "") or "").strip().lower()
        if section in _SKIP_SECTIONS:
            return False
        return True

    def scrape_article(self, url: str, entry=None) -> dict:
        doi = (getattr(entry, "dc_identifier", "") or "") if entry is not None else ""
        if doi:
            abstract = self._fetch_abstract_europe_pmc(doi)
            if abstract:
                return {"abstract": abstract, "subject_tags": []}
        # No abstract found — return empty so the caller falls back to the RSS
        # summary, which contains a useful teaser (200–600c) for all Cell Press feeds.
        return {"abstract": "", "subject_tags": []}

    def _fetch_abstract_europe_pmc(self, doi: str) -> str:
        try:
            r = requests.get(
                _EUROPE_PMC_URL,
                params={"query": f"DOI:{doi}", "resultType": "core", "format": "json"},
                timeout=15,
                headers={"User-Agent": "arxiv-grader/1.0 (mailto:contact@incomingscience.xyz)"},
            )
            if r.status_code == 200:
                results = r.json().get("resultList", {}).get("result", [])
                if results:
                    return results[0].get("abstractText", "") or ""
            log.debug("Europe PMC returned %d for DOI %s", r.status_code, doi)
        except Exception as e:
            log.warning("Europe PMC request failed for DOI %s: %s", doi, e)
        return ""
