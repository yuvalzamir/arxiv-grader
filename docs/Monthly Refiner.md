# Monthly Profile Refiner

[[Home]] | [[Taste Profile]] | [[Profile Edit Skill]] | [[AI Pipeline]]

Full design: `refiner_v2_design.md`

---

## Overview

Runs on the 2nd and 16th of each month. Reads the past ~17 days of ratings from `archive.json`, calls Claude Sonnet (Batch API) to recommend keyword/author grade changes, then calls Haiku for area management.

**Key principle:** Grade changes are **±1 per month maximum**. Claude signals direction only ("up" or "down"); Python applies the ±1 rule and clamps to 1–7.

---

## Rating Flow (Daily)

```
User taps rating button in PDF
        ↓
server.py writes to data/DATE/ratings.json
        ↓
Next morning: deduplicate_ratings.py → archive.py
        ↓
archive.json (permanent, append-only)
        ↓
Monthly refiner reads last ~17 days
```

---

## Discrepancy Buckets

Python pre-classifies rating discrepancies into 5 buckets before calling Claude:

| Bucket | Condition | Signal |
|--------|-----------|--------|
| `overconfident-high` | Scored ≥7, rated Irrelevant | Strong negative |
| `overconfident-mild` | Scored ≥8, rated Good | Mild overconfidence |
| `missed-excellent` | Not triaged or scored ≤3, rated Excellent | Missed strong signal |
| `missed-good` | Not triaged or scored ≤3, rated Good | Missed mild signal |
| `underscored` | Scored 4–6, rated Excellent | Systematic undervaluing |

Claude identifies which keywords/areas drove each mismatch and recommends grade adjustments.

---

## Refiner v2 — Two-Call Architecture

### Call 1: Main Refiner (Sonnet, Batch API)

Input: archive ratings, discrepancy analysis, full profile.

Output schema (`schemas/refiner_output_schema.json`):
```json
{
  "keyword_grade_changes": [{"keyword": "...", "direction": "up|down", "reason": "..."}],
  "new_keywords": [{"keyword": "...", "suggested_grade": 3|4|5, "areas": ["..."], "reason": "..."}],
  "new_authors": [{"name": "...", "reason": "..."}],
  "evolved_interests": "Updated rolling narrative paragraph"
}
```

Does **not** touch research areas (that's Call 2).

### Call 2: Area Management (Haiku, Synchronous)

A separate, cheap call decoupled from paper ratings. Input: keyword list with grades + pre-computed support ratios.

Output schema (`schemas/area_management_schema.json`):
```json
{
  "area_grade_changes": [{"area": "...", "direction": "up|down", "reason": "..."}],
  "new_areas": [{"area": "...", "suggested_grade": 3|4|5, "supporting_keywords": [...], "reason": "..."}]
}
```

**Caps:** max 1 area grade change + max 1 new area per run.

---

## Support Ratio Formula

Python pre-computes these before the Haiku call. Haiku receives the ratios as input and only makes judgment calls.

```
keyword_weight = (8 - keyword_grade) / 7
effective_support = sum(keyword_weight for keywords in area)
relative_support = effective_support / total_keywords
support_ratio = relative_support / (8 - area_grade)^1.5
```

**Grade-1 areas are excluded from gap detection** (they naturally accumulate many keywords, distorting comparisons).

A DOWN recommendation is made when the weakest area's support ratio is ~2× below the next weakest. An UP recommendation when the top-ranked area is well above areas at a higher importance level (lower grade number).

---

## Keyword/Area Removal Rules

**Keywords:** Grade-7 keywords that were **already at grade 7 before the current run** are removed. Keywords that reach grade 7 during the run get one more month.

**Areas:** Grade-7 areas are only removed if:
- Condition A: ≤2 keywords are associated with the area in `area_keyword_map`
- Condition B: None of those keywords has grade ≤3 (no active keyword still supports it)

Both conditions must be met. If either fails, the area stays at grade 7 for another month.

---

## Weekly-Only Mode

When a user has `daily_digest: false` and `weekly_digest: true`, the refiner automatically:
- Suppresses `missed-*` and `underscored` discrepancy buckets (structurally impossible — user only sees papers scored ≥8)
- Adds a note to the refiner message explaining the filtered view
- Treats borderline signals conservatively (lower rating volume by design)

---

## Grade Change Sequencing

```
1.  Load archive, profile, recent ratings
2.  Snapshot pre-run grade-7 keywords and areas
3.  Call main refiner (Sonnet, Batch API, structured outputs)
4.  Apply keyword grade changes (±1, clamped 1–7)
5.  Add new keywords → update area_keyword_map
6.  Add new authors
7.  Update evolved_interests
8.  Call area management (Haiku, synchronous)
9.  Apply area grade changes (±1, clamped 1–7)
10. Add new areas → update area_keyword_map
11. Remove grade-7 keywords (pre-run snapshot)
12. Remove grade-7 areas (safety check on area_keyword_map)
13. Write profile to disk
```

---

## Running the Refiner

```bash
python run_all_users.py --refine           # all users
python run_all_users.py --refine --dry-run # preview only, no writes
python run_all_users.py --refine --user alice  # single user
```

Minimum 5 ratings required to run the refiner for a user. If fewer, the user is skipped with a warning.

---

## Cost (Refiner v2)

| Step | Model | Cost |
|------|-------|------|
| Main refiner | Sonnet Batch | ~$0.006/user |
| Area management | Haiku sync | ~$0.00008/user |
