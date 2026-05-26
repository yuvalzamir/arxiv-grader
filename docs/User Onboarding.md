# User Onboarding

[[Home]] | [[Taste Profile]] | [[Infrastructure]]

Web onboarding design: `website_onboarding.md`
Profile creation logic: `create_profile_logic.md`

---

## Two Paths

| Path | Use case | Script |
|------|----------|--------|
| **Web signup** | Self-service; user fills 4 screens on the website | `process_pending.py` |
| **Interactive CLI** | Owner-assisted; runs locally | `create_profile.py` |

---

## Web Signup Flow

### User Side (incomingscience.xyz/signup)

4-screen flow, all state in `localStorage`:

```
Step 1 /signup          → Email + digest preferences (daily/weekly/both)
Step 2 /signup/field    → Research field selection (tree browser)
Step 3 /signup/interests → Free-text interests + researcher names
Step 4 /signup/papers   → Seed papers (XLSX upload or URL list)
Step 5 /signup/done     → POSTs to /onboarding/submit → success
```

**Final JSON shape** submitted to the server:
```json
{
  "email": "user@example.com",
  "daily_digest": true,
  "weekly_digest": false,
  "weekly_day": "friday",
  "field": "cond-mat",
  "interests_description": "...",
  "researchers": ["Jane Smith"],
  "paper_urls": ["https://arxiv.org/abs/2301.12345"],
  "scholar_url": "https://scholar.google.com/citations?user=..."  // optional
}
```

### Server Side

`POST /onboarding/submit` in `server.py`:
1. Validates required fields (`email`, `field`, `interests_description`, `researchers`)
2. Sanitises email → directory slug (alphanumeric + hyphens)
3. Saves to `users_pending/<slug>/onboarding.json`
4. Sends signup notification email to operator
5. Sends welcome email to user (with digest example image inline)

---

## Processing Pending Signups

```bash
python process_pending.py --list    # show unprocessed submissions
python process_pending.py --all     # process all pending
python process_pending.py <slug>    # process one by email slug
```

**What it does:**
1. Loads `users_pending/<slug>/onboarding.json`
2. If `scholar_url` is present → imports up to 60 papers from the Scholar profile (`scrapers/scholar.py`)
3. Fetches metadata for all seed paper URLs (arXiv batch API + HTML meta tags)
4. Pre-computes author frequencies
5. Calls Claude (using `ANTHROPIC_API_KEY_ONBOARDING` from root `.env`) to generate:
   - Ranked keywords (8–15, grades 1–5)
   - Research areas (3–6, grades 1–5)
   - Ranked authors
   - `why_relevant` per paper
6. Creates `users/<slug>/`:
   - `taste_profile.json`
   - `archive.json` (empty)
   - `.env` with `EMAIL_TO_DAILY` / `EMAIL_TO_WEEKLY`
7. Stamps `processed_at` on submission JSON to prevent re-processing

**After processing:** Owner must add `ANTHROPIC_API_KEY=sk-ant-...` to `users/<slug>/.env` before the next pipeline run. The onboarding step uses `ANTHROPIC_API_KEY_ONBOARDING` (shared), but daily scoring needs a per-user key.

---

## Interactive CLI Onboarding

```bash
python create_profile.py --user-dir users/<name>
```

**Stages:**
1. Validate Anthropic API key + collect email
2. arXiv categories to monitor (comma-separated)
3. Free-text research interests (multi-line)
4. Researchers to follow (names)
5. Excel file of recently-read paper URLs
6. Python fetches all paper metadata
7. Single Claude call → keywords, areas, authors, why_relevant per paper
8. User reviews draft; can reorder grades/rankings interactively
9. Writes `taste_profile.json`

**Cost:** ~$0.05–0.08 per onboarding (one Sonnet call, ~14k input tokens + ~1.3k output).

---

## Google Scholar Import

Optional. Triggered if the user provides their Scholar profile URL on the seed papers screen.

`scrapers/scholar.py`:
1. Fetch Scholar profile page → list of papers + Scholar detail URLs
2. Follow each detail page → get publisher URL
3. Fetch abstract via `<meta name="citation_abstract">` tags
4. For blocked publishers (APS, ACS) → fallback to OpenAlex title search

Papers without resolvable abstracts are included for author-frequency signal.

Up to 60 papers imported. Deduplicated with manually provided URLs (by arXiv ID, then by title).

---

## Required Environment Variables

Root `.env`:
```
ANTHROPIC_API_KEY_ONBOARDING=sk-ant-...   # Used by process_pending.py
RATING_BASE_URL=https://incomingscience.xyz
EMAIL_FROM=sender@gmail.com
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_SMTP_USER=sender@gmail.com
EMAIL_SMTP_PASSWORD=your-app-password
```

Per-user `.env` (created by process_pending.py, but owner must add the API key):
```
ANTHROPIC_API_KEY=sk-ant-...    # Added manually by owner
EMAIL_TO_DAILY=user@example.com
EMAIL_TO_WEEKLY=user@example.com
```
