# TODO

## `fetch_journals.py` — open issues

- [x] **4. Nature main wasteful scraping** — fixed: `d41586` DOI prefix filter in `NatureScraper.editorial_filter` drops news/views before page fetch. Saves ~45 unnecessary HTTP requests per run.
- [x] **5. Science RSS summary quality** — switched to eTOC feed (full last issue, 42 papers). Abstracts fetched via Semantic Scholar API (free, plain text). 20/42 papers get full abstracts; 22 editorial/opinion pieces fall back to short RSS summaries and are handled by triage.
- [x] **8. PRB publication lag** — not a lag; PRB simply didn't publish on March 25. Zero-paper days are normal and expected.
- [ ] **8b. Science date handling** — eTOC feed gives the full last issue; all 42 entries share the issue date (e.g. March 19). Date filter will return 0 on non-issue days. Need to decide: skip date filter for Science, or always include the most recent issue regardless of date.
- [x] **8b. Science date handling** — eTOC feed gives the full last issue; all entries share the issue date. Watermark handles this correctly — Science papers are picked up once per week when the new issue appears.
- [x] **8 (watermark)** — replaced fixed `--date` logic with per-journal watermark (`journal_watermarks.json`, keyed by RSS URL). Watermark advances to `min(max_entry_date, yesterday)` to prevent today's papers from being skipped tomorrow. `--since` flag overrides for manual re-runs without updating watermarks.
- [x] **1/6. Duplicate papers across feeds** — deduplication by `arxiv_id` added to `main()` in `fetch_journals.py` after all journals scraped.
- [x] **2. `import re` inside `_split_author_string()`** — already at module level in the rewrite.
- [x] **7. `requirements.txt`** — added `beautifulsoup4`, `lxml` (feedparser and requests were already present).

---

## Completed ✓

- [x] `fetch_papers.py` — arXiv RSS fetch and parse
- [x] `create_profile.py` — one-time user onboarding, multi-user aware (`--user-dir`)
- [x] `run_pipeline.py` — triage agent (Haiku) + scoring agent (Sonnet)
- [x] `build_digest_pdf.py` — PDF digest with rating buttons (embeds `&user=`)
- [x] `server.py` — Flask `/rate` endpoint, routes on `?user=`
- [x] `deduplicate_ratings.py` — deduplicates ratings.json per user
- [x] `archive.py` — appends to per-user archive.json
- [x] `run_daily.py` — daily orchestrator for one user (`--user-dir` required)
- [x] `run_all_users.py` — master orchestrator, loops all users under `users/`
- [x] `run_profile_refiner.py` — monthly profile refiner with discrepancy analysis and narrative memory
- [x] Email delivery — SMTP via smtplib/STARTTLS, hardcoded shared account
- [x] Multi-user support — directory-per-user layout under `users/<name>/`
- [x] Triage tuning — ranked output + hard cap of 20 + tighter medium definition
- [x] Hetzner CX23 VPS deployed — Ubuntu 24.04, IP 116.203.255.222
- [x] Domain `incomingscience.xyz` registered on Porkbun, A record pointing to Hetzner IP
- [x] Caddy reverse proxy + HTTPS (Let's Encrypt) configured and live
- [x] Gunicorn running as systemd service (auto-starts on boot)
- [x] Logging to `/var/log/arxiv-grader/`, logrotate configured
- [x] `RATING_BASE_URL=https://incomingscience.xyz/rate` set in root `.env`
- [x] Cron jobs wired — daily 7am Madrid time (weekdays), monthly refiner 1st of month 6am
- [x] End-to-end test passed — PDF delivered, rating buttons work, `ratings.json` populated
- [x] Landing page at `https://incomingscience.xyz`
- [x] `run_daily.py` reads `arxiv_categories` from `taste_profile.json` instead of hardcoding cond-mat
- [x] Cron rescheduled to 21:00 ET Sun–Thu (`TZ=America/New_York`) — aligned with arXiv's 20:00 ET release; digest arrives overnight
- [x] PDF digest header shows total paper count (`N papers today · M scored · K unscored`)
- [x] Unscored section: abstract removed for compactness (title + authors + rating buttons only)
- [x] Batch API — triage and scoring now use Anthropic Message Batches API (50% cost reduction); `_submit_and_poll()` helper in `run_pipeline.py`
- [x] Parallel user runs — `run_all_users.py` uses `ThreadPoolExecutor`; all users' pipelines run concurrently
- [x] `build_digest_pdf.py` — fixed `SyntaxWarning` on invalid escape sequence in docstring (raw string)

---

## Journal sources expansion (`journal_grader` branch)

Design documents: `docs/journal_sources_design.md` (architecture) and `docs/journal_implementation_plan.md` (step-by-step).

- [x] **1. `fields.json`** — complete. 10 journals (NanoLett deferred), section feeds for PRL, physical-sciences RSS for NatComms, eTOC feed for Science.

- [x] **2. `fetch_journals.py`** — complete. Publisher scraper classes (`scrapers/`), per-journal watermark, deduplication, Semantic Scholar for Science abstracts, 1.5s delay.

- [x] **3. `run_all_users.py`** — complete. Field discovery, single shared `fetch_journals.py` subprocess, `filter_for_field()` pure Python, per-user `--journals` arg, `--no-journals` flag.

- [x] **4. `run_pipeline.py`** — complete. `--journals` arg merges journal papers before triage (arXiv first). Separate triage caps: arXiv max 20, journals max 10, applied in Python. `source` field added to `_paper_block()`.

- [ ] **5. `prompts/triage.txt`** — add SOURCE FIELD section
  - See exact text in `docs/journal_sources_design.md`

- [ ] **6. `prompts/scoring.txt`** — add SOURCE FIELD section + "top venue" tag
  - See exact text in `docs/journal_sources_design.md`

- [x] **7. `run_daily.py`** — complete. `--journals` accepted and forwarded to `run_pipeline.py` if file exists.

- [ ] **8. `build_digest_pdf.py`** — two fixes + source badge
  - Replace `arxiv_url()` with `paper_url()`: DOIs (`10.*`) → `https://doi.org/{doi}`, else arXiv URL
  - URL-encode `paper_id` in `rate_url()` using `urllib.parse.quote(paper_id, safe="")`
  - Add source badge (small pill, same row as score badge) for papers with `source` field

- [ ] **9. `requirements.txt`** — done. `environment.yml` does not exist; no action needed.

- [ ] **10. User profiles** — add `"field": "cond-mat"` to each existing `taste_profile.json`

- [ ] **11. End-to-end test + deploy**
  - `python run_all_users.py --no-email --user yuval` — inspect PDF
  - Verify rating URL for journal paper is percent-encoded; title links to `doi.org`
  - `scp` updated files + `journal_watermarks.json` to server, `pip install beautifulsoup4 lxml`, test

---

## Upcoming

- [ ] **April 1st** — Check monthly profile refiner ran successfully:
  ```bash
  cat /var/log/arxiv-grader/refiner.log
  ```
  And verify `taste_profile.json` was updated:
  ```bash
  cat /opt/arxiv-grader/users/yuval/taste_profile.json
  ```

---

## Known rough edges (monitor, no action needed now)

- On Tuesdays, arXiv feed has 120–165 papers due to weekend accumulation — triage already handles this well (ranked cap of 20 keeps scoring cost bounded)
- Scoring agent `max_tokens=8192` — sufficient for up to ~80 filtered papers; hard cap of 20 makes this a non-issue in practice
- Cron UTC offset: `TZ=Europe/Madrid` set in crontab — handles summer/winter time automatically
