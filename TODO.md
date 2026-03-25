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
