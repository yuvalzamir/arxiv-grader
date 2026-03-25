#!/usr/bin/env python3
"""
deduplicate_ratings.py — Remove duplicate ratings, keeping the last one per paper.

If a paper was rated more than once (e.g. "good" then "excellent"), only the
most recent rating is kept. Processes the previous day's ratings by default.

Usage:
    python deduplicate_ratings.py                   # yesterday (called by run_daily.py)
    python deduplicate_ratings.py --date 2026-03-17 # specific date
"""

import json
import argparse
from datetime import date, timedelta
from pathlib import Path

_DEFAULT_DATA_DIR = Path(__file__).parent / "data"


def deduplicate(date_str: str, data_dir: Path | None = None) -> tuple[int, int]:
    """
    Deduplicate ratings.json for a given date. Last rating per paper_id wins.
    Returns (original_count, final_count).
    """
    if data_dir is None:
        data_dir = _DEFAULT_DATA_DIR
    ratings_path = data_dir / date_str / "ratings.json"

    if not ratings_path.exists():
        print(f"{date_str}: no ratings.json found — skipping.")
        return 0, 0

    ratings = json.loads(ratings_path.read_text(encoding="utf-8"))
    original_count = len(ratings)

    # Walk in chronological order; each paper_id overwrites the previous entry.
    seen: dict[str, dict] = {}
    for entry in ratings:
        seen[entry["paper_id"]] = entry

    deduplicated = list(seen.values())
    final_count = len(deduplicated)
    removed = original_count - final_count

    if removed == 0:
        print(f"{date_str}: no duplicates ({original_count} ratings).")
        return original_count, final_count

    ratings_path.write_text(
        json.dumps(deduplicated, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"{date_str}: removed {removed} duplicate(s) — {final_count} ratings kept.")
    return original_count, final_count


def main():
    p = argparse.ArgumentParser(
        description="Deduplicate ratings.json, keeping the last rating per paper."
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

    data_dir = (Path(args.user_dir) / "data") if args.user_dir else None
    date_str = args.date or (date.today() - timedelta(days=1)).isoformat()
    deduplicate(date_str, data_dir=data_dir)


if __name__ == "__main__":
    main()
