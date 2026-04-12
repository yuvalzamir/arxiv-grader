#!/usr/bin/env python3
"""
process_pending.py — Activate a pending web onboarding submission.

Reads users_pending/<slug>/onboarding.json, fetches seed paper metadata,
calls Claude to build a taste_profile.json, creates users/<slug>/ with
.env (EMAIL_TO set; ANTHROPIC_API_KEY left blank for owner to fill in)
and an empty archive.json.

Usage:
    python process_pending.py <slug>      # process one submission
    python process_pending.py --all       # process all unprocessed
    python process_pending.py --list      # list pending submissions
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

# Reuse all heavy-lifting functions from create_profile — no duplication.
from create_profile import (
    fetch_all_papers,
    build_user_message,
    call_llm,
    assemble_profile,
    build_area_keyword_map,
    load_system_prompt,
)

BASE_DIR    = Path(__file__).parent
USERS_DIR   = BASE_DIR / "users"
PENDING_DIR = BASE_DIR / "users_pending"
FIELDS_PATH = BASE_DIR / "fields.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_fields() -> dict:
    return json.loads(FIELDS_PATH.read_text(encoding="utf-8"))



def list_pending() -> list[Path]:
    """Return all pending dirs that have onboarding.json but no processed_at stamp."""
    if not PENDING_DIR.exists():
        return []
    results = []
    for d in sorted(PENDING_DIR.iterdir()):
        ob = d / "onboarding.json"
        if not ob.exists():
            continue
        data = json.loads(ob.read_text(encoding="utf-8"))
        if "processed_at" not in data:
            results.append(d)
    return results


# ---------------------------------------------------------------------------
# Core: process one pending submission
# ---------------------------------------------------------------------------

def process_one(slug: str) -> None:
    pending_dir = PENDING_DIR / slug
    ob_path = pending_dir / "onboarding.json"

    if not ob_path.exists():
        log.error("No onboarding.json found at %s", ob_path)
        sys.exit(1)

    submission = json.loads(ob_path.read_text(encoding="utf-8"))

    if "processed_at" in submission:
        log.warning("Slug %s was already processed at %s — skipping.", slug, submission["processed_at"])
        return

    # ---- Validate field -------------------------------------------------------
    fields = load_fields()
    field = submission.get("field", "")
    if field not in fields:
        log.error("Unknown field %r in submission. Known fields: %s", field, list(fields.keys()))
        sys.exit(1)

    arxiv_categories = fields[field].get("arxiv_categories") or [fields[field].get("arxiv_category", field)]

    # ---- Resolve API key ------------------------------------------------------
    api_key = os.environ.get("ANTHROPIC_API_KEY_ONBOARDING")
    if not api_key:
        log.error("No ANTHROPIC_API_KEY_ONBOARDING found in root .env.")
        sys.exit(1)
    os.environ["ANTHROPIC_API_KEY"] = api_key

    # ---- Build inputs dict (same shape as create_profile.collect_inputs) ------
    inputs = {
        "field":         field,
        "categories":    arxiv_categories,
        "interests_text": submission.get("interests_description", ""),
        "researchers":   submission.get("researchers", []),
        "paper_links":   submission.get("paper_urls", []),
    }

    delivery = {
        "daily_digest":  submission.get("daily_digest", True),
        "weekly_digest": submission.get("weekly_digest", False),
        "weekly_day":    submission.get("weekly_day", "friday"),
    }

    # ---- Fetch seed paper metadata --------------------------------------------
    log.info("Fetching metadata for %d seed paper(s)...", len(inputs["paper_links"]))
    papers = fetch_all_papers(inputs["paper_links"])

    # ---- Claude: build rankings -----------------------------------------------
    system_prompt = load_system_prompt()
    user_message  = build_user_message(inputs, papers)
    rankings      = call_llm(system_prompt, user_message)

    # ---- Assemble profile -----------------------------------------------------
    profile = assemble_profile(rankings, inputs, papers)
    profile.update(delivery)

    # ---- area_keyword_map (Haiku call) ----------------------------------------
    client = Anthropic()
    profile["area_keyword_map"] = build_area_keyword_map(
        profile.get("keywords", []),
        profile.get("research_areas", []),
        client,
    )

    # ---- Create user directory ------------------------------------------------
    user_dir = USERS_DIR / slug
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "data").mkdir(exist_ok=True)

    # taste_profile.json
    profile_path = user_dir / "taste_profile.json"
    profile_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Wrote %s", profile_path)

    # archive.json
    archive_path = user_dir / "archive.json"
    if not archive_path.exists():
        archive_path.write_text("[]", encoding="utf-8")
        log.info("Created empty %s", archive_path)

    # .env  — EMAIL_TO_DAILY / EMAIL_TO_WEEKLY based on digest preferences;
    #         ANTHROPIC_API_KEY left blank for owner to fill in
    env_path = user_dir / ".env"
    env_lines = []
    if delivery["daily_digest"]:
        env_lines.append(f"EMAIL_TO_DAILY={submission['email']}")
    if delivery["weekly_digest"]:
        env_lines.append(f"EMAIL_TO_WEEKLY={submission['email']}")
    env_lines.append("ANTHROPIC_API_KEY=")
    env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    log.info("Wrote %s  (ANTHROPIC_API_KEY is blank — fill in before first run)", env_path)

    # ---- Mark submission as processed -----------------------------------------
    submission["processed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ob_path.write_text(json.dumps(submission, indent=2, ensure_ascii=False), encoding="utf-8")

    log.info("Done. User directory: %s", user_dir)
    log.info("Next step: add ANTHROPIC_API_KEY to %s/.env", user_dir)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Activate pending web onboarding submissions.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("slug", nargs="?", help="Process a single pending slug.")
    group.add_argument("--all",  action="store_true", help="Process all unprocessed submissions.")
    group.add_argument("--list", action="store_true", help="List unprocessed submissions.")
    args = parser.parse_args()

    if args.list:
        pending = list_pending()
        if not pending:
            print("No pending submissions.")
        else:
            print(f"{len(pending)} pending submission(s):")
            for p in pending:
                data = json.loads((p / "onboarding.json").read_text(encoding="utf-8"))
                print(f"  {p.name}  —  {data.get('email', '?')}  —  submitted {data.get('submitted_at', '?')}")
        return

    if args.all:
        pending = list_pending()
        if not pending:
            log.info("No pending submissions to process.")
            return
        for p in pending:
            log.info("Processing %s ...", p.name)
            process_one(p.name)
        return

    if args.slug:
        process_one(args.slug)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
