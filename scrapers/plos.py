"""
scrapers/plos.py — Scraper for PLOS (Public Library of Science) journals.

Covers: PLOS Computational Biology, and any future PLOS journal added to
fields.json with publisher="plos".

PLOS is fully open access. Full abstracts are included in the RSS
<description> field as HTML. No HTTP requests to article pages are needed.

Editorial filter: skip corrections, retractions, and expressions of concern
by title. The feed is otherwise research-article-only.
"""

import logging
import re

from bs4 import BeautifulSoup

from .base import BaseScraper

log = logging.getLogger(__name__)

# PLOS titles that signal non-research content (case-insensitive)
_SKIP_RE = re.compile(
    r"\b(correction|retraction|expression of concern|erratum|corrigendum)\b",
    re.IGNORECASE,
)


class PlosScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        title = getattr(entry, "title", "")
        if _SKIP_RE.search(title):
            return False
        return True

    def scrape_article(self, url: str, entry=None) -> dict:
        if entry is not None:
            summary = getattr(entry, "summary", "")
            if summary:
                soup = BeautifulSoup(summary, "lxml")
                # PLOS RSS summaries begin with a <p>by Author1, Author2...</p>
                # followed by the abstract as plain text. Strip that author paragraph.
                first_p = soup.find("p")
                if first_p and first_p.get_text(strip=True).lower().startswith("by "):
                    first_p.decompose()
                abstract = soup.get_text(separator=" ", strip=True)
                if abstract:
                    # Signal the caller not to re-apply the RSS fallback, since
                    # we already extracted the abstract from the same summary field.
                    return {"abstract": abstract, "subject_tags": [], "skip_rss_fallback": True}
        return {"abstract": "", "subject_tags": []}
