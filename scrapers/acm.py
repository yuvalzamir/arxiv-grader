"""
scrapers/acm.py — Scraper for ACM Digital Library journals.

Covers: ACM TIST, and any future ACM journal added to fields.json
with publisher="acm".

Inherits SpringerScraper for editorial_filter, _doi_from_url, and
_fetch_by_doi. Overrides:
  - _doi_from_entry: ACM feeds have no prism:doi — always return "".
  - scrape_article: URL-only DOI extraction; no RSS fallback (ACM
    descriptions contain only volume/issue/page metadata, not abstracts).

Abstract coverage: OpenAlex (good for ACM TIST).
Subject tags: not available → always []
"""

from .springer import SpringerScraper


class ACMScraper(SpringerScraper):

    def _doi_from_entry(self, entry) -> str:
        """ACM feeds have no prism:doi — DOI is always taken from the URL."""
        return ""

    def scrape_article(self, url: str, entry=None) -> dict:
        doi = self._doi_from_url(url)
        if doi:
            return self._fetch_by_doi(doi)
        return {"abstract": "", "subject_tags": []}
