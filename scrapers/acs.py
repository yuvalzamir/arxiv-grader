"""
scrapers/acs.py — Scraper for ACS (American Chemical Society) journals.

Covers: ACS Nano, ACS Photonics, ACS Sensors, and any future ACS journal
added to fields.json with publisher="acs".

ACS RSS entries include title, DOI link, and authors, but NO abstract text.
ACS article pages are Cloudflare-protected (403) from server IPs.
Neither Semantic Scholar nor CrossRef provides ACS abstracts due to licensing.

Result: abstract is always empty. Triage relies on title + authors only.
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


class ACSScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        title = getattr(entry, "title", "")
        if _SKIP_RE.search(title):
            return False
        return True

    def scrape_article(self, url: str, entry=None) -> dict:
        # ACS pages return 403 from server IPs; no free API provides ACS abstracts.
        # skip_rss_fallback=True prevents fetch_journals.py from using the RSS
        # <description> as the abstract — it contains only a TOC graphic and DOI text.
        return {"abstract": "", "subject_tags": [], "skip_rss_fallback": True}
