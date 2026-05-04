"""
scrapers/tandfonline.py — Scraper for Taylor & Francis (tandfonline.com) journals.

Abstract coverage: OpenAlex by DOI.
  - T&F RSS entries include DOI in the article link (10.1080/...).
  - T&F article pages are not scraped (Cloudflare-protected from server IPs).
  - RSS description contains only volume/issue/page metadata — no abstract.
  - skip_rss_fallback=True to suppress the useless RSS description.

Subject tags: not available → always []
"""
import re
from .base import BaseScraper

_ERRATA = ("erratum", "corrigendum", "correction", "retraction")
_DOI_RE = re.compile(r"(10\.\d{4}/[^\s?#]+)")


class TandfonlineScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        return not any(t in getattr(entry, "title", "").lower() for t in _ERRATA)

    def scrape_article(self, url: str, entry=None) -> dict:
        m = _DOI_RE.search(url)
        if m:
            abstract = self._fetch_abstract_openalex(m.group(1))
            if abstract:
                return {"abstract": abstract, "subject_tags": [], "skip_rss_fallback": True}
        # Semantic Scholar title-search fallback for papers not yet in OpenAlex.
        title = getattr(entry, "title", "") if entry is not None else ""
        abstract = self._fetch_abstract_semanticscholar(title)
        return {"abstract": abstract, "subject_tags": [], "skip_rss_fallback": True}
