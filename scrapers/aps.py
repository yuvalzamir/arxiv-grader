"""
scrapers/aps.py — Scraper for APS journals (journals.aps.org).

Covers: PRL, PRB, PRX, PRX Quantum, and any future APS journal
added to fields.json with publisher="aps".

Abstract coverage: PARTIAL — truncated RSS abstract only (~2-3 sentences).
  - Article pages: Cloudflare-blocked (403) from server IPs (IP-based block,
    not TLS fingerprint — curl-cffi Chrome impersonation confirmed ineffective).
  - Semantic Scholar: no APS abstracts (APS licensing restriction).
  - CrossRef / OpenAlex: no abstracts deposited by APS.
  - Unpaywall/arXiv preprint: ~4% hit rate on real pipeline data (PRB-heavy).
  - RSS fallback: ~2-3 sentence truncation, sufficient for triage.
  Possible future improvement: ICFO institutional APS access (IP whitelist
  or API token) — check with library.

Subject tags: not available → always []
"""

import logging
import re

from .base import BaseScraper

log = logging.getLogger(__name__)

# APS uses two URL formats:
#   legacy:  http://journals.aps.org/prl/abstract/10.1103/PhysRevLett.XXX.XXXXXX
#   current: http://link.aps.org/doi/10.1103/fgh1-gq8p
_ABSTRACT_URL_RE = re.compile(
    r"(journals\.aps\.org/.*/abstract/10\.\d{4}/|link\.aps\.org/doi/10\.\d{4}/)"
)
_ERRATA_TITLES = ("erratum", "publisher's note")


class APSScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        url = getattr(entry, "link", "")
        if not _ABSTRACT_URL_RE.search(url):
            return False
        title = getattr(entry, "title", "").lower()
        if any(t in title for t in _ERRATA_TITLES):
            return False
        return True

    def scrape_article(self, url: str, entry=None) -> dict:
        # APS pages are Cloudflare-blocked (403) from datacenter IPs — IP-based,
        # not TLS fingerprint. Returning empty lets fetch_journals.py fall back
        # to the truncated abstract in the RSS <description>.
        return {"abstract": "", "subject_tags": []}
