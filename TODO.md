# TODO

## Pending

- [ ] **Profile edit skill with user input** — Build a Claude Code skill that walks through editing a user's `taste_profile.json` interactively (keywords, areas, authors, grades) with prompts for each section.
- [ ] **Measure daily fetch time** — Instrument `fetch_papers.py` and `fetch_journals.py` to log elapsed time per stage; check how long the full fetch takes on the server.
- [ ] **Parallelize journal scraping** — Journal fetching takes ~18 min sequentially (bottleneck: Neural Networks ~77s, TPAMI ~29s, etc.). Run scrapers concurrently per field using `ThreadPoolExecutor` in `fetch_journals.py`. Risk: per-publisher rate limits — may need to group by publisher and limit concurrency per group.

## Upcoming

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
- On Mondays, arXiv feed has 120–165 papers due to weekend accumulation — triage cap of 15 handles this
- Scoring agent `max_tokens=16000` — sufficient for up to ~30 filtered papers (cap 15+15)
- Cron: system timezone set to `America/New_York` (`timedatectl set-timezone`); crontab runs at 00:30 ET daily, 01:30 ET monthly refiner — DST handled automatically
- Anthropic Batch API (Sonnet) can get stuck during incidents — use `--no-batch` flag as fallback

---

## Backlog

### Funding & sustainability
- [ ] **Sponsorship / small grant** (#42) — Apply for small grants (Sloan Foundation, NSF CAREER supplements, EU Open Science) to fund the service as public scientific infrastructure. No billing complexity, keeps it free for users. One grant typically covers 1–2 years of operating costs.

### Failure recovery
- [ ] **Watermark auto-restore on total field failure** (#2) — If every user in a field failed triage, automatically restore `journal_watermarks.json` from the per-run snapshot. Currently requires manual `cp` command. Rare but high-stakes when it happens.

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

### Discovery
- Deferred to `docs/scaling_analysis.md` — need more users per field first.
