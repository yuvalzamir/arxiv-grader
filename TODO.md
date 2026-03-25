# TODO

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

- [ ] **1. `fetch_journals.py`** — new shared script
  - Hardcode the 11-journal config list (APS ×4, Nature ×5, Science, Nano Letters)
  - Per-publisher article filtering (APS: URL pattern + errata exclusion; Nature: `/articles/` path; Science: DOI pattern; ACS: pass-all)
  - Abstract scraping via `requests` + `BeautifulSoup` (per-publisher CSS selectors in design doc)
  - Soft failure on scraping error: keep paper with RSS snippet, log warning
  - `time.sleep(0.5)` between HTTP requests
  - Output schema: same as `today_papers.json` + `source` field
  - CLI: `--output` (required), `--date` (logging only)
  - Test each publisher's filtering and scraping in isolation before wiring up

- [ ] **2. `run_pipeline.py`** — add `--journals` argument
  - Load journal papers and merge with arXiv papers before triage (arXiv first)
  - Add `source` line to `_paper_block()` output (optional field, only if present)
  - No other logic changes — merged list flows through triage → scoring unchanged

- [ ] **3. `prompts/triage.txt`** — add SOURCE FIELD section
  - See exact text in `docs/journal_sources_design.md` (Triage and scoring prompt updates section)

- [ ] **4. `prompts/scoring.txt`** — add SOURCE FIELD section + "top venue" tag
  - See exact text in `docs/journal_sources_design.md`

- [ ] **5. `run_daily.py`** — accept and forward `--journals`
  - Add `--journals` arg, pass it to `run_pipeline.py` if the file exists

- [ ] **6. `run_all_users.py`** — run shared journal fetch before user loop
  - Derive `today_str` at top of `main()` from `args.date or date.today().isoformat()`
  - Run `fetch_journals.py --output data/YYYY-MM-DD/journal_papers.json` once
  - If it fails: log warning, continue arXiv-only (do not pass `--journals` to users)
  - Add `--no-journals` flag to skip journal fetch (testing)
  - Add `--journals` flag to supply a pre-built path (re-runs)

- [ ] **7. `build_digest_pdf.py`** — two fixes + source badge
  - Replace `arxiv_url()` with `paper_url()`: DOIs (`10.*`) → `https://doi.org/{doi}`, else arXiv URL
  - URL-encode `paper_id` in `rate_url()` using `urllib.parse.quote(paper_id, safe="")`
  - Add source badge (small pill, same row as score badge) for papers with `source` field

- [ ] **8. `environment.yml`** — add `beautifulsoup4` and `lxml`

- [ ] **9. End-to-end test + deploy**
  - Run `python fetch_journals.py --output /tmp/journals.json` and inspect output
  - Run `python run_all_users.py --no-email --user yuval` and inspect PDF
  - Verify rating URL for a journal paper is correctly percent-encoded
  - Verify clicking title in PDF opens `doi.org` link
  - `scp` updated files to server, `pip install beautifulsoup4 lxml`, restart if needed

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
