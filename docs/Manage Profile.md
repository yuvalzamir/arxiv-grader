# Manage Profile

[[Home]] | [[User Onboarding]] | [[Taste Profile]] | [[Profile Edit Skill]]

Design doc: `user_self_service_design.md`
Skills: `.claude/skills/edit-profile-from-file.md` · `.claude/skills/edit-profile.md`

---

## Overview

Self-service page at `incomingscience.xyz/manage` that lets existing users update delivery frequency and submit free-text interest changes. No password — identified by email only.

Linked from the landing page as a **"Manage my Profile"** button (secondary style, alongside "Register for Access").

---

## User Flow

```
User visits /manage
  → enters any registered email (slug email OR any EMAIL_TO/EMAIL_TO_DAILY/EMAIL_TO_WEEKLY from .env)
  → POST /manage/lookup
  → if found: shows current settings
  → if not found: same "not found" message (avoids email enumeration)

Settings page shows:
  - Field (read-only chip)
  - Frequency section: daily toggle, weekly toggle, day-of-week picker
    - "Revert" button resets to server values (no network call)
    - "Save frequency" button → POST /manage/update-frequency
    - Both-off warning if user disables both digests
  - Feedback section: free-text box (max 5000 chars, rate-limited 1/24h)
    - "Send feedback" button → POST /manage/submit-feedback
    - Locks on 200; shows inline error and stays editable on failure
    - If pending feedback already exists: shows "pending" notice, hides box
```

---

## Flask Endpoints (`server.py`)

| Route | Method | Purpose |
|-------|--------|---------|
| `/manage` | GET | Serves `manage_final/code.html` |
| `/manage/lookup` | POST | Email lookup → returns current settings |
| `/manage/update-frequency` | POST | Writes daily/weekly/weekly_day to `taste_profile.json` |
| `/manage/submit-feedback` | POST | Appends to `pending_profile_update.txt`, sends notification email |

### Email lookup (`_find_user_by_email`)

Two-step lookup:
1. Derive slug from email (`re.sub(r"[^a-z0-9]+", "-", email)`). Check if `users/<slug>/taste_profile.json` exists.
2. If not found: scan all `users/*/.env` files for `EMAIL_TO`, `EMAIL_TO_DAILY`, `EMAIL_TO_WEEKLY`. Values are comma-separated — each address is checked individually. First match wins.

This means any email address that receives digests for a user (including CC recipients) can access that user's manage page.

### Frequency update

Flask writes directly to `taste_profile.json` under `_write_lock`. No separate script. Validates `weekly_day` against a known set.

### Feedback submission

- Rate limit: 1 submission per 24h. Enforced by parsing the last `[YYYY-MM-DDTHH:MM:SSZ]` timestamp in `pending_profile_update.txt`.
- Appends a timestamped block (never overwrites).
- Sends notification email to operator with the feedback text.
- Returns 429 with message if rate-limited.

---

## Feedback File Format

```
users/<slug>/pending_profile_update.txt
```

```
[2026-05-28T15:30:00Z]
I've shifted focus toward quantum error correction...

---
[2026-05-29T10:00:00Z]
Also now following work by John Preskill closely.

---
```

---

## Operator Processing of Feedback

When a feedback notification email arrives, run the skill:

```
/edit-profile-from-file <slug>
```

The skill (`edit-profile-from-file.md`):
1. Asks operator to SCP down `taste_profile.json` + `pending_profile_update.txt`
2. Reads both files
3. Proposes a patch (new keywords, grade adjustments, appended interests description)
4. Asks operator to confirm
5. Writes updated `taste_profile.json`
6. Asks operator to SCP it back up and delete `pending_profile_update.txt` on server

**Claude never runs scp/ssh/rm itself** — always prints commands for the operator to execute.

---

## Website File

```
website/stitch_platform_user_expansion/manage_final/code.html  →  /manage
```

Tailwind CSS design system matches the onboarding pages. Two-phase UI: email lookup phase, then settings phase (hidden until lookup succeeds).

---

## Key Constraints

- No password / auth token — trust email input. Acceptable given low sensitivity of exposed data (delivery prefs) and operator review of all profile changes.
- Frequency changes are immediate (Flask writes directly); profile changes are always operator-reviewed.
- `pending_profile_update.txt` deleted after successful operator processing — clears the "pending" notice on the manage page.
