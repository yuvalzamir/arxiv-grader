# Incoming Science — arXiv Daily Digest

A personal arXiv digest tool for researchers. Every day it fetches the latest papers in your field, ranks them by relevance to your research interests using AI, and delivers a scored PDF to your inbox — ready to read on your phone. Rate papers with one tap; ratings feed back into an evolving taste profile that sharpens recommendations over time.

Live at [incomingscience.xyz](https://incomingscience.xyz)

---

## How it works

1. **Fetch** — pulls the arXiv RSS feed for your categories each morning
2. **Triage** — Claude Haiku filters ~80 papers down to the ~20 most likely to be relevant
3. **Score** — Claude Sonnet scores each surviving paper 1–10 with a one-line justification
4. **Deliver** — a ranked PDF digest is emailed to you as an attachment
5. **Rate** — tap Excellent / Good / Irrelevant buttons in the PDF; ratings are recorded
6. **Refine** — once a month, Claude Sonnet reviews your rating history and updates your taste profile

---

## Architecture

### 1. Data ingestion — `fetch_papers.py`

Pulls the arXiv RSS feed, filters to new submissions only (no cross-listings, no replacements), and writes `today_papers.json`.

**Output schema per paper:**
- arXiv ID, title, abstract, authors, subcategories

**Filters:** Only `announce_type == "new"` papers are kept. Supports `--category` for subcategory filtering (e.g. `cond-mat.str-el`). If the feed is empty (arXiv holiday or off-day), the pipeline exits cleanly with no API calls.

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

Two sequential Claude API calls using the Anthropic Message Batches API (50% cost discount, async processing).

#### Stage 1: Triage (Claude Haiku)

- **Input:** All daily papers + lean profile (keywords, areas, authors — no liked papers, no narrative)
- **Task:** Rank all papers best-first and classify each as high / medium / low
- **Medium threshold:** Requires at least one concrete anchor — a keyword hit, an author match, or subcategory match with clear topic overlap. Pure thematic adjacency without any profile anchor → low.
- **Output:** Top 20 medium-or-high papers forwarded to scoring (hard cap)

#### Stage 2: Scoring (Claude Sonnet)

- **Input:** Triage survivors + full profile (including `evolved_interests` and last 5 liked papers)
- **Task:** Score each paper 1–10 with a one-line justification and tags
- **Tags:** `author match`, `core topic`, `adjacent interest`, `new direction`
- **Output:** `scored_papers.json` — sorted by score descending

**Why two stages:** Triage is cheap pattern matching (Haiku, minimal output). Scoring is nuanced reasoning (Sonnet, full profile). Splitting the two avoids passing the full profile across many small batches and maintains quality on the papers that matter.

**Cost:** ~$0.05/user/day on a typical day (~80 papers fetched, ~20 scored), using the Batch API discount.

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

### 5. Delivery — `run_daily.py`

Daily orchestrator for a single user. Runs as a subprocess for each user via `run_all_users.py`.

**Steps in order:**
1. Deduplicate yesterday's ratings (`deduplicate_ratings.py`)
2. Archive yesterday's ratings to `archive.json` (`archive.py`)
3. Fetch today's arXiv papers
4. Exit cleanly if feed is empty (holiday / off-day)
5. Run triage → scoring pipeline
6. Build PDF digest
7. Email PDF to user
8. Clean up data folders older than 14 days

**Multi-user:** `run_all_users.py` discovers all valid user directories and runs each user's pipeline concurrently via `ThreadPoolExecutor`. A failure for one user does not affect others.

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
| `fetch_papers.py` | Daily arXiv RSS fetch and parse |
| `create_profile.py` | One-time interactive user onboarding |
| `run_pipeline.py` | Triage (Haiku) + scoring (Sonnet) pipeline |
| `build_digest_pdf.py` | Generates the daily PDF digest |
| `server.py` | Flask server — landing page, rating endpoint, static assets |
| `deduplicate_ratings.py` | Keeps the last rating per paper per day |
| `archive.py` | Appends daily ratings to permanent `archive.json` |
| `run_daily.py` | Daily orchestrator for one user |
| `run_all_users.py` | Master orchestrator — runs all users concurrently |
| `run_profile_refiner.py` | Monthly taste profile refiner |
| `prompts/profile_creator.txt` | System prompt for profile creation |
| `prompts/triage.txt` | System prompt for triage agent |
| `prompts/scoring.txt` | System prompt for scoring agent |
| `prompts/profile_refiner.txt` | System prompt for monthly refiner |
| `docs/logo.png` | Incoming Science logo |
| `docs/incoming_science_onboarding.docx` | Onboarding form for new users |
| `environment.yml` | Conda environment (Python 3.11) |

**Runtime files (not in repo):**

| Path | Purpose |
|------|---------|
| `users/<name>/taste_profile.json` | Each user's evolving taste profile |
| `users/<name>/archive.json` | Each user's permanent rating history |
| `users/<name>/.env` | `ANTHROPIC_API_KEY` + `EMAIL_TO` per user |
| `users/<name>/data/YYYY-MM-DD/` | Daily data folder: papers, scores, PDF, ratings |

---

## Infrastructure

- **Hosting:** Any Linux VPS
- **HTTPS:** Caddy (auto Let's Encrypt) → Gunicorn → Flask
- **Scheduling:** Cron — daily pipeline runs shortly after arXiv's nightly release; monthly refiner runs on the 2nd of each month, offset by one hour to avoid a race on `archive.json`
- **Email:** Shared SMTP account configured in root `.env`. Each user configures only `EMAIL_TO`.
- **LLM:** Anthropic Claude API — Haiku for triage, Sonnet for scoring and refinement. Each user supplies their own `ANTHROPIC_API_KEY`.

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
```

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
