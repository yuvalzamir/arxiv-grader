# Incoming Science — arXiv Daily Digest

A personal arXiv digest tool for researchers. Every day it fetches the latest papers in your field, ranks them by relevance to your research interests using AI, and delivers a scored PDF to your inbox — ready to read on your phone. Rate papers with one tap; ratings feed back into an evolving taste profile that sharpens recommendations over time.

Live at [incomingscience.xyz](https://incomingscience.xyz)

---

## How it works

1. **Fetch** — pulls the arXiv RSS feed and scrapes journals across multiple fields each morning
2. **Triage** — Claude Haiku filters ~80–120 papers down to the ~30 most likely to be relevant (15 arXiv + 15 journal cap)
3. **Score** — Claude Sonnet scores each surviving paper 1–10 with a one-line justification
4. **Deliver** — a ranked PDF digest is emailed to you as an attachment
5. **Rate** — tap Excellent / Good / Irrelevant buttons in the PDF; ratings are recorded
6. **Refine** — once a month, Claude Sonnet reviews your rating history and updates your taste profile

---

## Architecture

### 1. Data ingestion — `fetch_papers.py` + `fetch_journals.py`

**arXiv (`fetch_papers.py`):** Pulls the arXiv RSS feed, filters to new submissions only (no cross-listings, no replacements). Supports `--category` for field filtering (e.g. `cond-mat`). If the feed is empty (holiday or off-day), the pipeline exits cleanly. Fetched once per field, shared across all users in that field.

**Journals (`fetch_journals.py`):** Scrapes journals via RSS/eTOC feeds. Publisher-specific scraper classes live under `scrapers/` (APS, Nature, Science, ACS, Wiley, Optica, Cell, PLOS, PNAS). Field configuration — which journals to monitor and tag filters for multi-discipline journals — is defined in `fields.json`. A per-journal watermark (`journal_watermarks.json`) prevents re-fetching papers already seen. Fetched once per run, filtered per field, shared across all users. Use `--since YYYY-MM-DD` to override the watermark for a manual re-run without advancing it.

Each scraped paper is tagged with `feed_url` (the RSS URL it came from). `filter_for_field` uses this URL — not the display name — to decide whether a paper belongs to a field. This means the same journal can appear in multiple fields with different RSS subfeeds (e.g. a photonics subfeed for optics, a physics subfeed for cond-mat) and papers will be routed correctly. The `source` field (journal display name) is unaffected and used only for display in the PDF. `feed_url` is never passed to triage or scoring prompts.

**Abstract availability by publisher:** Nature scrapes article pages for full abstracts + subject tags. Science uses Semantic Scholar (~50% hit rate). APS uses the truncated RSS abstract (article pages Cloudflare-blocked, no API source). ACS uses the Europe PMC API (DOI lookup) — ~93–95% hit rate for NanoLett, ACSNano, ACSSensors; ACSPhotonics is not indexed by Europe PMC and falls back to empty abstract. Wiley extracts full abstracts directly from the RSS feed, no page fetches needed. Optica uses the RSS feed for metadata and OpenAlex API for full abstract reconstruction (high hit rate, no page fetches needed).

**Holiday handling:** arXiv papers are fetched before journals. If all fields return empty arXiv feeds (holiday or off-day), the pipeline exits before the journal scraper runs — watermarks are not advanced and journal papers are preserved for the next day.

**Journals covered:** Configured per field in `fields.json`. All fields share large multidisciplinary journals (Nature, Science, PNAS physics feed) with tag filters applied per-field:
- **cond-mat:** PRL (two section feeds), PRB, PRX, PRXQuantum, Nature, Nature Physics, Nature Materials, Nature Nanotechnology, Nature Communications, PNAS (physics), Science, Nano Letters
- **cond-mat-optics:** same as cond-mat (AMO/optics tag filters)
- **quantum-sensing:** ACS Nano, ACS Photonics, ACS Sensors, Nano Letters, Small, Nanophotonics, Nature, Nature Photonics, Nature Nanotechnology, Nature Materials, Nature Communications, PNAS (physics), Science
- **optics:** PRL (AMO section), PRA (quantum optics, quantum information, fundamental concepts sections), Nature, Nature Physics, Nature Photonics, Nature Communications (physics + optics-and-photonics feeds), PNAS (physics), Science, Optica, Optics Letters, Optics Express, ACS Photonics
- **systems-biology:** Cell, PLOS Biology, PNAS (biophysics/immunology/cell-biology/microbiology feeds), Science, Science Immunology, Science Advances, Nature, Nature Communications, eLife

**Output schema per paper:**
- arXiv ID (or DOI for journal papers), title, abstract, authors, subcategories
- Journal papers additionally carry: `source` (journal name), `doi`, `url`

---

### 2. User taste profile — `create_profile.py` + `taste_profile.json`

A one-time interactive onboarding script that creates `taste_profile.json`. The profile evolves over time through monthly automated refinement.

**Onboarding flow:**
1. Validates Anthropic API key and collects recipient email
2. User provides arXiv categories, a free-text description of interests, researchers to follow, and an Excel file of recently-read paper URLs
3. Python fetches title/authors/abstract for all provided papers
4. Python pre-computes author frequencies
5. A single Claude call returns ranked keywords, research areas, and authors
6. User reviews and can reorder rankings interactively

**Profile schema:**
```json
{
  "arxiv_categories": ["cond-mat.str-el", "cond-mat.mes-hall"],
  "interests_description": "Free-text description of research interests",
  "keywords": [
    {"keyword": "topological insulators", "grade": 1},
    {"keyword": "quantum transport", "grade": 2}
  ],
  "research_areas": [
    {"area": "strongly correlated electrons", "grade": 1}
  ],
  "authors": [
    {"name": "Jane Smith", "rank": 1}
  ],
  "liked_papers": [
    {
      "arxiv_id": "2301.12345",
      "title": "...",
      "rating": "excellent | good | irrelevant",
      "why_relevant": "..."
    }
  ],
  "evolved_interests": ""
}
```

**Grade system:** Grade 1 = most relevant (core interest). Grade 7 = fading. Grades 1–5 are assigned at creation or by user; grades 6–7 are assigned only by the monthly refiner. Keywords at grade 7 for two consecutive months are automatically removed. Authors use a separate rank system (rank 1 = highest priority).

**What grading agents see:** Interests description + keywords + areas + authors + `evolved_interests` narrative + last 5 liked papers. Not the full rating history, to keep context costs bounded.

---

### 3. Grading pipeline — `run_pipeline.py`

Two sequential Claude API calls per user.

#### Stage 1: Triage (Claude Haiku) — cached API

Triage runs **centrally per field** in `run_all_users.py` before the per-user scoring phase. Users in a field are triaged in parallel with staggered launches to maximise prompt cache hits while respecting rate limits.

**Prompt caching structure:** The paper list and system prompt are identical for all users in a field and are marked `cache_control: ephemeral`. The user's taste profile is appended as the non-cached suffix. The first user warms the cache; subsequent users pay ~10% of normal input token cost for the papers block.

**Two independent calls per user** (to avoid cross-pool calibration and use field-specific prompts):
- **arXiv triage** (`prompts/triage.txt`) — all arXiv papers for the field
- **Journal triage** (`prompts/triage_journals.txt`) — all journal papers for the field

Each call has its own pair of cache entries (system prompt + papers block), both live simultaneously.

- **Input per call:** Papers list (cached) + lean profile — keywords, areas, authors only (no liked papers, no narrative)
- **Task:** Rank papers best-first and classify each as high / medium / low
- **Medium threshold:** Requires at least one concrete anchor — a keyword hit, an author match, or subcategory match with clear topic overlap. Pure thematic adjacency without any profile anchor → low.
- **Caps:** Top 15 arXiv + top 15 journal papers forwarded to scoring (independent hard caps)
- **Results written to:** `users/<name>/data/DATE/filtered_papers.json`

**Rate limit and parallelism:** The cached API has a 50k input-token/minute limit shared across all calls. Each user's triage thread launches `i × 61s` apart so no two cached calls overlap within the same 60-second window. Batch calls run concurrently in the background (no rate limit applies). Within each thread, the cached call always fires before the Batch call to hit the cache while it is still warm. Token counts are estimated per call (chars/4) against a 40k safety threshold; if arXiv or journals individually exceeds 40k, or both combined exceed 40k, the larger pool is automatically routed to Batch.

#### Stage 2: Scoring (Claude Sonnet) — Batch API

Runs per-user in parallel via `ThreadPoolExecutor`. Uses the Anthropic Message Batches API (50% cost discount, async processing). Falls back to synchronous API after 20-minute timeout — a `batch_fallback.json` flag file is written to the user's data folder, and an alert email is sent to the operator after all users complete. Pass `--no-batch` to skip the Batch API for both triage and scoring (useful for single-user testing — fields with fewer than 4 users use the Batch API for triage by default).

- **Input:** Triage survivors + full profile (including `evolved_interests` and up to 5 liked papers sampled from `archive.json` — prioritising excellent-rated papers, padded with profile seed papers if needed)
- **Task:** Score each paper 1–10 with a one-line justification and tags
- **Tags:** `author match`, `core topic`, `adjacent interest`, `new direction`
- **Output:** `scored_papers.json` — sorted by score descending

**Why two stages:** Triage is cheap pattern matching (Haiku, minimal output). Scoring is nuanced reasoning (Sonnet, full profile). The split keeps triage cost low and scoring quality high.

**Cost:** ~$0.05/user/day on a typical day (~80–120 papers total, ~30 scored). Caching reduces triage cost further for fields with multiple users.

---

### 4. PDF digest — `build_digest_pdf.py`

Generates a single PDF that serves as both digest and reading interface, built with ReportLab.

**Layout:**
- **Header:** date + paper counts
- **Scored section:** papers ranked by score, each with title (linked to arXiv), authors, score badge, justification, abstract, and three rating buttons
- **Unscored section:** remaining papers with title, authors, and rating buttons only (no abstract, to keep it compact)

**Rating buttons** are hyperlinks embedded in the PDF:
```
https://incomingscience.xyz/rate?paper_id=2301.12345&rating=excellent&date=2026-03-18&user=alice
```
Tapping opens the browser briefly, the server records the rating, and returns a confirmation page. The `date` parameter ensures late ratings are attributed to the correct day.

---

### 5. Delivery — `run_daily.py` + `run_all_users.py` + `run_weekly_digest.py`

`run_all_users.py` is the master orchestrator. It handles all shared, field-level work before dispatching per-user tasks in parallel.

**Master orchestrator steps (`run_all_users.py`):**
1. Discover all user directories under `users/`
2. Scrape journals once (`fetch_journals.py`) → filter per field
3. Fetch arXiv papers once per field (`fetch_papers.py`)
4. Merge arXiv + journals per field → `{field}_today_papers.json`
5. Exit cleanly for any field with no papers today
6. Snapshot `journal_watermarks.json` → `data/DATE/journal_watermarks_snapshot.json` (recovery aid)
7. Run centralized triage per field — users triaged in parallel with staggered 61s launches
8. Dispatch per-user scoring + PDF + daily email in parallel (`ThreadPoolExecutor`)
9. Clean up shared data folders older than 3 days
10. Send batch fallback alert email if any scoring job timed out
11. Send run summary email — per-user OK/FAILED table to the operator (skipped for `--user` and `--no-email` runs)
12. Weekly digest phase — for any user with `weekly_digest: true` whose chosen weekday matches today, send their weekly email (runs after all daily work is complete)

**Per-user steps (`run_daily.py`):**
1. Deduplicate yesterday's ratings (`deduplicate_ratings.py`)
2. Archive yesterday's ratings to `archive.json` (`archive.py`)
3. Run scoring pipeline (`run_pipeline.py --skip-triage` — triage already done)
4. Build PDF digest
5. Email PDF to user (skipped if `daily_digest: false` in profile)
6. Clean up data folders older than 14 days

A failure for one user does not affect others.

#### Delivery modes

Each user independently controls whether they receive a daily digest, a weekly digest, or both. This is configured in `taste_profile.json`:

```json
"daily_digest": true,
"weekly_digest": false,
"weekly_day": "friday"
```

Both flags default to their values above if absent — existing users are unaffected. A user can have any combination: daily only, weekly only, or both.

**Weekly digest (`run_weekly_digest.py`):** Collects all papers scored ≥ 8 from the past 7 days, deduplicates by paper ID, and delivers a single PDF titled "weekly digest". Scoring and PDF generation still run every day regardless of delivery mode — the daily PDF accumulates in `data/YYYY-MM-DD/` and is available for the weekly aggregator even when no daily email is sent.

**Weekend weekly digest (`run_weekly_only.py`):** Standalone script for Saturday/Sunday cron runs. Discovers users whose `weekly_day` matches today and runs the weekly digest phase only — no arXiv fetch, no journal scraping, no triage or scoring. Use `--user <name>` to bypass the `weekly_day` check (useful for testing). Cron: `30 1 * * 0,6` → `run_weekly_only.py`.

**Mailing lists:** Daily and weekly emails can go to different recipients. Set `EMAIL_TO_DAILY` and `EMAIL_TO_WEEKLY` in the user's `.env`; both fall back to `EMAIL_TO` if not set.

**Refiner behaviour for weekly-only users:** When a user has `daily_digest: false` and `weekly_digest: true`, the monthly refiner automatically adjusts its analysis — it suppresses the "missed" and "underscored" discrepancy buckets (which are structurally impossible when the user only ever sees papers scored ≥ 8) and notes the filtered nature of the data to avoid misinterpreting sparse ratings.

---

### 6. Landing page & onboarding — `server.py` + `website/`

Flask app serving the public website and rating endpoint, running under Gunicorn behind a Caddy reverse proxy.

**Routes:**
- `GET /` — landing page (how it works, delivery options, about)
- `GET /signup` — onboarding step 1: email + delivery preferences
- `GET /signup/field` — onboarding step 2: research field selection
- `GET /signup/interests` — onboarding step 3: interests + researchers
- `GET /signup/papers` — onboarding step 4: seed papers (XLSX or URLs)
- `GET /signup/done` — success page
- `POST /onboarding/submit` — receives completed onboarding JSON; saves to `users_pending/<slug>/onboarding.json`
- `GET /assets/<filename>` — static assets (images, fonts, JS)
- `GET /fields.json` — serves `fields.json` directly (used by the onboarding field-selection page to load available fields dynamically)
- `GET /rate?paper_id=...&rating=...&date=...&user=...` — records a paper rating
- `GET /health` — liveness check

**Website:** Six mobile-responsive static HTML pages under `website/stitch_platform_user_expansion/`, served at clean URLs by Flask. Built with Tailwind CSS. All inter-page navigation uses absolute URLs. Assets served from `website/assets/`.

**Self-service onboarding flow:**
1. User visits `incomingscience.xyz/signup` and fills in 4 screens (email, field, interests/researchers, seed papers)
2. On the success screen, the browser POSTs the collected JSON to `POST /onboarding/submit`
3. Submission is saved to `users_pending/<email-slug>/onboarding.json`
4. Owner processes it with `process_pending.py` (see below)

**Processing pending signups (`process_pending.py`):**
```bash
python process_pending.py --list    # show unprocessed submissions
python process_pending.py --all     # process all pending
python process_pending.py <slug>    # process one by email slug
```
- Uses `ANTHROPIC_API_KEY_ONBOARDING` from root `.env` to call Claude for profile creation
- Creates `users/<slug>/taste_profile.json`, `archive.json`, and `.env` with `EMAIL_TO_DAILY` / `EMAIL_TO_WEEKLY`
- After processing, owner must add `ANTHROPIC_API_KEY=sk-ant-...` to `users/<slug>/.env` before the next pipeline run
- Stamps `processed_at` on the submission JSON to prevent re-processing
- If `scholar_url` is present in the submission, imports up to 60 papers from the Google Scholar profile before calling Claude (see below)

**Google Scholar import (`scrapers/scholar.py`):** Optional — triggered when the user pastes their Scholar profile URL on the seed papers screen. Fetches the profile page, follows each paper's Scholar citation detail page to get the publisher URL, fetches the abstract via citation meta tags, and falls back to OpenAlex title search for blocked publishers (APS, ACS). Papers without resolvable abstracts are still included for author-frequency signal. Merged with any manually provided URLs before profile creation; deduplicated by arXiv ID then by title.

---

### 7. Monthly profile refiner — `run_profile_refiner.py`

Runs on the 2nd of each month. Reads the last 30 days of ratings from `archive.json` and calls Claude Sonnet to update the taste profile.

**Rating flow (daily):**
1. User taps rating buttons in the PDF
2. `server.py` writes enriched entries to `data/DATE/ratings.json`
3. Next morning, `run_daily.py` deduplicates and archives them to `archive.json`

**Refinement logic:**
- Analyses rating history, plus score-vs-rating discrepancies (papers the pipeline misjudged)
- Python pre-classifies discrepancies into five buckets: overconfident-high, overconfident-mild, missed-excellent, missed-good, underscored
- Claude identifies which keywords/signals drove each mismatch and recommends grade adjustments
- Grade changes are ±1 per month maximum — Claude signals direction only, Python applies the rule
- Keywords/areas at grade 7 for two consecutive months are removed
- `evolved_interests` is updated with a rolling narrative: current trajectory, changes made this month, signals to watch next month

**Archive:** `archive.json` is a permanent, append-only record of all deduplicated ratings. The refiner reads only the last 30 days but the full history is preserved.

Uses the Anthropic Message Batches API (same as the daily pipeline).

---

## Design principles

### Agents are pure reasoning — no tools

All Claude calls (triage, scoring, profile refiner, profile creator) operate without function calling or tools. They receive structured data in-context and return structured JSON. All I/O — fetching feeds, reading files, writing files, calling APIs, sending email — lives in Python. This keeps agents simple, predictable, and cheap.

### Intelligence lives in system prompts

Each agent's quality comes from its system prompt, which encodes what signals to attend to, how to weigh them, what output format to produce, and edge case handling. The Python code is thin plumbing.

### Three-level rating over binary likes

Excellent / Good / Irrelevant provides richer signal than a binary like. "Excellent" = core research interest. "Good" = peripherally interesting. "Irrelevant" = actively not relevant (helps the system learn what to filter out). No rating = neutral.

---

## File inventory

| File | Purpose |
|------|---------|
| `fetch_papers.py` | Daily arXiv RSS fetch and parse (once per field) |
| `fetch_journals.py` | Journal scraping — journals across all fields via RSS/eTOC (once per run) |
| `scrapers/aps.py` | APS publisher scraper (PRL, PRB, PRX, PRXQuantum) — truncated RSS abstract |
| `scrapers/nature.py` | Nature publisher scraper — full abstract + subject tags from article page |
| `scrapers/science.py` | Science eTOC scraper — full abstract via Semantic Scholar API |
| `scrapers/acs.py` | ACS publisher scraper — no abstract available; title + authors only |
| `scrapers/wiley.py` | Wiley publisher scraper — full abstract from RSS feed, no page fetches |
| `scrapers/optica.py` | Optica Publishing Group scraper — RSS metadata + full abstract via OpenAlex API |
| `scrapers/scholar.py` | Google Scholar profile scraper — resolves papers to abstracts for onboarding |
| `scrapers/cell.py` | Cell Press scraper |
| `scrapers/plos.py` | PLOS scraper |
| `scrapers/pnas.py` | PNAS scraper (topic-specific RSS feeds) |
| `fields.json` | Field definitions — arxiv category, journal list, tag filters |
| `create_profile.py` | One-time interactive user onboarding |
| `process_pending.py` | Owner tool — processes web signups from `users_pending/` into full user profiles |
| `run_pipeline.py` | Triage (Haiku, cached) + scoring (Sonnet, Batch API) pipeline |
| `build_digest_pdf.py` | Generates the daily PDF digest |
| `server.py` | Flask server — website, onboarding submit endpoint, rating endpoint, static assets |
| `website/` | Mobile-responsive 6-page onboarding website (landing + 4 signup steps + success) |
| `deduplicate_ratings.py` | Keeps the last rating per paper per day |
| `archive.py` | Appends daily ratings to permanent `archive.json` |
| `run_daily.py` | Per-user orchestrator — scoring, PDF, daily email (called by run_all_users.py) |
| `run_all_users.py` | Master orchestrator — fetch, triage, parallel per-user scoring, weekly dispatch, run summary email |
| `run_weekly_digest.py` | Weekly digest — collects scored ≥ 8 papers from past 7 days, builds PDF, emails |
| `run_weekly_only.py` | Standalone weekend runner — runs weekly digest phase only (no fetch/triage/scoring) |
| `run_profile_refiner.py` | Monthly taste profile refiner |
| `prompts/profile_creator.txt` | System prompt for profile creation |
| `prompts/triage.txt` | System prompt for arXiv triage agent |
| `prompts/triage_journals.txt` | System prompt for journal triage agent |
| `prompts/scoring.txt` | System prompt for scoring agent |
| `prompts/profile_refiner.txt` | System prompt for monthly refiner |
| `docs/logo.png` | Incoming Science logo |
| `docs/incoming_science_onboarding.docx` | Onboarding form for new users |
| `environment.yml` | Conda environment (Python 3.11) |

**Runtime files (not in repo):**

| Path | Purpose |
|------|---------|
| `.env` | Root config — SMTP, rating URL, per-field triage API keys |
| `journal_watermarks.json` | Per-journal watermark — prevents re-fetching seen papers |
| `users/<name>/taste_profile.json` | Each user's evolving taste profile |
| `users/<name>/archive.json` | Each user's permanent rating history |
| `users/<name>/.env` | `ANTHROPIC_API_KEY` (scoring) + `EMAIL_TO` / `EMAIL_TO_DAILY` / `EMAIL_TO_WEEKLY` per user |
| `users/<name>/data/YYYY-MM-DD/` | Daily data folder: papers, filtered, scores, PDF, ratings |
| `users/<name>/data/YYYY-MM-DD/triage_arxiv_input.txt` | Full triage prompt sent to Haiku (arXiv papers) — written every run for debugging |
| `users/<name>/data/YYYY-MM-DD/triage_journals_input.txt` | Full triage prompt sent to Haiku (journal papers) — written every run for debugging |
| `users/<name>/data/YYYY-MM-DD/scoring_input.txt` | Full scoring prompt sent to Sonnet — written every run for debugging |

---

## Infrastructure

- **Hosting:** Any Linux VPS
- **HTTPS:** Caddy (auto Let's Encrypt) → Gunicorn → Flask
- **Scheduling:** Cron — daily pipeline (Mon–Fri 00:30 ET), weekend weekly digest (Sat/Sun 01:30 ET), monthly refiner (2nd of month 01:30 ET, offset by one hour to avoid a race on `archive.json`)
- **Email:** Shared SMTP account configured in root `.env`. Each user configures `EMAIL_TO` (default), `EMAIL_TO_DAILY`, and/or `EMAIL_TO_WEEKLY` in their `.env` — daily and weekly emails can go to different recipient lists.
- **LLM:** Anthropic Claude API — Haiku for triage (cached, one shared API key per field in root `.env`), Sonnet for scoring and refinement (Batch API, per-user `ANTHROPIC_API_KEY` in user `.env`).

---

## Setup

### Environment

```bash
conda env create -f environment.yml
conda activate arxiv-grader
```

### Root `.env`

Create `.env` in the project root:
```
RATING_BASE_URL=https://your-server.com
EMAIL_FROM=your-sender@gmail.com
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_SMTP_USER=your-sender@gmail.com
EMAIL_SMTP_PASSWORD=your-app-password

# Per-field Anthropic API keys for centralized triage
# Key format: ANTHROPIC_API_KEY_<FIELD_UPPERCASE_WITH_UNDERSCORES>
ANTHROPIC_API_KEY_COND_MAT=sk-ant-...
```

One API key per field is required for triage. Add a new key when adding a new field (e.g. `ANTHROPIC_API_KEY_QUANT_PH` for a `quant-ph` field). Per-user `ANTHROPIC_API_KEY` in each user's `.env` is used only for scoring.

### `fields.json` schema

Each top-level key is a field name (used as the `field` value in `taste_profile.json` and as the API key suffix in root `.env`):

```json
{
  "cond-mat": {
    "arxiv_category": "cond-mat",
    "description": "Condensed matter physics",
    "journals": [
      {
        "name": "PRB",
        "url": "http://feeds.aps.org/rss/recent/prb.xml",
        "publisher": "aps",
        "tag_filter": null
      },
      {
        "name": "Nature",
        "url": "https://www.nature.com/nature.rss",
        "publisher": "nature",
        "tag_filter": ["condensed-matter physics", "superconducting"]
      }
    ]
  }
}
```

- `publisher`: one of `aps`, `nature`, `science`, `acs`, `wiley`, `optica`, `cell`, `plos`, `pnas` — selects the scraper class
- `tag_filter`: `null` = field-specific journal, keep all papers; `[...]` = general journal, keep only papers whose subject tags contain at least one match
- The same journal can appear in multiple fields with different RSS URLs (e.g. a photonics subfeed for optics, a physics subfeed for cond-mat). Filtering is by URL, so papers are routed to the correct field regardless of the display `name`.
- Root `.env` requires `ANTHROPIC_API_KEY_<FIELD_UPPERCASE>` for each field (e.g. `ANTHROPIC_API_KEY_COND_MAT`)

See `docs/add_new_field.md` for a step-by-step guide.

### Add a user

**Interactive (owner-assisted):**
```bash
python create_profile.py --user-dir users/<name>
```

**Via web signup** (`incomingscience.xyz/signup`): users self-register; submissions land in `users_pending/`. Process them with:
```bash
python process_pending.py --list          # see pending signups
python process_pending.py --all           # process all
python process_pending.py <slug>          # process one
```
After processing, add `ANTHROPIC_API_KEY=sk-ant-...` to `users/<slug>/.env`. Requires `ANTHROPIC_API_KEY_ONBOARDING` in root `.env`.

### Run manually

```bash
python run_all_users.py                          # all users
python run_all_users.py --user alice             # single user
python run_all_users.py --no-email               # skip email (testing)
python run_all_users.py --refine                 # run monthly refiner
python run_all_users.py --no-batch               # skip Batch API, use synchronous API (2× cost, instant)
python run_all_users.py --no-fetch               # skip arXiv fetch — reuse existing {field}_arxiv_papers.json
python run_all_users.py --triage-only            # stop after triage, skip scoring/PDF/email (testing)
python run_all_users.py --no-advance-watermark   # re-scrape journals but don't save watermark updates (safe re-run)

# Weekend-only weekly digest (no pipeline overhead)
python run_weekly_only.py
python run_weekly_only.py --user alice  # run for specific user regardless of weekly_day
```

`--no-fetch` + `--triage-only` together are useful for weekend testing: place a previously fetched `{field}_arxiv_papers.json` in the shared data dir and verify cache behaviour without running the full pipeline.

**Re-running a failed user:** If a single user fails and needs to be re-run for a specific date, use `--no-advance-watermark` (not `--no-fetch` — `--no-fetch` only skips arXiv, not journal scraping):
```bash
python run_all_users.py --user alice --date 2026-04-14 --no-advance-watermark
```
If watermarks were already advanced incorrectly, restore from the snapshot saved at the start of every run:
```bash
cp data/2026-04-14/journal_watermarks_snapshot.json journal_watermarks.json
```
