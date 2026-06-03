# Check Daily Log Skill

## Description
Use this skill when the operator reports that today's daily run failed or behaved unexpectedly. Claude downloads the log, reads vault run notes for known bugs, and diagnoses what went wrong.

Trigger on phrases like "run failed", "check the log", "pipeline failed", "digest not sent", "what went wrong today", "/check-log".

---

## Instructions

### Step 1 — Establish the date

Use today's date as the run date unless the operator specifies otherwise. Confirm: "Checking the run for YYYY-MM-DD — is that correct?"

---

### Step 2 — Offer to download the log

**Never run scp yourself. Print the command and ask the operator to run it.**

```
scp root@116.203.255.222:/var/log/arxiv-grader/daily.log ./debugging/daily_log_MMDD.txt
```

(Replace MMDD with today's month and day, e.g. `0603` for June 3.)

Wait for the operator to confirm the download before proceeding.

---

### Step 3 — Read known bugs from vault run notes

Before reading the log, read all existing run notes to know what bugs have been seen before:

```
docs/runs/
```

Use `Glob` to list all files in `docs/runs/`, then read each one. This gives context for pattern-matching against the current log.

---

### Step 4 — Read the log

The log file is large — do not read it whole. Use targeted searches:

1. **Summary lines** — user OK/FAILED status:
   ```
   grep -E "(OK|FAILED|ERROR|Exception|Traceback|No papers|skipping)" debugging/daily_log_MMDD.txt | tail -100
   ```

2. **Failed users** — find which users failed and why:
   ```
   grep -E "FAILED|ERROR|Warning" debugging/daily_log_MMDD.txt | grep -v "HTTP"
   ```

3. **Traceback** — if a crash occurred, get context around it:
   ```
   grep -A 20 "Traceback" debugging/daily_log_MMDD.txt
   ```

4. **Missing items** — check if any expected users are absent from the summary.

---

### Step 5 — Diagnose

Produce a structured diagnosis:

```
Run diagnosis: YYYY-MM-DD
=========================

STATUS: [Complete / Partial failure / Full crash]

FAILED USERS:
  - <user>: <reason>

ERRORS:
  - <error message and likely cause>

MATCHES KNOWN BUG: [yes/no — reference docs/runs/<date>.md if yes]

RECOMMENDED ACTION:
  - <what to fix and how>
  - <recovery command if needed>
```

Common patterns to check against vault notes:
- `JSONDecodeError` in `_user_field` → corrupted taste_profile.json (see 2026-06-03)
- `SystemExit` propagating through `except Exception` → sys.exit() in run_pipeline.py (see 2026-05-28)
- `Missing env var ANTHROPIC_API_KEY_<FIELD>` → centralized triage key not set in server .env
- Batch API stuck polling → Anthropic incident; suggest `--no-batch` flag

---

### Step 6 — Recovery

Based on the diagnosis, print the appropriate recovery command. Do NOT run it yourself.

| Situation | Recovery command |
|-----------|-----------------|
| Full crash before any user ran | `python run_all_users.py --date YYYY-MM-DD` |
| Partial failure (some users OK) | `python run_failed_users.py --date YYYY-MM-DD` |
| Triage succeeded but scoring failed | `python run_all_users.py --date YYYY-MM-DD --score-only` |
| Batch API issue | `python run_all_users.py --date YYYY-MM-DD --no-batch` |
