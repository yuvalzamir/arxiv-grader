#!/usr/bin/env python3
"""
Retry the daily pipeline for users that failed in a previous run.

Steps:
  1. Parse daily.log to find users marked as failed for the target date.
  2. For each failed user, verify that their field's merged papers file
     exists in the shared data folder (data/DATE/{field}_today_papers.json).
  3. Call run_all_users.py --no-fetch --no-journals --user <list> --date DATE
     so that existing arXiv + journal JSON files are reused without re-scraping.

Usage:
  python run_failed_users.py                    # retry failed users from today's log
  python run_failed_users.py --date 2026-04-15  # specific date
  python run_failed_users.py --no-email         # skip email (testing)
  python run_failed_users.py --no-batch         # use direct API for scoring
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

BASE_DIR  = Path(__file__).parent
USERS_DIR = BASE_DIR / "users"
LOG_FILE  = Path("/var/log/arxiv-grader/daily.log")


def parse_failed_users(log_file: Path, date_str: str) -> list[str]:
    """
    Return usernames that failed for the given date.

    Primary source: the printed run summary block (last occurrence whose
    surrounding log context contains the target date). This captures both
    triage-failed and scoring-failed users.

    Fallback: scan for 'Skipped — triage failed' log lines stamped with
    the target date (used when the process crashed before the summary printed).
    """
    text  = log_file.read_text(errors="replace")
    lines = text.splitlines()

    # --- Primary: parse the last run summary block for this date ---
    # The summary is printed (no timestamp), so we find the last occurrence
    # of "Run summary" that appears after a log line stamped with date_str.
    last_date_line = -1
    for i, line in enumerate(lines):
        if line.startswith(date_str):
            last_date_line = i

    summary_start = None
    for i, line in enumerate(lines):
        if i > last_date_line:
            break
        if "Run summary" in line and "Weekly" not in line:
            summary_start = i

    if summary_start is not None:
        failed: list[str] = []
        # Skip the two separator lines (==== Run summary ====)
        for line in lines[summary_start + 2:]:
            m = re.match(r"^\s+(\S+)\s+(OK|FAILED)\s*$", line)
            if m:
                if m.group(2) == "FAILED":
                    failed.append(m.group(1))
            elif line.strip() == "" or line.startswith("="):
                continue
            else:
                break  # end of summary block
        if failed:
            return failed

    # --- Fallback: scan for triage-skipped log lines ---
    pattern = re.compile(r"--- \[(.+?)\] Skipped — triage failed")
    failed = []
    seen: set[str] = set()
    for line in lines:
        if not line.startswith(date_str):
            continue
        m = pattern.search(line)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            failed.append(m.group(1))
    return failed


def check_data_ready(username: str, date_str: str) -> bool:
    """
    Return True if the field's merged papers file exists for this user.
    That file is written by run_all_users.py before triage and is required
    for a retry run.
    """
    profile_path = USERS_DIR / username / "taste_profile.json"
    if not profile_path.exists():
        return False
    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    field = profile.get("field")
    if not field:
        return False
    merged = BASE_DIR / "data" / date_str / f"{field}_today_papers.json"
    return merged.exists()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Retry the daily pipeline for users that failed in a previous run."
    )
    parser.add_argument(
        "--date", default=None,
        help="Date to retry (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument("--no-email", action="store_true", help="Skip email delivery.")
    parser.add_argument("--no-batch", action="store_true", help="Use direct API instead of Batch API.")
    parser.add_argument(
        "--log", default=str(LOG_FILE),
        help=f"Path to the daily log file (default: {LOG_FILE}).",
    )
    args = parser.parse_args()

    date_str = args.date or date.today().isoformat()
    log_file = Path(args.log)

    if not log_file.exists():
        print(f"Error: log file not found: {log_file}", file=sys.stderr)
        sys.exit(1)

    # Step 1: find failed users
    failed = parse_failed_users(log_file, date_str)
    if not failed:
        print(f"No failed users found in log for {date_str}.")
        sys.exit(0)
    print(f"Failed users for {date_str}: {', '.join(failed)}")

    # Step 2: check data readiness
    retryable   = [u for u in failed if check_data_ready(u, date_str)]
    unretryable = [u for u in failed if u not in retryable]

    if unretryable:
        print(f"Skipping (merged papers file missing): {', '.join(unretryable)}")
    if not retryable:
        print("No users have data ready for retry.")
        sys.exit(0)
    print(f"Retrying: {', '.join(retryable)}")

    # Step 3: delegate to run_all_users.py
    cmd = [
        sys.executable, str(BASE_DIR / "run_all_users.py"),
        "--no-fetch", "--no-journals",
        "--date", date_str,
        "--user", *retryable,
    ]
    if args.no_email:
        cmd.append("--no-email")
    if args.no_batch:
        cmd.append("--no-batch")

    sys.exit(subprocess.run(cmd, cwd=str(BASE_DIR)).returncode)


if __name__ == "__main__":
    main()
