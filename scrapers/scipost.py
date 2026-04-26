"""
scrapers/scipost.py — Scraper for SciPost Physics journals.

Covers: SciPost Physics (hep-ph, hep-th, hep-ex discipline feeds) and any
future SciPost journal added to fields.json with publisher="scipost".

RSS: Per-discipline feeds (10 items each). No abstracts in feed —
descriptions contain only the journal citation string.
  - DOI pattern: scipost.org/SciPostPhys.X.Y.Z → 10.21468/SciPostPhys.X.Y.Z
  - Abstracts: OpenAlex API (100% hit rate for SciPost papers).
  - RSS fallback: suppressed (feed descriptions are citation strings, not
    scientific content).

Editorial filter: keeps only URLs matching the SciPost article pattern
(SciPostPhys.X.Y.Z). Anything without that pattern is skipped.

arXiv overlap: essentially all SciPost Physics papers are arXiv preprints.
They will also appear in the hep-* arXiv feeds for the same field. The
journal version provides the peer-reviewed status signal (mild score boost).

Subject tags: not available → always []
"""

import logging
import re

import requests

from .base import BaseScraper

log = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "arxiv-grader/1.0 (mailto:contact@incomingscience.xyz)"}
_OPENALEX_URL = "https://api.openalex.org/works/doi:{doi}"
# Matches: scipost.org/SciPostPhys.20.4.116 (and similar SciPost journal slugs)
_SCIPOST_PATH_RE = re.compile(r"scipost\.org/(SciPost\w+\.\d+\.\d+\.\d+)")
_DOI_PREFIX = "10.21468/"


def _reconstruct_openalex_abstract(inverted_index: dict) -> str:
    tokens: dict[int, str] = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            tokens[pos] = word
    return " ".join(tokens[i] for i in sorted(tokens))


class SciPostScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        link = getattr(entry, "link", "")
        return bool(_SCIPOST_PATH_RE.search(link))

    def scrape_article(self, url: str, entry=None) -> dict:
        doi = self._doi_from_url(url)
        if doi:
            abstract = self._fetch_openalex(doi)
            if abstract:
                return {"abstract": abstract, "subject_tags": [], "skip_rss_fallback": True}
        return {"abstract": "", "subject_tags": [], "skip_rss_fallback": True}

    def _doi_from_url(self, url: str) -> str:
        m = _SCIPOST_PATH_RE.search(url)
        if m:
            return _DOI_PREFIX + m.group(1)
        # Handle direct DOI URLs (e.g. scipost.org/10.21468/...)
        doi_m = re.search(r"(10\.21468/\S+)", url)
        if doi_m:
            return doi_m.group(1).rstrip("/")
        return ""

    def _fetch_openalex(self, doi: str) -> str:
        try:
            r = requests.get(
                _OPENALEX_URL.format(doi=doi),
                headers=_HEADERS,
                timeout=15,
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
