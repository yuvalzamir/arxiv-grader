# Taste Profile

[[Home]] | [[User Onboarding]] | [[Monthly Refiner]] | [[Profile Edit Skill]] | [[AI Pipeline]]

Full schema and logic: `create_profile_logic.md`

---

## Schema

```json
{
  "field": "cond-mat",
  "arxiv_categories": ["cond-mat.str-el", "cond-mat.mes-hall"],
  "interests_description": "Free-text description of research interests",
  "keywords": [
    {"keyword": "topological insulators", "grade": 1},
    {"keyword": "quantum transport",      "grade": 2}
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
      "why_relevant": "One sentence from Claude at profile creation."
    }
  ],
  "evolved_interests": "Rolling narrative updated monthly by the refiner.",
  "area_keyword_map": [
    {
      "area": "Scanning probe microscopy",
      "keywords": ["STM/STS", "photocurrent imaging"]
    }
  ],
  "daily_digest": true,
  "weekly_digest": false,
  "weekly_day": "friday",
  "paper_insights": false
}
```

---

## Grade System

**Keywords and research_areas** use a 1–7 grade scale:

| Grade | Meaning | Assigned by |
|-------|---------|-------------|
| 1 | Core interest — must-see topic | User / profile creator |
| 2 | High interest | User / profile creator |
| 3 | Clear interest | User / profile creator |
| 4 | Moderate interest | User / profile creator |
| 5 | Tentative at creation | User / profile creator |
| 6 | Fading — declining signal | Monthly refiner only |
| 7 | Marginal — last chance | Monthly refiner only |

- Grades 1–5 are assigned at creation or edited interactively
- Grades 6–7 are **only** assigned by the monthly refiner (interests fade over time)
- A keyword at grade 7 for **two consecutive months** is automatically removed

**Authors** use a separate `rank` field (integer, rank 1 = highest priority). No grade decay for authors.

---

## What Each Agent Sees

| Profile field | Triage (Haiku) | Scoring (Sonnet) |
|---|---|---|
| `keywords` | ✓ (lean profile) | ✓ |
| `research_areas` | ✓ (lean profile) | ✓ |
| `authors` | ✓ (lean profile) | ✓ |
| `interests_description` | ✗ | ✓ |
| `evolved_interests` | ✗ | ✓ |
| `liked_papers` (up to 5) | ✗ | ✓ |
| `arxiv_categories` | ✓ | ✓ |

Triage gets a **lean profile** to avoid bloating the context on the cached (shared) call.

---

## Delivery Flags

```json
"daily_digest": true,    // Send PDF daily (default: true)
"weekly_digest": false,  // Also/only send weekly summary (default: false)
"weekly_day": "friday"   // Which day for weekly (default: "friday")
```

Any combination is valid: daily-only, weekly-only, or both.

→ See [[Weekly Digest]] for delivery mode details.

---

## `area_keyword_map`

Added in Refiner v2. Maps each research area to the keywords that support it. Used by the area management step to compute **support ratios** — a measure of how well each area is backed by current keyword interests.

- Built once at profile creation (Claude assigns keywords → areas)
- Updated incrementally as the refiner adds new keywords
- Used to compute area support ratios before the Haiku area-management call
- An area is only auto-removed if it has ≤2 keywords and none at grade ≤3

→ See [[Monthly Refiner]] for the full support-ratio formula.

---

## `evolved_interests`

A rolling narrative paragraph updated monthly by the profile refiner. Records:
- Current research trajectory
- Changes made this month (new keywords added/promoted, fading ones demoted)
- Signals to watch next month

Starts as an empty string at profile creation. Used by the scoring agent to understand recent trajectory, not just static keywords.

---

## Per-User Environment

Each user needs `users/<name>/.env`:
```
ANTHROPIC_API_KEY=sk-ant-...      # Used for scoring (Batch API)
EMAIL_TO=alice@example.com         # Default recipient
EMAIL_TO_DAILY=alice@example.com   # Override for daily emails (optional)
EMAIL_TO_WEEKLY=group@lab.org      # Override for weekly emails (optional)
```
