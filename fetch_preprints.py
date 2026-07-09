#!/usr/bin/env python3
"""
fetch_preprints.py — Fetch working papers from preprint repositories.

Handles two types of preprint sources:
  1. NBER/CEPR-style (fields.json 'preprints' list): sequential numeric ID watermarking.
  2. bioRxiv/medRxiv (fields.json 'preprint_categories' dict): date-based watermarking.

Output: one JSON file per field at {output_dir}/{field}_preprints.json
NBER/CEPR papers use 'preprint_source' so they join the arXiv triage pool.
bioRxiv/medRxiv papers use 'source' = "bioRxiv"/"medRxiv" (routed to arXiv pool in run_pipeline.py).

Usage:
    python fetch_preprints.py --fields econ-political --output-dir data/2026-05-05
    python fetch_preprints.py --fields systems-biology --output-dir data/2026-05-25
    python fetch_preprints.py --fields systems-biology --output-dir data/... --no-advance-watermark
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

BIORXIV_FEED = "https://connect.biorxiv.org/biorxiv_xml.php?subject={subject}"
MEDRXIV_FEED = "https://connect.medrxiv.org/medrxiv_xml.php?subject={subject}"


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


def fetch_bio_preprints(field: str, field_config: dict, watermarks: dict) -> list[dict]:
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
        has_nber = bool(field_config.get("preprints"))
        has_bio = bool(field_config.get("preprint_categories"))
        if not has_nber and not has_bio:
            log.info("Field '%s': no preprints configured — skipping.", field)
            continue

        papers: list[dict] = []
        if has_nber:
            papers.extend(fetch_field_preprints(field, field_config, watermarks))
        if has_bio:
            papers.extend(fetch_bio_preprints(field, field_config, watermarks))

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
