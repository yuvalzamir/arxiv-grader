#!/usr/bin/env python3
"""
fetch_preprints.py — Fetch working papers from preprint repositories (NBER, CEPR, etc.).

Reads fields.json for 'preprints' config in each requested field.
Uses sequential numeric ID watermarking (preprint_watermarks.json) to avoid
re-fetching papers already seen, since NBER RSS has no reliable pubDate.

Each source entry in fields.json must have:
  - name: source label (e.g. "NBER")
  - url: RSS feed URL
  - id_pattern: regex with one capture group extracting the numeric ID from the entry link

Output: one JSON file per field at {output_dir}/{field}_preprints.json
Papers use 'preprint_source' (not 'source') so they join the arXiv triage pool.

Usage:
    python fetch_preprints.py --fields econ-political --output-dir data/2026-05-05
    python fetch_preprints.py --fields econ-political --output-dir data/... --no-advance-watermark
"""

import argparse
import json
import logging
import re
import sys
from pathlib import Path

import feedparser

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
WATERMARKS_FILE = BASE_DIR / "preprint_watermarks.json"
FIELDS_FILE = BASE_DIR / "fields.json"


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


def fetch_field_preprints(field: str, field_config: dict, watermarks: dict) -> list[dict]:
    """Fetch all new preprint papers for a field using sequential-ID watermarking."""
    sources = field_config.get("preprints", [])
    if not sources:
        return []

    all_papers: list[dict] = []

    for source in sources:
        name = source["name"]
        url = source["url"]
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
        all_papers.extend(new_papers)

    return all_papers


def main():
    _configure_logging()

    parser = argparse.ArgumentParser(description="Fetch preprint working papers (NBER, CEPR, ...).")
    parser.add_argument("--fields", nargs="+", required=True, help="Field names to fetch preprints for.")
    parser.add_argument("--output-dir", required=True, help="Directory to write {field}_preprints.json files.")
    parser.add_argument("--no-advance-watermark", action="store_true",
                        help="Do not update preprint_watermarks.json (for testing).")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    fields_data = json.loads(FIELDS_FILE.read_text())
    watermarks = _load_watermarks()

    any_error = False
    for field in args.fields:
        field_config = fields_data.get(field, {})
        if not field_config.get("preprints"):
            log.info("Field '%s': no preprints configured — skipping.", field)
            continue

        papers = fetch_field_preprints(field, field_config, watermarks)

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
