# Incoming Science — arXiv Daily Digest

A personal arXiv digest tool for researchers. Every day it fetches the latest papers in your field, ranks them by relevance to your research interests using AI, and delivers a scored PDF to your inbox — ready to read on your phone. Rate papers with one tap; ratings feed back into an evolving taste profile that sharpens recommendations over time.

Live at [incomingscience.xyz](https://incomingscience.xyz)

---

## How it works

1. **Fetch** — pulls the arXiv RSS feed and scrapes 11 top journals each morning
2. **Triage** — Claude Haiku filters ~80–120 papers down to the ~30 most likely to be relevant (15 arXiv + 15 journal cap)
3. **Score** — Claude Sonnet scores each surviving paper 1–10 with a one-line justification
4. **Deliver** — a ranked PDF digest is emailed to you as an attachment
5. **Rate** — tap Excellent / Good / Irrelevant buttons in the PDF; ratings are recorded
6. **Refine** — once a month, Claude Sonnet reviews your rating history and updates your taste profile

---

## Architecture

### 1. Data ingestion — `fetch_papers.py` + `fetch_journals.py`

**arXiv (`fetch_papers.py`):** Pulls the arXiv RSS feed, filters to new submissions only (no cross-listings, no replacements). Supports `--category` for field filtering (e.g. `cond-mat`). If the feed is empty (holiday or off-day), the pipeline exits cleanly. Fetched once per field, shared across all users in that field.

**Journals (`fetch_journals.py`):** Scrapes 11 top physics journals via RSS/eTOC feeds. Publisher-specific scraper classes live under `scrapers/` (APS, Nature, Science). Field configuration — which journals to monitor and tag filters for multi-discipline journals — is defined in `fields.json`. A per-journal watermark (`journal_watermarks.json`) prevents re-fetching papers already seen. Fetched once per run, filtered per field, shared across all users.

**Journals covered (cond-mat field):** PRL (two section feeds), PRB, PRX, PRXQuantum, Nature, Nature Physics, Nature Materials, Nature Nanotechnology, Nature Communications, Science.

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

Triage runs **centrally per field** in `run_all_users.py` before the per-user scoring phase. All users in a field are triaged sequentially to maximise prompt cache hits.

**Prompt caching structure:** The paper list and system prompt are identical for all users in a field and are marked `cache_control: ephemeral`. The user's taste profile is appended as the non-cached suffix. The first user in a field warms the cache; subsequent users pay ~10% of normal input token cost for the papers block.

**Two independent calls per user** (to avoid cross-pool calibration and use field-specific prompts):
- **arXiv triage** (`prompts/triage.txt`) — all arXiv papers for the field
- **Journal triage** (`prompts/triage_journals.txt`) — all journal papers for the field

Each call has its own pair of cache entries (system prompt + papers block), both live simultaneously.

- **Input per call:** Papers list (cached) + lean profile — keywords, areas, authors only (no liked papers, no narrative)
- **Task:** Rank papers best-first and classify each as high / medium / low
- **Medium threshold:** Requires at least one concrete anchor — a keyword hit, an author match, or subcategory match with clear topic overlap. Pure thematic adjacency without any profile anchor → low.
- **Caps:** Top 15 arXiv + top 15 journal papers forwarded to scoring (independent hard caps)
- **Results written to:** `users/<name>/data/DATE/filtered_papers.json`

#### Stage 2: Scoring (Claude Sonnet) — Batch API

Runs per-user in parallel via `ThreadPoolExecutor`. Uses the Anthropic Message Batches API (50% cost discount, async processing). Falls back to synchronous API after 1-hour timeout, with an alert email sent to the operator.

- **Input:** Triage survivors + full profile (including `evolved_interests` and last 5 liked papers sampled from archive)
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

### 5. Delivery — `run_daily.py` + `run_all_users.py`

`run_all_users.py` is the master orchestrator. It handles all shared, field-level work before dispatching per-user tasks in parallel.

**Master orchestrator steps (`run_all_users.py`):**
1. Discover all user directories under `users/`
2. Scrape journals once (`fetch_journals.py`) → filter per field
3. Fetch arXiv papers once per field (`fetch_papers.py`)
4. Merge arXiv + journals per field → `{field}_today_papers.json`
5. Exit cleanly for any field with no papers today
6. Run centralized triage per field — all users in a field triaged sequentially (cached API)
7. Dispatch per-user scoring + PDF + email in parallel (`ThreadPoolExecutor`)
8. Clean up shared data folder
9. Send batch fallback alert email if any scoring job timed out

**Per-user steps (`run_daily.py`):**
1. Deduplicate yesterday's ratings (`deduplicate_ratings.py`)
2. Archive yesterday's ratings to `archive.json` (`archive.py`)
3. Run scoring pipeline (`run_pipeline.py --skip-triage` — triage already done)
4. Build PDF digest
5. Email PDF to user
6. Clean up data folders older than 14 days

A failure for one user does not affect others.

---

### 6. Landing page & onboarding — `server.py`

Flask app serving both the public landing page and the rating endpoint, running under Gunicorn behind a Caddy reverse proxy.

**Routes:**
- `GET /` — landing page with logo, description, and onboarding instructions
- `GET /onboarding` — downloads the onboarding form (`docs/incoming_science_onboarding.docx`)
- `GET /rate?paper_id=...&rating=...&date=...&user=...` — records a paper rating
- `GET /health` — liveness check

**Onboarding flow for new users:**
1. User visits the landing page and downloads the onboarding form
2. User fills in research interests, keywords, arXiv categories, and representative papers
3. User emails the completed form back
4. Owner runs `create_profile.py --user-dir users/<name>` on the server

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
| `fetch_journals.py` | Journal scraping — 11 journals via RSS/eTOC (once per run) |
| `scrapers/aps.py` | APS publisher scraper (PRL, PRB, PRX, PRXQuantum) |
| `scrapers/nature.py` | Nature publisher scraper (Nature, NatPhys, NatMat, NatNano, NatComms) |
| `scrapers/science.py` | Science eTOC scraper with Semantic Scholar abstract fetch |
| `fields.json` | Field definitions — arxiv category, journal list, tag filters |
| `create_profile.py` | One-time interactive user onboarding |
| `run_pipeline.py` | Triage (Haiku, cached) + scoring (Sonnet, Batch API) pipeline |
| `build_digest_pdf.py` | Generates the daily PDF digest |
| `server.py` | Flask server — landing page, rating endpoint, static assets |
| `deduplicate_ratings.py` | Keeps the last rating per paper per day |
| `archive.py` | Appends daily ratings to permanent `archive.json` |
| `run_daily.py` | Per-user orchestrator — scoring, PDF, email (called by run_all_users.py) |
| `run_all_users.py` | Master orchestrator — fetch, triage, then parallel per-user scoring |
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
| `users/<name>/.env` | `ANTHROPIC_API_KEY` (scoring) + `EMAIL_TO` per user |
| `users/<name>/data/YYYY-MM-DD/` | Daily data folder: papers, filtered, scores, PDF, ratings |

---

## Infrastructure

- **Hosting:** Any Linux VPS
- **HTTPS:** Caddy (auto Let's Encrypt) → Gunicorn → Flask
- **Scheduling:** Cron — daily pipeline runs shortly after arXiv's nightly release; monthly refiner runs on the 2nd of each month, offset by one hour to avoid a race on `archive.json`
- **Email:** Shared SMTP account configured in root `.env`. Each user configures only `EMAIL_TO`.
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

### Add a user

```bash
python create_profile.py --user-dir users/<name>
```

### Run manually

```bash
python run_all_users.py               # all users
python run_all_users.py --user alice  # single user
python run_all_users.py --no-email    # skip email (testing)
python run_all_users.py --refine      # run monthly refiner
```
