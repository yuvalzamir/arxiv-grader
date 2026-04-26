"""
scrapers/edp.py — Scraper for EDP Sciences journals.

Covers: Astronomy & Astrophysics (A&A, aanda.org) and the European
Physical Journal C (EPJC, epjc.epj.org), both delivered via Feedburner
RSS. Any future EDP journal added to fields.json with publisher="edp"
will also use this scraper.

Abstract coverage: GOOD — scraped from open-access article pages.
  - Both A&A and EPJC are fully open access; article pages are publicly
    accessible without authentication.
  - A&A full-HTML page structure: <p class="bold">Abstract</p> followed
    by the abstract <p> sibling. No wrapper div/section.
  - EPJC uses generic div.abstract / section.abstract / div#abstract.
  - OpenAlex fallback: used when page fetch fails or yields no abstract
    (e.g. EPJC pages with unexpected HTML structure). OpenAlex has ~100%
    coverage for EPJC DOIs.
  - Final fallback: truncated RSS summary when both page fetch and
    OpenAlex return nothing.

DOI extraction: `10.XXXX/...` pattern from the article URL.

Subject tags: not available → always []
"""

import logging
import re

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper

log = logging.getLogger(__name__)

_ERRATA_TITLES = ("erratum", "corrigendum", "correction", "comment on", "reply to", "retraction")
_DOI_RE = re.compile(r"10\.\d{4}/")
_DOI_EXTRACT_RE = re.compile(r"(10\.\d{4}/[^\s?#]+)")
_LABEL_RE = re.compile(r"^(Abstract[:\s]*|ABSTRACT[:\s]*)", re.IGNORECASE)
_OPENALEX_URL = "https://api.openalex.org/works/doi:{doi}"
_HEADERS = {"User-Agent": "arxiv-grader/1.0 (mailto:contact@incomingscience.xyz)"}


def _reconstruct_openalex_abstract(inverted_index: dict) -> str:
    tokens: dict[int, str] = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            tokens[pos] = word
    return " ".join(tokens[i] for i in sorted(tokens))


class EDPScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        title = getattr(entry, "title", "").lower()
        if any(t in title for t in _ERRATA_TITLES):
            return False
        link = getattr(entry, "link", "")
        return bool(_DOI_RE.search(link))

    def scrape_article(self, url: str, entry=None) -> dict:
        response = self.get(url)
        if response is not None:
            soup = BeautifulSoup(response.text, "lxml")

            # A&A full-HTML structure: <p class="bold">Abstract</p> followed by
            # the abstract text in the next <p> sibling.
            for bold_p in soup.find_all("p", class_="bold"):
                if "abstract" in bold_p.get_text(strip=True).lower():
                    sibling = bold_p.find_next_sibling("p")
                    if sibling:
                        text = sibling.get_text(separator=" ", strip=True)
                        if len(text) > 50:
                            return {"abstract": text, "subject_tags": []}

            # Generic fallback selectors (EPJC and other EDP journals)
            for selector in ("div.abstract", "section.abstract", "div#abstract"):
                el = soup.select_one(selector)
                if el:
                    text = el.get_text(separator=" ", strip=True)
                    text = _LABEL_RE.sub("", text).strip()
                    if len(text) > 50:
                        return {"abstract": text, "subject_tags": []}

        # OpenAlex fallback — used when page fetch fails or yields no abstract
        # (covers EPJC and any other EDP journal with unexpected HTML structure).
        doi = self._doi_from_url(url)
        if doi:
            abstract = self._fetch_openalex(doi)
            if abstract:
                return {"abstract": abstract, "subject_tags": []}

        return {"abstract": "", "subject_tags": []}

    def _doi_from_url(self, url: str) -> str:
        m = _DOI_EXTRACT_RE.search(url)
        return m.group(1) if m else ""

    def _fetch_openalex(self, doi: str) -> str:
        try:
            r = requests.get(
                _OPENALEX_URL.format(doi=doi),
                headers=_HEADERS,
                timeout=15,
            )
            if r.status_code == 200:
                inverted = r.json().get("abstract_inverted_index")
                if inverted:
                    return _reconstruct_openalex_abstract(inverted)
            else:
                log.debug("OpenAlex returned %d for DOI %s", r.status_code, doi)
        except Exception as e:
            log.warning("OpenAlex request failed for DOI %s: %s", doi, e)
        return ""
