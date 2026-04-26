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
- [x] **Batch API auto-fallback + alert email** — `BatchTimeoutError` raised after 20-minute timeout. Both triage and scoring catch it, retry with `_call_direct()`, and write `batch_fallback.json` to the data folder. `run_all_users.py` scans for these files after all users complete and sends an alert email to `yuval.zamir@icfo.eu` with per-user/per-stage report.

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
  - [ ] **`create_profile.py` APS fetcher** — `fetch_journal_paper()` fails on APS URLs (Cloudflare block). Deferred until institutional APS access is available.
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
  - [ ] **Refiner — check 2026-05-03 (Sunday)** — Pull `refiner.log` and verify: new-user Saturday refiner ran with correct python, `last_refined_at` is being stamped, no JSON parse errors, no `python: not found`.
  - [ ] **Refiner — check 2026-05-10 (Sunday)** — Second check: confirm accumulated ratings since last run are picked up correctly via `last_refined_at`, min-rating threshold working as expected.

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

## Monitoring — how to check the logs

**Daily pipeline:**
```bash
scp root@116.203.255.222:/var/log/arxiv-grader/daily.log ./debugging/daily_log_MMDD.txt
```
Look for per-user `OK` / `FAILED` lines near the end, and `[TRIAGE]` / `[SCORE]` lines for rate-limit hits.

**Refiner (runs 2nd + 16th + new-user Saturday):**
```bash
scp root@116.203.255.222:/var/log/arxiv-grader/refiner.log ./debugging/refiner_log.txt
```
Key lines to check:
- `discrepancies: N total (overconfident-high=X, missed-excellent=Y, ...)` — one per user
- `Applying grade changes: ...` — what was actually changed
- `Pre-run grade-7 items` / `Removing grade-7` — keywords being pruned
- `Area management` lines — area grade changes from the Haiku step
- `Weekly-only delivery mode detected` — suppressed buckets for weekly-only users
- Any `ERROR` or `WARNING` lines indicate failures

**Weekly digest:**
```bash
scp root@116.203.255.222:/var/log/arxiv-grader/weekly.log ./debugging/weekly_log.txt
```

**Server (Flask/Gunicorn):**
```bash
scp root@116.203.255.222:/var/log/arxiv-grader/server.log ./debugging/server_log.txt
```

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

- [x] **ACS abstract access** — solved via Europe PMC API (DOI lookup). Hit rate: NanoLett 95%, ACSNano 93%, ACSSensors 92%, ACSPhotonics 0% (not indexed). Implemented in `scrapers/acs.py`; ACSPhotonics skipped to avoid wasted calls.
- [ ] **APS full abstracts** — investigated all viable sources (CrossRef, Europe PMC, CORE, Unpaywall, SS→arXiv preprint). Best option was SS DOI→arXiv ID + batched arXiv fetch: 48% hit rate, ~2min overhead. Not worth it given truncated RSS abstracts are sufficient for triage. Only remaining option: ICFO institutional APS access (IP whitelist or API token) — check with library if ever needed.
- [x] **systems-biology field + Yael onboarding** — scrapers and fields.json complete, deployed to server 2026-04-11. `ANTHROPIC_API_KEY_SYSTEMS_BIOLOGY` added to server root `.env`. Yael onboarded via `create_profile.py`. New scrapers: `cell.py`, `plos.py`, `pnas.py`. Extended `science.py` (Science Immunology + Science Advances). 18 journals. arXiv: `q-bio` + `physics.bio-ph`.
  - [x] **tag_filter tuning** — PNAS uses 4 topic-specific RSS feeds (biophys/immun/cell-bio/microbio); Science Advances uses its dedicated eTOC feed. Both are pre-filtered at the RSS level; `tag_filter: null` is correct.
- [x] **quantum-sensing field** — deployed and first user onboarded ✓

- [x] **HEP field** — `hep` field added to `fields.json` with arXiv categories `["hep-ph", "hep-th", "hep-ex", "hep-lat"]` and 12 journals: PRL (elementary particles + gravitation sections), PRD, PLB, NPB, EPJC, JCAP, SciPost (3 discipline feeds), Nature (tag_filter), Science. New scrapers: `scrapers/elsevier.py` (PLB/NPB — CrossRef PII→INSPIRE-HEP→OpenAlex), `scrapers/scipost.py` (OpenAlex). `scrapers/edp.py` extended with OpenAlex fallback for EPJC. Needs `ANTHROPIC_API_KEY_HEP` in server root `.env` when first user is onboarded.

- [x] **Multi-chunk prompt caching for large triage calls** — replaces the Monday batch-fallback for oversized arXiv feeds. `split_papers_block()` splits the formatted paper list at paper boundaries into up to 3 cache-control breakpoints (system prompt uses the 4th). For the first user, `n-1` lightweight warming calls (max_tokens=1) establish intermediate cache entries before the actual triage call; the orchestrator spaces them via the token bucket. Subsequent users pay only cache-read cost (free ITPM). Batch fallback now only triggers if a single pool exceeds 135k tokens (essentially impossible). Log shows `cached(2-chunk)` etc.

---

## Backlog

### Funding & sustainability
- [ ] **Sponsorship / small grant** (#42) — Apply for small grants (Sloan Foundation, NSF CAREER supplements, EU Open Science) to fund the service as public scientific infrastructure. No billing complexity, keeps it free for users. One grant typically covers 1–2 years of operating costs. Worth pursuing in parallel with any monetisation work.

### Failure recovery
- [ ] **Watermark auto-restore on total field failure** (#2) — If every user in a field failed triage, automatically restore `journal_watermarks.json` from the per-run snapshot. Currently requires manual `cp` command. Rare but high-stakes when it happens.
- [x] **Per-scraper try/except** (#3) — Per-article try/except added inside `scrape_journal()`. One bad article is skipped; rest of the journal continues. Per-journal try/except was already in `main()`. Two-level protection now in place.

### Refinement cadence
- [x] **Biweekly refiner for all users** (#15) — Refiner now runs on the 2nd and 16th of each month (was monthly). `WINDOW_DAYS` changed to 17 (covers worst-case 31-day gap). Cron updated to `30 1 2,16 * *`. The ±1 grade cap still applies per run.
- [x] **Weekly refiner for new users (first 8 weeks)** — `created_at` timestamp added to `taste_profile.json` at onboarding (`create_profile.py` + `process_pending.py`). `run_all_users.py --new-user-refine` runs weekly (Saturday cron) and filters for: `daily_digest=true`, `created_at` within 56 days, at least one rating in the past 7 days. Qualifying users get `run_profile_refiner.py --days 7`. After 8 weeks they graduate to the standard biweekly cadence automatically. Saturday cron: `30 1 * * 6 cd /opt/arxiv-grader && python run_all_users.py --new-user-refine >> /var/log/arxiv-grader/refiner.log 2>&1`

### Discovery
- Deferred to `docs/scaling_analysis.md` — need more users per field first.

### Abstract quality
- [x] **Abstract truncation flag in triage prompt** (#23) — `abstract_quality: full | truncated | missing` added to all journal papers in `fetch_journals.py` (length heuristic: <400 chars → truncated, empty → missing). `_paper_block()` emits the flag line only when degraded. `triage_journals.txt` instructs Haiku not to penalize papers for abstract quality. Also: subcategories line now omitted for journal papers (always empty), removing dead tokens from every journal triage call.
- [ ] **Semantic Scholar batch lookup across all publishers** (#24) — Semantic Scholar has a batch endpoint (up to 500 papers per call). Refactor the abstract-enrichment step to send all journal papers across all publishers through one batch call after scraping completes. Most benefit for Science and Wiley; reduces latency and catches papers missed by individual scrapers.

### Adaptation speed
- [ ] **Topic-aware liked-paper selection for scoring** (#32) — Make `_sample_liked_papers()` select papers most semantically similar to today's triage survivors (keyword overlap in Python, no embeddings). The scoring agent sees few-shot examples most relevant to today's specific batch rather than sampling broadly from the archive.
- [x] **Negative examples in scoring prompt** (#34) — `_sample_irrelevant_papers()` added to `run_pipeline.py`; samples up to 3 most recent irrelevant-rated papers from archive and includes them in the scoring message. Scoring prompt updated to instruct Sonnet to score similar patterns lower.

### Cost at scale
- [x] **Dormant user handling** (#36) — Weekly engagement report email sent every Friday alongside the run summary. Shows each user's rating count (7d + 30d) and delivery frequency (daily/weekly/off). Users with 0 ratings in 30 days are flagged `← no ratings`. Implemented in `run_all_users.py` (`_send_engagement_report()`). No automated intervention — operator decides case by case.

### Journal sources (backlog)
- [x] **Science Advances — add to other fields** — already present in cond-mat, cond-mat-optics, quantum-sensing, optics, soft-matter, systems-biology.
- [x] **PR Materials — add to cond-mat** — already present.
- [x] **ACS Nano — add to cond-mat** — already present in cond-mat and cond-mat-optics.

- [x] **Website mobile responsiveness** — done.

- [x] **`create_profile.py` — ask digest frequency during onboarding** — moved to website onboarding flow; no change needed in `create_profile.py`.

- [x] **Optics field + Amit Pando onboarding** — `optics` field added to `fields.json` (15 journals: PRL AMO, 3×PRA sections, Nature, NatPhys, NatPhoton, 2×NatComms, PNAS, Science, Optica, OpticsLetters, OpticsExpress, ACSPhotonics). New `scrapers/optica.py` built (OpenAlex abstract API). `ANTHROPIC_API_KEY_OPTICS` added to server. Amit onboarded via website. Also: PNAS `phys` feed added to cond-mat, cond-mat-optics, quantum-sensing. Field page now loads dynamically from `/fields.json` instead of hardcoded HTML.

- [x] **Weekly digest on Saturday and Sunday** — `run_weekly_only.py` added; cron `30 1 * * 0,6` deployed. Website day picker extended to Sat/Sun. `create_profile.py` accepts all 7 days. `process_pending.py` was already pass-through.

- [x] **Google Scholar profile import in onboarding** — optional Scholar URL field on the seed papers screen (`/signup/papers`). `scrapers/scholar.py` fetches the profile, resolves each paper via the Scholar citation detail page → publisher URL → citation meta tags, with OpenAlex fallback. Up to 60 papers, merged into seed papers in `process_pending.py`. Design doc: `docs/scholar_import_plan.md`.

- [x] **Self-service user onboarding** — web onboarding flow live at `incomingscience.xyz`. 5-screen static HTML flow (landing, identity/delivery, research field, interests/researchers, seed papers, success). Owner activates accounts manually via `process_pending.py`.
  - [x] **Web form** — 5-screen static HTML flow served at clean URLs: `/` (landing), `/signup` (step 1), `/signup/field`, `/signup/interests`, `/signup/papers`, `/signup/done`
  - [x] **`POST /onboarding/submit`** in `server.py` — receives final JSON, saves to `users_pending/<email-slug>/onboarding.json`
  - [x] **Success page** — POSTs JSON to `/onboarding/submit` before clearing localStorage
  - [x] **`process_pending.py`** — owner tool: `--list` shows pending submissions, `--all` or by slug processes them; uses `ANTHROPIC_API_KEY_ONBOARDING` from root `.env`; imports reusable functions from `create_profile.py`
  - [x] **Flask static serving** — website pages served at clean URLs via `server.py`; assets at `/assets/<filename>`; navigation links use absolute URLs
