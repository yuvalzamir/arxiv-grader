"""
scrapers/aps.py — Scraper for APS journals (journals.aps.org).

Covers: PRL, PRB, PRX, PRX Quantum, and any future APS journal
added to fields.json with publisher="aps".

Editorial filter: keep URLs matching the abstract pattern; drop errata and publisher's notes.
Abstract: APS article pages are Cloudflare-protected (403) from server IPs, and
Semantic Scholar does not provide APS abstracts (licensing restriction). The RSS
feed contains a truncated abstract (~3 sentences) which is used via the caller's
fallback in fetch_journals.py.
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
        # APS pages are Cloudflare-blocked (403) and Semantic Scholar has no APS
        # abstracts due to licensing. Returning empty here lets fetch_journals.py
        # fall back to the truncated abstract in the RSS <description>.
        return {"abstract": "", "subject_tags": []}
