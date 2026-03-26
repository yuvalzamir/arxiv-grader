"""
scrapers/nature.py — Scraper for Nature Portfolio journals (nature.com).

Covers: Nature, Nature Physics, Nature Materials, Nature Nanotechnology,
Nature Communications, and any future Nature journal added to fields.json
with publisher="nature".

Editorial filter: keep URLs containing /articles/; this excludes /news/,
/comment/, /correspondence/, /perspective/, etc.
Abstract selector: div#Abs1-content p
Subject tags: meta[name="dc.subject"] — confirmed present on nature.com article pages.
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

    def scrape_article(self, url: str) -> dict | None:
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
        return {"abstract": abstract, "subject_tags": subject_tags}
