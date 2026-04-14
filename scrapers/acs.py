"""
scrapers/acs.py — Scraper for ACS (American Chemical Society) journals.

Covers: ACS Nano, ACS Photonics, ACS Sensors, Nano Letters, and any future
ACS journal added to fields.json with publisher="acs".

Abstract coverage: Europe PMC API (~93–95% hit rate for NanoLett, ACSNano,
ACSSensors; 0% for ACSPhotonics which is not indexed by Europe PMC).
  - Article pages: Cloudflare-protected (403) from server IPs.
  - Semantic Scholar: no ACS abstracts (ACS licensing restriction).
  - CrossRef: no abstracts deposited by ACS.
  - RSS feed: description contains only a TOC graphic URL and DOI text —
    skip_rss_fallback=True prevents fetch_journals.py from using it.
  - Europe PMC: queried by DOI; returns full abstract for most ACS journals.
    ACSPhotonics (acs.photonics.*) is not indexed — skipped to avoid wasted calls.

Subject tags: not available → always []
"""

import logging
import re

import requests

from .base import BaseScraper

log = logging.getLogger(__name__)

# ACS titles that signal non-research content (case-insensitive)
_SKIP_RE = re.compile(
    r"\b(correction to|additions and corrections|erratum|retraction of|author correction)\b",
    re.IGNORECASE,
)

_DOI_RE = re.compile(r"(10\.1021/[^\s?#]+)")

# ACS journal DOI prefixes not indexed by Europe PMC — skip to avoid wasted calls
_EUROPEPMC_SKIP_PREFIXES = ("10.1021/acsphotonics.",)

_EUROPEPMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_EUROPEPMC_HEADERS = {"User-Agent": "arxiv-grader/1.0 (mailto:contact@incomingscience.xyz)"}


class ACSScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        title = getattr(entry, "title", "")
        if _SKIP_RE.search(title):
            return False
        return True

    def scrape_article(self, url: str, entry=None) -> dict:
        # ACS article pages return 403 from server IPs; use Europe PMC by DOI.
        # skip_rss_fallback=True prevents fetch_journals.py from using the RSS
        # <description> as the abstract — it contains only a TOC graphic and DOI text.
        doi = self._doi_from_url(url)
        if doi and not any(doi.startswith(p) for p in _EUROPEPMC_SKIP_PREFIXES):
            abstract = self._fetch_europepmc(doi)
            if abstract:
                return {"abstract": abstract, "subject_tags": [], "skip_rss_fallback": True}
        return {"abstract": "", "subject_tags": [], "skip_rss_fallback": True}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _doi_from_url(self, url: str) -> str:
        m = _DOI_RE.search(url)
        return m.group(1) if m else ""

    def _fetch_europepmc(self, doi: str) -> str:
        try:
            r = requests.get(
                _EUROPEPMC_URL,
                params={"query": f"DOI:{doi}", "format": "json", "resultType": "core"},
                headers=_EUROPEPMC_HEADERS,
                timeout=15,
            )
            if r.status_code == 200:
                results = r.json().get("resultList", {}).get("result", [])
                if results:
                    return results[0].get("abstractText", "")
            else:
                log.debug("Europe PMC returned %d for DOI %s", r.status_code, doi)
        except Exception as exc:
            log.warning("Europe PMC request failed for DOI %s: %s", doi, exc)
        return ""
