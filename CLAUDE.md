# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@TODO.md

## Project Memory

This project uses an Obsidian vault (vault root = project root, `.obsidian/` config present) as its knowledge base. Vault notes live in `docs/`.

**Entry point: `docs/Home.md`** — read this for navigation, quick-reference command table, and links to all topic notes.

Vault structure (all in `docs/`):
- `Home.md` — master index
- `Pipeline Overview.md` · `AI Pipeline.md` · `Prompt Caching.md` — pipeline internals
- `Journal Scrapers.md` · `Abstract Enrichment.md` — data ingestion
- `Taste Profile.md` · `User Onboarding.md` · `Monthly Refiner.md` · `Paper Insights.md` — user & profile
- `Daily Digest.md` · `Weekly Digest.md` — delivery
- `Infrastructure.md` · `Operations.md` · `Cost Model.md` — ops
- (deeper design docs live alongside the vault notes, also in `docs/`)

When you discover something significant — a decision, a new feature, a constraint, a failure mode — update or create the relevant note in the vault with `[[wikilinks]]` to related concepts.

## Claude's Responsibilities

**At the start of any task:** read `docs/Home.md` and identify which vault notes are relevant before beginning. Read those notes.

**When documenting or wrapping up a task:** update the relevant vault note(s) in `docs/`. Also update `docs/Home.md` if a new note was created or an existing one changed scope. Do this before any context compaction happens — treat it as part of completing the task, not optional follow-up.

**When analyzing a pipeline run (logs, costs, paper counts, triage rates):** create a note at `docs/runs/YYYY-MM-DD.md` as soon as analysis begins. Update it as findings emerge. Do not wait until the end to write it.

**When correcting a mistake traced to a vault note:** point out the stale or wrong entry explicitly and ask the user to confirm the correction before updating the note. Do not silently fix it — make the change visible.

## Project Overview

**Incoming Science** is a multi-user AI-powered daily arXiv digest system. It fetches papers from arXiv and top physics journals, grades them using a two-stage Claude pipeline (triage → scoring), generates a PDF digest with rating buttons, emails it to users, and uses collected ratings to refine each user's taste profile monthly.

The system runs as a cron job on a Hetzner VPS (`incomingscience.xyz`). Users rate papers via hyperlinks in the PDF that hit a Flask endpoint.

## Common Commands

```bash
# Run full pipeline for all users
python run_all_users.py

# Run for a single user (testing)
python run_all_users.py --user <name>

# Skip email delivery (testing)
python run_all_users.py --user <name> --no-email

# Override date
python run_all_users.py --date 2026-03-19

# Skip journal scraping
python run_all_users.py --no-journals

# Skip Batch API (use direct API; fallback mode)
python run_all_users.py --user <name> --no-batch

# Monthly profile refiner
python run_all_users.py --refine
python run_all_users.py --refine --dry-run

# Onboard a new user (interactive)
python create_profile.py --user-dir users/<name>

# Process pending web signups (non-interactive)
python process_pending.py --list          # see what's waiting
python process_pending.py --all           # process all pending
python process_pending.py <slug>          # process one by slug
# After processing: add ANTHROPIC_API_KEY to users/<slug>/.env

# Run Flask rating server locally
python server.py
```

## Architecture

### Daily Pipeline (`run_all_users.py` → `run_daily.py` per user)

1. `deduplicate_ratings.py` — keep latest rating per paper per day
2. `archive.py` — append deduplicated ratings to `users/<name>/archive.json`
3. `fetch_papers.py` — fetch arXiv RSS → `today_papers.json`
4. `fetch_journals.py` — scrape 11 top journals → append to today_papers
5. `run_pipeline.py` — two-stage AI grading via Anthropic Batch API
6. `build_digest_pdf.py` — generate PDF with embedded rating hyperlinks
7. `send_email()` — email PDF to user
8. `cleanup_old_folders()` — delete `data/` folders older than 14 days

Users run in parallel via `ThreadPoolExecutor`.

### AI Pipeline (`run_pipeline.py`)

Two-stage design using Anthropic Batch API (50% cost discount, async):

- **Triage** (Claude Haiku, `prompts/triage.txt`): Receives lean profile (keywords, areas, authors) + all ~80 papers. Classifies high/medium/low. Hard caps: max 15 arXiv + 15 journal papers forwarded.
- **Scoring** (Claude Sonnet, `prompts/scoring.txt`): Receives full profile + triage survivors. Outputs score 1–10 + one-line justification + tags.

**Paper Insights (opt-in):** Users with `"paper_insights": true` in `taste_profile.json` use `prompts/scoring_insights.txt` instead, which adds an `insights` object (`claim`, `novelty`, `relevance`) to each scored paper. The PDF renders these as a three-row box below the author band, replacing the justification and tags. Papers with truncated/missing abstracts are excluded from insights in Python (not just by prompt instruction). Enable per user by setting the flag manually in their server-side `taste_profile.json`.

On 20-minute batch timeout, auto-falls back to direct API and sends an alert email. Flag file `batch_fallback.json` is written when fallback occurs; `run_all_users.py` scans for these post-pipeline.

### User Data Layout

```
users/<name>/
├─ .env                    # ANTHROPIC_API_KEY, EMAIL_TO
├─ taste_profile.json      # Evolving profile (keywords/areas/authors/liked_papers)
├─ archive.json            # Permanent append-only ratings history
└─ data/YYYY-MM-DD/
   ├─ today_papers.json    # All fetched papers (arXiv + journals)
   ├─ filtered_papers.json # Triage survivors
   ├─ scored_papers.json   # Final ranked output
   ├─ digest.pdf
   └─ ratings.json         # Ratings recorded today
```

### Journal Scrapers (`fetch_journals.py`)

Per-publisher scraper classes under `scrapers/`: `aps.py`, `nature.py`, `science.py`, `acs.py`, `wiley.py`, `optica.py`, `cambridge.py`, `royalsociety.py`, `aip.py`, `cell.py`, `plos.py`, `pnas.py`, `iop.py`, `oup.py`, `edp.py`, `elsevier.py`, `scipost.py`. Field configuration (which journals, categories, tag filters) lives in `fields.json`. Watermarks in `journal_watermarks.json` prevent re-fetching duplicates.

### Rating Endpoint (`server.py`)

Flask app with three routes:
- `GET /` — landing page
- `GET /rate?user=&date=&paper_id=&rating=&...` — records rating to `data/DATE/ratings.json`
- `GET /health` — health check

### Monthly Refiner (`run_profile_refiner.py`)

Runs on the 2nd of each month. Loads 30 days of archive, pre-classifies score/rating discrepancies into 5 buckets, calls Claude Sonnet Batch to recommend `taste_profile.json` grade adjustments (±1 grade/month cap). Appends to `evolved_interests` narrative.

## Key Design Principles

- **Agents are pure reasoning — no tools**: All I/O (file reads, API calls, data prep) is done in Python. Claude receives structured in-context data and returns structured JSON.
- **System prompt quality over agent complexity**: Prompt engineering is the primary lever for accuracy. Read and preserve the triage/scoring rules carefully.
- **Concrete-anchor triage**: Medium classification requires at least one explicit keyword/author/subcategory anchor. Pure thematic adjacency is disqualified (this is intentional, see `prompts/triage.txt`).
- **Lean profile for triage**: Only keywords, areas, and authors go to Haiku. Full profile (interests description, liked papers, evolved_interests) is reserved for Sonnet scoring.

## Environment Setup

Two `.env` files required:
- **Root `.env`**: `RATING_BASE_URL`, `EMAIL_FROM`, `EMAIL_SMTP_HOST`, `EMAIL_SMTP_PORT`, `EMAIL_SMTP_USER`, `EMAIL_SMTP_PASSWORD`
- **Per-user `users/<name>/.env`**: `ANTHROPIC_API_KEY`, `EMAIL_TO`

```bash
pip install -r requirements.txt
```

## Production Infrastructure

- **VPS**: Hetzner CX23, Ubuntu 24.04, `116.203.255.222`
- **Web**: Caddy reverse proxy + HTTPS (Let's Encrypt) → Gunicorn (systemd)
- **Cron (system TZ=America/New_York, DST-aware)**:
  - Mon–Fri 00:30 ET → daily pipeline
  - 2nd of month 01:30 ET → monthly refiner
- **Logs**: `/var/log/arxiv-grader/daily.log`, `/var/log/arxiv-grader/refiner.log`

## Deploying to the Server

The server does **not** pull from git. Files must be copied manually via SCP:

```bash
scp <file1> <file2> root@116.203.255.222:/opt/arxiv-grader/
```

**Never SSH into the server or run the pipeline autonomously** — always provide commands for the user to run themselves.

## Known Constraints

- APS abstracts are full — fetched via `harvest.aps.org` Harvest API (no auth required; confirmed working for PRL, PRB, PRX, PRXQuantum, PRMaterials)
- Monday arXiv feed has 120–165 papers (weekend accumulation) — triage caps handle this
- Science eTOC gives all papers from the last issue sharing the same date; watermark prevents duplicates on repeated runs
