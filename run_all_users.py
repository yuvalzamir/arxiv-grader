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
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from email.mime.text import MIMEText
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


class TokenBucketOrchestrator:
    """
    Central rate-limit guard for all Anthropic cached API calls across all
    fields and users.

    The cached API has a 50k input-token-per-minute (ITPM) limit shared
    across the entire organisation. Only cache_creation tokens count;
    cache_read tokens are free. This orchestrator serialises cached calls
    so we never exceed the limit.

    Two call types:
      cache_write (is_cache_write=True):  first user in a field — creates the
          cache entry, costs full estimated_tokens.  The orchestrator waits until
          the bucket has enough capacity, deducts the tokens, then returns.
      cache_read  (is_cache_write=False): subsequent users — free ITPM, but we
          hold the lock for CACHE_READ_HOLD seconds so Claude has time to register
          the preceding cache_write before this read request arrives.
    """
    CAPACITY        = 50_000
    REFILL_RATE     = 50_000 / 60   # tokens per second
    BUFFER_SECS     = 5.0
    CACHE_READ_HOLD = 1.0            # seconds to hold lock for cache reads

    def __init__(self):
        self.bucket      = self.CAPACITY
        self.last_update = time.monotonic()
        self.lock        = threading.Lock()

    def _refill(self):
        """Must be called with lock held."""
        now = time.monotonic()
        self.bucket = min(
            self.CAPACITY,
            self.bucket + (now - self.last_update) * self.REFILL_RATE,
        )
        self.last_update = now

    def acquire(self, tokens: int, is_cache_write: bool) -> None:
        if not is_cache_write:
            # Hold lock for CACHE_READ_HOLD so Claude registers the preceding
            # cache_write before this read request arrives.
            with self.lock:
                self._refill()
                time.sleep(self.CACHE_READ_HOLD)
            return

        # cache_write: wait until bucket has enough tokens, then deduct.
        while True:
            with self.lock:
                self._refill()
                if self.bucket >= tokens:
                    self.bucket -= tokens
                    return
                deficit   = tokens - self.bucket
                wait_secs = deficit / self.REFILL_RATE + self.BUFFER_SECS
            log.info(
                "Orchestrator: bucket low (%d tokens available, %d needed) — waiting %.1fs.",
                int(self.bucket), tokens, wait_secs,
            )
            time.sleep(wait_secs)
            # Loop — re-check after sleep; another thread may have consumed tokens.


def discover_users(only: list[str] | None = None) -> list[Path]:
    """
    Return user directories under users/ that contain taste_profile.json.
    If `only` is given, return only those users' directories.
    """
    if not USERS_DIR.is_dir():
        log.error("users/ directory not found at %s", USERS_DIR)
        sys.exit(1)

    users = sorted(
        d for d in USERS_DIR.iterdir()
        if d.is_dir() and (d / "taste_profile.json").exists()
    )

    if only:
        matches = [u for u in users if u.name in only]
        missing = set(only) - {u.name for u in matches}
        for name in missing:
            log.warning("User '%s' not found under %s — skipping.", name, USERS_DIR)
        if not matches:
            log.error("None of the specified users found under %s", USERS_DIR)
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
    url_tag_filters = {j["url"]: j["tag_filter"] for j in field_config["journals"]}
    result = []
    for paper in scraped_papers:
        feed_url = paper.get("feed_url", "")
        if feed_url not in url_tag_filters:
            # Feed URL not in this field's config — exclude it
            keep = False
        elif url_tag_filters[feed_url] is None:
            keep = True
        else:
            tag_filter = url_tag_filters[feed_url]
            paper_tags = [t.lower() for t in paper.get("subject_tags", [])]
            keep = any(f.lower() in tag for f in tag_filter for tag in paper_tags)

        if keep:
            result.append({k: v for k, v in paper.items() if k != "subject_tags"})

    return result


def cleanup_old_shared_folders(keep_days: int = 3) -> None:
    """Delete shared data/YYYY-MM-DD folders older than keep_days."""
    shared_root = BASE_DIR / "data"
    if not shared_root.exists():
        return
    cutoff = date.today().toordinal() - keep_days
    for folder in shared_root.iterdir():
        if not folder.is_dir():
            continue
        try:
            folder_date = date.fromisoformat(folder.name)
        except ValueError:
            continue
        if folder_date.toordinal() < cutoff:
            shutil.rmtree(folder)
            log.info("Removed old shared data folder: %s", folder)


def run_journal_scrape(date_str: str, active_fields: list[str], shared_data_dir: Path, no_advance_watermark: bool = False) -> Path | None:
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
    if no_advance_watermark:
        cmd.append("--no-advance-watermark")
    log.info("Running journal scrape for fields: %s", active_fields)
    result = subprocess.run(cmd, cwd=str(BASE_DIR))
    if result.returncode != 0:
        log.warning("fetch_journals.py failed — all users will get arXiv-only today.")
        return None
    return scraped_path


def run_arxiv_fetch(field: str, field_config: dict, date_str: str, shared_data_dir: Path) -> Path | None:
    """
    Fetch arXiv papers for a field once, shared across all users in that field.
    Supports multiple arXiv categories via 'arxiv_categories' (list) in fields.json;
    falls back to 'arxiv_category' (string) for backward compatibility.
    Papers from all categories are merged and deduplicated by arxiv_id.
    Returns path to {field}_arxiv_papers.json on success, None on failure.
    """
    # Normalize to list — support both old string and new list form.
    raw = field_config.get("arxiv_categories") or field_config.get("arxiv_category") or field
    categories = [raw] if isinstance(raw, str) else list(raw)

    output_path = shared_data_dir / f"{field}_arxiv_papers.json"
    all_papers: list[dict] = []
    seen_ids: set[str] = set()

    for category in categories:
        tmp_path = shared_data_dir / f"{field}_arxiv_{category.replace('/', '_')}_tmp.json"
        cmd = [
            sys.executable, str(BASE_DIR / "fetch_papers.py"),
            "-o", str(tmp_path),
            "-c", category,
        ]
        log.info("Fetching arXiv papers for field '%s' (category: %s)...", field, category)
        result = subprocess.run(cmd, cwd=str(BASE_DIR))
        if result.returncode != 0:
            log.warning("fetch_papers.py failed for field '%s', category '%s'.", field, category)
            return None
        papers = json.loads(tmp_path.read_text())
        tmp_path.unlink(missing_ok=True)
        before = len(all_papers)
        for paper in papers:
            pid = paper.get("arxiv_id", "")
            if pid not in seen_ids:
                seen_ids.add(pid)
                all_papers.append(paper)
        log.info(
            "Category '%s': %d papers fetched, %d new after dedup (total: %d).",
            category, len(papers), len(all_papers) - before, len(all_papers),
        )

    output_path.write_text(json.dumps(all_papers, indent=2, ensure_ascii=False))
    return output_path


def run_centralized_triage(
    field: str,
    user_dirs: list[Path],
    papers: list[dict],
    date_str: str,
    no_batch: bool = False,
    orchestrator: "TokenBucketOrchestrator | None" = None,
) -> dict[str, bool]:
    """
    Run triage for all users in a field in parallel.

    The merged paper list (arXiv + journals) is the cached prefix — identical for
    all users in the field. Each user's taste profile is the non-cached per-user suffix.

    Rate-limit timing is managed centrally by the TokenBucketOrchestrator, which
    serialises all cached API calls across all fields and users. Batch API calls
    are unaffected and run immediately.

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

    CACHED_BUDGET = 45_000
    arxiv_papers   = [p for p in papers if not p.get("source")]
    journal_papers = [p for p in papers if p.get("source")]

    arxiv_tokens   = len(json.dumps(arxiv_papers))   // 4
    journal_tokens = len(json.dumps(journal_papers)) // 4

    base_batch = len(user_dirs) < 4 and not no_batch

    # Force Batch API for any individual call that exceeds the token budget.
    arxiv_overflow   = arxiv_tokens   > CACHED_BUDGET
    journal_overflow = journal_tokens > CACHED_BUDGET

    use_batch_arxiv    = base_batch or arxiv_overflow
    use_batch_journals = base_batch or journal_overflow

    if arxiv_overflow:
        log.warning("Field '%s': arXiv ~%d tokens > %dk — forcing Batch API for arXiv triage.", field, arxiv_tokens, CACHED_BUDGET // 1000)
    if journal_overflow:
        log.warning("Field '%s': journals ~%d tokens > %dk — forcing Batch API for journal triage.", field, journal_tokens, CACHED_BUDGET // 1000)

    log.info(
        "Field '%s': %d user(s) — triage mode: arXiv=%s  journals=%s  (orchestrator-managed)",
        field, len(user_dirs),
        "batch" if use_batch_arxiv else "cached",
        "batch" if use_batch_journals else "cached",
    )

    def _triage_one(i: int, user_dir: Path) -> tuple[str, bool]:
        log.info("--- [%s] Triage starting ---", user_dir.name)
        try:
            profile   = json.loads((user_dir / "taste_profile.json").read_text(encoding="utf-8"))
            today_dir = user_dir / "data" / date_str
            today_dir.mkdir(parents=True, exist_ok=True)

            filtered = run_triage(
                papers, profile,
                triage_prompt, triage_journal_prompt,
                debug_dir=today_dir,
                api_key=api_key,
                use_batch_arxiv=use_batch_arxiv,
                use_batch_journals=use_batch_journals,
                orchestrator=orchestrator,
                is_first_user=(i == 0),
            )

            filtered_path = today_dir / "filtered_papers.json"
            with open(filtered_path, "w", encoding="utf-8") as f:
                json.dump(filtered, f, indent=2, ensure_ascii=False)
            log.info("--- [%s] Triage done: %d papers passed ---", user_dir.name, len(filtered))
            return user_dir.name, True
        except Exception as e:
            log.error("--- [%s] Triage FAILED: %s ---", user_dir.name, e)
            return user_dir.name, False

    results: dict[str, bool] = {}
    with ThreadPoolExecutor(max_workers=len(user_dirs)) as executor:
        futures = [executor.submit(_triage_one, i, u) for i, u in enumerate(user_dirs)]
        for future in as_completed(futures):
            name, ok = future.result()
            results[name] = ok

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


def _send_run_summary(results: dict[str, bool], date_str: str) -> None:
    """Email the run summary table to the operator after every full pipeline run."""
    smtp_host = os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("EMAIL_SMTP_PORT", "587"))
    smtp_user = os.environ.get("EMAIL_SMTP_USER", "")
    smtp_pass = os.environ.get("EMAIL_SMTP_PASSWORD", "")
    from_addr = os.environ.get("EMAIL_FROM", smtp_user)
    to_addr   = "yuval.zamir@icfo.eu"

    ok_users     = [u for u, ok in results.items() if ok]
    failed_users = [u for u, ok in results.items() if not ok]

    lines = [f"Run date: {date_str}", ""]
    lines.append(f"{'User':<22} {'Status'}")
    lines.append("-" * 32)
    for name, ok in sorted(results.items()):
        lines.append(f"{name:<22} {'OK' if ok else 'FAILED'}")
    lines += [
        "",
        f"Total: {len(ok_users)} OK, {len(failed_users)} FAILED",
        "",
        "Full logs: /var/log/arxiv-grader/daily.log",
    ]
    body = "\n".join(lines)

    all_ok = not failed_users
    subject = (
        f"[Incoming Science] Run complete — {date_str} — all OK"
        if all_ok else
        f"[Incoming Science] Run complete — {date_str} — {len(failed_users)} FAILED"
    )

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"]    = from_addr
    msg["To"]      = to_addr

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_addr, [to_addr], msg.as_string())
        log.info("Run summary emailed to %s", to_addr)
    except Exception as e:
        log.error("Failed to send run summary: %s", e)


def main():
    parser = argparse.ArgumentParser(
        description="Run the daily pipeline or monthly refiner for all users."
    )
    parser.add_argument(
        "--refine", action="store_true",
        help="Run monthly profile refiner instead of daily pipeline.",
    )
    parser.add_argument(
        "--user", nargs="+", default=None,
        help="Run for specific user(s) only (e.g. --user alice bob).",
    )
    # Daily pipeline flags (passed through to run_daily.py)
    parser.add_argument("--no-email",     action="store_true", help="Skip email delivery.")
    parser.add_argument("--date",         default=None,        help="Override today's date (YYYY-MM-DD).")
    parser.add_argument("--keep-days",    type=int, default=None, help="Days of data folders to keep.")
    parser.add_argument("--skip-dedup",   action="store_true", help="Skip deduplication step.")
    parser.add_argument("--skip-archive", action="store_true", help="Skip archive step.")
    parser.add_argument("--no-journals",  action="store_true", help="Skip journal scraping.")
    parser.add_argument("--no-advance-watermark", action="store_true", help="Scrape journals using existing watermarks but do not save updates (useful for re-runs).")
    parser.add_argument("--no-fetch",     action="store_true", help="Skip arXiv fetch — expect {field}_arxiv_papers.json to already exist in shared data dir (useful for weekend testing).")
    parser.add_argument("--triage-only",  action="store_true", help="Stop after centralized triage — skip scoring, PDF, and email (useful for testing triage/caching).")
    parser.add_argument("--no-batch",     action="store_true", help="Use synchronous API for scoring instead of Batch API.")
    parser.add_argument("--score-only",   action="store_true", help="Skip fetch, triage, dedup, and archive — run scoring/PDF/email only. Requires filtered_papers.json to already exist for the user+date.")
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

    if not args.refine and not args.score_only:
        shared_data_dir.mkdir(parents=True, exist_ok=True)

        # Snapshot watermarks at the start of the run — useful for manual recovery
        # if a re-run is needed and watermarks have already advanced.
        watermarks_src = BASE_DIR / "journal_watermarks.json"
        if watermarks_src.exists():
            shutil.copy2(watermarks_src, shared_data_dir / "journal_watermarks_snapshot.json")

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
            scraped_path = run_journal_scrape(date_str, fields_with_papers, shared_data_dir, no_advance_watermark=args.no_advance_watermark)
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

        # Step 3: Merge arXiv + journals per field, then run triage for all fields
        # in parallel. All cached API calls across all fields share one orchestrator
        # that enforces the org-level 50k ITPM rate limit.
        orchestrator = TokenBucketOrchestrator()

        def _run_field_triage(field: str) -> tuple[dict[str, Path], dict[str, bool]]:
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

            field_user_papers = {u.name: merged_path for u in field_users}
            triage_results = run_centralized_triage(
                field, field_users, merged_papers, date_str,
                no_batch=args.no_batch, orchestrator=orchestrator,
            )
            return field_user_papers, triage_results

        with ThreadPoolExecutor(max_workers=len(fields_with_papers)) as executor:
            field_futures = {executor.submit(_run_field_triage, f): f for f in fields_with_papers}
            for future in as_completed(field_futures):
                field = field_futures[future]
                try:
                    field_user_papers, triage_results = future.result()
                    user_papers.update(field_user_papers)
                    for user_name, ok in triage_results.items():
                        if not ok:
                            triage_failed.add(user_name)
                except Exception as e:
                    log.error("Field '%s' triage FAILED: %s", field, e)
                    triage_failed.update(u.name for u in users if user_fields[u.name] == field)

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
        if args.score_only:
            base_extra_args += ["--skip-dedup", "--skip-archive"]

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

    # Clean up shared data folders older than 3 days (keeps today's for --no-fetch re-runs).
    try:
        cleanup_old_shared_folders(keep_days=3)
    except Exception as e:
        log.error("Shared folder cleanup failed: %s", e)

    # --- Weekly digest phase: runs after all daily work is complete ---
    # Only triggered on non-refine, non-triage-only runs. Each user's weekly_day
    # is compared against today; on a match the weekly digest is sent.
    if not args.refine and not args.triage_only:
        today_weekday = (date.fromisoformat(args.date) if args.date else date.today()).strftime("%A").lower()
        weekly_users = []
        for user_dir in users:
            profile_data = json.loads((user_dir / "taste_profile.json").read_text(encoding="utf-8"))
            if not profile_data.get("weekly_digest", False):
                continue
            if profile_data.get("weekly_day", "friday") != today_weekday:
                continue
            weekly_users.append(user_dir)

        if weekly_users:
            log.info(
                "Weekly digest day (%s) — sending weekly emails for %d user(s): %s",
                today_weekday, len(weekly_users), [u.name for u in weekly_users],
            )
            weekly_extra = []
            if args.no_email:
                weekly_extra.append("--no-email")
            if args.date:
                weekly_extra += ["--date", args.date]

            weekly_results: dict[str, bool] = {}
            with ThreadPoolExecutor(max_workers=len(weekly_users)) as executor:
                futures = {
                    executor.submit(run_for_user, u, "run_weekly_digest.py", weekly_extra): u.name
                    for u in weekly_users
                }
                for future in as_completed(futures):
                    weekly_results[futures[future]] = future.result()

            print()
            print("=" * 50)
            print("  Weekly digest summary")
            print("=" * 50)
            for name, ok in weekly_results.items():
                print(f"  {name:20s}  {'OK' if ok else 'FAILED'}")
            print()

            if not all(weekly_results.values()):
                results.update({k: False for k, v in weekly_results.items() if not v})

    # Send run summary email (full runs only — skip single-user and --no-email runs).
    # Sent after the weekly phase so weekly delivery results are included.
    if not args.refine and not args.user and not args.no_email:
        _send_run_summary(results, args.date or date.today().isoformat())

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
