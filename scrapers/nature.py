"""
scrapers/nature.py — Scraper for Nature Portfolio journals (nature.com).

Covers: Nature, Nature Physics, Nature Materials, Nature Nanotechnology,
Nature Communications, Nature Computational Science, and any future Nature
journal added to fields.json with publisher="nature".

Abstract coverage: FULL — scraped from article pages.
  - Article pages: accessible (no Cloudflare block from server IPs).
  - Selector: div#Abs1-content p — confirmed on all Nature Portfolio journals.
  - Returns None (skip entry) when no abstract section is found, which
    signals News, Views, and other non-research content.
  - ~45 HTTP requests saved per run by pre-filtering d41586 DOI prefix
    (Nature main news/views) in editorial_filter before any page fetch.

Subject tags: meta[name="dc.subject"] — full subject taxonomy from article pages.
Authors: meta[name="citation_author"] — complete author list from article pages.
"""

import logging

from bs4 import BeautifulSoup

from .base import BaseScraper

log = logging.getLogger(__name__)


class NatureScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        url = getattr(entry, "link", "")
        if "/articles/" not in url:
            return False
        # Nature main news/views/comments use the d41586 DOI prefix.
        # Research articles use journal-specific prefixes (s41586, s41567, etc.).
        # Dropping d41586 saves ~47 unnecessary page fetches per run.
        if "d41586" in url:
            return False
        return True

    def scrape_article(self, url: str, entry=None) -> dict | None:
        response = self.get(url)
        if response is None:
            return {"abstract": "", "subject_tags": []}
        soup = BeautifulSoup(response.text, "lxml")
        paragraphs = soup.select("div#Abs1-content p")
        if not paragraphs:
            # No abstract section — this is a News, Views, Retraction, or other
            # non-research content. Signal the caller to skip this entry.
            return None
        abstract = " ".join(p.get_text(strip=True) for p in paragraphs)
        subject_tags = [
            m.get("content", "")
            for m in soup.find_all("meta", {"name": "dc.subject"})
            if m.get("content")
        ]
        authors = [
            m.get("content", "")
            for m in soup.find_all("meta", {"name": "citation_author"})
            if m.get("content")
        ]
        return {"abstract": abstract, "subject_tags": subject_tags, "authors": authors}
