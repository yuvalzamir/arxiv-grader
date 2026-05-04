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
import sys
from datetime import date, timedelta
from pathlib import Path

from scrapers import SCRAPERS
from scrapers.sources import fetch_journal, journal_key

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


def main():
    _configure_logging()

    parser = argparse.ArgumentParser(description="Scrape journal RSS feeds.")
    parser.add_argument("--fields", nargs="+", required=True, help="Field names to scrape (e.g. cond-mat)")
    parser.add_argument("--output", required=True, help="Output JSON path")
    parser.add_argument("--since", default=None, help="Override watermark: scrape entries after this date (YYYY-MM-DD)")
    parser.add_argument("--no-advance-watermark", action="store_true", help="Read watermarks normally but do not save updates (useful for re-runs).")
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
        url_key = journal_key(journal)

        if args.since:
            since = date.fromisoformat(args.since)
        else:
            since = date.fromisoformat(watermarks[url_key]) if url_key in watermarks else yesterday - timedelta(days=1)

        log.info("%s: watermark is %s", journal["name"], since)

        try:
            papers, max_date = fetch_journal(journal, since, SCRAPERS)
            all_papers.extend(papers)

            if max_date is not None:
                # Advance watermark to min(max_date, yesterday) — never advance
                # to today, as papers published after this run would be missed tomorrow.
                new_watermark = min(max_date, yesterday)
                if not args.since and not args.no_advance_watermark:
                    watermarks[url_key] = new_watermark.isoformat()
                    log.info("%s: watermark advanced to %s", journal["name"], new_watermark)

        except Exception as e:
            log.warning("Unexpected error scraping %s: %s — skipping.", journal["name"], e)

    if not args.since and not args.no_advance_watermark:
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
