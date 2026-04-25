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

Abstract coverage: GOOD — Semantic Scholar then OpenAlex fallback (~90%+ hit rate
on kept entries).
  - Article pages: Cloudflare-protected (403) from server IPs.
  - Semantic Scholar: primary source, ~85% hit rate on research articles.
  - OpenAlex: fallback when Semantic Scholar returns nothing.
  - RSS fallback: short metadata string used when both APIs return nothing.

Subject tags: not available → always []
"""

import logging
import re

import requests

from .base import BaseScraper

log = logging.getLogger(__name__)

_DOI_RE = re.compile(r"10\.1126/")
_SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
_OPENALEX_URL = "https://api.openalex.org/works/doi:{doi}"
_HEADERS = {"User-Agent": "arxiv-grader/1.0 (mailto:contact@incomingscience.xyz)"}

# dc:type values worth including in a research digest.
# Drops: In Depth, Books et al., Research Highlights, Feature, Working Life,
#        Expert Voices, Editorial, Policy Article, Letter (no abstracts).
_KEEP_TYPES = {"Research Article", "Review", "Perspective"}


def _reconstruct_openalex_abstract(inverted_index: dict) -> str:
    tokens: dict[int, str] = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            tokens[pos] = word
    return " ".join(tokens[i] for i in sorted(tokens))


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
            abstract = self._fetch_semantic_scholar(doi)
            if abstract:
                return {"abstract": abstract, "subject_tags": []}
            abstract = self._fetch_openalex(doi)
            if abstract:
                return {"abstract": abstract, "subject_tags": []}

        # Fallback: RSS summary will be used by the caller
        return {"abstract": "", "subject_tags": []}

    def _fetch_semantic_scholar(self, doi: str) -> str:
        try:
            r = requests.get(
                _SEMANTIC_SCHOLAR_URL.format(doi=doi),
                params={"fields": "abstract"},
                timeout=15,
                headers=_HEADERS,
            )
            if r.status_code == 200:
                return r.json().get("abstract") or ""
            log.debug("Semantic Scholar returned %d for DOI %s", r.status_code, doi)
        except Exception as e:
            log.warning("Semantic Scholar request failed for DOI %s: %s", doi, e)
        return ""

    def _fetch_openalex(self, doi: str) -> str:
        try:
            r = requests.get(
                _OPENALEX_URL.format(doi=doi),
                timeout=15,
                headers=_HEADERS,
            )
            if r.status_code == 200:
                inverted = r.json().get("abstract_inverted_index")
                if inverted:
                    return _reconstruct_openalex_abstract(inverted)
            else:
                log.debug("OpenAlex returned %d for DOI %s", r.status_code, doi)
        except Exception as e:
            log.warning("OpenAlex request failed for DOI %s: %s", doi, e)
        return ""


def _extract_doi_from_url(url: str) -> str:
    """Extract a clean DOI from a URL, stripping query parameters."""
    # Match /10.XXXX/... pattern, stop at ? or #
    m = re.search(r"(10\.\d{4}/[^\s?#]+)", url)
    return m.group(1) if m else ""
