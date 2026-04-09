#!/usr/bin/env python3
"""
run_weekly_digest.py — Weekly digest email for a single user.

Scans the last 7 days of scored_papers.json files, collects all papers with
score >= 8, deduplicates, builds a PDF, and emails it to EMAIL_TO_WEEKLY
(falls back to EMAIL_TO).

Called automatically by run_all_users.py on the user's chosen weekly_day.

Usage:
    python run_weekly_digest.py --user-dir users/alice
    python run_weekly_digest.py --user-dir users/alice --date 2026-04-11
    python run_weekly_digest.py --user-dir users/alice --no-email
"""

import argparse
import json
import logging
import os
import smtplib
import subprocess
import sys
from datetime import date, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # root .env first; user .env loaded after arg parsing

BASE_DIR  = Path(__file__).parent
MIN_SCORE = 8

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
# Paper collection
# ---------------------------------------------------------------------------

def collect_weekly_papers(data_dir: Path, today_str: str) -> list[dict]:
    """
    Scan the last 7 days (including today) of scored_papers.json files.
    Return all papers with score >= MIN_SCORE, deduplicated by paper_id
    (highest score wins; earliest date breaks ties).
    """
    today = date.fromisoformat(today_str)
    dates = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]

    seen: dict[str, dict] = {}  # paper_id → best entry so far

    for day_str in dates:
        scored_path = data_dir / day_str / "scored_papers.json"
        if not scored_path.exists():
            continue
        try:
            papers = json.loads(scored_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not read %s: %s", scored_path, exc)
            continue

        for paper in papers:
            score = paper.get("score", 0) or 0
            try:
                score = int(score)
            except (TypeError, ValueError):
                score = 0
            if score < MIN_SCORE:
                continue

            pid = paper.get("paper_id") or paper.get("arxiv_id", "")
            if not pid:
                continue

            if pid not in seen or score > (seen[pid].get("score") or 0):
                seen[pid] = paper

    papers_out = sorted(seen.values(), key=lambda p: -(p.get("score") or 0))
    return papers_out


# ---------------------------------------------------------------------------
# Email delivery
# ---------------------------------------------------------------------------

def send_weekly_email(
    pdf_path: Path,
    start_date: str,
    end_date: str,
    username: str,
    paper_count: int,
) -> None:
    """Send the weekly PDF digest via SMTP."""
    raw = os.environ.get("EMAIL_TO_WEEKLY") or os.environ.get("EMAIL_TO", "")
    to_addr = [a.strip() for a in raw.split(",") if a.strip()]
    if not to_addr:
        log.error("Neither EMAIL_TO_WEEKLY nor EMAIL_TO is set in the user's .env")
        sys.exit(1)

    subject = f"Incoming Science Weekly — {start_date} to {end_date}"
    body = (
        f"Your weekly scientific literature digest is attached.\n\n"
        f"User: {username}\n"
        f"Period: {start_date} to {end_date}\n"
        f"Papers: {paper_count} (all scored {MIN_SCORE}+)\n\n"
        f"Tap the rating buttons on papers that catch your eye.\n"
    )

    msg = MIMEMultipart()
    msg["From"]    = _EMAIL_FROM
    msg["To"]      = ", ".join(to_addr)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with open(pdf_path, "rb") as f:
        attachment = MIMEApplication(f.read(), _subtype="pdf")
    attachment.add_header(
        "Content-Disposition", "attachment",
        filename=f"weekly_digest_{end_date}_{username}.pdf",
    )
    msg.attach(attachment)

    log.info("Connecting to SMTP %s:%d...", _SMTP_HOST, _SMTP_PORT)
    with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(_SMTP_USER, _SMTP_PASSWORD)
        server.sendmail(_EMAIL_FROM, to_addr, msg.as_string())

    log.info("Weekly email sent to %s.", to_addr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Send weekly digest email for one user."
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
        help="Build PDF but skip sending the email (testing).",
    )
    args = parser.parse_args()

    user_dir = Path(args.user_dir)
    if not user_dir.is_dir():
        log.error("User directory not found: %s", user_dir)
        sys.exit(1)

    load_dotenv(user_dir / ".env", override=True)

    # Re-read SMTP vars after user .env is loaded (in case they differ).
    global _SMTP_HOST, _SMTP_PORT, _SMTP_USER, _SMTP_PASSWORD, _EMAIL_FROM
    _SMTP_HOST     = os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")
    _SMTP_PORT     = int(os.environ.get("EMAIL_SMTP_PORT", "587"))
    _SMTP_USER     = os.environ.get("EMAIL_SMTP_USER", "")
    _SMTP_PASSWORD = os.environ.get("EMAIL_SMTP_PASSWORD", "")
    _EMAIL_FROM    = os.environ.get("EMAIL_FROM", "")

    username  = user_dir.name
    data_dir  = user_dir / "data"
    today_str = args.date or date.today().isoformat()

    log.info("=== Weekly digest — %s [user: %s] ===", today_str, username)

    # Collect papers scored >= 8 from the past 7 days.
    papers = collect_weekly_papers(data_dir, today_str)
    log.info("Collected %d paper(s) with score >= %d over the past 7 days.", len(papers), MIN_SCORE)

    if not papers:
        log.info("No papers scored %d+ this week — skipping weekly email.", MIN_SCORE)
        return

    # Determine date range label for the email subject.
    start_date = (date.fromisoformat(today_str) - timedelta(days=6)).isoformat()

    # Write the weekly papers JSON to today's data folder.
    today_dir = data_dir / today_str
    today_dir.mkdir(parents=True, exist_ok=True)
    weekly_papers_path = today_dir / "weekly_papers.json"
    weekly_papers_path.write_text(
        json.dumps(papers, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info("Wrote %d papers to %s", len(papers), weekly_papers_path)

    # Build PDF.
    pdf_path = today_dir / "weekly_digest.pdf"
    rating_base_url = os.environ.get("RATING_BASE_URL", "").strip()
    pdf_cmd = [
        sys.executable, str(BASE_DIR / "build_digest_pdf.py"),
        "--scored",  str(weekly_papers_path),
        "--papers",  str(weekly_papers_path),
        "--output",  str(pdf_path),
        "--user",    username,
        "--weekly",
    ]
    if rating_base_url:
        pdf_cmd += ["--base-url", rating_base_url]

    log.info("Building weekly PDF...")
    result = subprocess.run(pdf_cmd, cwd=str(BASE_DIR), capture_output=True, text=True)
    if result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            log.info("[pdf] %s", line)
    if result.stderr.strip():
        for line in result.stderr.strip().splitlines():
            log.info("[pdf] %s", line)
    if result.returncode != 0:
        log.error("PDF build failed (exit code %d) — aborting weekly email.", result.returncode)
        sys.exit(result.returncode)

    if not pdf_path.exists():
        log.error("PDF not found after build step: %s", pdf_path)
        sys.exit(1)

    log.info("Weekly PDF built: %s", pdf_path)

    # Send email.
    if args.no_email:
        log.info("[email] Skipped (--no-email).")
    else:
        send_weekly_email(pdf_path, start_date, today_str, username, len(papers))

    log.info("=== Weekly digest complete for %s [user: %s] ===", today_str, username)


if __name__ == "__main__":
    main()
