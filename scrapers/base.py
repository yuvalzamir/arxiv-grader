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
_CR_API_URL = "https://api.crossref.org/works/{doi}"
_S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
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

    @staticmethod
    def _fetch_metadata_openalex(doi: str) -> dict:
        """Return {title, abstract, authors} from OpenAlex. Missing fields are '' / []."""
        try:
            r = requests.get(
                _OPENALEX_API_URL.format(doi=doi),
                headers=_API_HEADERS,
                timeout=15,
            )
            if r.status_code != 200:
                log.debug("OpenAlex returned %d for DOI %s", r.status_code, doi)
                return {}
            data = r.json()
            title = data.get("title") or ""
            abstract = ""
            inv = data.get("abstract_inverted_index")
            if inv:
                abstract = BaseScraper._reconstruct_openalex_abstract(inv)
            authors = [
                a["author"]["display_name"]
                for a in data.get("authorships", [])
                if a.get("author", {}).get("display_name")
            ]
            return {"title": title, "abstract": abstract, "authors": authors}
        except Exception as exc:
            log.warning("OpenAlex request failed for DOI %s: %s", doi, exc)
            return {}

    def _fetch_abstract_openalex(self, doi: str) -> str:
        """Fetch abstract from OpenAlex by DOI. Returns "" on miss or error."""
        return self._fetch_metadata_openalex(doi).get("abstract", "")

    @staticmethod
    def _fetch_metadata_crossref(doi: str) -> dict:
        """Return {title, authors} from CrossRef. Used as title/author fallback."""
        try:
            r = requests.get(
                _CR_API_URL.format(doi=doi),
                headers=_API_HEADERS,
                timeout=15,
            )
            if r.status_code != 200:
                return {}
            msg = r.json().get("message", {})
            titles = msg.get("title", [])
            title = titles[0] if titles else ""
            authors = [
                " ".join(filter(None, [a.get("given", ""), a.get("family", "")]))
                for a in msg.get("author", [])
            ]
            return {"title": title, "authors": [a for a in authors if a]}
        except Exception as exc:
            log.debug("CrossRef metadata fetch failed for DOI %s: %s", doi, exc)
            return {}

    def _fetch_abstract_semanticscholar(self, title: str) -> str:
        """Fetch abstract from Semantic Scholar by title search. Returns "" on miss or error."""
        if not title:
            return ""
        try:
            r = requests.get(
                _S2_SEARCH_URL,
                params={"query": title, "fields": "abstract", "limit": 1},
                headers=_API_HEADERS,
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json().get("data", [])
                if data:
                    return data[0].get("abstract", "") or ""
            else:
                log.debug("Semantic Scholar returned %d for title '%s'", r.status_code, title[:60])
        except Exception as exc:
            log.warning("Semantic Scholar request failed for title '%s': %s", title[:60], exc)
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
