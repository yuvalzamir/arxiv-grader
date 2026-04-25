"""
scrapers/oup.py — Scraper for Oxford University Press / Oxford Academic journals.

Covers: Monthly Notices of the Royal Astronomical Society (MNRAS) and any
future OUP journal added to fields.json with publisher="oup".

Abstract coverage: GOOD — OpenAlex API by DOI (~high hit rate for MNRAS).
  - Oxford Academic article pages return 403 from server IPs (Cloudflare).
  - OpenAlex: free API, no key required. Provides abstract via
    abstract_inverted_index (word → position list); reconstructed here.
    High hit rate for MNRAS — confirmed working in testing.
  - Fallback: empty string (RSS summary used by caller) when OpenAlex
    returns nothing (very recent papers not yet indexed).

Subject tags: not available → always []
"""

import logging
import re

import requests

from .base import BaseScraper

log = logging.getLogger(__name__)

_ERRATA_TITLES = ("erratum", "corrigendum", "correction", "retraction")
_DOI_RE = re.compile(r"10\.\d{4}/")
_OPENALEX_URL = "https://api.openalex.org/works/doi:{doi}"
_OPENALEX_HEADERS = {"User-Agent": "arxiv-grader/1.0 (mailto:contact@incomingscience.xyz)"}


def _reconstruct_abstract(inverted_index: dict) -> str:
    """Reconstruct plain-text abstract from OpenAlex abstract_inverted_index."""
    if not inverted_index:
        return ""
    tokens: dict[int, str] = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            tokens[pos] = word
    return " ".join(tokens[i] for i in sorted(tokens))


class OUPScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        title = getattr(entry, "title", "").lower()
        if any(t in title for t in _ERRATA_TITLES):
            return False
        link = getattr(entry, "link", "")
        doi = getattr(entry, "dc_identifier", "")
        return bool(_DOI_RE.search(link) or _DOI_RE.search(str(doi)))

    def scrape_article(self, url: str, entry=None) -> dict:
        doi = self._doi_from_url(url)
        if doi:
            abstract = self._fetch_abstract_openalex(doi)
            if abstract:
                return {"abstract": abstract, "subject_tags": []}
        return {"abstract": "", "subject_tags": []}

    def _doi_from_url(self, url: str) -> str:
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
                inverted = r.json().get("abstract_inverted_index")
                if inverted:
                    return _reconstruct_abstract(inverted)
            else:
                log.debug("OpenAlex returned %d for DOI %s", r.status_code, doi)
        except Exception as e:
            log.warning("OpenAlex request failed for DOI %s: %s", doi, e)
        return ""
