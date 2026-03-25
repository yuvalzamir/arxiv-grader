# Multi-user architecture plan

## Context

~10 users, each with their own taste profile, history, API key, email address, and daily digest. The pipeline runs sequentially for all users once per day on a single server (Red Pitaya).

Research basis: for <20 users, directory-per-user with JSON files is the dominant pattern — avoids locking, keeps data completely isolated, requires minimal dependencies. Sources: appdirs pattern, small SaaS boilerplate conventions, SQLite official documentation ("appropriate uses" guidance).

---

## Current single-user assumptions (files that need changes)

| File | What's hardcoded today |
|------|------------------------|
| `run_daily.py` | `taste_profile.json` at root, single `data/` tree, reads one `.env` |
| `archive.py` | `DATA_DIR` and `ARCHIVE_PATH` both at project root |
| `deduplicate_ratings.py` | `DATA_DIR` at project root |
| `run_profile_refiner.py` | `taste_profile.json` and `archive.json` at project root |
| `server.py` | `DATA_DIR` fixed at project root; `/rate` has no user parameter |
| `build_digest_pdf.py` | Rating button URLs have no user identifier |
| `create_profile.py` | Creates `taste_profile.json` at root, writes single `.env` |
| `run_pipeline.py` | **No changes needed** — already fully argument-driven |

---

## Three options considered

### Option A — Directory-per-user ✓ CHOSEN

```
users/
  alice/
    .env                  ← ANTHROPIC_API_KEY + EMAIL_TO only
    taste_profile.json
    archive.json
    data/
      2026-03-19/
        today_papers.json
        filtered_papers.json
        scored_papers.json
        digest.pdf
        ratings.json
  bob/
    ...
run_all_users.py          ← new master orchestrator
```

Scripts get `--user-dir PATH`. All paths resolved relative to `--user-dir`. Rating URLs embed `&user=USERNAME`. Server routes on `?user=`.

**Pros:** Complete isolation. Add/remove = create/delete one directory. Independent backups. Dominant pattern at this scale.
**Cons:** Every script needs path-resolution changes (except `run_pipeline.py`).

---

### Option B — Namespace in shared directories (not chosen)

```
profiles/alice.json   archives/alice.json   data/alice/DATE/   envs/alice.env
users.json            ← registry
```

Scripts get `--user alice`; paths computed as `profiles/{user}.json`, etc.

**Why not chosen:** User data scattered across 3 shared directories. Adding/removing a user requires editing `users.json` AND cleaning up across multiple directories. A registry (users.json) is a second source of truth that can diverge from the actual files. No meaningful advantage over Option A.

---

### Option C — Shared fetch + per-user grading (not chosen)

Variant of Option A where `today_papers.json` is fetched once into `shared/DATE/` and shared across all users.

**Why not chosen:** The fetch step is free (pure RSS parsing, no API cost, ~1 second). Sharing it adds coordination complexity for near-zero savings. Also breaks if users have different `arxiv_categories`. Worth reconsidering only if user count exceeds ~50.

---

## Implementation plan for Option A

### New file: `run_all_users.py`

Logic (not code):
1. Scan `users/*/` for subdirectories that contain `taste_profile.json`
2. For each user directory, in sequence:
   a. Load that user's `.env` into the subprocess environment
   b. Call `run_daily.py --user-dir users/alice` (pass through all flags: `--date`, `--no-email`, `--keep-days`)
   c. Log success/failure per user; on failure, continue to next user rather than aborting
3. Sequential execution — avoids API rate limits, keeps logs readable
4. Total wall-clock: ~5 min × N users on a normal day

### Changes to existing scripts

**`run_daily.py`**
- Add `--user-dir PATH` argument (default: project root for backward compatibility)
- Resolve `taste_profile.json`, `data/`, `archive.json` relative to `--user-dir`
- Load `--user-dir/.env` in addition to root `.env` (user env takes precedence for `ANTHROPIC_API_KEY` and `EMAIL_TO`)
- Pass `--user-dir` through to subprocess calls for `archive.py`, `deduplicate_ratings.py`

**`archive.py`**
- Add `--user-dir PATH` argument
- Resolve `DATA_DIR` and `ARCHIVE_PATH` from `--user-dir` instead of `Path(__file__).parent`

**`deduplicate_ratings.py`**
- Add `--user-dir PATH` argument
- Resolve `DATA_DIR` from `--user-dir`

**`run_profile_refiner.py`**
- Add `--user-dir PATH` argument
- Resolve `taste_profile.json` and `archive.json` from `--user-dir`

**`server.py`**
- Parse `?user=USERNAME` from rating URL
- Validate `USERNAME` against known user directories (scan `users/*/`)
- Resolve `DATA_DIR` to `users/{USERNAME}/data/`
- If `?user=` missing or invalid, return 400 with clear error

**`build_digest_pdf.py`**
- Add `--user USERNAME` argument
- Embed `&user=USERNAME` in all three rating button URLs per paper

**`create_profile.py`**
- Add `--user-dir PATH` argument (or prompt for username and create `users/{username}/`)
- Create directory structure: `users/{username}/data/`
- Write `.env` to `users/{username}/.env` (only `ANTHROPIC_API_KEY` + `EMAIL_TO`)
- Write `taste_profile.json` to `users/{username}/taste_profile.json`

### Cron wiring (unchanged count)

Single cron entry replaces the per-user entry:
```
0 7 * * 1-5  conda run -n arxiv-grader python /path/to/run_all_users.py
0 7 1 * *    conda run -n arxiv-grader python /path/to/run_all_users.py --refine
```

`run_all_users.py` handles `--refine` by calling `run_profile_refiner.py` for each user instead of `run_daily.py`.

### Backward compatibility

Current single-user setup (files at project root) continues to work if `--user-dir` defaults to the project root. Migration path: move existing `taste_profile.json`, `archive.json`, and `data/` into `users/yuval/`, create `users/yuval/.env`, done.

---

## What does NOT change

- `run_pipeline.py` — already fully argument-driven (`--papers`, `--profile`, `--filtered`, `--scored`). No changes.
- `prompts/` — shared across all users. No changes.
- `fetch_papers.py` — run once per user (or once shared); already has `-o` flag. No changes needed for Option A.
- SMTP credentials — still hardcoded in `create_profile.py`; users only set `EMAIL_TO` in their `.env`.
- Anthropic API — each user provides their own `ANTHROPIC_API_KEY`. Costs are per-user.
