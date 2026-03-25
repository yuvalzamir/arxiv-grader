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
    python run_all_users.py --refine                # run monthly profile refiner instead
    python run_all_users.py --refine --dry-run      # dry run of refiner
    python run_all_users.py --user alice            # run for a single user only
"""

import argparse
import logging
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    parser.add_argument("--no-email",   action="store_true", help="Skip email delivery.")
    parser.add_argument("--date",       default=None,        help="Override today's date (YYYY-MM-DD).")
    parser.add_argument("--keep-days",  type=int, default=None, help="Days of data folders to keep.")
    parser.add_argument("--skip-dedup", action="store_true", help="Skip deduplication step.")
    parser.add_argument("--skip-archive", action="store_true", help="Skip archive step.")
    # Refiner flags (passed through to run_profile_refiner.py)
    parser.add_argument("--dry-run", action="store_true", help="(refine only) Don't write profile.")
    parser.add_argument("--days",    type=int, default=None, help="(refine only) Days of history to use.")
    args = parser.parse_args()

    users = discover_users(only=args.user)
    if not users:
        log.warning("No user directories found under %s", USERS_DIR)
        sys.exit(0)

    log.info("Found %d user(s): %s", len(users), [u.name for u in users])

    if args.refine:
        script = "run_profile_refiner.py"
        extra_args = []
        if args.dry_run:
            extra_args.append("--dry-run")
        if args.days is not None:
            extra_args += ["--days", str(args.days)]
    else:
        script = "run_daily.py"
        extra_args = []
        if args.no_email:
            extra_args.append("--no-email")
        if args.date:
            extra_args += ["--date", args.date]
        if args.keep_days is not None:
            extra_args += ["--keep-days", str(args.keep_days)]
        if args.skip_dedup:
            extra_args.append("--skip-dedup")
        if args.skip_archive:
            extra_args.append("--skip-archive")

    results: dict[str, bool] = {}
    with ThreadPoolExecutor(max_workers=len(users)) as executor:
        futures = {
            executor.submit(run_for_user, user_dir, script, extra_args): user_dir.name
            for user_dir in users
        }
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
