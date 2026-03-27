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

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; arxiv-grader/1.0)"}
REQUEST_TIMEOUT = 15
SLEEP_BETWEEN_REQUESTS = 1.5


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

    @abstractmethod
    def editorial_filter(self, entry) -> bool:
        """Return True if the RSS entry is a research article worth scraping."""

    @abstractmethod
    def scrape_article(self, url: str) -> dict:
        """
        Fetch the article page and return:
            {"abstract": str, "subject_tags": list[str]}
        Return None to signal the entry is not a research article and should be skipped.
        On fetch failure, return {"abstract": "", "subject_tags": []}.
        """
