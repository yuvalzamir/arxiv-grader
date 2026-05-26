# Pipeline Overview

[[Home]] | [[AI Pipeline]] | [[Journal Scrapers]] | [[Daily Digest]]

---

## Daily Execution Order

`run_all_users.py` is the master orchestrator. Steps run in this order every weekday at 00:30 ET:

```
1.  Discover user directories (users/<name>/taste_profile.json)
2.  fetch_journals.py — scrape all journals once (all fields)
          writes: data/YYYY-MM-DD/scraped_journals.json
          updates: journal_watermarks.json
3.  For each field:
      fetch_papers.py — fetch arXiv RSS
      filter_for_field() — filter journal papers for this field
      Merge arXiv + journals → data/YYYY-MM-DD/{field}_today_papers.json
4.  Exit cleanly if all fields are empty (holiday / arXiv off-day)
5.  Snapshot journal_watermarks.json → watermarks_snapshot.json (recovery)
6.  Centralized triage per field (staggered, parallel within field)
          writes: users/<name>/data/DATE/filtered_papers.json
7.  [ThreadPoolExecutor] Per-user: scoring → PDF → daily email
8.  Cleanup shared data/ folders older than 3 days
9.  Send batch-fallback alert email if any scoring job timed out
10. Send operator run-summary email (OK/FAILED table)
11. Weekly digest phase — send weekly emails for users whose weekly_day = today
```

**Per-user steps** (`run_daily.py`):
```
1. Deduplicate yesterday's ratings (deduplicate_ratings.py)
2. Archive deduplicated ratings → archive.json (archive.py)
3. run_pipeline.py --skip-triage  (triage already done in step 6 above)
4. build_digest_pdf.py
5. Send daily email (skipped if daily_digest: false)
6. Cleanup user data folders older than 14 days
```

---

## Field Architecture

Users are grouped by **field** (value of `"field"` in `taste_profile.json`). All users in a field share:
- One arXiv RSS fetch
- One journal scrape (filtered per-field)
- One triage cache (papers block is identical for all users)

Each user gets their own:
- Triage result (profile-block suffix varies per user)
- Scoring call (full profile, full context)
- PDF and email

---

## Holiday / Off-Day Handling

- arXiv papers are fetched **before** journals
- If **all** fields return empty arXiv feeds → pipeline exits cleanly before journals
- Journal watermarks are **not** advanced → papers preserved for next day
- Individual users with no papers skip scoring gracefully

---

## Data Files Per Run

**Shared** (`data/YYYY-MM-DD/`):
- `scraped_journals.json` — all journals across all fields
- `{field}_arxiv_papers.json` — arXiv papers per field
- `{field}_today_papers.json` — merged arXiv + journals per field
- `{field}_journals.json` — filtered journal papers per field
- `journal_watermarks_snapshot.json` — watermark recovery backup

**Per-user** (`users/<name>/data/YYYY-MM-DD/`):
- `filtered_papers.json` — triage survivors
- `scored_papers.json` — final ranked output
- `digest.pdf` — the PDF
- `ratings.json` — ratings recorded today
- `triage_arxiv_input.txt` — full triage prompt (debug)
- `triage_journals_input.txt` — full journal triage prompt (debug)
- `scoring_input.txt` — full scoring prompt (debug)

---

## Parallel Execution Strategy

- **Journal scraping**: sequential within publisher, all publishers in one pass
- **Triage** (per field): users in a field launched with 61-second stagger to hit the 50k ITPM cached-API rate limit without overlap → see [[Prompt Caching]]
- **Scoring + PDF + email**: fully parallel via `ThreadPoolExecutor`, one thread per user

---

## Re-Running a Failed User

```bash
# Safe re-run for a specific date (watermarks already advanced):
python run_all_users.py --user alice --date 2026-04-14 --no-advance-watermark

# Restore watermarks if they were advanced incorrectly:
cp data/2026-04-14/journal_watermarks_snapshot.json journal_watermarks.json

# Retry today's failed users (parses daily.log automatically):
python run_failed_users.py
```

---

## Weekend Runs

The main cron only runs Mon–Fri. Weekend weekly digest runs via a separate cron:
```bash
python run_weekly_only.py   # Sat/Sun 01:30 ET
```
This skips arXiv fetch, journal scraping, triage, and scoring — only runs the weekly digest phase for users whose `weekly_day` matches today.

→ See [[Weekly Digest]] for full design.
