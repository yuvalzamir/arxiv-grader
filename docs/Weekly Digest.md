# Weekly Digest

[[Home]] | [[Daily Digest]] | [[Pipeline Overview]] | [[Taste Profile]]

Full design: `weekly_digest_design.md`

---

## Overview

A weekly email containing only papers scored ≥8 from the past 7 days. Independent of the daily digest — each user configures their delivery mode in `taste_profile.json`.

The daily pipeline (fetch, triage, score, PDF build) **runs every day regardless** of delivery mode. Only the email send is conditional.

---

## Delivery Modes

```json
"daily_digest": true,
"weekly_digest": false,
"weekly_day": "friday"
```

| daily_digest | weekly_digest | Gets |
|---|---|---|
| true | false | Daily email (default) |
| false | true | Weekly email on chosen day only |
| true | true | Both emails |
| false | false | No emails (still scored/PDFs built) |

All combinations are valid. Backward-compatible: existing users without these fields default to `daily_digest: true`.

---

## Mailing Lists

Daily and weekly emails can go to different recipients:
```
EMAIL_TO_DAILY=alice@lab.org
EMAIL_TO_WEEKLY=group@lab.org,bob@lab.org
```
Both fall back to `EMAIL_TO` if not set.

---

## Weekly Digest Logic (`run_weekly_digest.py`)

1. Determine 7-day window: `[today - 6 days, today]`
2. Scan `users/<name>/data/YYYY-MM-DD/scored_papers.json` for each date in the window
3. Collect all papers with `score >= 8`
4. Deduplicate by `paper_id` — keep highest score if duplicated; if equal, keep earliest date
5. Sort by score descending
6. Write to `users/<name>/data/TODAY/weekly_papers.json`
7. If no papers collected → log warning, exit (no email sent)
8. Build PDF via `build_digest_pdf.py`
9. Send to `EMAIL_TO_WEEKLY` (or fallback)

**Email subject:** `"Incoming Science Weekly — {start_date} to {end_date}"`

**Rating URLs:** All use today's date (the send date), not the paper's original date. This means late ratings land in `data/FRIDAY/ratings.json` and archive correctly the next morning.

---

## Weekend-Only Cron

For users who want a Saturday or Sunday weekly digest, a separate cron runs `run_weekly_only.py`:

```bash
30 1 * * 0,6  python run_weekly_only.py  # Sat/Sun 01:30 ET
```

This skips the full pipeline (no arXiv fetch, no journal scraping, no triage, no scoring). It only runs the weekly digest phase for users whose `weekly_day` matches today.

```bash
python run_weekly_only.py                # auto-detect today's weekday
python run_weekly_only.py --user alice   # force regardless of weekly_day
```

---

## Integration in `run_all_users.py`

After all daily runs complete (full `ThreadPoolExecutor` shutdown), a weekly dispatch phase runs:

```python
today_weekday = date.today().strftime("%A").lower()
weekly_users = [u for u in user_dirs
                if profile.get("weekly_digest", False)
                and profile.get("weekly_day", "friday") == today_weekday]
# Run weekly digest for each in parallel
```

**Ordering guarantee:** Daily emails are always sent before weekly emails on the same day.

---

## Refiner Adjustment for Weekly-Only Users

When `daily_digest: false` and `weekly_digest: true`, the monthly refiner:
- **Suppresses** `missed-*` and `underscored` discrepancy buckets (structurally impossible — user only sees papers scored ≥8)
- **Adds** a weekly-only mode note to the refiner message
- **Treats** signals conservatively (fewer total ratings by design)

Detection:
```python
weekly_only = (not profile.get("daily_digest", True)
               and profile.get("weekly_digest", False))
```
