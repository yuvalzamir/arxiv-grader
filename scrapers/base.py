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
_S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
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

    def _fetch_abstract_openalex_title(self, title: str) -> str:
        """Fetch abstract from OpenAlex by title search. Returns "" on miss or error."""
        if not title:
            return ""
        try:
            r = requests.get(
                "https://api.openalex.org/works",
                params={"search": title, "per_page": 1, "select": "title,abstract_inverted_index"},
                headers=_API_HEADERS,
                timeout=15,
            )
            if r.status_code != 200:
                log.debug("OpenAlex title search returned %d for '%s'", r.status_code, title[:60])
                return ""
            results = r.json().get("results", [])
            if not results:
                return ""
            inv = results[0].get("abstract_inverted_index")
            if inv:
                return self._reconstruct_openalex_abstract(inv)
        except Exception as exc:
            log.warning("OpenAlex title search failed for '%s': %s", title[:60], exc)
        return ""

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

    @staticmethod
    def _fetch_abstracts_s2_batch(s2_ids: list[str], api_key: str = "") -> dict[str, str]:
        """POST up to 500 S2 IDs per chunk; returns {s2_id: abstract} for hits."""
        results: dict[str, str] = {}
        headers = dict(_API_HEADERS)
        if api_key:
            headers["x-api-key"] = api_key
        for i in range(0, len(s2_ids), 500):
            chunk = s2_ids[i:i + 500]
            try:
                r = requests.post(
                    _S2_BATCH_URL,
                    params={"fields": "abstract"},
                    json={"ids": chunk},
                    headers=headers,
                    timeout=30,
                )
                if r.status_code == 200:
                    for s2_id, item in zip(chunk, r.json()):
                        if item and item.get("abstract"):
                            results[s2_id] = item["abstract"]
                else:
                    log.warning("S2 batch returned %d for chunk of %d IDs", r.status_code, len(chunk))
            except Exception as exc:
                log.warning("S2 batch request failed: %s", exc)
        return results

    @staticmethod
    def enrich_missing_abstracts_s2(papers: list[dict], api_key: str = "") -> None:
        """Fill in missing abstracts from Semantic Scholar batch API (in-place)."""
        eligible = [p for p in papers if p["abstract_quality"] != "full" and p["arxiv_id"].startswith("10.")]
        if not eligible:
            return
        s2_ids = ["DOI:" + p["arxiv_id"] for p in eligible]
        hits = BaseScraper._fetch_abstracts_s2_batch(s2_ids, api_key)
        filled = 0
        for paper, s2_id in zip(eligible, s2_ids):
            abstract = hits.get(s2_id, "")
            if abstract and len(abstract) > len(paper["abstract"]):
                paper["abstract"] = abstract
                paper["abstract_quality"] = "full" if len(abstract) >= 400 else "truncated"
                filled += 1
        log.info("S2 batch: filled %d/%d missing abstracts", filled, len(eligible))

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
