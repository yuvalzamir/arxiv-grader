#!/usr/bin/env python3
"""
scripts/patch_area_keyword_map.py — One-time migration for existing users.

Adds area_keyword_map to taste_profile.json for users who were onboarded
before refiner v2. Uses a Haiku call to assign each keyword to its areas.

Idempotent: skips users who already have area_keyword_map.

Usage:
    python scripts/patch_area_keyword_map.py
    python scripts/patch_area_keyword_map.py --user yuval
    python scripts/patch_area_keyword_map.py --dry-run
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

BASE_DIR  = Path(__file__).parent.parent
USERS_DIR = BASE_DIR / "users"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def build_area_keyword_map(keywords: list[dict], areas: list[dict], client: Anthropic) -> list[dict]:
    """Haiku call: assign each keyword to the areas it semantically belongs to."""
    kw_list   = "\n".join(f"  - {kw['keyword']}" for kw in keywords) or "  (none)"
    area_list = "\n".join(f"  - {a['area']}"     for a  in areas)    or "  (none)"

    prompt = (
        f"You are building a keyword-to-area mapping for a researcher's taste profile.\n\n"
        f"Research areas:\n{area_list}\n\n"
        f"Keywords:\n{kw_list}\n\n"
        f"For each area, list which keywords semantically belong to it. "
        f"A keyword may belong to multiple areas. Use exact keyword names as given. "
        f"Return JSON only:\n"
        f'{{"area_keyword_map": [{{"area": "<area name>", "keywords": ["<keyword>", ...]}}]}}'
    )

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text.strip()
    log.info("  Haiku response: %d input tokens, %d output tokens.",
             response.usage.input_tokens, response.usage.output_tokens)

    for candidate in [text, "\n".join(l for l in text.splitlines() if not l.startswith("```")).strip()]:
        try:
            result    = json.loads(candidate)
            area_map  = result.get("area_keyword_map", [])
            mapped    = {e["area"] for e in area_map}
            for a in areas:
                if a["area"] not in mapped:
                    area_map.append({"area": a["area"], "keywords": []})
            return area_map
        except (json.JSONDecodeError, KeyError):
            pass

    log.warning("  Failed to parse Haiku response — initialising empty map.")
    return [{"area": a["area"], "keywords": []} for a in areas]


def patch_user(user_dir: Path, client: Anthropic, dry_run: bool) -> bool:
    profile_path = user_dir / "taste_profile.json"
    if not profile_path.exists():
        log.warning("[%s] taste_profile.json not found — skipping.", user_dir.name)
        return False

    profile = json.loads(profile_path.read_text(encoding="utf-8"))

    if "area_keyword_map" in profile:
        log.info("[%s] area_keyword_map already present — skipping.", user_dir.name)
        return True

    keywords = profile.get("keywords", [])
    areas    = profile.get("research_areas", [])

    if not keywords or not areas:
        log.warning("[%s] No keywords or areas found — writing empty map.", user_dir.name)
        area_map = [{"area": a["area"], "keywords": []} for a in areas]
    else:
        log.info("[%s] Building area_keyword_map (%d keywords, %d areas)...",
                 user_dir.name, len(keywords), len(areas))
        area_map = build_area_keyword_map(keywords, areas, client)

    # Show what would be written.
    for entry in area_map:
        log.info("  %s → %s", entry["area"], entry["keywords"])

    if dry_run:
        log.info("[%s] Dry run — taste_profile.json NOT updated.", user_dir.name)
        return True

    profile["area_keyword_map"] = area_map
    profile_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("[%s] taste_profile.json updated.", user_dir.name)
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Backfill area_keyword_map for existing users."
    )
    parser.add_argument("--user", default=None, help="Patch a single user only (e.g. --user yuval).")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing.")
    args = parser.parse_args()

    if not USERS_DIR.is_dir():
        log.error("users/ directory not found at %s", USERS_DIR)
        sys.exit(1)

    if args.user:
        user_dirs = [USERS_DIR / args.user]
        if not user_dirs[0].is_dir():
            log.error("User '%s' not found under %s", args.user, USERS_DIR)
            sys.exit(1)
    else:
        user_dirs = sorted(
            d for d in USERS_DIR.iterdir()
            if d.is_dir() and (d / "taste_profile.json").exists()
        )

    if not user_dirs:
        log.warning("No users found.")
        sys.exit(0)

    # Load per-user API key from user .env, fallback to root .env.
    client = Anthropic()

    ok = 0
    for user_dir in user_dirs:
        env_file = user_dir / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=True)
            client = Anthropic()
        if patch_user(user_dir, client, dry_run=args.dry_run):
            ok += 1

    log.info("Done: %d/%d user(s) processed.", ok, len(user_dirs))


if __name__ == "__main__":
    main()
