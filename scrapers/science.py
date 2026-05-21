"""
scrapers/science.py — Scraper for Science (science.org) / AAAS journals.

Covers: Science, Science Immunology, Science Advances, and any future
AAAS journal added to fields.json with publisher="science".

RSS: eTOC feed — gives the complete last issue (all article types).
tag_filter can be used to filter multi-discipline journals like Science Advances.

Editorial filter: dc:type field used to drop non-research content.
  Keeps: Research Article, Review, Perspective (~19/37 papers per issue).
  Drops: In Depth, News, Books et al., Research Highlights, Feature,
         Working Life, Expert Voices, Editorial, Policy Article, Letter.

Abstract coverage: GOOD — OpenAlex fallback + S2 batch enrichment (~90%+ hit rate
on kept entries).
  - Article pages: Cloudflare-protected (403) from server IPs.
  - OpenAlex: primary per-article source.
  - S2 batch: fills remaining misses after all articles are scraped.
  - RSS fallback: short metadata string used when both APIs return nothing.

Subject tags: not available → always []
"""

import logging
import re

from .base import BaseScraper

log = logging.getLogger(__name__)

_DOI_RE = re.compile(r"10\.1126/")

# dc:type values worth including in a research digest.
# Drops: In Depth, Books et al., Research Highlights, Feature, Working Life,
#        Expert Voices, Editorial, Policy Article, Letter (no abstracts).
_KEEP_TYPES = {"Research Article", "Review", "Perspective"}


class ScienceScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        link = getattr(entry, "link", "")
        doi = getattr(entry, "id", "")
        if not (_DOI_RE.search(link) or _DOI_RE.search(doi)):
            return False
        dc_type = getattr(entry, "dc_type", "") or ""
        # Drop non-research content (In Depth, News, Books, Highlights, etc.).
        # Accept entries with no dc_type to avoid silently dropping unknown types.
        if dc_type and dc_type not in _KEEP_TYPES:
            return False
        return True

    def scrape_article(self, url: str, entry=None) -> dict:
        doi = _extract_doi_from_url(url)
        if doi:
            abstract = self._fetch_abstract_openalex(doi)
            if abstract:
                return {"abstract": abstract, "subject_tags": []}
        # S2 batch will fill remaining misses after the full article loop
        return {"abstract": "", "subject_tags": []}


def _extract_doi_from_url(url: str) -> str:
    """Extract a clean DOI from a URL, stripping query parameters."""
    # Match /10.XXXX/... pattern, stop at ? or #
    m = re.search(r"(10\.\d{4}/[^\s?#]+)", url)
    return m.group(1) if m else ""
