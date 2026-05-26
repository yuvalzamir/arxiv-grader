# Operations & Monitoring

[[Home]] | [[Infrastructure]] | [[Pipeline Overview]]

---

## Fetching Logs

```bash
# Daily pipeline log
scp root@116.203.255.222:/var/log/arxiv-grader/daily.log ./debugging/daily_log_MMDD.txt

# Monthly refiner log
scp root@116.203.255.222:/var/log/arxiv-grader/refiner.log ./debugging/refiner_log.txt

# Weekend weekly digest log
scp root@116.203.255.222:/var/log/arxiv-grader/weekly.log ./debugging/weekly_log.txt

# Flask server log
scp root@116.203.255.222:/var/log/arxiv-grader/server.log ./debugging/server_log.txt
```

---

## Reading the Daily Log

Key lines to look for:

```
# Per-user summary near the end:
alice    OK
bob      OK
carol    FAILED

# Triage stats:
[TRIAGE] 12 papers passed triage (arXiv: 8/10, journals: 4/10; 3 qualifying not forwarded)

# Rate limit events:
[WARNING] Triage-arXiv: cached API failed — falling back to direct API

# Batch timeout:
[ERROR] Scoring: batch timed out — retrying with direct API

# Batch fallback alert sent (end of run):
[INFO] Batch fallback alert sent to yuval.zamir@icfo.eu
```

The operator also receives a **run summary email** after every non-test run listing all user OK/FAILED statuses.

---

## Reading the Refiner Log

```
# Per-user refiner run:
discrepancies: 12 total (overconfident-high=2, missed-excellent=1, ...)

# Applied grade changes:
Applying grade changes: {'quantum transport': -1, 'topological insulators': +1}

# Pre-run grade-7 items:
Pre-run grade-7 items: ['old keyword']
Removing grade-7: 'old keyword'

# Area management:
Area management → DOWN: 'Kondo physics' (grade 3→4): weakest support ratio

# Weekly-only mode:
Weekly-only delivery mode detected — suppressing missed/underscored buckets

# Any errors:
ERROR: ...
WARNING: ...
```

---

## Common Operations

### Run the Full Pipeline

```bash
python run_all_users.py                              # all users
python run_all_users.py --user alice                 # single user
python run_all_users.py --user alice --no-email      # skip email (testing)
python run_all_users.py --user alice --no-batch      # skip Batch API (2× cost, instant)
python run_all_users.py --no-fetch                   # reuse existing arxiv papers
python run_all_users.py --triage-only                # stop after triage (testing)
python run_all_users.py --no-advance-watermark       # re-scrape but keep watermarks
```

### Retry Failed Users

```bash
# Auto-parses today's daily.log and retries only failed users
python run_failed_users.py
python run_failed_users.py --date 2026-04-14    # specific date
python run_failed_users.py --no-email           # skip email
python run_failed_users.py --no-batch           # skip Batch API
```

### Monthly Refiner

```bash
python run_all_users.py --refine                    # all users
python run_all_users.py --refine --dry-run          # preview only
python run_all_users.py --refine --user alice       # single user
```

### Process New Signups

```bash
python process_pending.py --list    # show pending
python process_pending.py --all     # process all
python process_pending.py <slug>    # process one by slug
# After processing: add ANTHROPIC_API_KEY to users/<slug>/.env
```

### Watermark Recovery

```bash
# If watermarks were advanced incorrectly for a date:
cp data/2026-04-14/journal_watermarks_snapshot.json journal_watermarks.json
```

### Re-Run a Specific Date

```bash
# Safe re-run: re-scrape journals but don't advance watermarks
python run_all_users.py --user alice --date 2026-04-14 --no-advance-watermark
```

### Weekend Weekly Digest

```bash
python run_weekly_only.py                    # auto-detect today
python run_weekly_only.py --user alice       # ignore weekly_day check
```

---

## Debugging the Triage/Scoring Prompt

Each run writes full prompt inputs to the user's data folder:
```
users/<name>/data/YYYY-MM-DD/triage_arxiv_input.txt
users/<name>/data/YYYY-MM-DD/triage_journals_input.txt
users/<name>/data/YYYY-MM-DD/scoring_input.txt
```

These persist for 14 days (per-user cleanup) and are invaluable for understanding why a paper was or wasn't selected.

---

## Known Constraints

- **Monday arXiv feed**: 120–165 papers (weekend accumulation); triage caps of 10+10 handle this
- **Batch API incidents**: Sonnet Batch can get stuck during Anthropic incidents → use `--no-batch` as fallback
- **ACS abstracts**: Cloudflare-blocked; S2 batch enrichment fills ~50% post-triage
- **MUSE abstracts**: CAPTCHA-blocked; ~68% coverage via S2 + OpenAlex title search
- **Scoring `max_tokens=16000`**: Sufficient for up to ~20 filtered papers
- **Cost**: ~$0.05/user/day typical; spikes on Monday (more papers) or Batch fallback (2× cost)

---

## Adding a New User

1. Via web signup → `process_pending.py`
2. Via CLI → `python create_profile.py --user-dir users/<name>`

After either method: add `ANTHROPIC_API_KEY=sk-ant-...` to `users/<name>/.env`, then SCP to server.

→ See [[User Onboarding]] for full flow.

---

## Adding a New Field

See `add_new_field.md` for step-by-step guide. Short version:
1. Add to `fields.json` (with `tree_path`)
2. Add `ANTHROPIC_API_KEY_<FIELD_UPPER>` to root `.env`
3. Onboard a user in the new field
4. SCP updated files

→ See [[Journal Scrapers]] for `fields.json` schema.
