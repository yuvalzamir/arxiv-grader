#!/usr/bin/env python3
"""
run_weekly_only.py — Weekend weekly digest runner.

Runs ONLY the weekly digest phase for users whose weekly_day matches today.
No fetching, triage, scoring, or PDF building for daily papers — purely
collects already-scored papers from the past 7 days and emails the digest.

Intended for the weekend cron (Saturday and Sunday). On weekdays the weekly
digest phase is handled at the end of run_all_users.py.

Usage:
    python run_weekly_only.py                    # all users whose weekly_day = today
    python run_weekly_only.py --user alice       # single user (ignores weekly_day check)
    python run_weekly_only.py --date 2026-04-19  # override today's date
    python run_weekly_only.py --no-email         # build PDFs but skip sending
"""

import argparse
import json
import logging
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR  = Path(__file__).parent
USERS_DIR = BASE_DIR / "users"

load_dotenv(BASE_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def discover_users(only: str | None = None) -> list[Path]:
    """Return user directories under users/ that contain taste_profile.json."""
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


def run_for_user(user_dir: Path, extra_args: list[str]) -> bool:
    """Run run_weekly_digest.py for one user. Returns True on success."""
    cmd = [
        sys.executable, str(BASE_DIR / "run_weekly_digest.py"),
        "--user-dir", str(user_dir),
    ] + extra_args
    log.info("--- [%s] Starting weekly digest ---", user_dir.name)
    result = subprocess.run(cmd, cwd=str(BASE_DIR))
    if result.returncode != 0:
        log.error("--- [%s] FAILED (exit code %d) ---", user_dir.name, result.returncode)
        return False
    log.info("--- [%s] Done ---", user_dir.name)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send weekly digest emails for users whose weekly_day matches today."
    )
    parser.add_argument(
        "--user", default=None,
        help="Run for a single user by name (skips weekly_day check).",
    )
    parser.add_argument(
        "--date", default=None,
        help="Override today's date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--no-email", action="store_true",
        help="Build PDFs but skip sending emails (testing).",
    )
    args = parser.parse_args()

    today_str  = args.date or date.today().isoformat()
    today_date = date.fromisoformat(today_str)
    today_weekday = today_date.strftime("%A").lower()  # e.g. "saturday"

    all_users = discover_users(only=args.user)

    # If --user was given, skip the weekly_day check and run unconditionally.
    if args.user:
        weekly_users = all_users
        log.info(
            "=== run_weekly_only [%s] — forced for user: %s ===",
            today_str, args.user,
        )
    else:
        weekly_users = []
        for user_dir in all_users:
            try:
                profile = json.loads((user_dir / "taste_profile.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                log.warning("Could not read profile for %s: %s", user_dir.name, exc)
                continue
            if not profile.get("weekly_digest", False):
                continue
            if profile.get("weekly_day", "friday") != today_weekday:
                continue
            weekly_users.append(user_dir)

        log.info(
            "=== run_weekly_only [%s] (%s) — %d user(s) scheduled ===",
            today_str, today_weekday, len(weekly_users),
        )

    if not weekly_users:
        log.info("No users scheduled for weekly digest today — exiting.")
        return

    log.info("Users: %s", [u.name for u in weekly_users])

    # Build extra args to pass through to run_weekly_digest.py
    extra_args: list[str] = []
    if args.no_email:
        extra_args.append("--no-email")
    if args.date:
        extra_args += ["--date", args.date]

    # Run all eligible users in parallel.
    results: dict[str, bool] = {}
    with ThreadPoolExecutor(max_workers=len(weekly_users)) as executor:
        futures = {
            executor.submit(run_for_user, u, extra_args): u.name
            for u in weekly_users
        }
        for future in as_completed(futures):
            results[futures[future]] = future.result()

    print()
    print("=" * 50)
    print("  Weekly digest summary")
    print("=" * 50)
    for name, ok in sorted(results.items()):
        print(f"  {name:20s}  {'OK' if ok else 'FAILED'}")
    print()

    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
