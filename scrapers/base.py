"""
scrapers/base.py — Abstract base class for publisher scrapers.

Each publisher subclass must implement:
  - editorial_filter(entry)  → bool
  - scrape_article(url)      → {"abstract": str, "subject_tags": list[str]}
"""

import time
import logging
from abc import ABC, abstractmethod

import requests

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
REQUEST_TIMEOUT = 15
SLEEP_BETWEEN_REQUESTS = 1.5

_OPENALEX_API_URL = "https://api.openalex.org/works/doi:{doi}"
_EUROPEPMC_API_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_API_HEADERS = {"User-Agent": "arxiv-grader/1.0 (mailto:contact@incomingscience.xyz)"}


class BaseScraper(ABC):

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def get(self, url: str) -> requests.Response | None:
        """GET a URL, returning the response or None on failure."""
        try:
            response = self._session.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            time.sleep(SLEEP_BETWEEN_REQUESTS)
            return response
        except Exception as e:
            log.warning("HTTP error fetching %s: %s", url, e)
            return None

    @staticmethod
    def _reconstruct_openalex_abstract(inverted_index: dict) -> str:
        """Reconstruct plain-text abstract from OpenAlex abstract_inverted_index."""
        tokens: dict[int, str] = {}
        for word, positions in inverted_index.items():
            for pos in positions:
                tokens[pos] = word
        return " ".join(tokens[i] for i in sorted(tokens))

    def _fetch_abstract_openalex(self, doi: str) -> str:
        """Fetch abstract from OpenAlex by DOI. Returns "" on miss or error."""
        try:
            r = requests.get(
                _OPENALEX_API_URL.format(doi=doi),
                headers=_API_HEADERS,
                timeout=15,
            )
            if r.status_code == 200:
                inverted = r.json().get("abstract_inverted_index")
                if inverted:
                    return self._reconstruct_openalex_abstract(inverted)
            else:
                log.debug("OpenAlex returned %d for DOI %s", r.status_code, doi)
        except Exception as e:
            log.warning("OpenAlex request failed for DOI %s: %s", doi, e)
        return ""

    def _fetch_abstract_europepmc(self, doi: str) -> str:
        """Fetch abstract from Europe PMC by DOI. Returns "" on miss or error."""
        try:
            r = requests.get(
                _EUROPEPMC_API_URL,
                params={"query": f"DOI:{doi}", "format": "json", "resultType": "core"},
                headers=_API_HEADERS,
                timeout=15,
            )
            if r.status_code == 200:
                results = r.json().get("resultList", {}).get("result", [])
                if results:
                    return results[0].get("abstractText", "") or ""
            else:
                log.debug("Europe PMC returned %d for DOI %s", r.status_code, doi)
        except Exception as exc:
            log.warning("Europe PMC request failed for DOI %s: %s", doi, exc)
        return ""

    @abstractmethod
    def editorial_filter(self, entry) -> bool:
        """Return True if the RSS entry is a research article worth scraping."""

    @abstractmethod
    def scrape_article(self, url: str, entry=None) -> dict:
        """
        Fetch the article page and return:
            {"abstract": str, "subject_tags": list[str]}
        The RSS feed entry is passed as `entry` (feedparser dict) when available;
        scrapers that can extract data from the RSS itself should use it to avoid
        an extra HTTP request.
        Return None to signal the entry is not a research article and should be skipped.
        On fetch failure, return {"abstract": "", "subject_tags": []}.
        """
