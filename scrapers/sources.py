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
import socket
import threading
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

# Limit concurrent RSS fetches to avoid triggering CDN burst-detection (Cloudflare).
_RSS_SEMAPHORE = threading.Semaphore(2)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _entry_date(entry) -> date | None:
    """Return the publication date of an RSS entry, or None if unavailable.

    Some publishers (PNAS, ACS) carry both an online-first date (updated/published)
    and a prism:coverDate (official issue date). The cover date is used when it is
    in the past and later than the online-first date, so the watermark advances to
    the issue date on first scrape. Future cover dates (e.g. ACM eTOC feeds that
    pre-set the issue date months ahead) are ignored to prevent watermark stalling.
    """
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if parsed:
        pub_date = date(parsed.tm_year, parsed.tm_mon, parsed.tm_mday)
    else:
        # Fallback 1: dc:date (e.g. Wiley JSEP) — feedparser exposes as raw string,
        # not parsed. Format: "2026-05-14T09:40:35-07:00" → take first 10 chars.
        dc_date_str = getattr(entry, "dc_date", None)
        if dc_date_str:
            try:
                pub_date = date.fromisoformat(dc_date_str[:10])
            except ValueError:
                pub_date = None
        else:
            pub_date = None

        # Fallback 2: entry.published raw string with MM/DD/YYYY format.
        # IEEE csdl-api feeds use "05/20/2026 11:01 pm PST" — a non-standard format
        # that feedparser cannot parse into published_parsed.
        if pub_date is None:
            from datetime import datetime as _dt
            raw = getattr(entry, "published", None) or getattr(entry, "updated", None)
            if raw:
                try:
                    pub_date = _dt.strptime(raw.strip()[:10], "%m/%d/%Y").date()
                except ValueError:
                    pass

    cover_date = None
    cover_str = getattr(entry, "prism_coverdate", None)
    if cover_str:
        try:
            cd = date.fromisoformat(cover_str[:10])
            # Ignore future cover dates: ACM eTOC feeds pre-publish issue cover dates
            # months ahead, and using max() would prevent the watermark from advancing.
            if cd < date.today():
                cover_date = cd
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
    dc_id = getattr(entry, "dc_identifier", "") or ""
    if not isinstance(dc_id, str):
        dc_id = ""
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
    _origin = "/".join(journal["url"].split("/")[:3]) + "/"
    with _RSS_SEMAPHORE:
        _prev_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(90)
        try:
            feed = feedparser.parse(
                journal["url"],
                agent=HEADERS["User-Agent"],
                request_headers={
                    "Referer": _origin,
                    "Accept": "application/rss+xml, application/xml, text/xml, */*",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
        except OSError as exc:
            log.warning("%s: RSS fetch timed out or failed — %s", journal["name"], exc)
            return [], None
        finally:
            socket.setdefaulttimeout(_prev_timeout)

    if feed.bozo and not feed.entries:
        log.warning("%s: feed parse error — %s", journal["name"], feed.bozo_exception)
        return [], None, None

    id_re = re.compile(journal["id_pattern"], re.IGNORECASE) if "id_pattern" in journal else None
    since_id: int = journal.get("since_id", 0)

    papers = []
    max_date = None
    max_id: int | None = None
    skipped_date = 0
    skipped_error = 0

    for entry in feed.entries:
        try:
            url = getattr(entry, "link", "")

            if id_re is not None:
                m = id_re.search(url)
                if not m:
                    skipped_date += 1
                    continue
                paper_id = int(m.group(1))
                if paper_id <= since_id:
                    skipped_date += 1
                    continue
                if max_id is None or paper_id > max_id:
                    max_id = paper_id
            else:
                entry_date = _entry_date(entry)
                if entry_date is not None and entry_date <= since:
                    skipped_date += 1
                    continue
                if entry_date is not None and entry_date >= date.today():
                    continue  # skip today's papers; they'll be available in tomorrow's run

            if not scraper.editorial_filter(entry):
                continue

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

            if id_re is None and entry_date and (max_date is None or entry_date > max_date):
                max_date = entry_date

        except Exception as e:
            title = getattr(entry, "title", "<unknown>")
            log.warning("%s: skipping article '%s' due to error: %s", journal["name"], title, e)
            skipped_error += 1

    log.info("%s: %d articles scraped (skipped %d at or before watermark%s).",
             journal["name"], len(papers), skipped_date,
             f", {skipped_error} errors" if skipped_error else "")
    return papers, max_date, max_id


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
            if pub_date >= date.today():
                continue  # skip today's papers; they'll be available in tomorrow's run

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
            if pub_date >= date.today():
                continue  # skip today's papers; they'll be available in tomorrow's run
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
# IEEE ieeexplore.ieee.org internal REST API (early access + issued articles)
# ---------------------------------------------------------------------------

_IEEE_REST_URL = "https://ieeexplore.ieee.org/rest/search"
_IEEE_REST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://ieeexplore.ieee.org/",
}
_IEEE_ERRATA = ("erratum", "corrigendum", "correction", "retraction",
                "table of contents", "publication information",
                "computational intelligence society")


_IEEE_PUB_DATE_RE = re.compile(r"publicationDate=(\d+)\+(\w+)\+(\d{4})")
_IEEE_MONTHS = {m: i for i, m in enumerate(
    ["January","February","March","April","May","June",
     "July","August","September","October","November","December"], start=1)}


def _ieee_parse_pub_date(rights_link: str) -> date | None:
    """Parse publicationDate=15+May+2026 from ieeexplore rightsLink."""
    m = _IEEE_PUB_DATE_RE.search(rights_link)
    if not m:
        return None
    try:
        day, month_str, year = int(m.group(1)), m.group(2), int(m.group(3))
        month = _IEEE_MONTHS.get(month_str)
        if not month:
            return None
        return date(year, month, day)
    except (ValueError, TypeError):
        return None


def fetch_from_ieee_rest(journal: dict, since_id: int, since: date | None = None) -> tuple[list[dict], None, int | None]:
    """
    Fetch recent articles from ieeexplore via the internal REST API.
    Covers both early-access and issued papers (better than the TOC RSS).

    Watermark: `since_id` = highest IEEE articleNumber seen on the last run.
    Results are fetched newest-first and stopped when articleNumber <= since_id.
    On first run (since_id=0), `since` date is used as a fallback stop condition
    (parsed from the rightsLink publicationDate field).
    """
    pub_id = journal["ieee_pub_id"]
    name = journal["name"]
    tag_filter = journal.get("tag_filter")

    papers = []
    max_article_number: int | None = None
    page = 1
    rows = 25
    done = False

    log.info("Fetching IEEE REST: %s (pub %s, since_id %d)", name, pub_id, since_id)

    while not done:
        payload = {
            "queryText": "",
            "newsearch": True,
            "pageNumber": page,
            "rowsPerPage": rows,
            "punumber": pub_id,
            "sortType": "newest",
        }
        try:
            r = requests.post(_IEEE_REST_URL, json=payload, headers=_IEEE_REST_HEADERS, timeout=20)
            if r.status_code != 200 or not r.content:
                log.warning("%s: IEEE REST returned %d (page %d)", name, r.status_code, page)
                break
            data = r.json()
        except Exception as e:
            log.warning("%s: IEEE REST fetch failed (page %d): %s", name, page, e)
            break

        records = data.get("records", [])
        if not records:
            break

        total_pages = data.get("totalPages", page)

        for rec in records:
            art_num_str = rec.get("articleNumber", "")
            if not art_num_str:
                continue
            try:
                art_num = int(art_num_str)
            except ValueError:
                continue

            # ID-based stop (normal operation after first run)
            if since_id > 0 and art_num <= since_id:
                done = True
                break

            # Date-based stop (first run: since_id=0, use since date from rightsLink)
            if since_id == 0 and since is not None:
                rights_link = rec.get("rightsLink", "")
                pub_date = _ieee_parse_pub_date(rights_link)
                if pub_date is not None and pub_date <= since:
                    done = True
                    break

            if max_article_number is None or art_num > max_article_number:
                max_article_number = art_num

            title = (rec.get("articleTitle") or "").strip()
            if not title:
                continue
            if any(t in title.lower() for t in _IEEE_ERRATA):
                continue

            abstract_raw = (rec.get("abstract") or "").strip()
            # Strip trailing truncation artifact from API
            if abstract_raw.endswith("..."):
                abstract_raw = abstract_raw[:-3].rstrip()

            doi = rec.get("doi", "")

            raw_authors = rec.get("authors") or []
            if isinstance(raw_authors, dict):
                raw_authors = raw_authors.get("authors", [])
            authors = [a.get("normalizedName", "") or a.get("name", "") for a in raw_authors if isinstance(a, dict)]
            authors = [a for a in authors if a]

            if tag_filter:
                combined = [title.lower()]
                if not any(f.lower() in text for f in tag_filter for text in combined):
                    continue

            abstract_quality = ("missing" if not abstract_raw
                                else "truncated" if len(abstract_raw) < 400
                                else "full")

            papers.append({
                "arxiv_id":         doi or f"ieee:{art_num_str}",
                "title":            title,
                "abstract":         abstract_raw,
                "abstract_quality": abstract_quality,
                "authors":          authors,
                "subcategories":    [],
                "source":           name,
                "feed_url":         f"ieee_rest:{pub_id}",
                "subject_tags":     [],
            })

        if done or page >= total_pages:
            break
        page += 1

    log.info("%s: %d articles from IEEE REST.", name, len(papers))
    return papers, None, max_article_number


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def fetch_journal(journal: dict, since: date, scrapers: dict) -> tuple[list[dict], date | None, int | None]:
    """Dispatch to the correct fetch strategy based on journal config."""
    if "url" in journal:
        return fetch_from_rss(journal, since, scrapers)
    if "ieee_pub_id" in journal:
        since_id = journal.get("since_id", 0)
        return fetch_from_ieee_rest(journal, since_id, since=since)
    if "crossref_issn" in journal:
        papers, max_date = fetch_from_crossref(journal, since)
        return papers, max_date, None
    papers, max_date = fetch_from_openalex(journal, since)
    return papers, max_date, None


def journal_key(journal: dict) -> str:
    """Return the dedup/watermark key for a journal."""
    if "url" in journal:
        return journal["url"]
    if "ieee_pub_id" in journal:
        return f"ieee_rest:{journal['ieee_pub_id']}"
    if "crossref_issn" in journal:
        return f"crossref:{journal['crossref_issn']}"
    return f"openalex:{journal['openalex_issn']}"
