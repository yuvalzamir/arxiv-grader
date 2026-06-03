# Check Log Skill

[[Home]] | [[Operations]] | [[Pipeline Overview]]

Skill file: `.claude/skills/check-log.md`

---

## Purpose

A Claude Code skill for diagnosing a failed or incomplete daily pipeline run. Invoked when the user reports that the run failed, no digest arrived, or something looks wrong.

**Invoke with:** `/check-log` or phrases like "run failed today", "check the daily log", "something went wrong".

---

## Flow

```
1. Establish the date (today unless specified)
2. Offer SCP command to download the log
3. Read all docs/runs/ vault notes for known bug patterns
4. Run targeted grep searches on the downloaded log
5. Match findings against known patterns → structured diagnosis
6. Print recovery command
```

---

## Grep Searches Run (Step 4)

```bash
# Full crash before any user ran
grep -n "JSONDecodeError\|Traceback\|CRITICAL" daily.log | head -20

# Per-user status summary
grep -n "OK\|FAILED" daily.log | tail -30

# Triage and scoring stats
grep -n "\[TRIAGE\]\|\[SCORE\]\|batch timeout\|fallback" daily.log

# Rate limit and API errors
grep -n "rate.limit\|529\|overloaded\|retrying" daily.log

# Journal scrape errors
grep -n "feed parse error\|fetch error\|Cloudflare\|not well-formed" daily.log | head -20

# Watermark issues
grep -n "watermark\|duplicate\|already seen" daily.log
```

---

## Recovery Command Table

| Situation | Command |
|-----------|---------|
| Full crash before any user ran | `python run_all_users.py --date YYYY-MM-DD` |
| Some users FAILED, others OK | `python run_failed_users.py --date YYYY-MM-DD` |
| Triage OK, scoring failed (batch timeout) | `python run_failed_users.py --no-batch` |
| Journal scrape failed, arxiv OK | `python run_failed_users.py` (journals re-scraped automatically) |
| Single user test | `python run_all_users.py --user <name> --date YYYY-MM-DD --no-email` |

---

## Known Bug Patterns

| Error signature | Cause | Notes |
|----------------|-------|-------|
| `JSONDecodeError` in `_user_field` | Corrupted `taste_profile.json` (unescaped quotes) | Fix profile first, then re-run all users |
| `Missing env var ANTHROPIC_API_KEY_<FIELD>` | New field added to `fields.json` without adding root `.env` key | Add key to server `.env` |
| `feed parse error — not well-formed (invalid token)` × many journals | Cloudflare IP block on RSS feeds | Check `publisher_blocklist.json` |
| `SystemExit` propagated through `except Exception` | `sys.exit()` call inside pipeline (see [[runs/2026-05-28]]) | Fixed; document if recurs |
| Batch timeout → fallback email | Anthropic Batch API incident | Check Anthropic status page; `--no-batch` as workaround |

→ See `docs/runs/` for full incident notes on past failures.

---

## Relationship to Operations

This skill complements [[Operations]] (which documents manual commands) by automating the diagnosis step. Use Operations for manual interventions; use this skill to understand what went wrong before deciding which intervention to apply.
