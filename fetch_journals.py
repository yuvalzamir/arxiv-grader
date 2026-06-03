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
import os
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

from scrapers import SCRAPERS
from scrapers.base import BaseScraper
from scrapers.sources import fetch_journal, journal_key

log = logging.getLogger(__name__)

WATERMARKS_FILE          = Path(__file__).parent / "journal_watermarks.json"
PREPRINT_WATERMARKS_FILE = Path(__file__).parent / "preprint_watermarks.json"


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


def _load_preprint_watermarks() -> dict:
    if PREPRINT_WATERMARKS_FILE.exists():
        with open(PREPRINT_WATERMARKS_FILE) as f:
            return json.load(f)
    return {}


def _save_preprint_watermarks(watermarks: dict):
    with open(PREPRINT_WATERMARKS_FILE, "w") as f:
        json.dump(watermarks, f, indent=2)


BLOCKLIST_FILE = Path(__file__).parent / "publisher_blocklist.json"


def _load_publisher_blocklist(today: date) -> set[str]:
    """Return set of publisher names currently blocked (unblock date not yet reached)."""
    if not BLOCKLIST_FILE.exists():
        return set()
    with open(BLOCKLIST_FILE) as f:
        blocklist = json.load(f)
    blocked = set()
    for pub, unblock_str in blocklist.items():
        if today < date.fromisoformat(unblock_str):
            blocked.add(pub)
            log.info("Publisher '%s' is blocklisted until %s — skipping.", pub, unblock_str)
    return blocked


def _collect_journals(fields_data: dict, active_fields: list[str]) -> list[dict]:
    """Union all journals across active fields, deduplicated by URL or ISSN key."""
    seen_keys = set()
    journals = []
    for field in active_fields:
        if field not in fields_data:
            log.warning("Field '%s' not found in fields.json — skipping.", field)
            continue
        for journal in fields_data[field]["journals"]:
            key = journal_key(journal)
            if key not in seen_keys:
                seen_keys.add(key)
                journals.append(journal)
    return journals


def _scrape_publisher_group(
    publisher: str,
    pub_journals: list,
    watermarks: dict,
    preprint_watermarks: dict,
    lock: threading.Lock,
    since_override: str | None,
    advance_watermark: bool,
    yesterday: date,
) -> list:
    papers_out = []
    for journal in pub_journals:
        url_key = journal_key(journal)

        with lock:
            if since_override:
                since = date.fromisoformat(since_override)
            else:
                since = date.fromisoformat(watermarks[url_key]) if url_key in watermarks else yesterday - timedelta(days=1)

            if "id_pattern" in journal or "ieee_pub_id" in journal:
                journal = dict(journal)
                journal["since_id"] = preprint_watermarks.get(journal["name"], 0)
                log.info("[%s] %s: watermark is %s (ID-based)", publisher, journal["name"], journal["since_id"])
            else:
                log.info("[%s] %s: watermark is %s", publisher, journal["name"], since)

        try:
            papers, max_date, max_id = fetch_journal(journal, since, SCRAPERS)
        except Exception as e:
            log.warning("[%s] %s: fetch error — skipping. %s", publisher, journal.get("name", url_key), e)
            continue

        with lock:
            if advance_watermark:
                if max_id is not None:
                    preprint_watermarks[journal["name"]] = max_id
                    log.info("[%s] %s: ID watermark advanced to %d", publisher, journal["name"], max_id)
                elif max_date is not None:
                    new_watermark = min(max_date, yesterday)
                    watermarks[url_key] = new_watermark.isoformat()
                    log.info("[%s] %s: watermark advanced to %s", publisher, journal["name"], new_watermark)

        papers_out.extend(papers)
    return papers_out


def main():
    _configure_logging()

    parser = argparse.ArgumentParser(description="Scrape journal RSS feeds.")
    parser.add_argument("--fields", nargs="+", required=True, help="Field names to scrape (e.g. cond-mat)")
    parser.add_argument("--output", required=True, help="Output JSON path")
    parser.add_argument("--since", default=None, help="Override watermark: scrape entries after this date (YYYY-MM-DD)")
    parser.add_argument("--no-advance-watermark", action="store_true", help="Read watermarks normally but do not save updates (useful for re-runs).")
    parser.add_argument("--fields-file", default="fields.json", help="Path to fields.json")
    parser.add_argument("--max-publisher-workers", type=int, default=8,
                        help="Max concurrent publisher threads (default: 8).")
    args = parser.parse_args()

    yesterday = date.today() - timedelta(days=1)
    watermarks = _load_watermarks()
    preprint_watermarks = _load_preprint_watermarks()
    fields_data = _load_fields(Path(args.fields_file))
    journals = _collect_journals(fields_data, args.fields)

    if not journals:
        log.error("No journals found for fields: %s", args.fields)
        sys.exit(1)

    # Group journals by publisher so journals from the same publisher run
    # sequentially within their thread (respecting per-publisher rate limits),
    # while different publishers run concurrently.
    blocked_publishers = _load_publisher_blocklist(date.today())
    publisher_groups: dict = defaultdict(list)
    for journal in journals:
        pub = journal.get("publisher", "unknown")
        if pub not in blocked_publishers:
            publisher_groups[pub].append(journal)

    n_workers = min(len(publisher_groups), args.max_publisher_workers)
    advance = not args.since and not args.no_advance_watermark
    log.info(
        "Scraping %d journal(s) across %d publisher group(s) with up to %d concurrent workers — field(s): %s",
        len(journals), len(publisher_groups), n_workers, args.fields,
    )

    lock = threading.Lock()
    all_papers = []
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        futures = {
            executor.submit(
                _scrape_publisher_group,
                pub, pub_journals, watermarks, preprint_watermarks,
                lock, args.since, advance, yesterday,
            ): pub
            for pub, pub_journals in publisher_groups.items()
        }
        for future in as_completed(futures):
            pub = futures[future]
            try:
                papers = future.result()
                all_papers.extend(papers)
                log.info("Publisher '%s': %d paper(s) collected.", pub, len(papers))
            except Exception as e:
                log.error("Publisher '%s' thread failed entirely: %s", pub, e)

    if not args.since and not args.no_advance_watermark:
        _save_watermarks(watermarks)
        _save_preprint_watermarks(preprint_watermarks)

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

    BaseScraper.enrich_missing_abstracts_s2(deduped, os.environ.get("S2_API_KEY", ""))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(deduped, f, indent=2)

    log.info("Wrote %d total papers to %s", len(deduped), args.output)


if __name__ == "__main__":
    main()
