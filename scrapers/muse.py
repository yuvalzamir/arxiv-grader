"""
scrapers/muse.py — Scraper for Project MUSE journals.

RSS URL: https://muse.jhu.edu/feeds/latest_articles?jid=<journal_id>

Abstract coverage: Semantic Scholar by title.
  - MUSE RSS entries link to muse.jhu.edu/article/<id> — no DOI in URL or feed.
  - MUSE article pages are CAPTCHA-blocked from server IPs.
  - Semantic Scholar title-search: reasonable hit rate for major humanities journals.
  - skip_rss_fallback=True (RSS descriptions contain only article IDs, not text).

Subject tags: not available → always []
"""
from .base import BaseScraper

_ERRATA = ("erratum", "corrigendum", "correction", "retraction")


class MuseScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        return not any(t in getattr(entry, "title", "").lower() for t in _ERRATA)

    def scrape_article(self, url: str, entry=None) -> dict:
        title = getattr(entry, "title", "") if entry is not None else ""
        abstract = self._fetch_abstract_semanticscholar(title)
        return {"abstract": abstract, "subject_tags": [], "skip_rss_fallback": True}
