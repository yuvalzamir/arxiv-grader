"""
scrapers/sage.py — Scraper for SAGE Publications journals (journals.sagepub.com).

Abstract coverage: OpenAlex by DOI.
  - Sage RSS entries include DOI in the article link (10.1177/...).
  - Sage article pages are not scraped (Cloudflare-protected from server IPs).
  - RSS description contains only 1-2 sentence teasers — not full abstracts.
  - skip_rss_fallback=True to suppress the useless RSS description.

Subject tags: not available → always []
"""
import re
from .base import BaseScraper

_ERRATA = ("erratum", "corrigendum", "correction", "retraction")
_DOI_RE = re.compile(r"(10\.\d{4}/[^\s?#]+)")


class SageScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        return not any(t in getattr(entry, "title", "").lower() for t in _ERRATA)

    def scrape_article(self, url: str, entry=None) -> dict:
        m = _DOI_RE.search(url)
        if m:
            abstract = self._fetch_abstract_openalex(m.group(1))
            if abstract:
                return {"abstract": abstract, "subject_tags": [], "skip_rss_fallback": True}
        title = getattr(entry, "title", "") if entry is not None else ""
        abstract = self._fetch_abstract_semanticscholar(title)
        return {"abstract": abstract, "subject_tags": [], "skip_rss_fallback": True}
