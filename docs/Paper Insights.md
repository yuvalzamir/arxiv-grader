# Paper Insights (Opt-In Feature)

[[Home]] | [[AI Pipeline]] | [[Daily Digest]] | [[Taste Profile]]

---

## Overview

An optional scoring enhancement that generates a structured three-field analysis for each paper instead of the standard one-line justification. Enabled per user — not a global toggle.

---

## How to Enable

Set `"paper_insights": true` in the user's `taste_profile.json` on the server:
```json
{
  "paper_insights": true,
  ...
}
```

This must be set manually (no UI toggle currently).

---

## What Changes

When `paper_insights: true`:
- `run_pipeline.py` loads `prompts/scoring_insights.txt` instead of `prompts/scoring.txt`
- The scoring agent outputs an `insights` object per paper

**Standard scoring output:**
```json
{
  "arxiv_id": "2301.12345",
  "score": 9,
  "justification": "One-line justification.",
  "tags": ["core topic"]
}
```

**Insights scoring output:**
```json
{
  "arxiv_id": "2301.12345",
  "score": 9,
  "justification": "One-line justification.",
  "tags": ["core topic"],
  "insights": {
    "claim": "What the paper claims or demonstrates",
    "novelty": "What makes it methodologically or conceptually new",
    "relevance": "Why it's specifically relevant to this user's research"
  }
}
```

---

## PDF Rendering

Papers with an `insights` object are rendered differently in the PDF:
- A **three-row box** appears below the author band
- Rows: Claim · Novelty · Relevance
- Replaces the standard justification + tags display

Papers without insights (e.g. truncated abstracts) fall back to the standard justification layout, so the PDF is always well-formed.

---

## Abstract Quality Gate

Papers with truncated or missing abstracts are excluded from insights in Python, **not just by prompt instruction:**

```python
# In run_pipeline.py run_scoring():
abstract = paper.get("abstract", "")
abstract_quality = paper.get("abstract_quality", "")
if "insights" in s and abstract_quality not in ("truncated", "missing") and len(abstract) >= 100:
    entry["insights"] = s["insights"]
```

The minimum abstract length is 100 characters. This prevents the model from hallucinating insights for papers it couldn't actually read.

---

## Prompt File

`prompts/scoring_insights.txt` — extends the standard scoring prompt with instructions for the `insights` object. The rest of the scoring logic (grade weighting, tag assignment, score calibration) is unchanged.

---

## Cost Impact

Insights add roughly 2–3× more output tokens per paper (3 structured sentences vs 1 line). Approximate additional cost per user per day: **~$0.010–0.020** on top of the standard ~$0.018 scoring cost.
