"""
scrapers/science.py — Scraper for Science (science.org).

Covers: Science, and any future AAAS journal added to fields.json
with publisher="science".

RSS: eTOC feed — gives the complete last issue (all article types).
tag_filter should be null — full issue is passed to triage.

Editorial filter: requires a valid 10.1126/science. DOI.
Abstract: Science.org is Cloudflare-protected (403). Uses Semantic Scholar
API (api.semanticscholar.org) for full abstracts. Falls back to RSS summary.
"""

import logging
import re

import requests

from .base import BaseScraper

log = logging.getLogger(__name__)

_DOI_RE = re.compile(r"10\.1126/science\.")
_SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"


class ScienceScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        link = getattr(entry, "link", "")
        doi = getattr(entry, "id", "")
        return bool(_DOI_RE.search(link) or _DOI_RE.search(doi))

    def scrape_article(self, url: str) -> dict:
        # Extract DOI from URL (strip query params like ?af=R)
        doi = _extract_doi_from_url(url)
        if doi:
            abstract = self._fetch_abstract_semantic_scholar(doi)
            if abstract:
                return {"abstract": abstract, "subject_tags": []}

        # Fallback: RSS summary will be used by the caller
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


def _extract_doi_from_url(url: str) -> str:
    """Extract a clean DOI from a URL, stripping query parameters."""
    # Match /10.XXXX/... pattern, stop at ? or #
    m = re.search(r"(10\.\d{4}/[^\s?#]+)", url)
    return m.group(1) if m else ""
