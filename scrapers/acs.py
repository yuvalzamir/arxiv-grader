"""
scrapers/acs.py — Scraper for ACS (American Chemical Society) journals.

Covers: ACS Nano, ACS Photonics, ACS Sensors, Nano Letters, Langmuir,
Macromolecules, Biomacromolecules, and any future ACS journal added to
fields.json with publisher="acs".

Abstract coverage: Europe PMC API with OpenAlex fallback.
  - Article pages: Cloudflare-protected (403) from server IPs.
  - Semantic Scholar: no ACS abstracts (ACS licensing restriction).
  - CrossRef: no abstracts deposited by ACS.
  - RSS feed: description contains only a TOC graphic URL and DOI text —
    skip_rss_fallback=True prevents fetch_journals.py from using it.
  - Europe PMC: queried by DOI; high hit rate for NanoLett, ACSNano,
    ACSSensors, Langmuir, Biomacromolecules. ACSPhotonics not indexed.
  - OpenAlex: fallback when Europe PMC returns nothing. Covers journals
    not indexed by Europe PMC (e.g. Macromolecules), with a few-week
    indexing lag for very recent papers.

Subject tags: not available → always []
"""

import logging
import re

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


class ACSScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        title = getattr(entry, "title", "")
        if _SKIP_RE.search(title):
            return False
        return True

    def scrape_article(self, url: str, entry=None) -> dict:
        # ACS article pages return 403 from server IPs; use Europe PMC then
        # OpenAlex as fallback. skip_rss_fallback=True prevents fetch_journals.py
        # from using the RSS <description> — it contains only a TOC graphic and DOI text.
        doi = self._doi_from_url(url)
        if doi:
            if not any(doi.startswith(p) for p in _EUROPEPMC_SKIP_PREFIXES):
                abstract = self._fetch_abstract_europepmc(doi)
                if abstract:
                    return {"abstract": abstract, "subject_tags": [], "skip_rss_fallback": True}
            abstract = self._fetch_abstract_openalex(doi)
            if abstract:
                return {"abstract": abstract, "subject_tags": [], "skip_rss_fallback": True}
        return {"abstract": "", "subject_tags": [], "skip_rss_fallback": True}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _doi_from_url(self, url: str) -> str:
        m = _DOI_RE.search(url)
        return m.group(1) if m else ""

