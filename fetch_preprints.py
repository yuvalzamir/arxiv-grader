#!/usr/bin/env python3
"""
fetch_preprints.py — Fetch working papers from preprint repositories.

Handles three types of preprint sources:
  1. NBER/CEPR-style (fields.json 'preprints' list): sequential numeric ID watermarking.
  2. bioRxiv/medRxiv (fields.json 'preprint_categories' dict): date-based watermarking.
  3. SSRN research networks (fields.json 'ssrn_networks' list): date+ids watermarking
     via the unauthenticated api.ssrn.com bindings listing; abstracts scraped from
     paper pages through FlareSolverr (Cloudflare). See docs/SSRN Access.md.

Output: one JSON file per field at {output_dir}/{field}_preprints.json
NBER/CEPR papers use 'preprint_source' so they join the arXiv triage pool.
bioRxiv/medRxiv/SSRN papers use 'source' (routed to arXiv pool in run_pipeline.py).

Sources shared by several fields (e.g. NBER, EduRN) are fetched once per run and
the same papers are written to every subscribing field — the watermark advances on
the first fetch, so re-fetching would return nothing for later fields.

Usage:
    python fetch_preprints.py --fields econ-political --output-dir data/2026-05-05
    python fetch_preprints.py --fields systems-biology --output-dir data/2026-05-25
    python fetch_preprints.py --fields systems-biology --output-dir data/... --no-advance-watermark
"""

import argparse
import html as html_module
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import feedparser
import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
WATERMARKS_FILE = BASE_DIR / "preprint_watermarks.json"
FIELDS_FILE = BASE_DIR / "fields.json"

BIORXIV_FEED = "https://connect.biorxiv.org/biorxiv_xml.php?subject={subject}"
MEDRXIV_FEED = "https://connect.medrxiv.org/medrxiv_xml.php?subject={subject}"

# Preprint platforms that set 'source' but must NOT be treated as journals
# downstream (triage pool routing, scoring source line, PDF section split).
PREPRINT_SOURCES = {"bioRxiv", "medRxiv", "SSRN"}

# SSRN bindings listing: no auth, no Cloudflare, but rejects non-browser UAs.
# The paper pages themselves ARE Cloudflare-walled — abstracts go through
# FlareSolverr (same service the journal scrapers use for Tandfonline/SAGE).
SSRN_API = "https://api.ssrn.com/content/v1/bindings/{binding_id}/papers"
SSRN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}
SSRN_PAGE_SIZE = 100
SSRN_MAX_PAGES = 3                 # lookback safety: never page past 300 papers
SSRN_FIRST_RUN_LOOKBACK_DAYS = 2   # bindings are unbounded — bound the first run
FLARESOLVERR_URL = os.environ.get("FLARESOLVERR_URL", "http://localhost:8191/v1")
FLARESOLVERR_MAX_FAILURES = 3      # consecutive failures before aborting a pass
SSRN_FETCH_DELAY = 1.5             # seconds between page fetches (avoid CF burst detection)
SSRN_RETRY_COOLDOWN = 45           # seconds before the retry pass (lets CF escalation decay)

# Abstract cache, filled by the evening --prefetch-ssrn cron so the 00:30
# pipeline run only scrapes stragglers approved late in the evening.
SSRN_CACHE_FILE = BASE_DIR / "ssrn_abstract_cache.json"
SSRN_CACHE_MAX_AGE_DAYS = 7


def _configure_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _load_watermarks() -> dict:
    if WATERMARKS_FILE.exists():
        with open(WATERMARKS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_watermarks(watermarks: dict):
    with open(WATERMARKS_FILE, "w", encoding="utf-8") as f:
        json.dump(watermarks, f, indent=2)


def _build_paper(entry, source_name: str, feed_url: str) -> dict:
    """Build a paper dict from a feedparser entry."""
    link = getattr(entry, "link", "") or ""
    # Strip tracking suffixes like #fromrss
    link = link.split("#")[0].strip()

    raw_title = getattr(entry, "title", "") or ""
    # NBER titles often end in " -- by Author1, Author2"
    authors = []
    title = raw_title
    by_match = re.search(r"\s+--\s+by\s+(.+)$", raw_title)
    if by_match:
        title = raw_title[: by_match.start()].strip()
        authors_str = by_match.group(1).strip()
        authors = [a.strip() for a in authors_str.split(",") if a.strip()]

    abstract = getattr(entry, "summary", "") or ""

    return {
        "arxiv_id": link,
        "title": title,
        "abstract": abstract,
        "abstract_quality": "full",
        "authors": authors,
        "subcategories": [],
        "preprint_source": source_name,
        "feed_url": feed_url,
    }


def fetch_field_preprints(field: str, field_config: dict, watermarks: dict, cache: dict) -> list[dict]:
    """Fetch all new preprint papers for a field using sequential-ID watermarking."""
    sources = field_config.get("preprints", [])
    if not sources:
        return []

    all_papers: list[dict] = []

    for source in sources:
        name = source["name"]
        url = source["url"]
        cache_key = f"{name}:{url}"
        if cache_key in cache:
            log.info("%s: shared source — reusing %d papers fetched earlier this run.",
                     name, len(cache[cache_key]))
            all_papers.extend(cache[cache_key])
            continue
        id_pattern = re.compile(source["id_pattern"], re.IGNORECASE)
        max_seen = watermarks.get(name, 0)
        new_max = max_seen
        new_papers: list[dict] = []

        log.info("Fetching %s from %s (watermark: %d)...", name, url, max_seen)
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            log.warning("%s: feed parse error: %s", name, e)
            continue

        if not feed.entries:
            log.info("%s: no entries in feed.", name)
            continue

        for entry in feed.entries:
            link = getattr(entry, "link", "") or ""
            m = id_pattern.search(link)
            if not m:
                continue
            paper_id = int(m.group(1))
            if paper_id <= max_seen:
                continue
            new_max = max(new_max, paper_id)
            new_papers.append(_build_paper(entry, name, url))

        log.info("%s: %d new papers (watermark %d → %d).", name, len(new_papers), max_seen, new_max)
        watermarks[name] = new_max
        cache[cache_key] = new_papers
        all_papers.extend(new_papers)

    return all_papers


def parse_biorxiv_authors(creator: str) -> list[str]:
    """
    Parse bioRxiv dc:creator field: "Bankole, K., McIntyre, L. M., Morse, A. M."
    Splits at ", " where the next token starts with a capital + lowercase (= last name).
    Returns names like ["Bankole K", "McIntyre L M"].
    """
    if not creator:
        return []
    parts = re.split(r",\s+(?=[A-Z][a-z])", creator)
    authors = []
    for part in parts:
        # Remove trailing periods, replace ", " separator between last/first with space
        cleaned = part.replace(".", "").replace(", ", " ").strip()
        if cleaned:
            authors.append(cleaned)
    return authors


def fetch_bio_preprints(field: str, field_config: dict, watermarks: dict, cache: dict) -> list[dict]:
    """
    Fetch bioRxiv/medRxiv preprints for a field using date-based watermarking.
    Reads 'preprint_categories' dict from field_config: {"biorxiv": [...], "medrxiv": [...]}.
    Deduplicates across subjects by DOI.
    Watermark keys: "{server}:{subject}" → "YYYY-MM-DD" last date seen.
    """
    preprint_categories = field_config.get("preprint_categories", {})
    if not preprint_categories:
        return []

    server_urls = {"biorxiv": BIORXIV_FEED, "medrxiv": MEDRXIV_FEED}
    seen_dois: set[str] = set()
    all_papers: list[dict] = []

    for server, subjects in preprint_categories.items():
        url_template = server_urls.get(server)
        if not url_template or not subjects:
            continue
        source_name = "bioRxiv" if server == "biorxiv" else "medRxiv"

        for subject in subjects:
            wm_key = f"{server}:{subject}"
            if wm_key in cache:
                log.info("%s/%s: shared source — reusing %d papers fetched earlier this run.",
                         server, subject, len(cache[wm_key]))
                for paper in cache[wm_key]:
                    if paper["arxiv_id"] not in seen_dois:
                        seen_dois.add(paper["arxiv_id"])
                        all_papers.append(paper)
                continue
            since_date = watermarks.get(wm_key, "2000-01-01")
            url = url_template.format(subject=subject)

            log.info("Fetching %s/%s from %s (since: %s)...", server, subject, url, since_date)
            try:
                feed = feedparser.parse(url)
            except Exception as e:
                log.warning("%s/%s: feed parse error: %s", server, subject, e)
                continue

            if not feed.entries:
                log.info("%s/%s: no entries in feed.", server, subject)
                continue

            new_max_date = since_date
            new_papers: list[dict] = []

            for entry in feed.entries:
                # Date: try dc_date then date_parsed
                dc_date = getattr(entry, "dc_date", None) or getattr(entry, "date", None) or ""
                if dc_date:
                    dc_date = dc_date[:10]  # keep YYYY-MM-DD
                if not dc_date or dc_date <= since_date:
                    continue

                # DOI: try dc_identifier then link
                doi = getattr(entry, "dc_identifier", None) or ""
                doi = doi.replace("doi:", "").strip()
                if not doi:
                    doi = getattr(entry, "link", "") or ""
                if not doi or doi in seen_dois:
                    continue
                seen_dois.add(doi)

                title = re.sub(r"\s+", " ", getattr(entry, "title", "").strip())
                raw_abstract = getattr(entry, "summary", "") or ""
                abstract = re.sub(r"<[^>]+>", "", raw_abstract)
                abstract = re.sub(r"\s+", " ", abstract).strip()
                creator = getattr(entry, "author", "") or ""
                authors = parse_biorxiv_authors(creator)

                new_papers.append({
                    "arxiv_id": doi,
                    "title": title,
                    "abstract": abstract,
                    "authors": authors,
                    "subcategories": [],
                    "source": source_name,
                    "preprint_date": dc_date,
                })
                if dc_date > new_max_date:
                    new_max_date = dc_date

            log.info("%s/%s: %d new papers (watermark %s → %s).",
                     server, subject, len(new_papers), since_date, new_max_date)
            watermarks[wm_key] = new_max_date
            cache[wm_key] = new_papers
            all_papers.extend(new_papers)

    return all_papers


# ---------------------------------------------------------------------------
# SSRN research networks (see docs/SSRN Access.md)
# ---------------------------------------------------------------------------

def _parse_ssrn_date(raw: str) -> str | None:
    """Parse SSRN's '17 Sep 2026' into ISO 'YYYY-MM-DD'; None if unparseable."""
    try:
        return datetime.strptime(raw.strip(), "%d %b %Y").date().isoformat()
    except (ValueError, AttributeError):
        return None


def _flaresolverr_get(url: str, session: str | None = None) -> str | None:
    """Fetch a Cloudflare-walled page via FlareSolverr; None on any failure."""
    payload = {"cmd": "request.get", "url": url, "maxTimeout": 60000}
    if session:
        payload["session"] = session
    try:
        resp = requests.post(FLARESOLVERR_URL, json=payload, timeout=75)
        data = resp.json()
        if data.get("status") != "ok":
            log.warning("FlareSolverr status=%s for %s", data.get("status"), url)
            return None
        return data["solution"].get("response") or None
    except Exception as exc:
        log.warning("FlareSolverr unavailable for %s: %s", url, exc)
        return None


def _flaresolverr_session_create() -> str | None:
    """Create a FlareSolverr browser session (reuses the cf_clearance cookie
    across requests — one challenge solve instead of one per page)."""
    try:
        resp = requests.post(FLARESOLVERR_URL, json={"cmd": "sessions.create"}, timeout=75)
        data = resp.json()
        if data.get("status") == "ok" and data.get("session"):
            return data["session"]
        log.warning("FlareSolverr sessions.create failed: %s", data.get("message"))
    except Exception as exc:
        log.warning("FlareSolverr sessions.create unavailable: %s", exc)
    return None


def _flaresolverr_session_destroy(session: str) -> None:
    """Best-effort teardown of a FlareSolverr session (frees its Chrome)."""
    try:
        requests.post(FLARESOLVERR_URL,
                      json={"cmd": "sessions.destroy", "session": session}, timeout=30)
    except Exception:
        pass


_XML_BUILTIN_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}

# Known element names in SSRN's listing XML plus inline HTML that appears in
# text fields (affiliations sometimes carry <i>…</i>). Anything else after
# '<' is treated as unescaped text.
_SSRN_XML_TAGS = {
    "paperresultset", "total", "papers", "abstract_type", "publication_status",
    "is_paid", "reference", "page_count", "title", "authors", "id",
    "last_name", "first_name", "url", "affiliations", "is_approved",
    "approved_date", "downloads", "downloads_last_month", "downloads_this_year",
    "i", "b", "em", "strong", "br", "sup", "sub", "u", "p", "span",
}


def _neutralize_html_entities(text: str) -> str:
    """
    Replace named HTML entities (&eacute;, &rsquo;, …) with their unicode
    characters — SSRN's XML serializer emits them, but they are undefined in
    XML and crash ElementTree. The five XML built-ins and numeric refs are
    left alone; unknown names get their ampersand escaped instead.
    """
    def repl(m):
        name = m.group(1)
        if name in _XML_BUILTIN_ENTITIES:
            return m.group(0)
        unescaped = html_module.unescape(m.group(0))
        return unescaped if unescaped != m.group(0) else f"&amp;{name};"

    return re.sub(r"&([A-Za-z][A-Za-z0-9]*);", repl, text)


def _ssrn_xml_to_dict(xml_text: str) -> dict:
    """
    Convert the SSRN listing's XML form into the same dict shape as its JSON
    form. Chrome sends Accept: application/xml, so via FlareSolverr the API
    responds with <PaperResultSet><total>N</total><papers><papers>…</papers>
    </papers></PaperResultSet> (repeated <papers> per paper, nested
    <authors><authors> per author, field names identical to the JSON).

    Parsed with lxml in recovery mode (BeautifulSoup "xml") — SSRN's XML is
    sometimes malformed (unescaped '<' in titles crashed ElementTree with
    "mismatched tag" on PSN/LIT, 2026-09-17); recovery salvages the intact
    records. recursive=False everywhere: the container and the per-paper
    elements share the name "papers" (likewise "authors"), and papers and
    authors both have <id>/<url> children.
    """
    # Unescaped '<' in text (e.g. "p < 0.05" or "x <y" in a title) is not a
    # tag start — escape everything that isn't a known SSRN element or inline
    # HTML tag, so one malformed title can't swallow the papers after it
    # (lxml recovery would otherwise absorb them into a phantom element).
    xml_text = re.sub(
        r"</?([A-Za-z][A-Za-z0-9_]*)?",
        lambda m: m.group(0) if m.group(1) and m.group(1).lower() in _SSRN_XML_TAGS
        else m.group(0).replace("<", "&lt;"),
        xml_text,
    )
    soup = BeautifulSoup(_neutralize_html_entities(xml_text), "xml")

    def text(el, name: str) -> str:
        child = el.find(name, recursive=False)
        return child.get_text().strip() if child else ""

    papers = []
    container = soup.find("papers")
    for p in (container.find_all("papers", recursive=False) if container else []):
        authors = []
        author_container = p.find("authors", recursive=False)
        if author_container:
            for a in author_container.find_all("authors", recursive=False):
                authors.append({
                    "first_name": text(a, "first_name"),
                    "last_name": text(a, "last_name"),
                })
        paper_id = text(p, "id")
        papers.append({
            "id": int(paper_id) if paper_id.isdigit() else None,
            "title": text(p, "title"),
            "approved_date": text(p, "approved_date"),
            "url": text(p, "url"),
            "is_approved": text(p, "is_approved") != "false",
            "authors": authors,
        })
    root = soup.find("PaperResultSet")
    total = text(root, "total") if root else ""
    return {"total": int(total) if total.isdigit() else None, "papers": papers}


def _flaresolverr_get_json(url: str) -> dict | None:
    """
    Fetch the SSRN listing endpoint via FlareSolverr and return the parsed
    dict. Chrome wraps the response in a viewer page: JSON lands in a
    <pre> block, XML (the usual case — Chrome's Accept header makes the API
    return XML) in the hidden webkit-xml-viewer-source-xml div, HTML-escaped.
    None on any failure.
    """
    body = _flaresolverr_get(url)
    if not body:
        return None
    text = body.strip()

    m = re.search(r'<div[^>]+id="webkit-xml-viewer-source-xml"[^>]*>(.*?)</div>',
                  text, re.DOTALL)
    if m:
        try:
            return _ssrn_xml_to_dict(html_module.unescape(m.group(1)))
        except Exception as exc:
            log.warning("FlareSolverr listing fetch: XML parse failed for %s: %s", url, exc)
            return None

    if text.startswith("<"):
        pre = re.search(r"<pre[^>]*>(.*?)</pre>", text, re.DOTALL)
        if not pre:
            log.warning("FlareSolverr listing fetch: unrecognized wrapper for %s", url)
            return None
        text = html_module.unescape(pre.group(1)).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        log.warning("FlareSolverr listing fetch: JSON parse failed for %s: %s", url, exc)
        return None


def _parse_ssrn_abstract(html: str) -> str:
    """Extract the abstract from an SSRN paper page; '' if not found."""
    soup = BeautifulSoup(html, "lxml")
    meta = soup.find("meta", {"name": "citation_abstract"})
    if meta and meta.get("content", "").strip():
        return re.sub(r"\s+", " ", meta["content"]).strip()
    paragraphs = soup.select("div.abstract-text p")
    if paragraphs:
        return re.sub(r"\s+", " ", " ".join(p.get_text(strip=True) for p in paragraphs)).strip()
    return ""


def _load_ssrn_cache() -> dict:
    """Load the prefetched-abstract cache: {ssrn_id_str: {abstract, fetched}}."""
    if SSRN_CACHE_FILE.exists():
        try:
            return json.loads(SSRN_CACHE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("SSRN abstract cache is corrupt — starting fresh.")
    return {}


def _save_ssrn_cache(cache: dict) -> None:
    """Persist the abstract cache, pruning entries older than the max age."""
    min_fetched = (date.today() - timedelta(days=SSRN_CACHE_MAX_AGE_DAYS)).isoformat()
    pruned = {k: v for k, v in cache.items() if v.get("fetched", "") >= min_fetched}
    SSRN_CACHE_FILE.write_text(json.dumps(pruned, indent=2, ensure_ascii=False),
                               encoding="utf-8")


def _enrich_ssrn_abstracts(papers: list[dict]) -> None:
    """
    Fill each paper's abstract (in place): first from the prefetch cache
    (written by the evening --prefetch-ssrn cron), then by scraping the
    SSRN page for the misses. Newly scraped abstracts are added to the cache.

    SSRN pages are Cloudflare-walled, so scraping only works where FlareSolverr
    runs (the server). Uses a FlareSolverr session so the challenge is solved
    once and the cf_clearance cookie is reused — without one, ~15 back-to-back
    challenge solves triggered Cloudflare escalation and timeouts (2026-09-17).
    Two passes with pacing; a pass aborts after FLARESOLVERR_MAX_FAILURES
    consecutive failures. Unfetched papers keep abstract_quality 'missing'.
    """
    abstract_cache = _load_ssrn_cache()
    to_scrape = []
    for paper in papers:
        cached = abstract_cache.get(str(paper["ssrn_id"]))
        if cached and cached.get("abstract"):
            paper["abstract"] = cached["abstract"]
            paper["abstract_quality"] = "full"
        else:
            to_scrape.append(paper)
    if len(to_scrape) < len(papers):
        log.info("SSRN abstracts: %d/%d served from prefetch cache.",
                 len(papers) - len(to_scrape), len(papers))
    if not to_scrape:
        return

    session = _flaresolverr_session_create()
    try:
        pending = list(to_scrape)
        for attempt in (1, 2):
            failures: list[dict] = []
            consecutive_failures = 0
            for i, paper in enumerate(pending, 1):
                if consecutive_failures >= FLARESOLVERR_MAX_FAILURES:
                    failures.extend(pending[i - 1:])
                    log.warning("SSRN abstracts: pass %d aborted after %d consecutive failures.",
                                attempt, consecutive_failures)
                    break
                html = _flaresolverr_get(paper["arxiv_id"], session=session)
                abstract = _parse_ssrn_abstract(html) if html else ""
                if abstract:
                    paper["abstract"] = abstract
                    paper["abstract_quality"] = "full"
                    consecutive_failures = 0
                else:
                    failures.append(paper)
                    consecutive_failures += 1
                if i % 10 == 0:
                    log.info("SSRN abstracts: pass %d, %d/%d pages fetched...",
                             attempt, i, len(pending))
                time.sleep(SSRN_FETCH_DELAY)
            if not failures:
                break
            pending = failures
            if attempt == 1:
                log.info("SSRN abstracts: retrying %d failed pages after cool-down...", len(failures))
                time.sleep(SSRN_RETRY_COOLDOWN)
    finally:
        if session:
            _flaresolverr_session_destroy(session)

    newly_scraped = {
        str(p["ssrn_id"]): {"abstract": p["abstract"], "fetched": date.today().isoformat()}
        for p in to_scrape if p["abstract_quality"] == "full"
    }
    if newly_scraped:
        abstract_cache.update(newly_scraped)
        _save_ssrn_cache(abstract_cache)

    fetched = sum(1 for p in papers if p["abstract_quality"] == "full")
    missing = len(papers) - fetched
    if missing:
        log.warning("SSRN abstracts: %d fetched, %d missing (FlareSolverr down or parse failures).",
                    fetched, missing)
    else:
        log.info("SSRN abstracts: %d/%d fetched.", fetched, len(papers))


def _fetch_ssrn_network(name: str, binding_id: int, watermarks: dict) -> list[dict]:
    """
    Fetch new papers from one SSRN research network via the bindings listing
    (newest first). Watermark: {"date": ISO max approved_date seen, "ids": [ids
    seen on that date]} — same-date papers arriving later are caught by the ids
    list instead of being skipped or duplicated.
    """
    wm_key = f"ssrn:{name}"
    wm = watermarks.get(wm_key, {})
    cutoff = wm.get("date") or (date.today() - timedelta(days=SSRN_FIRST_RUN_LOOKBACK_DAYS)).isoformat()
    seen_ids = set(wm.get("ids", []))

    new_papers: list[dict] = []
    max_date, max_date_ids = cutoff, set(seen_ids)
    reached_cutoff = False

    log.info("SSRN %s (binding %d): fetching since %s...", name, binding_id, cutoff)
    # Cloudflare 403s the listing API from datacenter IPs (plain requests works
    # from residential IPs); after the first 403 all pages go via FlareSolverr.
    via_flaresolverr = False
    for page in range(SSRN_MAX_PAGES):
        page_url = (f"{SSRN_API.format(binding_id=binding_id)}"
                    f"?index={page * SSRN_PAGE_SIZE}&count={SSRN_PAGE_SIZE}&sort=0")
        listing = None
        if not via_flaresolverr:
            try:
                resp = requests.get(page_url, headers=SSRN_HEADERS, timeout=30)
                resp.raise_for_status()
                listing = resp.json().get("papers", [])
            except Exception as exc:
                log.info("SSRN %s: direct listing fetch failed (%s) — retrying via FlareSolverr.",
                         name, exc)
                via_flaresolverr = True
        if via_flaresolverr:
            data = _flaresolverr_get_json(page_url)
            if data is None:
                log.warning("SSRN %s: listing fetch failed (direct and FlareSolverr).", name)
                return []
            listing = data.get("papers", [])

        if not listing:
            break

        for item in listing:
            iso = _parse_ssrn_date(item.get("approved_date", ""))
            paper_id = item.get("id")
            if iso is None or paper_id is None or not item.get("is_approved", True):
                continue
            if iso < cutoff:
                reached_cutoff = True
                break
            if iso == cutoff and paper_id in seen_ids:
                continue
            if iso > max_date:
                max_date, max_date_ids = iso, set()
            if iso == max_date:
                max_date_ids.add(paper_id)

            url = item.get("url") or f"https://papers.ssrn.com/sol3/papers.cfm?abstract_id={paper_id}"
            authors = [
                " ".join(part for part in [a.get("first_name", "").strip(), a.get("last_name", "").strip()] if part)
                for a in item.get("authors", [])
            ]
            new_papers.append({
                "arxiv_id": url,
                "ssrn_id": paper_id,
                "title": re.sub(r"\s+", " ", item.get("title", "")).strip(),
                "abstract": "",
                "abstract_quality": "missing",
                "authors": [a for a in authors if a],
                "subcategories": [],
                "source": "SSRN",
                "preprint_date": iso,
            })

        if reached_cutoff:
            break

    if not reached_cutoff and new_papers:
        log.warning("SSRN %s: hit the %d-page lookback backstop before reaching the %s "
                    "watermark — papers older than the fetched window are permanently skipped.",
                    name, SSRN_MAX_PAGES, cutoff)
    log.info("SSRN %s: %d new papers (watermark %s → %s).", name, len(new_papers), cutoff, max_date)
    watermarks[wm_key] = {"date": max_date, "ids": sorted(max_date_ids)}
    return new_papers


def prefetch_ssrn_abstracts(fields_data: dict, only_fields: list[str] | None = None) -> None:
    """
    Evening cron mode (--prefetch-ssrn): warm the abstract cache so the 00:30
    pipeline run barely scrapes. Reads watermarks to know what is new but
    NEVER saves them — the daily run must still see these papers as new.
    SSRN approvals happen through the US-Eastern business day, so a ~22:30 ET
    prefetch catches essentially everything the 00:30 run will list.
    """
    watermarks = _load_watermarks()
    networks: dict[str, int] = {}
    for field, cfg in fields_data.items():
        if only_fields and field not in only_fields:
            continue
        for n in cfg.get("ssrn_networks", []):
            networks.setdefault(n["name"], n["binding_id"])

    if not networks:
        log.info("Prefetch: no SSRN networks configured.")
        return

    for name, binding_id in networks.items():
        throwaway = json.loads(json.dumps(watermarks))  # advances are discarded
        papers = _fetch_ssrn_network(name, binding_id, throwaway)
        if papers:
            _enrich_ssrn_abstracts(papers)  # fills + saves the cache
    log.info("Prefetch done: cache now holds %d abstracts.", len(_load_ssrn_cache()))


def fetch_ssrn_preprints(field: str, field_config: dict, watermarks: dict, cache: dict) -> list[dict]:
    """
    Fetch new SSRN papers for a field from its configured research networks.
    fields.json entry: "ssrn_networks": [{"name": "EduRN", "binding_id": 3118597}].
    Abstracts are scraped per paper via FlareSolverr after the (cheap) listing calls.
    """
    networks = field_config.get("ssrn_networks", [])
    if not networks:
        return []

    all_papers: list[dict] = []
    seen: set[int] = set()

    for network in networks:
        name = network["name"]
        cache_key = f"ssrn:{name}"
        if cache_key in cache:
            log.info("SSRN %s: shared source — reusing %d papers fetched earlier this run.",
                     name, len(cache[cache_key]))
            papers = cache[cache_key]
        else:
            papers = _fetch_ssrn_network(name, network["binding_id"], watermarks)
            if papers:
                _enrich_ssrn_abstracts(papers)
            cache[cache_key] = papers

        for paper in papers:
            if paper["ssrn_id"] not in seen:
                seen.add(paper["ssrn_id"])
                all_papers.append(paper)

    return all_papers


def main():
    _configure_logging()

    parser = argparse.ArgumentParser(description="Fetch preprint working papers (NBER, CEPR, ...).")
    parser.add_argument("--fields", nargs="+", help="Field names to fetch preprints for.")
    parser.add_argument("--output-dir", help="Directory to write {field}_preprints.json files.")
    parser.add_argument("--no-advance-watermark", action="store_true",
                        help="Do not update preprint_watermarks.json (for testing).")
    parser.add_argument("--prefetch-ssrn", action="store_true",
                        help="Evening cron mode: warm the SSRN abstract cache for all "
                             "configured networks (no watermark advance, no output files).")
    args = parser.parse_args()

    fields_data = json.loads(FIELDS_FILE.read_text(encoding="utf-8"))

    if args.prefetch_ssrn:
        prefetch_ssrn_abstracts(fields_data, only_fields=args.fields)
        sys.exit(0)

    if not args.fields or not args.output_dir:
        parser.error("--fields and --output-dir are required (except with --prefetch-ssrn)")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    watermarks = _load_watermarks()

    any_error = False
    cache: dict[str, list[dict]] = {}  # shared-source fetch results, keyed per source
    for field in args.fields:
        field_config = fields_data.get(field, {})
        has_nber = bool(field_config.get("preprints"))
        has_bio = bool(field_config.get("preprint_categories"))
        has_ssrn = bool(field_config.get("ssrn_networks"))
        if not has_nber and not has_bio and not has_ssrn:
            log.info("Field '%s': no preprints configured — skipping.", field)
            continue

        papers: list[dict] = []
        if has_nber:
            papers.extend(fetch_field_preprints(field, field_config, watermarks, cache))
        if has_bio:
            papers.extend(fetch_bio_preprints(field, field_config, watermarks, cache))
        if has_ssrn:
            papers.extend(fetch_ssrn_preprints(field, field_config, watermarks, cache))

        out_path = output_dir / f"{field}_preprints.json"
        out_path.write_text(json.dumps(papers, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("Field '%s': wrote %d preprint papers to %s.", field, len(papers), out_path)

    if not args.no_advance_watermark:
        _save_watermarks(watermarks)
        log.info("Watermarks saved to %s.", WATERMARKS_FILE)
    else:
        log.info("--no-advance-watermark: watermarks NOT saved.")

    sys.exit(1 if any_error else 0)


if __name__ == "__main__":
    main()
