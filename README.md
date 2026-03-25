# arXiv cond-mat daily grader — architecture document

## Project overview

A daily workflow that scrapes the arXiv condensed matter listing, grades each paper's relevance to the user using LLM sub-agents, and delivers a ranked PDF digest to the user's phone. The user can rate papers, and those ratings feed back into an evolving taste profile that sharpens recommendations over time.

---

## Core components

### 1. Data ingestion — `fetch_papers.py` ✓ DONE

A Python script that runs daily via cron. It pulls the arXiv cond-mat RSS/Atom feed from `https://rss.arxiv.org/rss/cond-mat`, parses it, and writes a structured JSON file.

**Output:** `today_papers.json` — an array of paper objects, each containing:
- arXiv ID
- Title
- Abstract
- Authors
- Subcategories

No LLM calls. Pure parsing.

**Filters:** Only `announce_type == "new"` papers are kept. Cross-listings, replacements, and replacement cross-listings are discarded. Supports an optional `--category` flag to filter to a specific subcategory.

---

### 2. User taste profile — `create_profile.py` + `taste_profile.json` ✓ DONE

A one-time onboarding script creates `taste_profile.json`, which is then evolved over time through user ratings. See [`create_profile_logic.md`](create_profile_logic.md) for a detailed walkthrough of the creation logic.

**Creation flow (credential setup → 4-part interview → Python fetches → single Claude call → user reviews):**
0. `setup_credentials()` runs first: validates the Anthropic API key (live test call) and collects the user's recipient email address. Shared SMTP settings are written silently — users provide only their API key and personal email.
1. User provides arXiv categories, a free-text description of interests, researchers to follow, and an Excel file of recently-read paper links (arXiv or journal URLs)
2. Python fetches title/authors/abstract for all papers (arXiv batch API + HTML meta tag parsing for journals)
3. Python pre-computes author frequencies across all papers
4. A single Claude call receives the clean structured data and returns ranked keywords, research areas, and authors, plus a `why_relevant` note per paper
5. Python assembles the full JSON; user reviews and can reorder rankings interactively

**Schema (as built):**
```json
{
  "arxiv_categories": ["cond-mat.str-el", "cond-mat.mes-hall"],
  "interests_description": "Original free-text from user, verbatim",
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

**Grade system (keywords and research areas):**
- Grade 1 = most relevant (core, high-confidence)
- Grade 2–3 = strong/solid signal
- Grade 4–5 = moderate/tentative (assigned at creation)
- Grade 6–7 = fading (assigned by monthly profile refiner only)
- Grade 7 keywords are removed at the next monthly refinement
- Authors use a separate sequential rank system (rank 1 = highest priority)

**What the grading agents see:** Original interests + authors + `evolved_interests` narrative + last 5 liked papers. Not the full history, to keep context costs bounded.

---

### 3. Grading pipeline — two-stage sub-agent design

The grading uses two sequential Claude API calls per day, following a triage-then-score pattern. This avoids passing the taste profile redundantly across many small batches.

#### Stage 1: Triage agent

- **Model:** `claude-haiku-4-5-20251001` — fast and cheap; triage is pattern matching, not reasoning
- **Input:** All daily papers + lean profile (categories, keywords, research_areas, authors — no liked_papers, no evolved_interests)
- **Task:** Rank all papers by relevance (best first) and classify each as **high / medium / low**
- **Output format:** Papers emitted in ranked order (position = rank), one `N: label` line each. Python takes the top `MAX_TRIAGE_PASS` (20) medium-or-high papers. Papers that only reach "high"/"medium" count but fall outside the top 20 are dropped.
- **Medium threshold:** Requires at least one concrete anchor — a keyword hit in title/abstract, an author match, or subcategory match combined with clear topic overlap with a grade 1–4 area. Pure thematic adjacency without any profile anchor → low.
- **Hard cap:** At most 20 papers forwarded to scoring. If fewer than 20 qualify, only those pass (no padding).
- **API:** Uses Anthropic Message Batches API (async, 50% discount). Polls every 15s, 1-hour timeout.

#### Stage 2: Scoring agent

- **Model:** `claude-sonnet-4-6` — nuanced multi-signal reasoning
- **Input:** Filtered high+medium papers + full profile (including `evolved_interests` and last 5 `liked_papers`)
- **Task:** Score each paper 1–10 with a one-line justification and tags
- **Output:** JSON array with `score`, `justification`, `tags` per paper. Python merges with metadata and sorts.
- **Tags:** `"author match"`, `"core topic"`, `"adjacent interest"`, `"new direction"`
- **API:** Uses Anthropic Message Batches API (async, 50% discount). Polls every 15s, 1-hour timeout.
- **Cost target:** ~$0.05/day total (both stages) on a normal day (~80 papers, 20 scored).

**Why two stages:** Sending all papers in one big scoring call risks quality degradation on a long list. The triage pass is cheap (minimal output) and filters to only the papers worth careful evaluation. The taste profile is sent exactly twice per day, not per-batch.

---

### 4. PDF digest — `build_digest_pdf.py`

Generates a single daily PDF that serves as both the digest and the reading interface.

**Layout:**

0. **Header:** Date + total paper count (`N papers today · M scored · K unscored`).

1. **Scored section (top):** Papers ranked by score (highest first). Each entry contains:
   - Title (linked to arXiv page)
   - Authors
   - Score badge (1–10)
   - One-line justification
   - Abstract
   - Three rating buttons: Excellent / Good / Irrelevant

2. **Divider**

3. **Unscored section (bottom):** All remaining low-triage papers. Abstract is omitted to keep the section compact — each entry contains only:
   - Title (linked to arXiv page)
   - Authors
   - Three rating buttons: Excellent / Good / Irrelevant

**Rating buttons:** Implemented as styled hyperlinks in the PDF:
```
https://your-server.com/rate?paper_id=2301.12345&rating=excellent&date=2026-03-18
https://your-server.com/rate?paper_id=2301.12345&rating=good&date=2026-03-18
https://your-server.com/rate?paper_id=2301.12345&rating=irrelevant&date=2026-03-18
```
The `date` parameter tells the server which day's folder to write to, so ratings that arrive a day late are still attributed correctly.

Tapping opens the browser briefly, the server registers the rating, and returns a simple confirmation page. Papers with no rating are ignored (neutral, not negative).

---

### 5. Delivery — email with PDF attachment

The simplest and most phone-friendly delivery method. The pipeline runs on a cron schedule (01:30 UTC nightly) on a cheap VPS. After the PDF is generated, it's emailed to the user as an attachment.

**Sending account:** All users receive their digest from `incomingscience@gmail.com`. SMTP credentials are shared infrastructure embedded in `create_profile.py` — users only configure their own recipient address.

**The user's morning workflow:**
1. Open email, open PDF
2. Scroll through scored papers (best first)
3. Tap rating buttons on papers that catch their eye
4. Optionally scroll down to browse unscored papers
5. Tap arXiv links to read full papers

No app to install, no special client. Works on any phone.

---

### 6. Landing page & onboarding — `server.py` + `docs/`

The Flask server also serves a public landing page at `https://incomingscience.xyz`.

**Routes:**
- `GET /` — landing page: logo, description, numbered onboarding steps, download button, contact email
- `GET /logo.png` — serves `docs/logo.png`
- `GET /onboarding` — downloads `docs/incoming_science_onboarding.docx` as an attachment

**Onboarding flow for new users:**
1. User visits the landing page and downloads the onboarding form
2. User fills in their research interests, keywords, and representative papers
3. User emails the completed form to `yuval.zamir@icfo.eu`
4. Owner SSH's into the server, runs `create_profile.py --user-dir users/<name>`, and the user is live

**Design:** Warm off-white palette (`#F7F4EF` background, `#DDD5C8` borders) matching the PDF digest. Nunito font matching the logo's rounded sans-serif.

---

### 7. Feedback loop — monthly profile refiner

Runs on the first of each month via cron. Reads the last 30 days of ratings from `archive.json` and calls Claude Sonnet to update the taste profile.

**Daily rating flow:**
1. User taps rating buttons in the PDF digest
2. `server.py` writes enriched entries to `data/DATE/ratings.json`
3. Each morning, `run_daily.py` runs `deduplicate_ratings.py` (keeps last rating per paper) then `archive.py` (appends to permanent `archive.json`)

**Monthly refinement (`run_profile_refiner.py`):**
- **Input:** Current `taste_profile.json` + last 30 days from `archive.json`
- **Task:** Reason about interest shifts using three signals: rating history, score-vs-rating discrepancies, and last month's narrative
- **Score-rating discrepancy analysis:** Python pre-classifies rated papers into five buckets (overconfident-high, overconfident-mild, missed-excellent, missed-good, underscored) and passes them to Claude with justifications. Claude identifies which keywords/signals caused the mismatch.
- **Narrative as rolling memory:** `evolved_interests` is written by the refiner each month with three components: current trajectory, changes made this month and why, emerging signals worth watching next month. Next month's refiner reads it as a corroborating signal — a borderline case backed by the narrative becomes decisive.
- **Grade rules (applied by Python after Claude's response):**
  - Grade changes are ±1 per month maximum (Claude signals direction only)
  - Keywords/areas already at grade 7 before the run and still at grade 7 after → removed. Items that only reach grade 7 during this run survive to next month (natural trial period for newly added keywords).
- **Output:** Updated `taste_profile.json`

**Archive:** `archive.json` is a permanent growing list of all deduplicated ratings. It is never truncated — the monthly refiner reads only the last 30 days, but the full history is preserved.

---

## Design principles

### Agents are pure reasoning — no tools

All three sub-agents (triage, scoring, profile updater) operate without function calling or tools. They receive data in-context and return structured JSON. The orchestration logic (reading files, writing files, calling APIs, sending email) lives entirely in Python scripts. This keeps agents simple, testable, and safe.

**Exception to consider (future):** The scoring agent could be given a `fetch_pdf` tool to retrieve full paper PDFs for very high-scoring papers (8+). Not needed for v1.

### Intelligence lives in system prompts

Each agent's quality comes from its system prompt, which encodes: what signals to attend to, how to weigh them, what output format to produce, and the persona. The Python code is thin plumbing.

### Three-level rating > binary likes

The Excellent / Good / Irrelevant rating scale provides richer signal than a binary like. "Excellent" = core research interest. "Good" = peripherally interesting. "Irrelevant" = actively not interested (helps the system learn what to filter out). No rating = neutral.

---

## File inventory

| File | Status | Purpose |
|------|--------|---------|
| `fetch_papers.py` | ✓ Done | Daily arXiv RSS fetch and parse |
| `create_profile.py` | ✓ Done | One-time user onboarding — creates `users/<name>/` directory structure |
| `create_profile_logic.md` | ✓ Done | Detailed logic documentation for create_profile.py |
| `run_pipeline.py` | ✓ Done | Triage agent + scoring agent |
| `build_digest_pdf.py` | ✓ Done | Generates the daily PDF digest (embeds `&user=` in rating URLs) |
| `server.py` | ✓ Done | Flask server — `/` landing page, `/rate` rating endpoint, `/logo.png`, `/onboarding` download |
| `docs/logo.png` | ✓ Done | Incoming Science logo — served at `/logo.png` |
| `docs/incoming_science_onboarding.docx` | ✓ Done | Onboarding form — downloadable from landing page |
| `deduplicate_ratings.py` | ✓ Done | Deduplicates ratings.json, keeps last per paper |
| `archive.py` | ✓ Done | Appends daily ratings to user's permanent archive.json |
| `run_daily.py` | ✓ Done | Daily orchestrator for one user — requires `--user-dir` |
| `run_all_users.py` | ✓ Done | Master orchestrator — runs all users concurrently via ThreadPoolExecutor, calls run_daily.py per user |
| `run_profile_refiner.py` | ✓ Done | Monthly profile refiner — reads archive, updates taste_profile.json |
| `prompts/profile_creator.txt` | ✓ Done | System prompt for profile creation agent |
| `prompts/triage.txt` | ✓ Done | System prompt for triage agent (Haiku) |
| `prompts/scoring.txt` | ✓ Done | System prompt for scoring agent (Sonnet) |
| `prompts/profile_refiner.txt` | ✓ Done | System prompt for monthly profile refiner |
| `grading_pipeline_design.md` | ✓ Done | Design doc: triage vs. scoring comparison |
| `users/<name>/taste_profile.json` | Runtime | Each user's evolving taste profile |
| `users/<name>/archive.json` | Runtime | Each user's permanent rating history |
| `users/<name>/.env` | Runtime | Each user's `ANTHROPIC_API_KEY` + `EMAIL_TO` |
| `users/<name>/data/YYYY-MM-DD/` | Runtime | Daily folder per user: today_papers, filtered, scored, digest.pdf, ratings |
| `environment.yml` | ✓ Done | Conda environment definition (Python 3.11) |

---

## Infrastructure

- **Server:** Hetzner CX23 VPS (Ubuntu 24.04, Falkenstein EU, ~€4.60/mo incl. IPv4). Static public IP: `116.203.255.222`.
- **Domain:** `incomingscience.xyz` — registered on Porkbun, A record points to Hetzner IP ✓ live
- **HTTPS:** Caddy reverse proxy — auto-obtains Let's Encrypt certificate, proxies to Gunicorn on `127.0.0.1:5000`
- **Rating URL:** `https://incomingscience.xyz/rate?paper_id=...&rating=...&date=...&user=...`
- **Scheduling:** Cron — `run_all_users.py` at **05:30 UTC** Tue–Sat (= 00:30 EST / 01:30 EDT, 30 min after arXiv's 00:00 ET release); `run_all_users.py --refine` on the 2nd of each month at **06:30 UTC** (offset 1 hour from daily to avoid race on `archive.json`). All times are in UTC — no `TZ=` override needed. The server timezone is UTC. Logs to `/var/log/arxiv-grader/`.
- **Multi-user:** Each user has their own directory under `users/<name>/` containing `.env`, `taste_profile.json`, `archive.json`, and `data/`. Add a new user by running `create_profile.py --user-dir users/<name>`. `run_all_users.py` discovers users automatically by scanning for directories containing `taste_profile.json`.
- **Rating server:** Flask app (`server.py`) running under Gunicorn as a systemd service (auto-starts on boot). Routes on `?user=` parameter, validates against `users/*/` on each request — no restart needed when adding users.
- **Email:** SMTP via `incomingscience@gmail.com` (shared sending account, hardcoded). Each user sets only `EMAIL_TO` in their `.env`.
- **LLM API:** Anthropic Claude API (Haiku for triage, Sonnet for scoring and profile refinement). Each user supplies their own `ANTHROPIC_API_KEY`.

---

## Open questions for implementation

1. ~~What PDF library to use~~ — ReportLab with DejaVu Sans font
2. ~~Cross-listings~~ — resolved in fetch_papers.py by filtering to `announce_type == "new"` only
3. ~~Threshold for triggering profile updates~~ — monthly cron on 1st of each month
4. ~~Mobile-friendly PDF styling~~ — implemented in build_digest_pdf.py
