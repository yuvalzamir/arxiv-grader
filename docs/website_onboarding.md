# Web Onboarding — Design & Implementation

## Overview

A static multi-page HTML onboarding flow that collects user registration data and produces a structured JSON profile. Hosted alongside the Flask server at `incomingscience.xyz`. New users self-register; the owner manually activates each account by adding an Anthropic API key and running `process_pending.py`.

## File layout

```
website/stitch_platform_user_expansion/
├── incoming_science_how_it_works_final/code.html   — Landing / home page
├── onboarding_identity_delivery_final/code.html    — Step 1: Email + digest settings
├── onboarding_research_field_final/code.html       — Step 2: Research field selection
├── onboarding_signals_interests_final/code.html    — Step 3: Interests + researchers
├── onboarding_seed_papers_final/code.html          — Step 4: Seed papers (XLSX or URLs)
└── onboarding_success_final/code.html              — Step 5: Confirmation + JSON display
```

## User flow

```
Landing → Identity → Research → Signals → Papers → Success → Landing
```

Back/Next buttons on every page. Logo links back to Landing from all pages.

## State management

All form data is stored in `localStorage` under a single key `is_onboarding`. Each page reads and writes this key. On the Papers page, the full final JSON is compiled and saved as `is_onboarding_final`. The Success page reads `is_onboarding_final`, displays it, then clears both keys.

### Final JSON shape

```json
{
  "email": "user@example.com",
  "daily_digest": true,
  "weekly_digest": false,
  "weekly_day": "friday",
  "field": "cond-mat",
  "interests_description": "Free text description of research interests",
  "researchers": ["Jane Smith", "Prof. A. Jones"],
  "paper_urls": ["https://arxiv.org/abs/2301.12345", "https://doi.org/10.1000/xyz"]
}
```

## Screen-by-screen details

### Step 1 — Identity (`onboarding_identity_delivery_final`)
- Email input with live validation (regex). "Valid Email" indicator fades in when valid.
- Daily digest toggle (default: on) and weekly digest toggle (default: on).
- Weekly day selector appears when weekly digest is on.
- **Next button disabled** until email is valid AND at least one digest is toggled on.

### Step 2 — Research (`onboarding_research_field_final`)
- Dropdown populated dynamically from embedded `fields.json` data (not hardcoded).
- On selection, shows the field's arXiv categories and tracked journals.
- "Contact us" mailto link below subtitle for missing fields.
- **Next button disabled** until a field is selected.

### Step 3 — Signals (`onboarding_signals_interests_final`)
- Textarea for free-text research interests description.
- Researcher chip input: type a name, press Enter to add; click × to remove.
- **Next button disabled** until textarea has at least one character AND at least one researcher chip.

### Step 4 — Papers (`onboarding_seed_papers_final`)
- **Left panel**: XLSX file upload. Uses SheetJS (CDN) to parse client-side. Validates `.xlsx` extension. On upload: extracts all non-empty cell values as URLs, populates the right-side textarea, locks textarea and Clear List button.
- Delete button removes the file and re-enables the textarea.
- **Right panel**: Manual URL textarea (one URL per line). Clear List button.
- No button guard — seed papers are optional.

### Step 5 — Success (`onboarding_success_final`)
- Reads `is_onboarding_final` from localStorage and displays it as formatted JSON.
- Clears both `is_onboarding` and `is_onboarding_final` from localStorage.
- "Go to Home" returns to landing page.

## Sidebar design

All four onboarding pages share the same step-progress sidebar:
- Numbered circles (1–4) connected by a thin vertical line.
- **Active**: dark filled circle + bold label.
- **Completed**: lighter filled circle + muted label.
- **Future**: outlined circle + faded row (`opacity-35`).
- Not interactive — no hover cursors or click handlers.

## Dependencies

- [Tailwind CSS](https://cdn.tailwindcss.com) — utility classes
- [Google Fonts](https://fonts.google.com) — Newsreader (serif) + Inter
- [Material Symbols](https://fonts.google.com/icons) — icons
- [SheetJS / xlsx.js](https://cdn.jsdelivr.net/npm/xlsx/dist/xlsx.full.min.js) — XLSX parsing (Step 4 only)

## Fields data

Step 2 embeds a snapshot of `fields.json` as a JS constant in the page script. When adding a new field to `fields.json`, update the `fieldData` constant in `onboarding_research_field_final/code.html` to match.

## Completed backend work

1. **`POST /onboarding/submit`** in `server.py` — receives the final JSON from the success page, saves to `users_pending/<email-slug>/onboarding.json`.
2. **Success page** — POSTs the compiled JSON to `/onboarding/submit` before clearing localStorage.
3. **`process_pending.py`** — owner tool for processing pending submissions. Supports `--list` (show pending), `--all` (process all), or by slug. Uses `ANTHROPIC_API_KEY_ONBOARDING` from root `.env`. Imports reusable keyword/area generation functions from `create_profile.py` to build `taste_profile.json` without interactive prompts.
4. **Flask static serving** — `server.py` serves the website pages at clean URLs: `/` (landing), `/signup` (step 1 — identity/delivery), `/signup/field` (step 2), `/signup/interests` (step 3), `/signup/papers` (step 4), `/signup/done` (step 5 — success); static assets served at `/assets/<filename>`.
5. **Navigation links** — all HTML pages use absolute URLs (`/signup`, `/signup/field`, etc.) instead of relative paths, so they work correctly when served from Flask routes.
