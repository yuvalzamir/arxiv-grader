# TODO

## Pending

- [ ] **APS full abstracts** — check if ICFO has institutional APS access (IP whitelist or API token).

---

## Upcoming

- [ ] **Refiner — check 2026-05-10 (Sunday)** — Second check: confirm accumulated ratings since last run are picked up correctly via `last_refined_at`, min-rating threshold working as expected.
- [ ] **Abstract bank — monitor** — Check `[BANK] Retrying N banked papers` in daily.log after next run to confirm bank has entries and retry is firing. Then check for `[BANK] injected` lines appearing within 7 days as OpenAlex/Europe PMC catch up.
- [ ] **APS full abstracts (deeper investigation)** — Best option found was SS DOI→arXiv ID + batched arXiv fetch: 48% hit rate, ~2min overhead. Not worth it given truncated RSS abstracts are sufficient for triage. Only remaining option: ICFO institutional APS access (IP whitelist or API token).

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

## Backlog

### Funding & sustainability
- [ ] **Sponsorship / small grant** (#42) — Apply for small grants (Sloan Foundation, NSF CAREER supplements, EU Open Science) to fund the service as public scientific infrastructure. No billing complexity, keeps it free for users. One grant typically covers 1–2 years of operating costs.

### Failure recovery
- [ ] **Watermark auto-restore on total field failure** (#2) — If every user in a field failed triage, automatically restore `journal_watermarks.json` from the per-run snapshot. Currently requires manual `cp` command. Rare but high-stakes when it happens.

### Abstract quality
- [ ] **Semantic Scholar batch lookup across all publishers** (#24) — Semantic Scholar has a batch endpoint (up to 500 papers per call). Refactor abstract-enrichment to send all journal papers through one batch call after scraping completes. Most benefit for Science and Wiley.

### Adaptation speed
- [ ] **Topic-aware liked-paper selection for scoring** (#32) — Make `_sample_liked_papers()` select papers most semantically similar to today's triage survivors (keyword overlap in Python, no embeddings). Scoring agent sees few-shot examples most relevant to today's batch.

### Discovery
- Deferred to `docs/scaling_analysis.md` — need more users per field first.
