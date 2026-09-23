# Profile Edit Skill

[[Home]] | [[Taste Profile]] | [[Monthly Refiner]] | [[User Onboarding]] | [[Manage Profile]]

Skill files: `.claude/skills/edit-profile.md` · `.claude/skills/edit-profile-from-file.md` (variant — see [[#Variant: edit-profile-from-file]])

---

## Purpose

A Claude Code skill for incorporating free-text user feedback into a `taste_profile.json`. Used when a digest user communicates new interests, shifts in focus, or corrections — without waiting for the next monthly refiner cycle.

**Invoke with:** `/edit-profile` or phrases like "update profile from feedback", "incorporate user input into profile".

---

## When to Use

| Situation | Use |
|-----------|-----|
| User emails or messages about new research interests | This skill |
| User's ratings are drifting from their scores | [[Monthly Refiner]] (automatic) |
| Brand-new user being set up | [[User Onboarding]] |
| Profile feels stale after a topic pivot | This skill |
| User submitted feedback via the `/manage` page | `edit-profile-from-file` variant |

The key difference from the monthly refiner: **this skill takes explicit user input** (their words), while the refiner infers from implicit behavior (paper ratings vs scores).

---

## Flow

```
1. Identify user (from command or ask)
2. Pull authoritative profile from server (SCP)
3. Read taste_profile.json
4. Fetch pending_profile_update.txt from server (SCP), or ask for manual paste if absent
5. Claude analyzes feedback → patch plan
6. Print full change summary (confirm before writing)
7. Write updated profile
8. Print SCP deploy command
```

---

## What Claude Does in Step 5

Claude reads the feedback against the current profile and produces a patch covering three categories:

### A. New items to add

Extracts topics, techniques, and authors not already in the profile. Assigns grades based on phrasing:

| Phrasing | Grade |
|----------|-------|
| "I work on / central to my research" | 1 |
| "very interested in / actively following" | 2 |
| "interested in / want to learn more about" | 3 |
| "curious about / tangentially relevant" | 4 |
| "mentioned in passing / not sure yet" | 5 |

New authors are appended after the existing lowest rank.

### B. Grade adjustments to existing items

Only adjusts items **explicitly mentioned** in the feedback. Maximum shift ±3, clamped to 1–7. Shift size reflects phrasing strength:

| Phrasing | Shift |
|----------|-------|
| "now central / main focus" | toward 1 by 2–3 |
| "much more interested than before" | toward 1 by 1–2 |
| "less relevant now" | toward 7 by 1–2 |
| "no longer relevant / moved away from" | toward 7 by 2–3 |

Each adjustment is recorded with the exact quote that justified it.

### C. Interests description update

Appends **only the genuinely new content** from the feedback (not verbatim repetition of what's already there), with a `[YYYY-MM-DD]` date stamp.

`area_keyword_map` is updated consistently with any added/removed keywords or areas.

---

## Key Design Principles

- **Additive by default** — existing keywords, areas, and authors are never touched unless explicitly mentioned in the feedback
- **Conservative on grade shifts** — operator guidance may further restrict changes when feedback is known to be heavily duplicative of existing content
- **Human confirmation before write** — full change summary is printed and confirmed before any file is modified
- **Server copy is authoritative** — always pull from server before editing (refiner may have updated the profile between sessions)

---

## Change Summary Format

```
Profile patch for users/<name>/taste_profile.json
==================================================

KEYWORDS
  + added:   "privacy issues in LLM-generated applications"   grade 2  (new)
  ~ adjusted: "altermagnetism"    grade 4 → 2  | "altermagnetism is now a main focus of my lab"

RESEARCH AREAS
  + added:   "Quantum optics"     grade 3  (new)

AUTHORS
  + added:   "Jun Ye"             rank 30 (appended)

INTERESTS DESCRIPTION
  ~ appended [2026-05-27] one sentence capturing new content

AREA_KEYWORD_MAP
  ~ updated accordingly

NO CHANGES to: <list of untouched elements>
```

---

## Relationship to Monthly Refiner

The monthly refiner and this skill are **complementary, not competing**:

- Refiner: implicit signal (ratings) → conservative ±1 grade/month shifts
- This skill: explicit signal (user words) → up to ±3 grade shifts, new items added immediately

Both update `keywords`, `research_areas`, `authors`, and `area_keyword_map`. Neither touches `liked_papers`.

If a user's topic pivot is large enough that the monthly refiner would take months to catch up, use this skill first to realign the profile, then let the refiner maintain it from there.

---

## Variant: edit-profile-from-file

Skill file: `.claude/skills/edit-profile-from-file.md` · invoke: `/edit-profile-from-file <slug>`

For feedback submitted through the [[Manage Profile]] page (`/manage/submit-feedback`), which appends timestamped blocks to `users/<slug>/pending_profile_update.txt` on the server.

**Flow:**
```
1. Identify slug (from command, or Glob users/*/pending_profile_update.txt and ask)
2. Operator SCPs down taste_profile.json + pending_profile_update.txt
3. Read profile
4. Read pending file — all [ISO-timestamp] blocks concatenated; newest block wins on contradiction
5. Patch (same A/B/D logic as above)
6. Change summary → operator confirms
7. Write profile
8. Operator SCPs profile up, then deletes the pending file on server + locally
```

**Differences from `/edit-profile`:**
- Feedback source is always the pending file (no pasted text).
- **Interests description: appends the raw feedback verbatim** under a `---` / `[YYYY-MM-DD]` separator, rather than distilling only the new content.
- **Extra cleanup step**: deleting `pending_profile_update.txt` on the server clears the "feedback pending" notice on `/manage` and resets the 24h submission rate-limit anchor. Skipping it leaves the user seeing "pending" indefinitely.

**Plain `/edit-profile` for `/manage` feedback:** `/edit-profile` can also fetch the pending file (Step 4 fallback), but it does not include the server-side delete. Use it that way only if you then delete the file by hand.

---

## Invocation caveat

Both skills (plus `check-log.md`, `new-field.md`) are flat files in `.claude/skills/`. Claude Code only registers skills stored as `.claude/skills/<name>/SKILL.md`, so these do **not** show up as `/` commands. For now, invoke them by asking Claude to "follow `.claude/skills/<file>.md`". (Noted 2026-09-23.)
