# TODO

---

## Bug backlog — 2026-07-20 audit (details + line numbers in `docs/hidden_bugs_audit.md`, second round)

Three high-severity bugs from this audit were fixed 2026-07-20 (Friday-ratings archiving, malformed-profile crash, archive corruption wipe). Remaining, in priority order:

**Crash-proofing (small fixes):**
- [ ] Scoring join: `item["arxiv_id"]` KeyError on one malformed model entry kills the run post-billing (`run_pipeline.py:688`) — use `.get()` + warning.
- [ ] `feedparser.parse()` timeout fix never landed in `fetch_papers.py:138` / `fetch_preprints.py:106,179` — still can hang the pipeline.
- [ ] PDF build crashes on null insights value (`build_digest_pdf.py:406` `.strip()` on None) and on tags containing `&`/`<` (line 425, unescaped).

**Recovery-run correctness:**
- [ ] `build_digest_pdf.py` has no `--date` — rebuilt digests stamp rating URLs with today's date (wrong folder for ratings).
- [ ] `run_daily.py:180-189` cleanup uses `date.today()` (ignores `--date`) + raw string compare — `--date` rebuilds delete the folder they just created.
- [ ] Retry runs overwrite `journal_watermarks_snapshot.json` with post-advance watermarks (`run_all_users.py` snapshot block) — gate it on a fresh (non-retry) run.
- [ ] Weekly phase re-triggers on retry runs → duplicate weekly digest emails (`run_all_users.py` weekly block).

**Fallback robustness:**
- [ ] Triage fallbacks never write `batch_fallback.json` → no alert email for triage 2x-cost days (`run_pipeline.py:479-513`). (Recurred 2026-09-04: ~20 users fell back silently.)
- [ ] Scoring falls back to direct API only on timeout; an `errored`/`expired` batch exits instead (`run_pipeline.py:403-416`).

**Quality / minor:**
- [ ] Liked-papers sampler joins archive on `arxiv_id` but archive stores `paper_id` (`run_pipeline.py:207,227`) — broken dedup, arXiv papers labeled `[journal]`.
- [ ] Per-article scrape errors are skipped but the watermark advances past them — permanent paper loss (`scrapers/sources.py:331-334`).
- [ ] Quiet days on journals-only fields exit 1 while summary email says all-OK (`run_all_users.py` exit logic; NO-RUN/None is falsy).
- [ ] Undated feed entries bypass watermark + same-day skip → repeat in consecutive digests (`scrapers/sources.py:279-283`).
- [ ] `run_failed_users.py:114-116` doesn't apply the `cond-mat` field default → legacy profiles unretryable; weekly-send failures invisible to it as well.
- [ ] Evening manual runs without `--date` straddle midnight (parent vs child recompute); `--date` reruns >3 days old get their shared folder cleaned up at end of run; best-effort batch cancel can double-bill.

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
- On Mondays, arXiv feed has 120–165 papers due to weekend accumulation — triage cap of 10 handles this
- Scoring agent `max_tokens` raised 16000 → 24000 on 2026-08-25 (`SCORING_MAX_TOKENS`) after a full 20-paper insights batch hit the old cap (15,671 tokens, ruihaoliu). Headroom now ~50% over worst observed.
- Cron: system timezone set to `America/New_York` (`timedatectl set-timezone`); crontab runs at 00:30 ET daily, 01:30 ET monthly refiner — DST handled automatically
- Anthropic Batch API (Sonnet) can get stuck during incidents — use `--no-batch` flag as fallback

---

## Backlog

### Funding & sustainability
- [ ] **Sponsorship / small grant** (#42) — Apply for small grants (Sloan Foundation, NSF CAREER supplements, EU Open Science) to fund the service as public scientific infrastructure. No billing complexity, keeps it free for users. One grant typically covers 1–2 years of operating costs.

### Failure recovery
- [ ] **Web service self-healing after 2026-08-26 futex-deadlock outage** (see `docs/runs/2026-08-26.md`) — the single Gunicorn worker deadlocked on a futex while the process stayed `active (running)`, so systemd `Restart=` never fired; site was 502 for 1+ hours. Done 2026-08-26: `copytruncate` added to logrotate (service was log-blind — rotation orphaned Gunicorn's log fd); `py-spy` installed in the venv; **health-check watchdog live** — root cron runs `/opt/arxiv-grader/watchdog.sh` (in repo) every minute: on `/health` failure it py-spy-dumps the worker's stacks to `/var/log/arxiv-grader/watchdog.log`, then restarts the service. If the site blips, check that log — a captured stack = the deadlock recurred and we can root-cause it. **Update 2026-09-10:** watchdog fired 8× on Sep 3–4; every py-spy stack shows the lone sync worker blocked in `sock.recv` mid-request-parse (slow/held client connection starving the worker — a scanner burst, NOT the futex deadlock). Watchdog kept each blip ≤1 min; quiet since Sep 4 09:30. See `docs/runs/2026-09-10.md`. Remaining: (1) Caddyfile upstream `localhost:5000` → `127.0.0.1:5000` (avoids the ::1-first dial and its 3s penalty per request); (2) `-w 2` in the gunicorn unit so one wedged worker doesn't kill the site — the Sep 3–4 episode makes this the priority fix.
- [ ] **FlareSolverr outage 2026-09-08→10 — RESOLVED 2026-09-10, verify next run** — `ConnectionResetError(104)` on every call for 3 days (25/48/42 failures on Sep 8/9/10); Cloudflare-walled publishers (Tandfonline, SAGE, Wiley, Chicago) fetched nothing. Root cause: **stale `docker-proxy`** — Docker's port-mapping state got corrupted (~Sep 7–8): the current container had no registered mapping (`docker port` empty) while an orphaned proxy process still held 127.0.0.1:8191 and reset every connection. `docker restart` cannot fix this; the container had to be removed and re-created (`docker rm -f` + kill stale proxy + original `docker run`). Health check OK after recreation. Check the next daily log: T&F/SAGE feeds should return and drain the 3-day backlog via watermarks — then delete this item. See `docs/runs/2026-09-10.md`.
- [ ] **IEEE SPL: 0 papers, whole feed "skipped at or before watermark" daily** — SPL's watermark advances daily while every entry is skipped, which is contradictory; suspect feed entries carry a feed-build date so nothing is ever "new". Investigate `fetch_from_rss` date handling for the ieeexplore.ieee.org feed. (TSE recovered on its own 2026-08-17: 17 articles, watermark advanced — its stall was just no new feed content.)
- [ ] **Watermark auto-restore on total field failure** (#2) — If every user in a field failed triage, automatically restore `journal_watermarks.json` from the per-run snapshot. Currently requires manual `cp` command. Rare but high-stakes when it happens.
- [ ] **Retry on truncated JSON in scoring** — On 2026-06-04 Yael's scoring failed on truncated JSON mid-string in an `insights.relevance` field (6153 output tokens, well under the cap — transient API issue). Recurred 3× week of Aug 10–14 (Yael, sudha, nadav), Mon 2026-08-17 (Ediz), Tue 2026-08-25 (ruihaoliu), Wed 2026-08-26 (Yael, 7013 output tokens — well under the new 24k cap, confirming the transient-fault class persists independently), and 4× the week of Sep 1–10 (anton-sv 09-01, marta 09-02, eudomar 09-03, yanirmr 09-09) — mostly auto-recovered via `run_failed_users.py` at 2× cost, **but on 2026-09-09 the retry hit the same truncation and yanirmr received no digest that day — first user-visible miss from this bug class.** The 08-25 case was genuine `max_tokens` cap truncation (15,671 ≈ 16,000 with 20 insights papers) — **fixed 2026-08-25: scoring `max_tokens` raised to `SCORING_MAX_TOKENS = 24000`** (`run_pipeline.py:37`; no cost impact — only generated tokens are billed). Remaining for the transient-fault cases: if JSON parse fails and the response looks truncated (no closing `]`), retry once via direct API before giving up.

### Adaptation speed
- [ ] **Topic-aware liked-paper selection for scoring** (#32) — Make `_sample_liked_papers()` select papers most semantically similar to today's triage survivors (keyword overlap in Python, no embeddings). Scoring agent sees few-shot examples most relevant to today's batch.

### Abstract coverage — CORE API fallback
- [ ] **CORE API abstract enrichment** — API key: `HyQYgNwRSCc0Mtix1Xv7rJof9lpmOAkF`. Add `_fetch_abstract_core(doi)` to `base.py` using `GET https://api.core.ac.uk/v3/works/doi:{doi}` with `Authorization: {key}` header. Returns `abstract` field for indexed OA papers. Add as third fallback in `TandfonlineScraper.scrape_article` (after OpenAlex, before S2 batch) and in `SageScraper`. Rate: 1,000 req/day registered — sufficient. Expected lift: ~5–10% on OA papers not yet in OpenAlex.

  **Relevant journals by field (all tandfonline publisher):**
  - `edu-policy`: JEdPolicy, ComparativeEdu, StudiesHigherEdu, OxfordReviewEdu, AssessmentInEdu
  - `econ-political`: PoliticalComm
  - `econ-education`: EduEconomics, JEconEducation, SchoolLeadership, JEdWork
  - `gender-studies`: GenderPlaceCulture
  - `literature-and-culture`: JModernJewishStudies, JewishCultureHistory

  Also relevant for Elsevier social-science journals with same Nov-2024 restriction (elsevier_general): EconEdReview, TeachingTeacherEdu, EarlyChildhoodResQ, IntJEdDevelopment, ComputersEdu (edu-policy field).

  Also relevant for `library-science` (added 2026-08-21): JAcademicLibrarianship + LISResearch (elsevier_general, 43/61 and 5/8 abstracts missing in verification) and JLSC (OA but platform is Anubis-bot-walled; OpenAlex has no abstracts — CORE should, since it's OA).

### Discovery
- Deferred to `docs/scaling_analysis.md` — need more users per field first.
