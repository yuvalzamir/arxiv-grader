"""
scrapers/sources.py — Journal-level paper-list fetching.

Three strategies, all returning (papers: list[dict], max_date: date | None):
  fetch_from_rss(journal, since, scrapers)   — RSS feed + publisher scraper
  fetch_from_openalex(journal, since)        — OpenAlex API by journal ISSN
  fetch_from_crossref(journal, since)        — CrossRef API by journal ISSN

Public entry point:
  fetch_journal(journal, since, scrapers)    — dispatches to the right strategy
  journal_key(journal)                       — watermark/dedup key for a journal
"""

import logging
import re
from datetime import date, timedelta

import feedparser
import requests
from bs4 import BeautifulSoup

from scrapers.base import HEADERS

log = logging.getLogger(__name__)

_OPENALEX_WORKS_URL   = "https://api.openalex.org/works"
_OPENALEX_HEADERS     = {"User-Agent": "arxiv-grader/1.0 (mailto:contact@incomingscience.xyz)"}
_CROSSREF_JOURNAL_URL = "https://api.crossref.org/journals/{issn}/works"
_CROSSREF_HEADERS     = {"User-Agent": "arxiv-grader/1.0 (mailto:contact@incomingscience.xyz)"}
_JATS_TAG_RE          = re.compile(r"</?jats:[^>]+>")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _entry_date(entry) -> date | None:
    """Return the publication date of an RSS entry, or None if unavailable.

    Some publishers (PNAS) carry both an online-first date (updated/published)
    and a prism:coverDate (official issue date). The cover date is always the
    later of the two for batch-released journals, so we take the maximum to
    ensure the watermark advances to the issue date on first scrape.
    """
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    pub_date = date(parsed.tm_year, parsed.tm_mon, parsed.tm_mday) if parsed else None

    cover_date = None
    cover_str = getattr(entry, "prism_coverdate", None)
    if cover_str:
        try:
            cover_date = date.fromisoformat(cover_str[:10])
        except ValueError:
            pass

    candidates = [d for d in (pub_date, cover_date) if d is not None]
    return max(candidates) if candidates else None


def _parse_authors(entry) -> list[str]:
    """Extract author names from an RSS entry."""
    if hasattr(entry, "authors") and entry.authors:
        names = [a.get("name", "") for a in entry.authors if a.get("name")]
        if len(names) > 1:
            return names
        if names:
            return _split_author_string(names[0])
    if hasattr(entry, "author") and entry.author:
        return _split_author_string(entry.author)
    return []


def _split_author_string(s: str) -> list[str]:
    """Split 'A, B, C, and D' or 'A and B' into ['A', 'B', 'C', 'D']."""
    s = re.sub(r",?\s+and\s+", ", ", s)
    return [name.strip() for name in s.split(",") if name.strip()]


def _extract_doi(entry) -> str:
    """Best-effort DOI extraction from an RSS entry."""
    dc_id = getattr(entry, "dc_identifier", "")
    if dc_id and dc_id.startswith("10."):
        return dc_id

    for attr in ("id", "link"):
        val = getattr(entry, attr, "")
        if val.startswith("10."):
            return val.split("?")[0].split("#")[0]
        if "/10." in val:
            doi = "10." + val.split("/10.", 1)[1]
            return doi.split("?")[0].split("#")[0]
    return ""


def _reconstruct_abstract(inverted_index: dict) -> str:
    """Reconstruct plain-text abstract from OpenAlex abstract_inverted_index."""
    tokens: dict[int, str] = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            tokens[pos] = word
    return " ".join(tokens[i] for i in sorted(tokens))


# ---------------------------------------------------------------------------
# Fetch strategies
# ---------------------------------------------------------------------------

def fetch_from_rss(journal: dict, since: date, scrapers: dict) -> tuple[list[dict], date | None]:
    """
    Fetch one journal's RSS feed and scrape all articles published after `since`.

    Returns (papers, max_date) where max_date is the most recent entry date found,
    or None if no papers were scraped.
    """
    publisher = journal["publisher"]
    if publisher not in scrapers:
        log.warning("No scraper for publisher '%s' (journal: %s) — skipping.", publisher, journal["name"])
        return [], None

    scraper = scrapers[publisher]()
    log.info("Fetching RSS: %s (%s)", journal["name"], journal["url"])
    feed = feedparser.parse(journal["url"], agent=HEADERS["User-Agent"])

    if feed.bozo and not feed.entries:
        log.warning("%s: feed parse error — %s", journal["name"], feed.bozo_exception)
        return [], None

    papers = []
    max_date = None
    skipped_date = 0
    skipped_error = 0

    for entry in feed.entries:
        try:
            entry_date = _entry_date(entry)
            if entry_date is not None and entry_date <= since:
                skipped_date += 1
                continue

            if not scraper.editorial_filter(entry):
                continue

            url = getattr(entry, "link", "")
            result = scraper.scrape_article(url, entry=entry)
            if result is None:
                continue

            doi = result.get("doi") or _extract_doi(entry)
            arxiv_id = doi if doi else url

            abstract = result["abstract"]
            if not abstract and not result.get("skip_rss_fallback"):
                rss_summary = getattr(entry, "summary", "")
                if rss_summary:
                    abstract = BeautifulSoup(rss_summary, "lxml").get_text(separator=" ", strip=True)

            if not abstract:
                abstract_quality = "missing"
            elif len(abstract) < 400:
                abstract_quality = "truncated"
            else:
                abstract_quality = "full"

            tag_filter = journal.get("tag_filter")
            if tag_filter:
                title_lower = getattr(entry, "title", "").lower()
                tags_lower  = [t.lower() for t in result["subject_tags"]]
                combined    = [title_lower] + tags_lower
                if not any(f.lower() in text for f in tag_filter for text in combined):
                    continue

            papers.append({
                "arxiv_id":         arxiv_id,
                "title":            getattr(entry, "title", "").strip(),
                "abstract":         abstract,
                "abstract_quality": abstract_quality,
                "authors":          result.get("authors") or _parse_authors(entry),
                "subcategories":    [],
                "source":           journal["name"],
                "feed_url":         journal["url"],
                "subject_tags":     result["subject_tags"],
            })

            if entry_date and (max_date is None or entry_date > max_date):
                max_date = entry_date

        except Exception as e:
            title = getattr(entry, "title", "<unknown>")
            log.warning("%s: skipping article '%s' due to error: %s", journal["name"], title, e)
            skipped_error += 1

    log.info("%s: %d articles scraped (skipped %d at or before watermark%s).",
             journal["name"], len(papers), skipped_date,
             f", {skipped_error} errors" if skipped_error else "")
    return papers, max_date


def fetch_from_openalex(journal: dict, since: date) -> tuple[list[dict], date | None]:
    """
    Fetch recent papers from OpenAlex by journal ISSN.
    Used for journals with no RSS feed (e.g. TACL).
    Queries all works from `since + 1 day` onward.
    """
    issn = journal["openalex_issn"]
    fetch_from = (since + timedelta(days=1)).isoformat()
    params = {
        "filter": f"primary_location.source.issn:{issn},from_publication_date:{fetch_from}",
        "sort": "publication_date:desc",
        "per-page": "50",
        "select": "id,doi,title,abstract_inverted_index,authorships,publication_date,topics",
        "mailto": "contact@incomingscience.xyz",
    }
    log.info("Fetching OpenAlex: %s (ISSN %s, since %s)", journal["name"], issn, since)

    try:
        r = requests.get(_OPENALEX_WORKS_URL, params=params, headers=_OPENALEX_HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning("%s: OpenAlex fetch failed — %s", journal["name"], e)
        return [], None

    tag_filter = journal.get("tag_filter")
    papers = []
    max_date = None

    for work in data.get("results", []):
        try:
            pub_date_str = work.get("publication_date", "")
            if not pub_date_str:
                continue
            pub_date = date.fromisoformat(pub_date_str[:10])

            title = (work.get("title") or "").strip()
            if not title:
                continue

            doi_url = work.get("doi") or ""
            doi = doi_url.replace("https://doi.org/", "").replace("http://doi.org/", "")

            abstract = _reconstruct_abstract(work.get("abstract_inverted_index") or {})

            authors = [
                a["author"]["display_name"]
                for a in work.get("authorships", [])
                if a.get("author", {}).get("display_name")
            ]

            subject_tags = [t["display_name"] for t in work.get("topics", [])]

            if tag_filter:
                combined = [title.lower()] + [t.lower() for t in subject_tags]
                if not any(f.lower() in text for f in tag_filter for text in combined):
                    continue

            abstract_quality = "missing" if not abstract else ("truncated" if len(abstract) < 400 else "full")

            papers.append({
                "arxiv_id":         doi or work.get("id", ""),
                "title":            title,
                "abstract":         abstract,
                "abstract_quality": abstract_quality,
                "authors":          authors,
                "subcategories":    [],
                "source":           journal["name"],
                "feed_url":         f"openalex:{issn}",
                "subject_tags":     subject_tags,
            })

            if max_date is None or pub_date > max_date:
                max_date = pub_date

        except Exception as e:
            log.warning("%s: skipping work — %s", journal["name"], e)

    log.info("%s: %d articles from OpenAlex.", journal["name"], len(papers))
    return papers, max_date


def fetch_from_crossref(journal: dict, since: date) -> tuple[list[dict], date | None]:
    """
    Fetch recent papers from CrossRef by journal ISSN.
    Used for journals where CrossRef has good abstract coverage (AER, AEJ series).
    """
    issn = journal["crossref_issn"]
    fetch_from = (since + timedelta(days=1)).isoformat()
    params = {
        "filter": f"from-pub-date:{fetch_from}",
        "sort": "published", "order": "desc",
        "rows": "50",
        "select": "title,abstract,author,DOI,published",
    }
    log.info("Fetching CrossRef: %s (ISSN %s, since %s)", journal["name"], issn, since)
    try:
        r = requests.get(
            _CROSSREF_JOURNAL_URL.format(issn=issn),
            params=params, headers=_CROSSREF_HEADERS, timeout=20,
        )
        r.raise_for_status()
        items = r.json().get("message", {}).get("items", [])
    except Exception as e:
        log.warning("%s: CrossRef fetch failed — %s", journal["name"], e)
        return [], None

    papers, max_date = [], None
    for item in items:
        try:
            date_parts = item.get("published", {}).get("date-parts", [[]])[0]
            if not date_parts:
                continue
            pub_date = date(
                date_parts[0],
                date_parts[1] if len(date_parts) > 1 else 1,
                date_parts[2] if len(date_parts) > 2 else 1,
            )
            titles = item.get("title", [])
            title = titles[0].strip() if titles else ""
            if not title:
                continue
            doi = item.get("DOI", "")
            abstract = _JATS_TAG_RE.sub("", item.get("abstract", "") or "").strip()
            authors = [
                " ".join(filter(None, [a.get("given", ""), a.get("family", "")]))
                for a in item.get("author", [])
            ]
            abstract_quality = "missing" if not abstract else ("truncated" if len(abstract) < 400 else "full")
            papers.append({
                "arxiv_id":         doi or f"crossref:{issn}:{title[:50]}",
                "title":            title,
                "abstract":         abstract,
                "abstract_quality": abstract_quality,
                "authors":          [a for a in authors if a],
                "subcategories":    [],
                "source":           journal["name"],
                "feed_url":         f"crossref:{issn}",
                "subject_tags":     [],
            })
            if max_date is None or pub_date > max_date:
                max_date = pub_date
        except Exception as e:
            log.warning("%s: skipping CrossRef item — %s", journal["name"], e)

    log.info("%s: %d articles from CrossRef.", journal["name"], len(papers))
    return papers, max_date


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def fetch_journal(journal: dict, since: date, scrapers: dict) -> tuple[list[dict], date | None]:
    """Dispatch to the correct fetch strategy based on journal config."""
    if "url" in journal:
        return fetch_from_rss(journal, since, scrapers)
    if "crossref_issn" in journal:
        return fetch_from_crossref(journal, since)
    return fetch_from_openalex(journal, since)


def journal_key(journal: dict) -> str:
    """Return the dedup/watermark key for a journal."""
    if "url" in journal:
        return journal["url"]
    if "crossref_issn" in journal:
        return f"crossref:{journal['crossref_issn']}"
    return f"openalex:{journal['openalex_issn']}"
