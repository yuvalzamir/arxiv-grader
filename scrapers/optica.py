"""
scrapers/optica.py — Scraper for Optica Publishing Group journals.

Covers: Optica, and any future OPG journal added to fields.json with
publisher="optica".

RSS structure: Dublin Core namespace only (dc:title, dc:creator, dc:description,
dc:identifier, dc:date). Multiple dc:creator elements, one per author.
DOI is in dc:identifier as "doi:10.1364/OPTICA.xxxxxx".

Abstract coverage: GOOD — OpenAlex API (~high hit rate for Optica papers).
  - Article pages: JS-redirected (Cloudflare), cannot scrape.
  - Semantic Scholar: returns null for Optica DOIs (licensing restriction).
  - OpenAlex: free API, no key required. Provides abstract via
    abstract_inverted_index (word → position list); reconstructed here.
    Fallback: truncated RSS dc:description (~1-2 sentences) when OpenAlex
    returns nothing (very recent papers not yet indexed).

Subject tags: not available → always []
Authors: extracted from dc:creator tags (one element per author — clean).
"""

import logging
import re

import requests

from .base import BaseScraper

log = logging.getLogger(__name__)

_OPTICA_DOI_RE = re.compile(r"10\.1364/")
_OPENALEX_URL  = "https://api.openalex.org/works/doi:{doi}"
_OPENALEX_HEADERS = {"User-Agent": "arxiv-grader/1.0 (mailto:contact@incomingscience.xyz)"}


def _reconstruct_abstract(inverted_index: dict) -> str:
    """Reconstruct plain-text abstract from OpenAlex abstract_inverted_index."""
    if not inverted_index:
        return ""
    # inverted_index: {"word": [pos, pos, ...], ...}
    tokens: dict[int, str] = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            tokens[pos] = word
    return " ".join(tokens[i] for i in sorted(tokens))


class OpticaScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        """Accept entries whose DOI matches the Optica Publishing Group prefix."""
        dc_id = getattr(entry, "dc_identifier", "")
        link  = getattr(entry, "link", "")
        return bool(
            _OPTICA_DOI_RE.search(dc_id)
            or _OPTICA_DOI_RE.search(link)
        )

    def scrape_article(self, url: str, entry=None) -> dict:
        doi = self._doi_from_entry(entry) or self._doi_from_url(url)
        if doi:
            abstract = self._fetch_abstract_openalex(doi)
            if abstract:
                return {"abstract": abstract, "subject_tags": []}

        # Fallback: caller will use RSS dc:description / summary
        return {"abstract": "", "subject_tags": []}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _doi_from_entry(self, entry) -> str:
        """Extract DOI from dc:identifier field ('doi:10.1364/...')."""
        if entry is None:
            return ""
        dc_id = getattr(entry, "dc_identifier", "")
        if dc_id.startswith("doi:"):
            return dc_id[4:]          # strip "doi:" prefix
        if dc_id.startswith("10."):
            return dc_id
        return ""

    def _doi_from_url(self, url: str) -> str:
        """Extract DOI from article URL as fallback."""
        m = re.search(r"(10\.\d{4}/[^\s?#]+)", url)
        return m.group(1) if m else ""

    def _fetch_abstract_openalex(self, doi: str) -> str:
        try:
            r = requests.get(
                _OPENALEX_URL.format(doi=doi),
                timeout=15,
                headers=_OPENALEX_HEADERS,
            )
            if r.status_code == 200:
                data = r.json()
                inverted = data.get("abstract_inverted_index")
                if inverted:
                    return _reconstruct_abstract(inverted)
            else:
                log.debug("OpenAlex returned %d for DOI %s", r.status_code, doi)
        except Exception as e:
            log.warning("OpenAlex request failed for DOI %s: %s", doi, e)
        return ""
