#!/usr/bin/env python3
"""
run_all_users.py — Run the daily pipeline (or monthly refiner) for all users.

Discovers all user directories under users/ (any subdirectory containing
taste_profile.json) and runs the appropriate script for each, sequentially.
A failure for one user is logged but does not abort the remaining users.

Usage:
    python run_all_users.py                         # run daily pipeline for all users
    python run_all_users.py --no-email              # skip email (testing)
    python run_all_users.py --date 2026-03-19       # override today's date
    python run_all_users.py --no-journals           # skip journal scraping
    python run_all_users.py --refine                # run monthly profile refiner instead
    python run_all_users.py --refine --dry-run      # dry run of refiner
    python run_all_users.py --user alice            # run for a single user only
"""

import argparse
import json
import logging
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

BASE_DIR  = Path(__file__).parent
USERS_DIR = BASE_DIR / "users"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def discover_users(only: str | None = None) -> list[Path]:
    """
    Return user directories under users/ that contain taste_profile.json.
    If `only` is given, return only that user's directory (or exit if not found).
    """
    if not USERS_DIR.is_dir():
        log.error("users/ directory not found at %s", USERS_DIR)
        sys.exit(1)

    users = sorted(
        d for d in USERS_DIR.iterdir()
        if d.is_dir() and (d / "taste_profile.json").exists()
    )

    if only:
        matches = [u for u in users if u.name == only]
        if not matches:
            log.error("User '%s' not found under %s", only, USERS_DIR)
            sys.exit(1)
        return matches

    return users


def _user_field(user_dir: Path) -> str:
    """Return the field name from a user's taste_profile.json, defaulting to 'cond-mat'."""
    with open(user_dir / "taste_profile.json") as f:
        return json.load(f).get("field", "cond-mat")


def filter_for_field(scraped_papers: list[dict], field_config: dict) -> list[dict]:
    """
    Filter scraped journal papers for a specific field and strip subject_tags.

    tag_filter: null  → field-specific journal, keep all papers from it.
    tag_filter: [...]  → general journal, keep only papers whose subject_tags
                         contain at least one case-insensitive substring match.
    """
    journal_tag_filters = {j["name"]: j["tag_filter"] for j in field_config["journals"]}
    result = []
    for paper in scraped_papers:
        source = paper.get("source", "")
        if source not in journal_tag_filters:
            # Unknown source — keep it to be safe
            keep = True
        elif journal_tag_filters[source] is None:
            keep = True
        else:
            tag_filter = journal_tag_filters[source]
            paper_tags = [t.lower() for t in paper.get("subject_tags", [])]
            keep = any(f.lower() in tag for f in tag_filter for tag in paper_tags)

        if keep:
            result.append({k: v for k, v in paper.items() if k != "subject_tags"})

    return result


def run_journal_scrape(date_str: str, active_fields: list[str], shared_data_dir: Path) -> Path | None:
    """
    Run fetch_journals.py once for all active fields.
    Returns path to scraped_journals.json on success, None on failure.
    """
    scraped_path = shared_data_dir / "scraped_journals.json"
    cmd = [
        sys.executable, str(BASE_DIR / "fetch_journals.py"),
        "--fields", *active_fields,
        "--output", str(scraped_path),
    ]
    log.info("Running journal scrape for fields: %s", active_fields)
    result = subprocess.run(cmd, cwd=str(BASE_DIR))
    if result.returncode != 0:
        log.warning("fetch_journals.py failed — all users will get arXiv-only today.")
        return None
    return scraped_path


def run_for_user(user_dir: Path, script: str, extra_args: list[str]) -> bool:
    """Run a script for one user. Returns True on success, False on failure."""
    cmd = [sys.executable, str(BASE_DIR / script), "--user-dir", str(user_dir)] + extra_args
    log.info("--- [%s] Starting ---", user_dir.name)
    result = subprocess.run(cmd, cwd=str(BASE_DIR))
    if result.returncode != 0:
        log.error("--- [%s] FAILED (exit code %d) ---", user_dir.name, result.returncode)
        return False
    log.info("--- [%s] Done ---", user_dir.name)
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Run the daily pipeline or monthly refiner for all users."
    )
    parser.add_argument(
        "--refine", action="store_true",
        help="Run monthly profile refiner instead of daily pipeline.",
    )
    parser.add_argument(
        "--user", default=None,
        help="Run for a single user only (e.g. --user alice).",
    )
    # Daily pipeline flags (passed through to run_daily.py)
    parser.add_argument("--no-email",     action="store_true", help="Skip email delivery.")
    parser.add_argument("--date",         default=None,        help="Override today's date (YYYY-MM-DD).")
    parser.add_argument("--keep-days",    type=int, default=None, help="Days of data folders to keep.")
    parser.add_argument("--skip-dedup",   action="store_true", help="Skip deduplication step.")
    parser.add_argument("--skip-archive", action="store_true", help="Skip archive step.")
    parser.add_argument("--no-journals",  action="store_true", help="Skip journal scraping.")
    # Refiner flags (passed through to run_profile_refiner.py)
    parser.add_argument("--dry-run", action="store_true", help="(refine only) Don't write profile.")
    parser.add_argument("--days",    type=int, default=None, help="(refine only) Days of history to use.")
    args = parser.parse_args()

    users = discover_users(only=args.user)
    if not users:
        log.warning("No user directories found under %s", USERS_DIR)
        sys.exit(0)

    log.info("Found %d user(s): %s", len(users), [u.name for u in users])

    # --- Journal scrape (daily pipeline only) ---
    # Maps user name → path to their field's filtered journal file (or None).
    user_journals: dict[str, Path | None] = {u.name: None for u in users}

    if not args.refine and not args.no_journals:
        date_str = args.date or date.today().isoformat()
        shared_data_dir = BASE_DIR / "data" / date_str
        shared_data_dir.mkdir(parents=True, exist_ok=True)

        user_fields = {u.name: _user_field(u) for u in users}
        active_fields = sorted(set(user_fields.values()))
        log.info("Active fields: %s", active_fields)

        scraped_path = run_journal_scrape(date_str, active_fields, shared_data_dir)

        if scraped_path:
            fields_data = json.loads((BASE_DIR / "fields.json").read_text())
            with open(scraped_path) as f:
                scraped_papers = json.load(f)

            for field in active_fields:
                if field not in fields_data:
                    log.warning("Field '%s' not in fields.json — skipping filter.", field)
                    continue
                filtered = filter_for_field(scraped_papers, fields_data[field])
                field_path = shared_data_dir / f"{field}_journals.json"
                with open(field_path, "w") as f:
                    json.dump(filtered, f, indent=2)
                log.info("Field %s: %d journal papers after filtering.", field, len(filtered))

            for user_name, field in user_fields.items():
                field_path = shared_data_dir / f"{field}_journals.json"
                if field_path.exists():
                    user_journals[user_name] = field_path

    # --- Build per-user args and run ---
    if args.refine:
        script = "run_profile_refiner.py"
        base_extra_args = []
        if args.dry_run:
            base_extra_args.append("--dry-run")
        if args.days is not None:
            base_extra_args += ["--days", str(args.days)]
    else:
        script = "run_daily.py"
        base_extra_args = []
        if args.no_email:
            base_extra_args.append("--no-email")
        if args.date:
            base_extra_args += ["--date", args.date]
        if args.keep_days is not None:
            base_extra_args += ["--keep-days", str(args.keep_days)]
        if args.skip_dedup:
            base_extra_args.append("--skip-dedup")
        if args.skip_archive:
            base_extra_args.append("--skip-archive")

    results: dict[str, bool] = {}
    with ThreadPoolExecutor(max_workers=len(users)) as executor:
        futures = {}
        for user_dir in users:
            extra_args = list(base_extra_args)
            journals_path = user_journals.get(user_dir.name)
            if journals_path:
                extra_args += ["--journals", str(journals_path)]
            futures[executor.submit(run_for_user, user_dir, script, extra_args)] = user_dir.name

        for future in as_completed(futures):
            results[futures[future]] = future.result()

    print()
    print("=" * 50)
    print("  Run summary")
    print("=" * 50)
    for name, ok in results.items():
        print(f"  {name:20s}  {'OK' if ok else 'FAILED'}")
    print()

    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
