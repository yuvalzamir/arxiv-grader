# TODO

## Triage tuning — DONE ✓

Created `prompts/triage_journals.txt` with abstract content signal (grade 1–5).
Caps: arXiv 20→15, journals 10→15. See `docs/journal_triage_tuning.md` for full log.

---

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

- [x] **4. `run_pipeline.py`** — complete. `--journals` arg merges journal papers before triage (arXiv first). Separate triage batches with independent caps: arXiv 15, journals 15. `source` field added to `_paper_block()`.

- [x] **7. `run_daily.py`** — complete. `--journals` accepted and forwarded to `run_pipeline.py` if file exists.

- [x] **8. `build_digest_pdf.py`** — `paper_url()` implemented (DOI → doi.org, full URL passthrough, else arXiv); `rate_url()` URL-encodes paper_id. Source badge deferred.
  - [x] Add source badge (small pill, same row as score badge) for papers with `source` field

- [x] **9. `requirements.txt`** — done. `environment.yml` does not exist; no action needed.

- [x] **11. End-to-end test + deploy** — deployed 2026-03-27. See `docs/journal_triage_tuning.md`.
  pip installed on server: `beautifulsoup4`, `lxml`, `matplotlib`. First live run tonight.

---

## Completed post-deploy (2026-03-27) ✓

- [x] **`run_pipeline.py` — archive NameError** — `run_scoring()` was referencing `archive` as a free variable; fixed by passing it as a parameter.
- [x] **`create_profile.py` — empty archive on onboarding** — creates `archive.json = []` alongside `taste_profile.json` on first save, so new users don't hit NameError on first run.
- [x] **`run_pipeline.py` — debug prompt files** — triage and scoring prompts (system + user) are written to `triage_arxiv_input.txt`, `triage_journals_input.txt`, `scoring_input.txt` in the data folder on every run.
- [x] **`run_pipeline.py` — `--no-batch` flag** — `_call_direct()` added; pass `--no-batch` to bypass Batch API queue and use synchronous messages API (2x cost, instant response). Threaded through `run_daily.py` and `run_all_users.py`.
- [x] **Batch API auto-fallback + alert email** — `BatchTimeoutError` raised after 1-hour timeout. Both triage and scoring catch it, retry with `_call_direct()`, and write `batch_fallback.json` to the data folder. `run_all_users.py` scans for these files after all users complete and sends an alert email to `yuval.zamir@icfo.eu` with per-user/per-stage report.

---

## APS abstract scraping — investigated 2026-03-27

Full investigation log in `docs/aps_cloudflare_proxy.md` (branch `APS_Scraping`).

- Semantic Scholar: no APS abstracts (licensing restriction — `abstract` is null even when paper is indexed)
- CrossRef: no APS abstracts (APS doesn't deposit them)
- OpenAlex: same — no abstracts for fresh APS papers
- Direct APS scrape: 403 on Hetzner IP (`link.aps.org` uses Cloudflare bot protection with JS challenge)
- Cloudflare Worker proxy: attempted but failed — APS itself runs Cloudflare, Worker fetch can't pass JS challenge
- **Resolution: accept truncated RSS abstracts** (~2–3 sentences, sufficient for triage). ICFO institutional APS access may help — check with library if APS whitelists IP ranges or provides API token.

---

## Pending

- [x] **Shared data folder cleanup** — `run_daily.py` has `cleanup_old_folders()` (default: keep 14 days). Confirmed working. Note: this cleans per-user `users/<name>/data/` folders; the shared `data/` folder (journal scrape) is cleaned by `run_all_users.py` after each run.
- [x] **Journal triage tuning** — monitoring confirmed current tuning is working well. No action needed.
- [x] **April 2nd refiner check** — confirmed refiner ran (2026-04-02). Revealed need for refiner v2 (see below).
- [ ] **APS full abstracts** — check if ICFO has institutional APS access (IP whitelist or API token).
  - [ ] **`create_profile.py` APS fetcher** — `fetch_journal_paper()` will also fail on APS URLs (same Cloudflare block). Once an APS access solution is found, update the journal fetcher in `create_profile.py` to handle `link.aps.org` URLs.
- [x] **Security audit** — `porkbun key.txt` found committed in initial commit; keys were already dead and repo is private. Purged from all git history via `git filter-repo`, force-pushed all branches. `.gitignore` updated with `*key*.txt`, `*secret*.txt`, `*token*.txt`, `*credentials*.txt` patterns. Server checked — clean.

---

## Upcoming

- [x] **PDF journal links fix** — `paper_url()` in `build_digest_pdf.py` now passes through full `http(s)://` URLs directly. Root cause: `fetch_journals.py` sets `arxiv_id = doi if doi else url` (line 157), so when no DOI is extracted the field holds the raw article URL; the old `paper_url()` wrapped it in `https://arxiv.org/abs/`.

- [x] **Triage: switch from Batch API to cached API** — Done in commit `d2026d6`. Field-level cached API, sequential per user to warm cache.

- [x] **Refiner v2** — Implemented and tested (dry run 2026-04-06). Full overhaul of `run_profile_refiner.py`. Three changes:
  1. Structured outputs (replace `parse_json_response()`, schemas in `schemas/`)
  2. Area management as a separate Haiku call — keyword-driven, decoupled from paper ratings; bidirectional grade recommendations; new area suggestions (min 3 unmatched keywords); static `area_keyword_map` stored in `taste_profile.json`
  3. Remove area grade changes from the main refiner (Sonnet) entirely — areas exclusively managed by the Haiku step
  - [ ] **Refiner v2 — May check** — Verify refiner v2 runs correctly on real data after May 2nd cron. Check area management recommendations make sense given a full month of ratings.

- [x] **Multiple arXiv categories per field** — allow a field to span more than one top-level arXiv category (e.g. `cond-mat` + `physics`).
  - **`fields.json`**: renamed `"arxiv_category"` (string) → `"arxiv_categories"` (list). Old string form still supported as fallback.
  - **`run_all_users.py` — `run_arxiv_fetch()`**: normalizes to list, fetches each category into a temp file, merges results, deduplicates by `arxiv_id`, writes to `{field}_arxiv_papers.json`.
  - **`fetch_papers.py`**: no changes needed.
  - Everything downstream (triage, scoring, PDF) is unchanged.

---

## Security review

- [x] **Audit credentials and sensitive files** — `porkbun key.txt` found committed in initial commit; keys were already dead and repo is private. Purged from all git history via `git filter-repo`, force-pushed all branches. `.gitignore` updated with `*key*.txt`, `*secret*.txt`, `*token*.txt`, `*credentials*.txt` patterns. Server checked — clean (only venv package files matched).

---

## Documentation audit ✓

- [x] **Review README coverage** — completed 2026-04-06. Added: flags (`--no-fetch`, `--triage-only`, `--no-batch`), batch fallback mechanics, watermark `--since`, holiday ordering, archive sampling, debug prompt files, `fields.json` schema. Created `docs/add_new_field.md`.

---

## Known rough edges (monitor, no action needed now)

- Cron changed to Mon–Fri 05:30 UTC (was Tue–Sat) — Friday arXiv data now delivered Monday
- APS abstracts truncated (RSS fallback) — Hetzner IP blocked by APS Cloudflare protection
- On Mondays, arXiv feed has 120–165 papers due to weekend accumulation — triage cap of 15 handles this
- Scoring agent `max_tokens=8192` — sufficient for up to ~30 filtered papers (cap 15+15)
- Cron: system timezone set to `America/New_York` (`timedatectl set-timezone`); crontab runs at 00:30 ET daily, 01:30 ET monthly refiner — DST handled automatically
- Anthropic Batch API (Sonnet) can get stuck during incidents — use `--no-batch` flag as fallback

---

## Upcoming

- [ ] **ACS abstract access — awaiting response** — email sent to ACS requesting API or institutional access to paper abstracts. If granted, implement in `scrapers/acs.py` (currently returns empty abstract). Follow up if no response.
- [x] **systems-biology field + Yael onboarding** — scrapers and fields.json complete, deployed to server 2026-04-11. `ANTHROPIC_API_KEY_SYSTEMS_BIOLOGY` added to server root `.env`. Yael onboarded via `create_profile.py`. New scrapers: `cell.py`, `plos.py`, `pnas.py`. Extended `science.py` (Science Immunology + Science Advances). 18 journals. arXiv: `q-bio` + `physics.bio-ph`.
  - [x] **tag_filter tuning** — PNAS uses 4 topic-specific RSS feeds (biophys/immun/cell-bio/microbio); Science Advances uses its dedicated eTOC feed. Both are pre-filtered at the RSS level; `tag_filter: null` is correct.
- [x] **quantum-sensing field** — deployed and first user onboarded ✓

## Backlog

- [ ] **Weekly highlight report** — optional weekly email (e.g. every Friday) containing only papers scored 8 and above from the past week. Opt-in per user via `taste_profile.json` flag. Useful for users who want a curated high-signal summary without reading daily digests.
  - **Opt-in flag:** add `"weekly_digest": true` to `taste_profile.json`; default false
  - **Trigger:** new cron entry, e.g. Friday 01:00 ET → `run_all_users.py --weekly`
  - **Data source:** scan `users/<name>/data/*/scored_papers.json` for the past 7 days; collect all papers with `score >= 8`
  - **Deduplication:** a paper may appear in multiple daily files if re-fetched; deduplicate by `arxiv_id` / DOI, keeping highest score
  - **PDF:** reuse `build_digest_pdf.py` with a filter; add a "Weekly Highlights" header and date range
  - **No triage/scoring needed** — purely a post-processing step over already-scored data
  - **New file:** `run_weekly_digest.py` — loops users, checks opt-in flag, collects papers, builds PDF, emails it
  - **Edge cases:** fewer than 7 days of data (new user), no papers scored ≥ 8 that week (skip or send empty notice)

- [ ] **`create_profile.py` — ask digest frequency during onboarding** — add interactive questions for `daily_digest` (yes/no), `weekly_digest` (yes/no), and `weekly_day` (if weekly enabled). Write these fields into `taste_profile.json` at creation time so they never need to be added manually (manual edits caused JSON corruption in April 2026).

- [ ] **Self-service user onboarding** — allow new users to onboard without owner intervention. Possible scheme: user fills out a web form (hosted on `incomingscience.xyz`), submits it, and `create_profile.py` runs automatically on the server to create their profile and add them to the pipeline. Requires auth/validation to prevent abuse, automated directory creation, and a confirmation email flow.
  - **Web form (`server.py`):** new route `GET /onboarding/form` serving an HTML form with fields: name, email, arXiv categories, free-text interests, keywords (comma-separated), authors to follow, and optionally a list of representative paper URLs
  - **Submission endpoint:** `POST /onboarding/submit` — validates input, writes a pending request to `onboarding_queue/<token>.json`, sends a verification email to the user with a confirm link
  - **Email verification:** `GET /onboarding/confirm?token=<token>` — marks request as confirmed, triggers profile creation
  - **Profile creation:** confirmed request calls `create_profile.py` non-interactively (all inputs from form JSON, skip interactive review steps); creates `users/<name>/` directory, `.env` (with `EMAIL_TO`), `taste_profile.json`, `archive.json`
  - **API key handling:** new users need their own `ANTHROPIC_API_KEY`; options: (a) owner-provided shared key per field stored in root `.env`, (b) user supplies key in the form. Decision needed before implementation.
  - **Confirmation email to user:** sent after profile creation — confirms they're enrolled, explains the schedule, links to landing page
  - **Alert to owner:** email to operator on each new confirmed signup
  - **Security:** rate-limit submissions by IP; token expiry (e.g. 24h); sanitize all user inputs used in directory names (alphanumeric + hyphen only for `<name>`); no shell execution of user-supplied strings
  - **`create_profile.py` changes:** add a `--non-interactive` mode that reads all profile fields from a JSON file instead of prompting; skips the Excel upload and interactive ranking review; calls Claude once to generate initial keyword/area ranking from the free-text inputs
