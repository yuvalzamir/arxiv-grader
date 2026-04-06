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
import os
import shutil
import smtplib
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from email.mime.text import MIMEText
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


def run_arxiv_fetch(field: str, field_config: dict, date_str: str, shared_data_dir: Path) -> Path | None:
    """
    Fetch arXiv papers for a field once, shared across all users in that field.
    Returns path to {field}_arxiv_papers.json on success, None on failure.
    """
    arxiv_category = field_config.get("arxiv_category", field)
    output_path = shared_data_dir / f"{field}_arxiv_papers.json"
    cmd = [
        sys.executable, str(BASE_DIR / "fetch_papers.py"),
        "-o", str(output_path),
        "-c", arxiv_category,
    ]
    log.info("Fetching arXiv papers for field '%s' (category: %s)...", field, arxiv_category)
    result = subprocess.run(cmd, cwd=str(BASE_DIR))
    if result.returncode != 0:
        log.warning("fetch_papers.py failed for field '%s'.", field)
        return None
    return output_path


def run_centralized_triage(
    field: str,
    user_dirs: list[Path],
    papers: list[dict],
    date_str: str,
) -> dict[str, bool]:
    """
    Run triage for all users in a field sequentially using the cached API.

    The merged paper list (arXiv + journals) is the cached prefix — identical for
    all users in the field. Each user's taste profile is the non-cached per-user suffix.
    Sequential execution ensures the first user warms the cache for subsequent users.

    Returns {user_name: success} dict.
    """
    from run_pipeline import run_triage, load_prompt  # noqa: PLC0415

    key_name = f"ANTHROPIC_API_KEY_{field.upper().replace('-', '_')}"
    api_key = os.environ.get(key_name)
    if not api_key:
        log.error("Missing env var %s — cannot run centralized triage for field '%s'.", key_name, field)
        return {u.name: False for u in user_dirs}

    triage_prompt         = load_prompt("triage.txt")
    triage_journal_prompt = load_prompt("triage_journals.txt")

    results = {}
    for user_dir in user_dirs:
        log.info("--- [%s] Triage ---", user_dir.name)
        try:
            profile = json.loads((user_dir / "taste_profile.json").read_text(encoding="utf-8"))
            today_dir = user_dir / "data" / date_str
            today_dir.mkdir(parents=True, exist_ok=True)

            filtered = run_triage(
                papers, profile,
                triage_prompt, triage_journal_prompt,
                debug_dir=today_dir,
                api_key=api_key,
            )

            filtered_path = today_dir / "filtered_papers.json"
            with open(filtered_path, "w", encoding="utf-8") as f:
                json.dump(filtered, f, indent=2, ensure_ascii=False)
            log.info("--- [%s] Triage done: %d papers passed ---", user_dir.name, len(filtered))
            results[user_dir.name] = True
        except Exception as e:
            log.error("--- [%s] Triage FAILED: %s ---", user_dir.name, e)
            results[user_dir.name] = False

    return results


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


def _send_batch_fallback_alert(
    fallback_reports: dict[str, list[dict]],
    results: dict[str, bool],
    date_str: str,
) -> None:
    """Send an alert email when batch API timeouts triggered automatic fallback."""
    smtp_host = os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("EMAIL_SMTP_PORT", "587"))
    smtp_user = os.environ.get("EMAIL_SMTP_USER", "")
    smtp_pass = os.environ.get("EMAIL_SMTP_PASSWORD", "")
    from_addr = os.environ.get("EMAIL_FROM", smtp_user)
    to_addr   = "yuval.zamir@icfo.eu"

    lines = [
        f"Batch API timeout(s) occurred during the {date_str} run.",
        "The pipeline automatically retried with the synchronous API.",
        "",
        "Affected users:",
    ]
    for user, events in fallback_reports.items():
        run_status = "OK" if results.get(user) else "FAILED"
        lines.append(f"\n  {user}  (overall run: {run_status})")
        for ev in events:
            stage = ev.get("stage", "?")
            nb_ok = ev.get("no_batch_succeeded")
            nb_str = "succeeded" if nb_ok else "FAILED"
            lines.append(f"    - {stage}: batch timed out → no-batch {nb_str}")

    lines += ["", f"Full logs: /var/log/arxiv-grader/daily.log"]
    body = "\n".join(lines)

    msg = MIMEText(body)
    msg["Subject"] = f"[Incoming Science] Batch API fallback — {date_str}"
    msg["From"]    = from_addr
    msg["To"]      = to_addr

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_addr, [to_addr], msg.as_string())
        log.info("Batch fallback alert sent to %s", to_addr)
    except Exception as e:
        log.error("Failed to send batch fallback alert: %s", e)


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
    parser.add_argument("--no-fetch",     action="store_true", help="Skip arXiv fetch — expect {field}_arxiv_papers.json to already exist in shared data dir (useful for weekend testing).")
    parser.add_argument("--triage-only",  action="store_true", help="Stop after centralized triage — skip scoring, PDF, and email (useful for testing triage/caching).")
    parser.add_argument("--no-batch",     action="store_true", help="Use synchronous API for scoring instead of Batch API.")
    # Refiner flags (passed through to run_profile_refiner.py)
    parser.add_argument("--dry-run", action="store_true", help="(refine only) Don't write profile.")
    parser.add_argument("--days",    type=int, default=None, help="(refine only) Days of history to use.")
    args = parser.parse_args()

    users = discover_users(only=args.user)
    if not users:
        log.warning("No user directories found under %s", USERS_DIR)
        sys.exit(0)

    log.info("Found %d user(s): %s", len(users), [u.name for u in users])

    # --- Daily pipeline setup: fetch, triage (skipped for refiner) ---
    # Maps user name → path to their field's merged papers (arXiv + journals).
    user_papers: dict[str, Path | None] = {u.name: None for u in users}
    triage_failed: set[str] = set()
    shared_data_dir: Path | None = None

    if not args.refine:
        date_str = args.date or date.today().isoformat()
        shared_data_dir = BASE_DIR / "data" / date_str
        shared_data_dir.mkdir(parents=True, exist_ok=True)

        user_fields  = {u.name: _user_field(u) for u in users}
        active_fields = sorted(set(user_fields.values()))
        fields_data   = json.loads((BASE_DIR / "fields.json").read_text())
        log.info("Active fields: %s", active_fields)

        # Step 1: Fetch arXiv for all fields first — before journal scrape so that
        # an empty feed (holiday or niche field) doesn't advance journal watermarks.
        arxiv_papers_by_field: dict[str, list[dict]] = {}
        for field in active_fields:
            field_users = [u for u in users if user_fields[u.name] == field]

            if args.no_fetch:
                arxiv_path = shared_data_dir / f"{field}_arxiv_papers.json"
                if not arxiv_path.exists():
                    log.error("--no-fetch set but %s not found — skipping field '%s'.", arxiv_path, field)
                    triage_failed.update(u.name for u in field_users)
                    continue
                log.info("Field '%s': --no-fetch — using existing %s.", field, arxiv_path)
            else:
                arxiv_path = run_arxiv_fetch(field, fields_data.get(field, {}), date_str, shared_data_dir)
                if arxiv_path is None:
                    log.warning("Field '%s': arXiv fetch failed — skipping %d user(s).", field, len(field_users))
                    triage_failed.update(u.name for u in field_users)
                    continue

            papers = json.loads(arxiv_path.read_text())
            if not papers:
                log.info("Field '%s': no arXiv papers today — skipping field.", field)
                triage_failed.update(u.name for u in field_users)
                continue

            arxiv_papers_by_field[field] = papers

        # If every field is empty it's a global holiday — exit before journal scrape
        # so watermarks are not advanced for papers that will never be delivered.
        fields_with_papers = list(arxiv_papers_by_field)
        if not fields_with_papers:
            log.info("No arXiv papers in any field today — holiday or off-day. Skipping pipeline.")
            sys.exit(0)

        # Step 2: Journal scraping — only for fields that have arXiv papers.
        if not args.no_journals:
            scraped_path = run_journal_scrape(date_str, fields_with_papers, shared_data_dir)
            if scraped_path:
                with open(scraped_path) as f:
                    scraped_papers = json.load(f)
                for field in fields_with_papers:
                    if field not in fields_data:
                        log.warning("Field '%s' not in fields.json — skipping filter.", field)
                        continue
                    filtered = filter_for_field(scraped_papers, fields_data[field])
                    field_path = shared_data_dir / f"{field}_journals.json"
                    with open(field_path, "w") as f:
                        json.dump(filtered, f, indent=2)
                    log.info("Field '%s': %d journal papers after filtering.", field, len(filtered))

        # Step 3: Merge arXiv + journals and run centralized triage per field.
        for field in fields_with_papers:
            field_users = [u for u in users if user_fields[u.name] == field]
            arxiv_papers = arxiv_papers_by_field[field]

            journal_papers: list[dict] = []
            journals_path = shared_data_dir / f"{field}_journals.json"
            if journals_path.exists():
                journal_papers = json.loads(journals_path.read_text())

            merged_papers = arxiv_papers + journal_papers  # arXiv first
            merged_path = shared_data_dir / f"{field}_today_papers.json"
            merged_path.write_text(json.dumps(merged_papers, indent=2, ensure_ascii=False))
            log.info(
                "Field '%s': %d arXiv + %d journal = %d total papers.",
                field, len(arxiv_papers), len(journal_papers), len(merged_papers),
            )

            for user_dir in field_users:
                user_papers[user_dir.name] = merged_path

            triage_results = run_centralized_triage(field, field_users, merged_papers, date_str)
            for user_name, ok in triage_results.items():
                if not ok:
                    triage_failed.add(user_name)

    # --- Triage-only mode: stop here, skip scoring/PDF/email ---
    if args.triage_only:
        log.info("--triage-only: stopping after triage. filtered_papers.json written per user.")
        for name, failed in [(u.name, u.name in triage_failed) for u in users]:
            log.info("  %-20s  %s", name, "FAILED" if failed else "OK")
        return

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
        if args.no_batch:
            base_extra_args.append("--no-batch")

    results: dict[str, bool] = {}
    with ThreadPoolExecutor(max_workers=len(users)) as executor:
        futures = {}
        for user_dir in users:
            if user_dir.name in triage_failed:
                log.warning("--- [%s] Skipped — triage failed or no papers today ---", user_dir.name)
                results[user_dir.name] = False
                continue
            extra_args = list(base_extra_args)
            papers_path = user_papers.get(user_dir.name)
            if papers_path:
                extra_args += ["--papers", str(papers_path)]
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

    # Clean up shared journal data folder — not needed after all users have run.
    if shared_data_dir and shared_data_dir.exists():
        shutil.rmtree(shared_data_dir)
        log.info("Removed shared data folder: %s", shared_data_dir)

    # Check for batch API fallback reports and send alert if any.
    if not args.refine:
        date_str = args.date or date.today().isoformat()
        fallback_reports: dict[str, list[dict]] = {}
        for user_dir in users:
            fallback_file = user_dir / "data" / date_str / "batch_fallback.json"
            if fallback_file.exists():
                try:
                    fallback_reports[user_dir.name] = json.loads(fallback_file.read_text())
                except Exception:
                    pass
        if fallback_reports:
            _send_batch_fallback_alert(fallback_reports, results, date_str)

    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
