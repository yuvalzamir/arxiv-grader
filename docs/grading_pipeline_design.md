# Grading pipeline design — triage vs. scoring

## Core philosophy

| | Triage | Scoring |
|---|---|---|
| **Job** | Eliminate clear misses, rank candidates | Evaluate genuine candidates |
| **Question asked** | "Could this be relevant? Rank from best to worst." | "How relevant is this, and why?" |
| **Bias direction** | Conservative — include when uncertain, but require at least one concrete anchor | Precise — discriminate within the interesting set |
| **Error you fear** | False negative (missing a good paper) | Neither — just get the ranking right |

The cost of a triage false negative is permanent: the paper never gets scored and the user never sees it. The cost of a triage false positive is trivial: one extra paper goes to scoring (~$0.001). But sending too many papers to scoring degrades quality and raises cost — so triage does two jobs: eliminate clear misses **and** rank survivors so Python can cap at 20.

---

## Triage design: ranked output with hard cap

Triage does **not** just classify — it emits papers in ranked order (most relevant first). Python reads the output top-to-bottom and takes the first 20 that meet the high/medium threshold. This means:

- The model is forced to compare papers against each other, not just assign labels in isolation
- The hard cap is enforced by Python without any extra model output
- Papers that only reach "medium" and fall outside the top 20 are silently dropped

**Hard cap:** `MAX_TRIAGE_PASS = 20`. If fewer than 20 papers qualify, only those pass — no padding with low papers.

### Output format

```
7: high
23: medium
1: medium
45: low
...
```

Papers emitted in ranked order. Position = rank. Every paper must appear exactly once. No explanations, no preamble — only these lines.

---

## Classification rules

### High
- A grade 1–2 keyword appears in the title or abstract, **OR**
- A followed author is on the paper

### Medium
- At least one **concrete anchor** is present:
  - A profile keyword (grade 3–6) appears in the title or abstract
  - A followed author is on the paper
  - The subcategory matches a monitored category **AND** the topic has clear overlap with a grade 1–4 research area
- Pure thematic adjacency without any keyword, author, or subcategory anchor → **always low**

### Low
- No concrete anchor: no keyword hit, no author match, no qualifying subcategory+topic combination

**Why the medium threshold matters:** Before tightening, the model would pass papers on vague thematic adjacency — "this touches correlated electrons broadly" — which inflated pass rates to 40%+. The concrete-anchor requirement brings this to ~10–15% on a typical day.

---

## Data passed to each agent

| Data | Triage | Scoring |
|---|---|---|
| Title | ✓ | ✓ |
| Authors | ✓ | ✓ |
| Abstract | ✓ | ✓ |
| arXiv subcategory | ✓ | ✓ |
| Full paper PDF | ✗ | ✗ (v1 — possible future for 8+ scores) |
| `keywords` (graded 1–7) | ✓ | ✓ |
| `research_areas` (graded 1–7) | ✓ | ✓ |
| `authors` (ranked) | ✓ | ✓ |
| `evolved_interests` | ✗ — not needed for fast filter | ✓ — captures recent trajectory |
| Last 5 `liked_papers` | ✗ — too much context for a classifier | ✓ — used for pattern matching |
| `interests_description` | ✗ | ✓ full text |

Triage gets a **lean profile** — keywords, research areas, and followed authors only.
Scoring gets the **full profile context** including evolved interests and recent liked papers.

---

## Signals each agent uses

### Triage — concrete anchors required

1. **Author match** — any author is in the followed list → sufficient for high or medium
2. **Keyword hit in title/abstract** — title or abstract contains a grade 1–2 keyword → high; grade 3–6 → medium
3. **Subcategory + topic** — paper's subcategory matches a monitored category AND topic clearly overlaps with a grade 1–4 research area → medium only
4. **Topic adjacency alone** (no keyword, no author, no subcategory match) → always low; no exceptions

### Scoring — weighted, multi-signal reasoning

1. All triage signals, now weighted by **grade** (grade-1 keyword >> grade-5 keyword)
2. **Author rank weight** — rank-1 author gets a larger boost than rank-5
3. **Keyword density** — how many profile keywords appear, and how prominently
4. **Evolved interests alignment** — does this fit recent trajectory or an older interest?
5. **Liked papers connections** — does this resemble papers the user rated Excellent?
6. **Multi-signal bonus** — papers matching keyword + author + subcategory score higher than any single match
7. **Abstract depth** — methodology, claims, theory vs. experiment, scope of result

---

## Output per paper

| | Triage | Scoring |
|---|---|---|
| Output per paper | rank position + `"high"` / `"medium"` / `"low"` label | Score (1–10) + one-line justification + tags |
| Output tokens/paper | ~4 (index + label only) | ~60–80 |
| Total output (161 papers in, 11 out) | ~650 tokens | ~900 tokens |

**Tags** assigned by scoring agent: `"author match"`, `"core topic"`, `"adjacent interest"`, `"new direction"`

---

## Cost and model

| | Triage | Scoring |
|---|---|---|
| Papers in call | all daily papers (~50–170) | up to 20 (hard cap) |
| Input tokens | ~30–60K (all papers + lean profile) | ~5–10K (filtered papers + full profile) |
| Output tokens | ~650 (ranked IDs, no explanations) | ~900 |
| **Model** | **Haiku** — pattern matching, no nuance needed | **Sonnet** — nuanced multi-signal reasoning |
| **Estimated cost/day** | ~$0.002 | ~$0.018 |

Total grading cost: ~**$0.02/day**.

---

## Output files

| File | Written by | Contents |
|---|---|---|
| `filtered_papers.json` | Triage stage | Papers classified `high` or `medium`, with triage label, in ranked order |
| `scored_papers.json` | Scoring stage | Papers with score, justification, tags, sorted by score descending |
