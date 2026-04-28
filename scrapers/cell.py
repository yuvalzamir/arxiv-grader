"""
scrapers/cell.py — Scraper for Cell Press journals (cell.com).

Covers: Cell, Cell Systems, iScience, Immunity, and any future Cell Press
journal added to fields.json with publisher="cell".

Abstract coverage: GOOD overall, varies by journal.
  - Article pages: Cloudflare-protected (403) from server IPs.
  - Semantic Scholar: no Cell Press abstracts (Elsevier licensing).
  - Europe PMC REST API (primary source): free, no key required.
      Cell:         ~67% hit rate (6/7 in live test, 2026-04-11)
      Cell Systems: ~83% hit rate (7/7 in live test, 2026-04-11)
      Immunity:     ~87% hit rate (7/8 in live test, 2026-04-11)
      iScience:       0% hit rate — Europe PMC does not index iScience
  - RSS summary fallback (secondary source): Cell Press inpress feeds
    carry short teasers in entry.summary (200-450c for Cell/Cell Systems/
    Immunity, ~575c full abstracts for iScience). Used when Europe PMC
    returns nothing. Sufficient for triage in all cases.

Editorial filter: prism:section = "Correction" (and Erratum, Retraction,
Expression of Concern) excluded. All other sections (Article, Review,
Perspective, Methods) are kept. Missing section → included by default.

DOI: stored in dc:identifier on Cell Press RSS entries. fetch_journals.py
_extract_doi() reads dc_identifier so Cell papers get their DOI as
arxiv_id rather than the PII-based article URL.

Subject tags: not available → always []
"""

import logging

from .base import BaseScraper

log = logging.getLogger(__name__)

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
            abstract = self._fetch_abstract_europepmc(doi)
            if abstract:
                return {"abstract": abstract, "subject_tags": []}
        # No abstract found — return empty so the caller falls back to the RSS
        # summary, which contains a useful teaser (200–600c) for all Cell Press feeds.
        return {"abstract": "", "subject_tags": []}

