#!/usr/bin/env python3
"""
run_daily.py — Per-user daily orchestrator (scoring, PDF, email).

Paper fetching and triage are handled upstream by run_all_users.py.
This script receives pre-fetched papers and pre-written filtered_papers.json
and handles the per-user steps: dedup, archive, scoring, PDF, email, cleanup.

Steps (in order):
  1. Deduplicate yesterday's ratings
  2. Archive yesterday's ratings to archive.json
  3. Run scoring pipeline (triage already done; --skip-triage passed automatically)
  4. Build PDF digest
  5. Send PDF by email
  6. Cleanup data folders older than --keep-days days

Requires in .env (or environment):
  ANTHROPIC_API_KEY   — Anthropic API key (used by run_pipeline.py for scoring)
  EMAIL_FROM          — sender address
  EMAIL_TO            — recipient address (your phone/email)
  EMAIL_SMTP_HOST     — SMTP server host (e.g. smtp.gmail.com)
  EMAIL_SMTP_PORT     — SMTP port (default 587, STARTTLS)
  EMAIL_SMTP_USER     — SMTP login username
  EMAIL_SMTP_PASSWORD — SMTP login password / app password
  RATING_BASE_URL     — base URL of the /rate endpoint (e.g. http://redpitaya.local:5000)
"""

import argparse
import json
import logging
import os
import shutil
import smtplib
import subprocess
import sys
from datetime import date, datetime, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # root .env first; user .env loaded after arg parsing

BASE_DIR  = Path(__file__).parent
KEEP_DAYS = 14

# Shared sending account — loaded from root .env, not user-configurable.
_SMTP_HOST     = os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")
_SMTP_PORT     = int(os.environ.get("EMAIL_SMTP_PORT", "587"))
_SMTP_USER     = os.environ.get("EMAIL_SMTP_USER", "")
_SMTP_PASSWORD = os.environ.get("EMAIL_SMTP_PASSWORD", "")
_EMAIL_FROM    = os.environ.get("EMAIL_FROM", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Subprocess runner
# ---------------------------------------------------------------------------

def run(cmd: list[str], step: str) -> None:
    """Run a subprocess, streaming its output to the log. Exits on failure."""
    log.info("[%s] Running: %s", step, " ".join(cmd))
    result = subprocess.run(
        cmd,
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            log.info("[%s] %s", step, line)
    if result.stderr.strip():
        for line in result.stderr.strip().splitlines():
            log.info("[%s] %s", step, line)
    if result.returncode != 0:
        log.error("[%s] FAILED with exit code %d", step, result.returncode)
        sys.exit(result.returncode)


# ---------------------------------------------------------------------------
# Email delivery
# ---------------------------------------------------------------------------

def send_email(pdf_path: Path, today_str: str, username: str) -> None:
    """Send the PDF digest as an email attachment via SMTP (STARTTLS)."""
    to_addr = [a.strip() for a in os.environ.get("EMAIL_TO", "").split(",") if a.strip()]
    if not to_addr:
        log.error("EMAIL_TO is not set in the user's .env")
        sys.exit(1)

    smtp_host = _SMTP_HOST
    smtp_port = _SMTP_PORT
    smtp_user = _SMTP_USER
    smtp_pass = _SMTP_PASSWORD
    from_addr = _EMAIL_FROM

    subject = f"Incoming Science — {today_str}"
    body = (
        f"Your daily scientific literature digest is attached.\n\n"
        f"Digest for: {username}\n"
        f"Date: {today_str}\n"
        f"Open the PDF, tap rating buttons on papers that catch your eye.\n"
    )

    msg = MIMEMultipart()
    msg["From"]    = from_addr
    msg["To"]      = ", ".join(to_addr)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with open(pdf_path, "rb") as f:
        attachment = MIMEApplication(f.read(), _subtype="pdf")
    attachment.add_header(
        "Content-Disposition", "attachment",
        filename=f"arxiv_digest_{today_str}_{username}.pdf",
    )
    msg.attach(attachment)

    log.info("Connecting to SMTP %s:%d...", smtp_host, smtp_port)
    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(smtp_user, smtp_pass)
        server.sendmail(from_addr, to_addr, msg.as_string())

    log.info("Email sent to %s.", to_addr)


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def cleanup_old_folders(data_dir: Path, keep_days: int) -> None:
    """Delete data/YYYY-MM-DD folders older than keep_days days."""
    cutoff = (date.today() - timedelta(days=keep_days)).isoformat()
    if not data_dir.exists():
        return
    removed = 0
    for folder in data_dir.iterdir():
        if folder.is_dir() and folder.name <= cutoff:
            log.info("Cleanup: removing old folder %s", folder.name)
            shutil.rmtree(folder)
            removed += 1
    if removed:
        log.info("Cleanup: removed %d folder(s) older than %d days.", removed, keep_days)
    else:
        log.info("Cleanup: no folders to remove.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Daily arXiv grader orchestrator."
    )
    parser.add_argument(
        "--user-dir", required=True,
        help="User directory (e.g. users/alice). Must contain taste_profile.json and .env.",
    )
    parser.add_argument(
        "--date", default=None,
        help="Override today's date (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--no-email", action="store_true",
        help="Skip email delivery (useful for local testing).",
    )
    parser.add_argument(
        "--keep-days", type=int, default=KEEP_DAYS,
        help=f"Days of data folders to keep (default: {KEEP_DAYS}).",
    )
    parser.add_argument(
        "--skip-dedup", action="store_true",
        help="Skip deduplication of yesterday's ratings.",
    )
    parser.add_argument(
        "--skip-archive", action="store_true",
        help="Skip archiving yesterday's ratings.",
    )
    parser.add_argument(
        "--papers", required=True,
        help="Path to today's merged papers JSON (arXiv + journals, written by run_all_users.py).",
    )
    parser.add_argument(
        "--no-batch", action="store_true",
        help="Use synchronous API for scoring instead of Batch API (faster, no queue, 2x cost).",
    )
    args = parser.parse_args()

    user_dir = Path(args.user_dir)
    if not user_dir.is_dir():
        log.error("User directory not found: %s", user_dir)
        sys.exit(1)

    # Load user's .env — overrides any root-level .env values.
    load_dotenv(user_dir / ".env", override=True)

    username  = user_dir.name
    data_dir  = user_dir / "data"
    profile   = user_dir / "taste_profile.json"

    today_str     = args.date or date.today().isoformat()
    yesterday_str = (datetime.strptime(today_str, "%Y-%m-%d").date() - timedelta(days=1)).isoformat()

    today_dir = data_dir / today_str
    today_dir.mkdir(parents=True, exist_ok=True)

    papers_path   = Path(args.papers)
    filtered_path = today_dir / "filtered_papers.json"
    scored_path   = today_dir / "scored_papers.json"
    pdf_path      = today_dir / "digest.pdf"

    log.info("=== arXiv daily grader — %s [user: %s] ===", today_str, username)

    # ------------------------------------------------------------------
    # Step 1: Deduplicate yesterday's ratings
    # ------------------------------------------------------------------
    if not args.skip_dedup:
        run(
            [sys.executable, "deduplicate_ratings.py",
             "--date", yesterday_str, "--user-dir", str(user_dir)],
            step="dedup",
        )
    else:
        log.info("[dedup] Skipped.")

    # ------------------------------------------------------------------
    # Step 2: Archive yesterday's ratings
    # ------------------------------------------------------------------
    if not args.skip_archive:
        run(
            [sys.executable, "archive.py",
             "--date", yesterday_str, "--user-dir", str(user_dir)],
            step="archive",
        )
    else:
        log.info("[archive] Skipped.")

    # ------------------------------------------------------------------
    # Step 3: Run scoring pipeline (triage already done by run_all_users.py)
    # ------------------------------------------------------------------
    archive_path = user_dir / "archive.json"
    grade_cmd = [
        sys.executable, "run_pipeline.py",
        "--papers",      str(papers_path),
        "--profile",     str(profile),
        "--filtered",    str(filtered_path),
        "--scored",      str(scored_path),
        "--archive",     str(archive_path),
        "--skip-triage",
    ]
    if args.no_batch:
        grade_cmd.append("--no-batch")
    run(grade_cmd, step="grade")

    # ------------------------------------------------------------------
    # Step 4: Build PDF digest
    # ------------------------------------------------------------------
    rating_base_url = os.environ.get("RATING_BASE_URL", "").strip()
    pdf_cmd = [
        sys.executable, "build_digest_pdf.py",
        "--scored",  str(scored_path),
        "--papers",  str(papers_path),
        "--output",  str(pdf_path),
        "--user",    username,
    ]
    if rating_base_url:
        pdf_cmd += ["--base-url", rating_base_url]
    run(pdf_cmd, step="pdf")

    if not pdf_path.exists():
        log.error("PDF not found after build step: %s", pdf_path)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 6: Send email
    # ------------------------------------------------------------------
    if args.no_email:
        log.info("[email] Skipped (--no-email).")
    else:
        send_email(pdf_path, today_str, username)

    # ------------------------------------------------------------------
    # Step 7: Cleanup old data folders
    # ------------------------------------------------------------------
    cleanup_old_folders(data_dir, args.keep_days)

    log.info("=== Daily run complete for %s [user: %s] ===", today_str, username)


if __name__ == "__main__":
    main()
