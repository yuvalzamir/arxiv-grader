# AI Pipeline — Triage & Scoring

[[Home]] | [[Pipeline Overview]] | [[Prompt Caching]] | [[Taste Profile]]

Design rationale: `grading_pipeline_design.md`

---

## Two-Stage Design

| | Stage 1: Triage | Stage 2: Scoring |
|---|---|---|
| **Model** | Claude Haiku | Claude Sonnet |
| **Job** | Eliminate clear misses, rank candidates | Score 1–10 with justification |
| **Input** | Lean profile (keywords, areas, authors only) | Full profile + evolved_interests + liked papers + irrelevant examples |
| **Papers in** | ~80–200 per field | ≤10 arXiv + ≤10 journal (hard caps) |
| **Output** | Ranked list with high/medium/low labels | JSON with score, justification, tags |
| **API mode** | Cached synchronous (or Batch for overflow) | Batch API (50% discount) |
| **Cost/user/day** | ~$0.002 | ~$0.018 |

---

## Stage 1 — Triage

### Two separate calls per user

arXiv and journal papers are triaged in **independent** calls using different prompts:
- `prompts/triage.txt` — for arXiv papers (uses subcategory signal)
- `prompts/triage_journals.txt` — for journal papers (subcategory absent; uses abstract content signal instead)

**Why separate?** Prevents cross-pool calibration — a mediocre arXiv paper won't rank "high" just because journal papers in the same context were weak.

### Classification Rules

**High** — any of:
- A grade 1–2 keyword appears in title or abstract
- A followed author is on the paper

**Medium** — requires at least one concrete anchor:
- Grade 3–6 keyword in title/abstract, OR
- Followed author match, OR
- Subcategory matches a monitored category AND topic clearly overlaps with a grade 1–4 area

**Low** — no concrete anchor (pure thematic adjacency → always low, no exceptions)

### Output Format

Triage outputs a ranked list — best papers first. Python reads top-to-bottom and caps at:
- **10 arXiv papers** (`MAX_TRIAGE_PASS = 10`)
- **10 journal papers** (`MAX_TRIAGE_PASS_JOURNAL = 10`)

```
7: high
23: medium
1: medium
45: low
...
```

### Prompt Caching

The papers block is identical for all users in a field → cached. See [[Prompt Caching]] for the full architecture.

---

## Stage 2 — Scoring

### Input to Scoring Agent

Built by `build_scoring_message()`:
- Full taste profile: keywords + areas + authors + interests_description + evolved_interests
- Up to 5 "liked papers" sampled from archive (excellent-rated, padded with seed papers)
- Up to 3 "irrelevant papers" as negative examples (most recent)
- All triage survivors (≤20 total)

### Output Schema

```json
[
  {
    "arxiv_id": "2301.12345",
    "score": 9,
    "justification": "One sentence explaining relevance.",
    "tags": ["core topic", "author match"]
  }
]
```

**Tags:** `"author match"`, `"core topic"`, `"adjacent interest"`, `"new direction"`

### Batch API

Scoring uses the Anthropic Message Batches API (50% cost discount). A single-request batch is submitted, polled every 15 seconds, and canceled + re-tried via direct API after 20-minute timeout.

**Fallback:** On timeout, `batch_fallback.json` is written to the user's data folder. `run_all_users.py` scans for these after all users complete and sends an alert email to the operator.

Use `--no-batch` to skip the Batch API for all calls (useful for testing: faster but 2× cost).

---

## Liked-Paper Sampling

```python
def _sample_liked_papers(archive, seed_papers):
    # 1. Random sample of 10 from archive
    sample = random.sample(archive, min(10, len(archive)))
    # 2. Keep up to 5 rated "excellent"
    excellent = [e for e in sample if e["rating"] == "excellent"][:5]
    # 3. Pad with seed papers from profile if still under 5
    seen_ids = {e["arxiv_id"] for e in excellent}
    padding = [p for p in seed_papers if p["arxiv_id"] not in seen_ids]
    return excellent + padding[:5 - len(excellent)]
```

This prevents the model from always seeing the same examples and keeps the context fresh.

---

## Paper Insights (Opt-In)

Users with `"paper_insights": true` in `taste_profile.json` use `prompts/scoring_insights.txt` instead of the standard scoring prompt. This adds an `insights` object to each scored paper:

```json
"insights": {
  "claim": "What the paper claims",
  "novelty": "What makes it new",
  "relevance": "Why it's relevant to this user"
}
```

The PDF renders these as a three-row box. Papers with truncated/missing abstracts are excluded from insights in Python (not just by prompt instruction).

→ See [[Paper Insights]] for full details.

---

## JSON Parsing — Three-Tier Fallback

The scoring output is parsed with three attempts in case Claude adds prose:
1. Direct `json.loads()`
2. Strip markdown fences (` ``` `), then parse
3. Regex-extract first `[...]` or `{...}` block, then parse

---

## Debug Files

Every run writes full prompt inputs for debugging:
- `triage_arxiv_input.txt` — system prompt + papers + profile for arXiv triage
- `triage_journals_input.txt` — same for journal triage
- `scoring_input.txt` — system prompt + full scoring message

These are in `users/<name>/data/YYYY-MM-DD/` and persist for 14 days.
