"""
scrapers/wiley.py — Scraper for Wiley / Wiley-VCH journals.

Covers: Advanced Materials, Advanced Functional Materials, Small, Nanophotonics,
and any other Wiley journal added to fields.json with publisher="wiley".

Abstract coverage: FULL — extracted directly from RSS feed.
  - Wiley RSS feeds include full abstracts in the dc:description element,
    exposed by feedparser as entry.content (type="text/plain").
  - No HTTP requests to article pages are needed.
  - Content format: "Short graphical abstract...\n\n\nABSTRACT\nFull text..."
    The scraper splits on "ABSTRACT" and takes the trailing portion.

Subject tags: not available → always []
"""

import logging

from .base import BaseScraper

log = logging.getLogger(__name__)

# prism_section values (uppercased) that are worth including
_KEEP_SECTIONS = {"RESEARCH ARTICLE", "REVIEW", "COMMUNICATION", "FULL PAPER",
                  "RESEARCH ARTICLES", "REVIEWS", "COMMUNICATIONS"}


class WileyScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        section = (getattr(entry, "prism_section", "") or "").strip().upper()
        if not section:
            # No section tag — include by default so we don't silently drop papers.
            return True
        return section in _KEEP_SECTIONS

    def scrape_article(self, url: str, entry=None) -> dict:
        if entry is not None:
            for item in entry.get("content") or []:
                if item.get("type") == "text/plain":
                    text = item["value"].strip()
                    # Extract the ABSTRACT section when present; otherwise use full text.
                    if "\nABSTRACT\n" in text:
                        abstract = text.split("\nABSTRACT\n", 1)[1].strip()
                    elif "ABSTRACT" in text:
                        abstract = text.split("ABSTRACT", 1)[1].strip()
                    else:
                        abstract = text
                    if abstract:
                        return {"abstract": abstract, "subject_tags": []}
        return {"abstract": "", "subject_tags": []}
