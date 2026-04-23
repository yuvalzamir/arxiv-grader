#!/usr/bin/env python3
"""
One-off migration: add created_at to all existing taste_profile.json files.

All users get today's date (treated as new, enters weekly refiner track)
except yuval, who gets 9 weeks ago (already established, biweekly only).

Run once on the server:
    python migrate_created_at.py
"""

import json
from datetime import date, timedelta
from pathlib import Path

USERS_DIR = Path(__file__).parent / "users"
TODAY = date.today()
NINE_WEEKS_AGO = (TODAY - timedelta(weeks=9)).isoformat()
TODAY_ISO = TODAY.isoformat()

OVERRIDES = {
    "yuval": NINE_WEEKS_AGO,
}

for user_dir in sorted(USERS_DIR.iterdir()):
    profile_path = user_dir / "taste_profile.json"
    if not profile_path.exists():
        continue

    profile = json.loads(profile_path.read_text(encoding="utf-8"))

    if "created_at" in profile:
        print(f"  {user_dir.name:30s} already has created_at={profile['created_at']} — skipping")
        continue

    created_at = OVERRIDES.get(user_dir.name, TODAY_ISO)
    profile["created_at"] = created_at
    profile_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  {user_dir.name:30s} created_at set to {created_at}")

print("Done.")
