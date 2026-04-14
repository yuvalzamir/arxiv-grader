"""
scrapers/scholar.py — Google Scholar profile scraper for onboarding.

Fetches a user's publication list from their Google Scholar profile, resolves
each paper to a publisher URL via the Scholar citation detail page, and
fetches the abstract using citation meta tags (standard across most
publishers).  Falls back to OpenAlex title search when the publisher page is
inaccessible (Cloudflare-blocked APS/ACS, paywalled pages, etc.).

Public API:
    fetch_scholar_papers(profile_url, max_papers=60) -> list[dict]
    ScholarFetchError  — raised when the profile page itself cannot be loaded

Returned paper dicts are compatible with create_profile.py's liked_papers:
    {title, abstract, authors, url, arxiv_id}

Papers where no abstract could be resolved are still returned (title +
authors are sufficient for the profile creator's author-frequency signal).
"""

import logging
import random
import re
import time

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}
_SCHOLAR_BASE   = "https://scholar.google.com"
_OPENALEX_URL   = "https://api.openalex.org/works"
_OPENALEX_HDR   = {"User-Agent": "arxiv-grader/1.0 (mailto:contact@incomingscience.xyz)"}
_REQUEST_DELAY  = 1.5   # seconds between Scholar requests
_HTML_CAP       = 200_000


class ScholarFetchError(Exception):
    """Raised when the Scholar profile page itself cannot be fetched."""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def fetch_scholar_papers(profile_url: str, max_papers: int = 60) -> list[dict]:
    """
    Fetch and resolve papers from a Google Scholar profile URL.

    Returns a list of paper dicts: {title, abstract, authors, url, arxiv_id}.
    Papers with unresolvable abstracts are included with abstract=''.
    Raises ScholarFetchError if the profile page cannot be fetched.
    """
    rows = _fetch_profile_rows(profile_url)
    if not rows:
        log.info("Scholar profile returned 0 papers.")
        return []

    if len(rows) > max_papers:
        rows = random.sample(rows, max_papers)
    log.info("Resolving %d Scholar papers...", len(rows))

    papers = []
    for i, row in enumerate(rows):
        paper = _resolve_paper(row)
        papers.append(paper)
        if i < len(rows) - 1:
            time.sleep(_REQUEST_DELAY)

    resolved = sum(1 for p in papers if p["abstract"])
    log.info("Scholar import done: %d/%d papers have abstracts.", resolved, len(papers))
    return papers


# ---------------------------------------------------------------------------
# Step 1 — fetch Scholar profile page
# ---------------------------------------------------------------------------

def _fetch_profile_rows(profile_url: str) -> list[dict]:
    """
    Fetch the Scholar profile page and parse paper rows.
    Raises ScholarFetchError on HTTP error or CAPTCHA.
    """
    url = _normalise_profile_url(profile_url)
    log.info("Fetching Scholar profile: %s", url)
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20)
    except Exception as exc:
        raise ScholarFetchError(f"Request failed: {exc}") from exc

    if resp.status_code != 200:
        raise ScholarFetchError(f"HTTP {resp.status_code} fetching Scholar profile.")

    text = resp.text
    if "captcha" in text.lower() or "unusual traffic" in text.lower():
        raise ScholarFetchError("Google Scholar returned a CAPTCHA page.")

    soup = BeautifulSoup(text[:_HTML_CAP], "lxml")
    rows = soup.select("tr.gsc_a_tr")
    if not rows:
        return []

    results = []
    for row in rows:
        title_el = row.select_one("a.gsc_a_at")
        if not title_el:
            continue
        title         = title_el.get_text(strip=True)
        citation_path = title_el.get("href", "")
        grey          = row.select(".gs_gray")
        authors_str   = grey[0].get_text(strip=True) if grey else ""
        year_el       = row.select_one(".gsc_a_y span")
        year          = year_el.get_text(strip=True) if year_el else ""
        results.append({
            "title":         title,
            "authors_str":   authors_str,
            "year":          year,
            "citation_path": citation_path,
        })

    log.info("Found %d papers on Scholar profile.", len(results))
    return results


def _normalise_profile_url(url: str) -> str:
    sep = "&" if "?" in url else "?"
    if "pagesize=" not in url:
        url += f"{sep}pagesize=100"
        sep = "&"
    if "sortby=" not in url:
        url += f"{sep}sortby=pubdate"
    return url


# ---------------------------------------------------------------------------
# Step 2 — resolve one paper (citation page → publisher URL → abstract)
# ---------------------------------------------------------------------------

def _resolve_paper(row: dict) -> dict:
    title    = row["title"]
    authors  = _split_authors(row.get("authors_str", ""))
    arxiv_id = ""
    pub_url  = ""

    citation_path = row.get("citation_path", "")
    if citation_path:
        pub_url, arxiv_id = _resolve_citation_page(citation_path)

    # Fetch abstract
    abstract = ""
    if arxiv_id:
        abstract = _fetch_arxiv_abstract(arxiv_id)
        if not pub_url:
            pub_url = f"https://arxiv.org/abs/{arxiv_id}"
    elif pub_url:
        abstract = _fetch_publisher_abstract(pub_url)

    # OpenAlex fallback
    if not abstract and title:
        abstract = _openalex_fallback(title)

    return {
        "title":    title,
        "abstract": abstract,
        "authors":  authors,
        "url":      pub_url,
        "arxiv_id": arxiv_id,
    }


# ---------------------------------------------------------------------------
# Step 2a — Scholar citation detail page → publisher URL
# ---------------------------------------------------------------------------

def _resolve_citation_page(citation_path: str) -> tuple[str, str]:
    """
    Fetch the Scholar citation detail page and extract the publisher URL.
    Returns (publisher_url, arxiv_id); either may be empty string.
    """
    url = _SCHOLAR_BASE + citation_path
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20)
        if resp.status_code != 200:
            log.debug("Citation page HTTP %d: %s", resp.status_code, url)
            return "", ""
    except Exception as exc:
        log.debug("Citation page fetch failed: %s", exc)
        return "", ""

    soup = BeautifulSoup(resp.text[:_HTML_CAP], "lxml")
    link_el = soup.select_one("#gsc_oci_title a")
    if not link_el:
        return "", ""

    href = link_el.get("href", "")
    if not href:
        return "", ""

    if href.startswith("/"):
        href = _SCHOLAR_BASE + href

    arxiv_id = _arxiv_id_from_url(href)
    return href, arxiv_id


def _arxiv_id_from_url(url: str) -> str:
    m = re.search(
        r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)",
        url, re.IGNORECASE,
    )
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# Abstract fetchers
# ---------------------------------------------------------------------------

def _fetch_arxiv_abstract(arxiv_id: str) -> str:
    """Fetch abstract from the arXiv Atom API."""
    clean_id = re.sub(r"v\d+$", "", arxiv_id)
    try:
        resp = requests.get(
            f"https://export.arxiv.org/api/query?id_list={clean_id}",
            timeout=15,
        )
        if resp.status_code == 200:
            m = re.search(r"<summary[^>]*>(.*?)</summary>", resp.text, re.DOTALL)
            if m:
                return re.sub(r"\s+", " ", m.group(1)).strip()
    except Exception as exc:
        log.debug("arXiv API fetch failed for %s: %s", arxiv_id, exc)
    return ""


def _fetch_publisher_abstract(url: str) -> str:
    """
    Fetch abstract from a publisher page via citation meta tags.
    Same parsing logic as create_profile.fetch_journal_paper.
    """
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20)
        if resp.status_code != 200:
            log.debug("Publisher page HTTP %d: %s", resp.status_code, url)
            return ""
        html = resp.text[:_HTML_CAP]
    except Exception as exc:
        log.debug("Publisher page fetch failed %s: %s", url, exc)
        return ""

    m = re.search(
        r'<meta\s[^>]*name=["\']citation_abstract["\'][^>]*content=["\'](.*?)["\']',
        html, re.IGNORECASE | re.DOTALL,
    )
    if m:
        return m.group(1).strip()

    m = re.search(
        r'<meta[^>]*name=["\']description["\'][^>]*content=["\'](.*?)["\']',
        html, re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    return ""


def _openalex_fallback(title: str) -> str:
    """Search OpenAlex by title; reconstruct abstract from inverted index."""
    try:
        resp = requests.get(
            _OPENALEX_URL,
            params={"search": title, "filter": "type:article", "per_page": 3},
            headers=_OPENALEX_HDR,
            timeout=15,
        )
        if resp.status_code != 200:
            return ""
        for result in resp.json().get("results", []):
            if _title_match(title, result.get("title", "")):
                inverted = result.get("abstract_inverted_index")
                if inverted:
                    return _reconstruct_abstract(inverted)
    except Exception as exc:
        log.debug("OpenAlex fallback failed for %r: %s", title[:50], exc)
    return ""


def _reconstruct_abstract(inverted_index: dict) -> str:
    tokens: dict[int, str] = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            tokens[pos] = word
    return " ".join(tokens[i] for i in sorted(tokens))


def _title_match(a: str, b: str) -> bool:
    """Loose normalised title match (handles truncated Scholar titles)."""
    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9 ]", "", s.lower().strip())
    na, nb = norm(a), norm(b)
    if na == nb:
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    return len(shorter) > 10 and longer.startswith(shorter[:40])


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _split_authors(authors_str: str) -> list[str]:
    """
    Parse Scholar author string 'A Name, B Name, ... - Journal, Year'
    into a clean list of names.
    """
    if not authors_str:
        return []
    # Strip journal/year suffix after the last ' - '
    parts = authors_str.rsplit(" - ", 1)
    names_part = parts[0]
    return [n.strip() for n in names_part.split(",") if n.strip()]
