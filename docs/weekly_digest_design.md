# Weekly Digest — Design Document

## Overview

Add support for a **weekly email digest** containing only papers scored ≥ 8 from the past 7 days. This is orthogonal to the existing daily digest: each user independently opts in or out of daily and weekly delivery. A typical use case is a small research group sharing one taste profile, where some members want the daily feed and others prefer a curated weekly summary.

The daily pipeline (fetch, triage, score, PDF build) runs unchanged for all users every day. The only thing that changes is **which emails are sent, and when**.

---

## Profile Changes — `taste_profile.json`

Add three new fields:

```json
"daily_digest": true,
"weekly_digest": false,
"weekly_day": "friday"
```

**Rules:**
- `daily_digest`: if `true` (or absent — backward-compatible default), send the daily email. If `false`, the daily PDF is still built and stored in `data/YYYY-MM-DD/` but no email is sent.
- `weekly_digest`: if `true`, send the weekly digest email on `weekly_day`. Defaults to `false` if absent.
- `weekly_day`: lowercase weekday name (`"monday"` … `"sunday"`). Defaults to `"friday"` if absent.

Both flags are independent — a user can have `daily_digest: true, weekly_digest: true` (gets both), or `daily_digest: false, weekly_digest: true` (weekly only), or any other combination.

---

## `.env` Changes — Per-User

Add two new optional environment variables alongside the existing `EMAIL_TO`:

```
EMAIL_TO_DAILY=alice@example.com
EMAIL_TO_WEEKLY=group@example.com,bob@example.com
```

**Fallback logic (in order of priority):**
- Daily email: use `EMAIL_TO_DAILY` if set; otherwise fall back to `EMAIL_TO`.
- Weekly email: use `EMAIL_TO_WEEKLY` if set; otherwise fall back to `EMAIL_TO`.

This means existing users whose `.env` only has `EMAIL_TO` continue to work without any changes.

---

## File Changes

### 1. `run_daily.py` — conditional daily email + correct mailing list

**Change 1 — mailing list:** In `send_email()`, replace the direct `os.environ.get("EMAIL_TO", "")` lookup with:

```python
to_addr_raw = os.environ.get("EMAIL_TO_DAILY") or os.environ.get("EMAIL_TO", "")
```

**Change 2 — skip email if `daily_digest: false`:** After building the PDF and before calling `send_email()`, read the profile and check the flag:

```python
profile_data = json.loads((user_dir / "taste_profile.json").read_text())
send_daily = profile_data.get("daily_digest", True)

if args.no_email or not send_daily:
    log.info("[email] Skipped (%s).", "--no-email" if args.no_email else "daily_digest=false")
else:
    send_email(pdf_path, today_str, username)
```

No other changes to `run_daily.py`. Scoring, PDF build, dedup, archive, and cleanup all run regardless.

---

### 2. New script — `run_weekly_digest.py`

Full standalone script. Called by `run_all_users.py` at the end of the daily run.

**Arguments:**
```
--user-dir   users/<name>    (required)
--date       YYYY-MM-DD      (optional, defaults to today — override for testing)
--no-email                   (skip sending, for testing)
```

**Logic:**

1. Load `taste_profile.json` and user `.env`.
2. Determine the 7-day window: `[today - 6 days, today]` (inclusive).
3. Scan `users/<name>/data/YYYY-MM-DD/scored_papers.json` for each date in the window that has a file. Skip missing dates silently (holidays, weekends with no arXiv).
4. Collect all papers with `score >= 8` across all scanned files.
5. Deduplicate by `paper_id` — if the same paper appears on multiple days (e.g. re-fetched), keep the entry with the highest score. If scores are equal, keep the earliest date's entry.
6. Sort by score descending.
7. Write a temp JSON file to `users/<name>/data/TODAY/weekly_papers.json`.
8. If no papers collected (score ≥ 8 threshold not met all week), log a warning and exit cleanly — no email sent.
9. Call `build_digest_pdf.py` to build the weekly PDF:
   ```
   python build_digest_pdf.py
     --scored   users/<name>/data/TODAY/weekly_papers.json
     --papers   users/<name>/data/TODAY/weekly_papers.json
     --output   users/<name>/data/TODAY/weekly_digest.pdf
     --user     <name>
     --date     TODAY
     --base-url <RATING_BASE_URL>
   ```
   Note: `--scored` and `--papers` both point to the same file. The PDF builder uses `--papers` to know the full paper set (for the "unscored" section) and `--scored` for the ranked section. Since all weekly papers are scored ≥ 8, there will be no unscored section — this is fine.

10. Send the PDF to `EMAIL_TO_WEEKLY` (fallback to `EMAIL_TO`).

**Email details:**
- Subject: `"Incoming Science Weekly — {start_date} to {end_date}"`
- Body: brief note explaining these are all papers scored 8 or above from the past 7 days, with rating buttons embedded.

**Rating URLs:** Use today's date (the weekly send date) for all rating button URLs — i.e., pass `--date TODAY` to the PDF builder, same as the daily pipeline. When a user taps a rating button, the rating is written to `data/TODAY/ratings.json`. The next morning, `archive.py` archives it. The refiner reads it from `archive.json` by `paper_id` — the date metadata doesn't affect refiner logic.

No changes to `build_digest_pdf.py`.

---

### 3. `run_all_users.py` — trigger weekly at end of daily run

After the `ThreadPoolExecutor` block that runs all per-user daily work (scoring, PDF, daily email) completes, add a **weekly dispatch phase**:

```python
today_weekday = date.today().strftime("%A").lower()  # e.g. "friday"

weekly_users = []
for user_dir in user_dirs:
    profile = load_profile(user_dir)
    if not profile.get("weekly_digest", False):
        continue
    if profile.get("weekly_day", "friday") != today_weekday:
        continue
    weekly_users.append(user_dir)

if weekly_users:
    log.info("Weekly digest day — sending weekly emails for %d user(s).", len(weekly_users))
    with ThreadPoolExecutor(max_workers=len(weekly_users)) as ex:
        futures = {ex.submit(run_weekly_for_user, u): u for u in weekly_users}
        for fut in as_completed(futures):
            u = futures[fut]
            try:
                fut.result()
            except Exception as exc:
                log.error("Weekly digest failed for %s: %s", u.name, exc)
```

`run_weekly_for_user()` is a thin wrapper that calls `run_weekly_digest.py --user-dir <path>` as a subprocess, same pattern as the existing per-user daily dispatch.

**Ordering guarantee:** The weekly phase only starts after all daily runs (including daily emails) are complete — the `executor.shutdown()` / `as_completed()` loop of the daily phase finishes first. So a user with both `daily_digest: true` and `weekly_digest: true` on a Friday will get their daily email first, then their weekly email.

---

### 4. Refiner — `run_profile_refiner.py` + `prompts/profile_refiner.txt`

**When to apply:** Only when `daily_digest: false` AND `weekly_digest: true`. A user with both flags true sees both paper sets and generates full signal; no special handling needed for the refiner.

**Prompt injection (Python side, not prompt file):** In `build_refiner_message()`, add a `weekly_only_mode: bool` parameter. If `True`, prepend the following block to the discrepancy section (before the existing discrepancy text):

```
IMPORTANT — WEEKLY-ONLY DELIVERY MODE
======================================
This user receives only papers scored ≥ 8 (weekly digest). They never see papers
that were triaged out or scored below 8. As a result:
  - "MISSED" discrepancies (not triaged or scored ≤ 3, user rated Excellent/Good)
    are structurally impossible and will always be empty. Do not treat their absence
    as evidence that triage is working correctly.
  - "UNDERSCORED" discrepancies (scored 4–6, user rated Excellent) are also impossible.
  - The only actionable discrepancy signals are OVERCONFIDENT ones:
      · Scored ≥ 7, user rated Irrelevant → strong signal, act on it
      · Scored ≥ 8, user rated Good → mild overconfidence
  - For new keywords and authors, rely on Excellent and Good ratings from the weekly
    digest. The bar is still the same (2+ Good papers, or 1 Excellent paper), but
    expect lower total volume since only high-scored papers are rated.
  - Do not penalise a sparse month. Weekly-only users will generate fewer ratings
    than daily users by design. Treat borderline signals conservatively.

```

Also, suppress the MISSED and UNDERSCORED bucket text in `build_discrepancy_section()` when `weekly_only_mode=True` — these buckets will always be empty and showing empty sections wastes context and may confuse the model.

**How to detect weekly-only mode in `run_profile_refiner.py`:**
```python
weekly_only = (
    not profile.get("daily_digest", True)
    and profile.get("weekly_digest", False)
)
msg = build_refiner_message(profile, recent_ratings, weekly_only_mode=weekly_only)
```

No changes to the prompt file itself — the injection is entirely Python-side, added to the user message.

---

## No Changes Required

- `build_digest_pdf.py` — no changes. Weekly PDF uses today's date for all rating URLs.
- `fetch_papers.py`, `fetch_journals.py` — no changes.
- `run_pipeline.py` — no changes.
- `server.py` — no changes. Rating routing by date works the same way.
- `archive.py`, `deduplicate_ratings.py` — no changes.
- `prompts/` (triage, scoring, profile_refiner) — no changes to files on disk. The weekly-mode addition to the refiner is injected by Python into the user message at runtime.

---

## Cron — No New Entries

The weekly dispatch is handled inside the existing daily cron job. No new cron line is needed.

Current cron (system TZ=America/New_York):
```
30 0 * * 1-5  cd /opt/arxiv-grader && python run_all_users.py >> /var/log/arxiv-grader/daily.log 2>&1
```

On Fridays (or whichever `weekly_day` a user has), the weekly phase runs automatically at the tail of this job. The job takes a few minutes longer on those days.

---

## Summary of Files to Create / Modify

| Action | File | What changes |
|--------|------|-------------|
| Create | `run_weekly_digest.py` | New script — collects ≥8 papers, builds PDF, sends weekly email |
| Modify | `run_daily.py` | Check `daily_digest` flag; use `EMAIL_TO_DAILY` env var |
| Modify | `run_all_users.py` | Add weekly dispatch phase after daily runs complete |
| Modify | `run_profile_refiner.py` | Detect weekly-only mode; pass flag to message builder |
| Modify | `prompts/profile_refiner.txt` | No change — injection is Python-side |

---

## Testing Checklist

- [ ] User with `daily_digest: true, weekly_digest: false` — behavior unchanged
- [ ] User with `daily_digest: false, weekly_digest: true` — no daily email; weekly email sent on correct weekday
- [ ] User with `daily_digest: true, weekly_digest: true` — both emails sent; daily first, weekly after
- [ ] Weekly PDF rating buttons land in `data/FRIDAY/ratings.json` and archive correctly the next morning
- [ ] Week with no papers scoring ≥ 8 — no weekly email sent, no crash
- [ ] Week with duplicate paper_ids across days — deduplicated correctly (highest score kept)
- [ ] Refiner weekly-only mode — MISSED/UNDERSCORED buckets absent from message; weekly-mode note present
- [ ] Refiner with `daily_digest: true, weekly_digest: true` — no weekly-only mode applied
- [ ] `EMAIL_TO_WEEKLY` set — weekly email goes to correct list
- [ ] `EMAIL_TO_WEEKLY` absent, `EMAIL_TO` set — weekly email falls back to `EMAIL_TO`
- [ ] `--no-email` flag — suppresses both daily and weekly emails
