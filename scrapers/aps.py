"""
scrapers/aps.py — Scraper for APS journals via harvest.aps.org Harvest API.

Covers: PRL, PRB, PRX, PRX Quantum, and any future APS journal
added to fields.json with publisher="aps".

Abstract coverage: FULL for all APS journals without authentication — confirmed
  for PRL, PRB, PRX, PRX Quantum, PRMaterials via unauthenticated Harvest API.
  APS_API_KEY env var is supported for future use but not currently required.

Subject tags: parsed from classificationSchemes.subjectAreas in Harvest API response.
"""

import logging
import os
import re

from bs4 import BeautifulSoup

from .base import BaseScraper

log = logging.getLogger(__name__)

_HARVEST_API = "http://harvest.aps.org/v2/journals/articles/{doi}"
APS_API_KEY = os.environ.get("APS_API_KEY", "")

# APS uses two URL formats:
#   legacy:  http://journals.aps.org/prl/abstract/10.1103/PhysRevLett.XXX.XXXXXX
#   current: http://link.aps.org/doi/10.1103/fgh1-gq8p
_DOI_RE = re.compile(r"10\.\d{4}/[^\s?#]+")
_ERRATA_TITLES = ("erratum", "publisher's note")
_ABSTRACT_URL_RE = re.compile(
    r"(journals\.aps\.org/.*/abstract/10\.\d{4}/|link\.aps\.org/doi/10\.\d{4}/)"
)


def _doi_from_url(url: str) -> str:
    """Extract DOI (10.XXXX/...) from an APS article URL. Returns '' if not found."""
    m = _DOI_RE.search(url)
    return m.group(0) if m else ""


class APSScraper(BaseScraper):

    def editorial_filter(self, entry) -> bool:
        url = getattr(entry, "link", "")
        if not _ABSTRACT_URL_RE.search(url):
            return False
        title = getattr(entry, "title", "").lower()
        if any(t in title for t in _ERRATA_TITLES):
            return False
        return True

    def scrape_article(self, url: str, entry=None) -> dict:
        doi = _doi_from_url(url)
        if not doi:
            return {"abstract": "", "subject_tags": []}

        headers = {
            "Accept": "application/vnd.tesseract.article+json",
            "User-Agent": (
                "IncomingScience-Bot/1.0 (automated academic digest; "
                "https://incomingscience.xyz; not-for-profit; contact@incomingscience.xyz)"
            ),
        }
        if APS_API_KEY:
            headers["Authorization"] = f"Bearer {APS_API_KEY}"

        try:
            resp = self._session.get(
                _HARVEST_API.format(doi=doi),
                headers=headers,
                timeout=15,
            )
        except Exception as exc:
            log.warning("Harvest API request failed for DOI %s: %s", doi, exc)
            return {"abstract": "", "subject_tags": []}

        if resp.status_code != 200:
            log.debug("Harvest API returned %d for DOI %s", resp.status_code, doi)
            return {"abstract": "", "subject_tags": []}

        try:
            data = resp.json().get("data", {})
            raw_abstract = data.get("abstract", {}).get("value", "") or ""
            abstract = BeautifulSoup(raw_abstract, "lxml").get_text(separator=" ", strip=True) if raw_abstract else ""
            subject_areas = (
                data.get("classificationSchemes", {}).get("subjectAreas", []) or []
            )
            subject_tags = [item["label"] for item in subject_areas if item.get("label")]
        except Exception as exc:
            log.warning("Harvest API parse error for DOI %s: %s", doi, exc)
            return {"abstract": "", "subject_tags": []}

        return {"abstract": abstract, "subject_tags": subject_tags}
