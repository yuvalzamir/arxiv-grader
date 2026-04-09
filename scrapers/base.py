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
