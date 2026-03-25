#!/usr/bin/env python3
"""
archive.py — Append deduplicated daily ratings to the permanent archive.

Reads data/DATE/ratings.json and appends any new entries to archive.json,
skipping entries already present (identified by paper_id + date).

Usage:
    python archive.py                   # yesterday (called by run_daily.py)
    python archive.py --date 2026-03-17 # specific date
"""

import json
import argparse
from datetime import date, timedelta
from pathlib import Path

_DEFAULT_DATA_DIR    = Path(__file__).parent / "data"
_DEFAULT_ARCHIVE_PATH = Path(__file__).parent / "archive.json"


def load_archive(archive_path: Path) -> list[dict]:
    try:
        return json.loads(archive_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as exc:
        print(f"WARNING: archive.json is malformed ({exc}). Starting fresh.")
        return []


def archive_date(
    date_str: str,
    data_dir: Path | None = None,
    archive_path: Path | None = None,
) -> tuple[int, int]:
    """
    Append ratings for date_str to archive.json. Last-rating-per-paper wins
    (same deduplication guarantee as deduplicate_ratings.py).
    Returns (new_entries_added, already_present).
    """
    if data_dir is None:
        data_dir = _DEFAULT_DATA_DIR
    if archive_path is None:
        archive_path = _DEFAULT_ARCHIVE_PATH
    ratings_path = data_dir / date_str / "ratings.json"

    if not ratings_path.exists():
        print(f"{date_str}: no ratings.json found — skipping.")
        return 0, 0

    daily = json.loads(ratings_path.read_text(encoding="utf-8"))
    if not daily:
        print(f"{date_str}: ratings.json is empty — skipping.")
        return 0, 0

    existing = load_archive(archive_path)

    # Build a set of (paper_id, date) pairs already in the archive.
    already_archived = {
        (e["paper_id"], e.get("date", ""))
        for e in existing
    }

    added = 0
    skipped = 0
    for entry in daily:
        key = (entry["paper_id"], entry.get("date", date_str))
        if key in already_archived:
            skipped += 1
        else:
            existing.append(entry)
            already_archived.add(key)
            added += 1

    if added:
        archive_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    print(f"{date_str}: added {added} new rating(s) to archive"
          + (f" ({skipped} already present)." if skipped else "."))
    return added, skipped


def main():
    p = argparse.ArgumentParser(
        description="Append daily ratings to the permanent archive.json."
    )
    p.add_argument(
        "--date", default=None,
        help="Date folder to process (YYYY-MM-DD). Defaults to yesterday.",
    )
    p.add_argument(
        "--user-dir", default=None,
        help="User directory (e.g. users/alice). Defaults to project root.",
    )
    args = p.parse_args()

    data_dir = archive_path = None
    if args.user_dir:
        base = Path(args.user_dir)
        data_dir = base / "data"
        archive_path = base / "archive.json"

    date_str = args.date or (date.today() - timedelta(days=1)).isoformat()
    archive_date(date_str, data_dir=data_dir, archive_path=archive_path)


if __name__ == "__main__":
    main()
