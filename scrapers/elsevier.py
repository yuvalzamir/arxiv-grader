"""
scrapers/elsevier.py — Scraper for Elsevier/ScienceDirect journals.

Covers: Physics Letters B, Nuclear Physics B, and any future SCOAP3
Elsevier journal added to fields.json with publisher="elsevier".

RSS: ScienceDirect feeds (rss.sciencedirect.com) — give paper list only;
descriptions contain publication metadata but no abstracts. Links are
PII-based ScienceDirect URLs (no DOIs in the feed).

Abstract coverage: GOOD (~75–90%) — pipeline:
  1. CrossRef PII→DOI lookup: extracts PII from the ScienceDirect URL and
     resolves it to a DOI via the CrossRef alternative-id filter.
  2. INSPIRE-HEP by DOI: primary abstract source for PLB. Returns full
     abstracts for most indexed HEP papers.
  3. OpenAlex by DOI: fallback after INSPIRE-HEP. Covers papers not yet
     indexed in INSPIRE-HEP and non-HEP NPB content.
  4. INSPIRE-HEP title search: last resort when CrossRef resolution fails.
     Works for PLB; less reliable for NPB (broader scope, special chars).
  - Article pages: Cloudflare-blocked from server IPs.
  - RSS fallback: suppressed — ScienceDirect descriptions contain only
    volume/date/author metadata, not scientific content.

Corrections/errata detected by title keywords and skipped.
Subject tags: not available → always []
"""

import logging
import re

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper

log = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "arxiv-grader/1.0 (mailto:contact@incomingscience.xyz)"}
_CROSSREF_URL = "https://api.crossref.org/works"
_INSPIREHEP_URL = "https://inspirehep.net/api/literature"
_OPENALEX_URL = "https://api.openalex.org/works/doi:{doi}"
_PII_RE = re.compile(r"/pii/([A-Z0-9]+)", re.IGNORECASE)
_DOI_RE = re.compile(r"(10\.\d{4}/[^\s?#]+)")
_ERRATA_TITLES = ("erratum", "corrigendum", "correction", "retraction", "addendum")


def _reconstruct_openalex_abstract(inverted_index: dict) -> str:
    tokens: dict[int, str] = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            tokens[pos] = word
    return " ".join(tokens[i] for i in sorted(tokens))


def _clean_title(raw: str) -> str:
    """Strip HTML markup from RSS title (ScienceDirect uses <em>, <sub>, etc.)."""
    return BeautifulSoup(raw, "lxml").get_text(separator=" ", strip=True)


class ElsevierScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        title = getattr(entry, "title", "").lower()
        if any(t in title for t in _ERRATA_TITLES):
            return False
        return True

    def scrape_article(self, url: str, entry=None) -> dict:
        # Step 1: resolve PII → DOI via CrossRef
        doi = self._doi_from_pii(url) or self._doi_from_entry(entry)

        if doi:
            # Step 2: INSPIRE-HEP by DOI
            abstract = self._fetch_inspirehep(f"doi {doi}")
            if abstract:
                return {"abstract": abstract, "subject_tags": [], "skip_rss_fallback": True}
            # Step 3: OpenAlex by DOI
            abstract = self._fetch_openalex(doi)
            if abstract:
                return {"abstract": abstract, "subject_tags": [], "skip_rss_fallback": True}

        # Step 4: INSPIRE-HEP title search (last resort; works for PLB)
        if entry is not None:
            title = _clean_title(getattr(entry, "title", ""))
            if title:
                abstract = self._fetch_inspirehep(f't "{title}"')
                if abstract:
                    return {"abstract": abstract, "subject_tags": [], "skip_rss_fallback": True}

        return {"abstract": "", "subject_tags": [], "skip_rss_fallback": True}

    # ------------------------------------------------------------------
    # DOI resolution helpers
    # ------------------------------------------------------------------

    def _doi_from_pii(self, url: str) -> str:
        """Extract PII from a ScienceDirect URL and resolve to DOI via CrossRef."""
        m = _PII_RE.search(url)
        if not m:
            return ""
        pii = m.group(1)
        try:
            r = requests.get(
                _CROSSREF_URL,
                params={"filter": f"alternative-id:{pii}", "rows": 1},
                headers=_HEADERS,
                timeout=15,
            )
            if r.status_code == 200:
                items = r.json().get("message", {}).get("items", [])
                if items:
                    return items[0].get("DOI", "")
            else:
                log.debug("CrossRef returned %d for PII %s", r.status_code, pii)
        except Exception as e:
            log.warning("CrossRef request failed for PII %s: %s", pii, e)
        return ""

    def _doi_from_entry(self, entry) -> str:
        """Try to extract DOI directly from feedparser entry fields."""
        if entry is None:
            return ""
        # prism:doi (feedparser namespace)
        doi = getattr(entry, "prism_doi", "") or ""
        if doi.startswith("10."):
            return doi.strip()
        # dc:identifier — may carry "DOI:" or "doi:" prefix
        dc_id = getattr(entry, "dc_identifier", "") or ""
        dc_id = re.sub(r"^(?:DOI:|doi:)\s*", "", dc_id.strip())
        if dc_id.startswith("10."):
            return dc_id
        return ""

    # ------------------------------------------------------------------
    # Abstract fetch helpers
    # ------------------------------------------------------------------

    def _fetch_inspirehep(self, query: str) -> str:
        try:
            r = requests.get(
                _INSPIREHEP_URL,
                params={"q": query, "fields": "abstracts", "size": 1},
                headers=_HEADERS,
                timeout=15,
            )
            if r.status_code == 200:
                hits = r.json().get("hits", {}).get("hits", [])
                if hits:
                    abstracts = hits[0].get("metadata", {}).get("abstracts", [])
                    if abstracts:
                        return abstracts[0].get("value", "")
            else:
                log.debug("INSPIRE-HEP returned %d for query '%s'", r.status_code, query[:60])
        except Exception as e:
            log.warning("INSPIRE-HEP request failed for query '%s': %s", query[:60], e)
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
