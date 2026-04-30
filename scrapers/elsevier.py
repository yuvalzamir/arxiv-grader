"""
scrapers/elsevier.py — Scraper for Elsevier/ScienceDirect journals.

Two scraper classes:
  - ElsevierScraper       (publisher="elsevier")       — HEP journals (PLB, NPB).
                                                          Uses INSPIRE-HEP + OpenAlex.
  - ElsevierGeneralScraper (publisher="elsevier_general") — General Elsevier journals
                                                          (Pattern Recognition, Neural
                                                          Networks, CVIU, etc.).
                                                          Uses OpenAlex only (no INSPIRE).

RSS: ScienceDirect feeds (rss.sciencedirect.com) — give paper list only.
  - <description> contains: publication date, source (volume/part), author list.
  - No abstract in the feed.
  - Authors extracted from "Author(s): Name1, Name2, ..." in the description HTML.
  - Links are PII-based ScienceDirect URLs (no DOIs in the feed).

Abstract coverage — ElsevierScraper (HEP, ~75–90%):
  1. CrossRef PII→DOI lookup
  2. INSPIRE-HEP by DOI (primary for PLB)
  3. OpenAlex by DOI (fallback)
  4. INSPIRE-HEP title search (last resort)

Abstract coverage — ElsevierGeneralScraper (non-HEP, ~80–90%):
  1. CrossRef PII→DOI lookup
  2. OpenAlex by DOI

Article pages: Cloudflare-blocked from server IPs.
RSS fallback: suppressed — descriptions contain no abstract content.
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
_PII_RE = re.compile(r"/pii/([A-Z0-9]+)", re.IGNORECASE)
_DOI_RE = re.compile(r"(10\.\d{4}/[^\s?#]+)")
_ERRATA_TITLES = ("erratum", "corrigendum", "correction", "retraction", "addendum")


def _clean_title(raw: str) -> str:
    """Strip HTML markup from RSS title (ScienceDirect uses <em>, <sub>, etc.)."""
    return BeautifulSoup(raw, "lxml").get_text(separator=" ", strip=True)


class ElsevierScraper(BaseScraper):
    # Specifies an additional domain-specific DB to query before OpenAlex.
    # Set to None in subclasses to use OpenAlex only.
    # Supported values: "inspire" | None
    SPECIFIC_DB: str | None = "inspire"

    def editorial_filter(self, entry) -> bool:
        title = getattr(entry, "title", "").lower()
        if any(t in title for t in _ERRATA_TITLES):
            return False
        return True

    def scrape_article(self, url: str, entry=None) -> dict:
        authors = self._extract_authors_from_description(entry)

        # Step 1: resolve PII → DOI via CrossRef
        doi = self._doi_from_pii(url) or self._doi_from_entry(entry)

        if doi:
            if self.SPECIFIC_DB == "inspire":
                # Step 2: INSPIRE-HEP by DOI (HEP journals only)
                abstract = self._fetch_inspirehep(f"doi {doi}")
                if abstract:
                    return {"abstract": abstract, "subject_tags": [], "skip_rss_fallback": True, "doi": doi, "authors": authors}
            # Step 3: OpenAlex by DOI
            abstract = self._fetch_abstract_openalex(doi)
            if abstract:
                return {"abstract": abstract, "subject_tags": [], "skip_rss_fallback": True, "doi": doi, "authors": authors}
            # No abstract found yet but DOI is resolved — return it so the bank can retry later
            return {"abstract": "", "subject_tags": [], "skip_rss_fallback": True, "doi": doi, "authors": authors}

        if self.SPECIFIC_DB == "inspire":
            # Step 4: INSPIRE-HEP title search (last resort; works for PLB)
            if entry is not None:
                title = _clean_title(getattr(entry, "title", ""))
                if title:
                    abstract = self._fetch_inspirehep(f't "{title}"')
                    if abstract:
                        return {"abstract": abstract, "subject_tags": [], "skip_rss_fallback": True, "authors": authors}

        return {"abstract": "", "subject_tags": [], "skip_rss_fallback": True, "authors": authors}

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

    def _extract_authors_from_description(self, entry) -> list[str]:
        """Parse 'Author(s): Name1, Name2, ...' from the ScienceDirect RSS description HTML."""
        if entry is None:
            return []
        raw = getattr(entry, "summary", "") or getattr(entry, "description", "")
        if not raw:
            return []
        soup = BeautifulSoup(raw, "lxml")
        for p in soup.find_all("p"):
            text = p.get_text(strip=True)
            if text.startswith("Author(s):"):
                names = text[len("Author(s):"):].strip()
                return [n.strip() for n in names.split(",") if n.strip()]
        return []

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


class ElsevierGeneralScraper(ElsevierScraper):
    """ElsevierScraper for general (non-HEP) Elsevier journals.

    Use publisher="elsevier_general" in fields.json.
    Abstract pipeline: CrossRef PII→DOI → OpenAlex (no domain-specific DB).
    """
    SPECIFIC_DB = None
