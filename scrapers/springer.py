"""
scrapers/springer.py — Scraper for Springer Nature journals (link.springer.com).

Covers: IJCV (journal id 11263), and any future Springer journal added to
fields.json with publisher="springer".

RSS structure: Springer uses standard PRISM/Dublin Core namespaces.
  - Abstract: <description> (feedparser: entry.summary) — full abstract
  - DOI: <prism:doi> (feedparser: entry.prism_doi), also embedded in article URL
  - Authors: <dc:creator> elements (feedparser: entry.authors / entry.author)

RSS feed URL pattern:
  https://link.springer.com/search.rss?facet-content-type=Article&facet-journal-id={id}&query=

Abstract coverage and authors:
  1. OpenAlex by DOI — primary source. Returns abstract + authors in one call.
     Springer has excellent OpenAlex coverage. Springer RSS carries no author
     data, so OpenAlex is required to populate the authors field.
  2. RSS <description> — fallback for very recent papers not yet in OpenAlex.
     Confirmed full abstracts for IJCV; no authors available in this path.

Subject tags: not available → always []
"""

import logging
import re

from bs4 import BeautifulSoup

from .base import BaseScraper

log = logging.getLogger(__name__)

_ERRATA_TITLES = ("erratum", "corrigendum", "correction", "retraction", "publisher's note")
_DOI_RE = re.compile(r"(10\.\d{4}/[^\s?#]+)")


class SpringerScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        title = getattr(entry, "title", "").lower()
        return not any(t in title for t in _ERRATA_TITLES)

    def _fetch_by_doi(self, doi: str) -> dict:
        """Fetch abstract + authors from OpenAlex by DOI. Shared with subclasses."""
        meta = self._fetch_metadata_openalex(doi)
        abstract = meta.get("abstract", "")
        authors = meta.get("authors", [])
        if abstract:
            return {"abstract": abstract, "subject_tags": [], "doi": doi,
                    "authors": authors, "skip_rss_fallback": True}
        return {"abstract": "", "subject_tags": [], "doi": doi, "authors": authors}

    def scrape_article(self, url: str, entry=None) -> dict:
        doi = self._doi_from_entry(entry) or self._doi_from_url(url)

        # Step 1: OpenAlex by DOI — provides both abstract and authors in one call.
        # Springer has good OpenAlex coverage and the RSS carries no author data.
        if doi:
            result = self._fetch_by_doi(doi)
            if result.get("abstract"):
                return result
            # No OpenAlex abstract yet (very recent paper) — fall through to RSS.
            # Do NOT set skip_rss_fallback so the caller can use entry.summary.
            return {"abstract": "", "subject_tags": [], "doi": doi,
                    "authors": result.get("authors", [])}

        # Step 2: RSS <description> — used only when DOI is unavailable.
        if entry is not None:
            raw = getattr(entry, "summary", "") or getattr(entry, "description", "")
            if raw:
                text = BeautifulSoup(raw, "lxml").get_text(separator=" ", strip=True)
                if len(text) > 100:
                    return {"abstract": text, "subject_tags": []}

        return {"abstract": "", "subject_tags": []}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _doi_from_entry(self, entry) -> str:
        """Extract DOI from prism:doi namespace field."""
        if entry is None:
            return ""
        doi = getattr(entry, "prism_doi", "") or ""
        if doi.strip().startswith("10."):
            return doi.strip()
        return ""

    def _doi_from_url(self, url: str) -> str:
        """Extract DOI from Springer article URL (e.g. /article/10.1007/s11263-...)."""
        m = _DOI_RE.search(url)
        return m.group(1) if m else ""
