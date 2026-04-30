"""
scrapers/ieee.py — Scraper for IEEE journals.

Covers two feed types:

1. ieeexplore.ieee.org/rss/TOC{id}.XML  (used for IEEE TIP)
   - Abstract: full, in <description> / entry.summary
   - Authors: custom <authors> tag, semicolon-delimited
   - DOI: not in feed; arxiv_id falls back to article URL

2. csdl-api.computer.org/api/rss/periodicals/trans/{abbr}/rss.xml  (used for IEEE TPAMI)
   - Abstract: not in feed → OpenAlex fallback via DOI
   - Authors: not in feed → OpenAlex fallback
   - DOI: in entry.id as "http://doi.ieeecomputersociety.org/10.1109/..."

Both feed types are handled by the same scraper class:
  1. Try entry.summary for abstract (ieeexplore feeds).
  2. If empty, extract DOI from entry.id and query OpenAlex for abstract + authors
     (csdl-api feeds, or any ieeexplore feed where the abstract is missing).

Subject tags: not available → always []
"""

import logging
import re

from bs4 import BeautifulSoup

from .base import BaseScraper

log = logging.getLogger(__name__)

_ERRATA_TITLES = ("erratum", "corrigendum", "correction", "retraction", "publisher's note")
_DOI_RE = re.compile(r"(10\.\d{4}/[^\s?#]+)")


class IEEEScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        title = getattr(entry, "title", "").lower()
        return not any(t in title for t in _ERRATA_TITLES)

    def scrape_article(self, url: str, entry=None) -> dict:
        abstract = ""
        authors = []

        if entry is not None:
            # Step 1: try abstract from RSS (ieeexplore feeds have it in entry.summary)
            raw = getattr(entry, "summary", "") or getattr(entry, "description", "")
            if raw:
                text = BeautifulSoup(raw, "lxml").get_text(separator=" ", strip=True)
                if text:
                    abstract = text

            # Authors from custom <authors> tag (ieeexplore feeds only)
            raw_authors = getattr(entry, "authors", None)
            if isinstance(raw_authors, str):
                authors = [a.strip() for a in raw_authors.split(";") if a.strip()]
            elif isinstance(raw_authors, list):
                authors = [a.get("name", "") for a in raw_authors if a.get("name")]

        # Step 2: if no abstract, try OpenAlex via DOI (csdl-api feeds)
        if not abstract:
            doi = self._doi_from_entry(entry) or self._doi_from_url(url)
            if doi:
                meta = self._fetch_metadata_openalex(doi)
                abstract = meta.get("abstract", "")
                if not authors:
                    authors = meta.get("authors", [])
                if abstract:
                    return {"abstract": abstract, "subject_tags": [], "authors": authors,
                            "doi": doi, "skip_rss_fallback": True}

        return {"abstract": abstract, "subject_tags": [], "authors": authors}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _doi_from_entry(self, entry) -> str:
        """Extract DOI from entry.id (csdl-api format: http://doi.ieeecomputersociety.org/10....)."""
        if entry is None:
            return ""
        entry_id = getattr(entry, "id", "") or ""
        m = _DOI_RE.search(entry_id)
        return m.group(1) if m else ""

    def _doi_from_url(self, url: str) -> str:
        """Extract DOI from article URL as fallback."""
        m = _DOI_RE.search(url)
        return m.group(1) if m else ""
