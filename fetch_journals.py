#!/usr/bin/env python3
"""
fetch_journals.py — Unified journal scraper.

Reads fields.json, unions all journals for the requested fields,
fetches each RSS feed, applies the publisher editorial filter,
scrapes each surviving article for abstract + subject tags, and
writes a shared cache used by all users.

Uses a per-journal watermark (journal_watermarks.json) to track the last
scraped date per journal. Each run fetches all entries published after the
watermark. The watermark advances to min(max_entry_date, yesterday) so that
papers published on the run date itself are never skipped on the next run.

Usage:
    python fetch_journals.py --fields cond-mat --output data/YYYY-MM-DD/scraped_journals.json
    python fetch_journals.py --fields cond-mat hep-th --output data/YYYY-MM-DD/scraped_journals.json
    python fetch_journals.py --fields cond-mat --since 2026-03-20 --output ...  # override watermark
"""

import argparse
import json
import logging
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import feedparser
from bs4 import BeautifulSoup

from scrapers import SCRAPERS

log = logging.getLogger(__name__)

WATERMARKS_FILE = Path(__file__).parent / "journal_watermarks.json"


def _configure_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _load_fields(fields_path: Path) -> dict:
    with open(fields_path) as f:
        return json.load(f)


def _load_watermarks() -> dict:
    if WATERMARKS_FILE.exists():
        with open(WATERMARKS_FILE) as f:
            return json.load(f)
    return {}


def _save_watermarks(watermarks: dict):
    with open(WATERMARKS_FILE, "w") as f:
        json.dump(watermarks, f, indent=2)


def _collect_journals(fields_data: dict, active_fields: list[str]) -> list[dict]:
    """Union all journals across active fields, deduplicated by URL."""
    seen_urls = set()
    journals = []
    for field in active_fields:
        if field not in fields_data:
            log.warning("Field '%s' not found in fields.json — skipping.", field)
            continue
        for journal in fields_data[field]["journals"]:
            if journal["url"] not in seen_urls:
                seen_urls.add(journal["url"])
                journals.append(journal)
    return journals


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
    for attr in ("id", "link"):
        val = getattr(entry, attr, "")
        if val.startswith("10."):
            return val.split("?")[0].split("#")[0]
        if "/10." in val:
            doi = "10." + val.split("/10.", 1)[1]
            return doi.split("?")[0].split("#")[0]
    return ""


def _entry_date(entry) -> date | None:
    """Return the publication date of an RSS entry, or None if unavailable."""
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if parsed:
        return date(parsed.tm_year, parsed.tm_mon, parsed.tm_mday)
    return None


def scrape_journal(journal: dict, since: date) -> tuple[list[dict], date | None]:
    """
    Fetch one journal's RSS feed and scrape all articles published after `since`.

    Returns (papers, max_date) where max_date is the most recent entry date found,
    or None if no papers were scraped.
    """
    publisher = journal["publisher"]
    if publisher not in SCRAPERS:
        log.warning("No scraper for publisher '%s' (journal: %s) — skipping.", publisher, journal["name"])
        return [], None

    scraper = SCRAPERS[publisher]()
    log.info("Fetching RSS: %s (%s)", journal["name"], journal["url"])
    feed = feedparser.parse(journal["url"])

    if feed.bozo and not feed.entries:
        log.warning("%s: feed parse error — %s", journal["name"], feed.bozo_exception)
        return [], None

    papers = []
    max_date = None
    skipped_date = 0

    for entry in feed.entries:
        entry_date = _entry_date(entry)
        if entry_date is not None and entry_date <= since:
            skipped_date += 1
            continue

        if not scraper.editorial_filter(entry):
            continue

        url = getattr(entry, "link", "")
        result = scraper.scrape_article(url)
        if result is None:
            continue

        doi = _extract_doi(entry)
        arxiv_id = doi if doi else url

        abstract = result["abstract"]
        if not abstract:
            rss_summary = getattr(entry, "summary", "")
            if rss_summary:
                abstract = BeautifulSoup(rss_summary, "lxml").get_text(separator=" ", strip=True)

        papers.append({
            "arxiv_id":      arxiv_id,
            "title":         getattr(entry, "title", "").strip(),
            "abstract":      abstract,
            "authors":       result.get("authors") or _parse_authors(entry),
            "subcategories": [],
            "source":        journal["name"],
            "subject_tags":  result["subject_tags"],
        })

        if entry_date and (max_date is None or entry_date > max_date):
            max_date = entry_date

    log.info("%s: %d articles scraped (skipped %d at or before watermark).",
             journal["name"], len(papers), skipped_date)
    return papers, max_date


def main():
    _configure_logging()

    parser = argparse.ArgumentParser(description="Scrape journal RSS feeds.")
    parser.add_argument("--fields", nargs="+", required=True, help="Field names to scrape (e.g. cond-mat)")
    parser.add_argument("--output", required=True, help="Output JSON path")
    parser.add_argument("--since", default=None, help="Override watermark: scrape entries after this date (YYYY-MM-DD)")
    parser.add_argument("--fields-file", default="fields.json", help="Path to fields.json")
    args = parser.parse_args()

    yesterday = date.today() - timedelta(days=1)
    watermarks = _load_watermarks()
    fields_data = _load_fields(Path(args.fields_file))
    journals = _collect_journals(fields_data, args.fields)

    if not journals:
        log.error("No journals found for fields: %s", args.fields)
        sys.exit(1)

    log.info("Scraping %d journal(s) for field(s): %s", len(journals), args.fields)

    all_papers = []
    for journal in journals:
        url_key = journal["url"]

        if args.since:
            since = date.fromisoformat(args.since)
        else:
            since = date.fromisoformat(watermarks[url_key]) if url_key in watermarks else yesterday - timedelta(days=1)

        log.info("%s: watermark is %s", journal["name"], since)

        try:
            papers, max_date = scrape_journal(journal, since)
            all_papers.extend(papers)

            if max_date is not None:
                # Advance watermark to min(max_date, yesterday) — never advance
                # to today, as papers published after this run would be missed tomorrow.
                new_watermark = min(max_date, yesterday)
                if not args.since:  # don't update watermarks on manual overrides
                    watermarks[url_key] = new_watermark.isoformat()
                    log.info("%s: watermark advanced to %s", journal["name"], new_watermark)

        except Exception as e:
            log.warning("Unexpected error scraping %s: %s — skipping.", journal["name"], e)

    if not args.since:
        _save_watermarks(watermarks)

    # Deduplicate by arxiv_id (DOI or URL) — a paper can appear in multiple
    # feeds (e.g. two PRL section feeds). Keep first occurrence.
    seen_ids = set()
    deduped = []
    for paper in all_papers:
        pid = paper["arxiv_id"]
        if pid not in seen_ids:
            seen_ids.add(pid)
            deduped.append(paper)
    if len(deduped) < len(all_papers):
        log.info("Deduplication: removed %d duplicate(s).", len(all_papers) - len(deduped))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(deduped, f, indent=2)

    log.info("Wrote %d total papers to %s", len(deduped), args.output)


if __name__ == "__main__":
    main()
