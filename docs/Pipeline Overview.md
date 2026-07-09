# Pipeline Overview

[[Home]] | [[AI Pipeline]] | [[Journal Scrapers]] | [[Preprint Sources]] | [[Daily Digest]]

---

## Daily Execution Order

`run_all_users.py` is the master orchestrator. Steps run in this order every weekday at 00:30 ET:

```
1.  Discover user directories (users/<name>/taste_profile.json)
2.  For each field:
      fetch_papers.py — fetch arXiv RSS
          writes: data/YYYY-MM-DD/{field}_arxiv_papers.json
3.  Exit cleanly if all fields are empty (holiday / arXiv off-day)
      → journal + preprint watermarks NOT advanced on holidays
4.  fetch_preprints.py — fetch bioRxiv/medRxiv + NBER/CEPR preprints per field
          writes: data/YYYY-MM-DD/{field}_preprints.json
          updates: preprint_watermarks.json
5.  fetch_journals.py — scrape all journals once (all fields)
          writes: data/YYYY-MM-DD/scraped_journals.json
          updates: journal_watermarks.json
      filter_for_field() — filter journal papers per field
          writes: data/YYYY-MM-DD/{field}_journals.json
6.  Snapshot journal_watermarks.json → watermarks_snapshot.json (recovery)
7.  For each field: merge arXiv + preprints + journals → {field}_today_papers.json
8.  Centralized triage per field (staggered, parallel within field)
          writes: users/<name>/data/DATE/filtered_papers.json
9.  [ThreadPoolExecutor] Per-user: scoring → PDF → daily email
10. Cleanup shared data/ folders older than 3 days
11. Send batch-fallback alert email if any scoring job timed out
12. Send operator run-summary email (OK/FAILED table)
13. Weekly digest phase — send weekly emails for users whose weekly_day = today
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

One preprint fetch (bioRxiv/medRxiv categories per field, deduplicated by DOI)

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
- `{field}_preprints.json` — bioRxiv/medRxiv + NBER/CEPR preprints per field
- `{field}_journals.json` — filtered journal papers per field
- `{field}_today_papers.json` — merged arXiv + preprints + journals per field
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

---

## Threading Gotcha — SystemExit Propagation

`ThreadPoolExecutor` catches `Exception` but NOT `BaseException`. `sys.exit()` raises `SystemExit` (a `BaseException`), so any `sys.exit()` call inside a thread propagates silently through `except Exception` handlers, hits `ThreadPoolExecutor.__exit__` (which calls `shutdown(wait=True)`, waiting for all running threads to finish), then kills the process.

**Fixed (2026-05-28):** Both `except Exception` catches in `run_all_users.py` triage code changed to `except BaseException` — `_triage_one` (per-user triage worker) and the outer field triage loop. This ensures a `sys.exit()` in `run_pipeline.py` is caught and treated as a per-user failure rather than killing the entire run.

Root cause of the original bug: `run_pipeline.py` calls `sys.exit(1)` in several error paths (JSON parse failure, batch API errors, no-parseable-labels). Safe to call from `__main__` but dangerous when called from a thread.

→ See [[runs/2026-05-28]] for the full incident analysis.
