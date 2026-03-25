# create_profile.py — Logic Documentation

## Purpose

One-time onboarding script. Interviews the user, fetches metadata for papers they have read, calls Claude once to extract and rank their research interests, and writes `taste_profile.json`. This profile is the seed that drives all future paper recommendations.

---

## High-level flow

```
User interview (4 parts)
        │
        ▼
Excel → paper links (arXiv + journal)
        │
        ▼
Python fetches paper metadata
  ├── arXiv: batch API call → title, authors, abstract
  └── journal: HTML fetch → citation meta tags → title, authors, abstract
        │
        ▼
Python pre-computes author frequency counts
        │
        ▼
Single Claude API call
  Input:  free-text + researchers + author counts + paper titles/abstracts
  Output: ranked keywords, ranked areas, ranked authors, why_relevant per paper
        │
        ▼
Python assembles taste_profile.json
        │
        ▼
User reviews draft, optionally edits rankings
        │
        ▼
Saved to taste_profile.json
```

---

## Stage 1 — User interview (`collect_inputs`)

Four sequential prompts:

| Part | What is collected | Format |
|------|-------------------|--------|
| 1 | arXiv categories to monitor | Comma-separated (e.g. `cond-mat.str-el, quant-ph`) |
| 2 | Free-text research interests | Multi-line paragraph, blank line to end |
| 3 | Researchers to follow | One name per line, or comma-separated on one line |
| 4 | Path to Excel file of recently read papers | Single file path |

The free-text description in Part 2 is the richest input — Claude pays particular attention to emphasis words ("mainly", "focus on", "also interested in") to infer ranking.

---

## Stage 2 — Excel parsing (`read_excel_papers`, `normalize_paper_link`)

The Excel file has one paper per row. Each row is scanned cell by cell; the first cell containing a recognisable paper reference is taken and the rest of the row is ignored.

Accepted cell formats, normalised to canonical URLs:

| Input format | Normalised to |
|---|---|
| `https://arxiv.org/abs/2301.12345` | `https://arxiv.org/abs/2301.12345` |
| `https://arxiv.org/pdf/2301.12345v2` | `https://arxiv.org/abs/2301.12345v2` |
| `2301.12345` (bare ID) | `https://arxiv.org/abs/2301.12345` |
| `https://doi.org/10.1103/...` | unchanged |
| `10.1103/PhysRevB.105.045140` (bare DOI) | `https://doi.org/10.1103/PhysRevB.105.045140` |
| Any other `https://` URL | unchanged |

---

## Stage 3 — Paper metadata fetching (`fetch_all_papers`)

Papers are split into two groups and fetched differently.

### arXiv papers — batch API (`fetch_arxiv_batch`)

All arXiv IDs are submitted in a single HTTP request to the arXiv Atom API:

```
https://export.arxiv.org/api/query?id_list=ID1,ID2,...&max_results=N
```

The Atom XML response is parsed with `xml.etree.ElementTree`. For each entry, the script extracts: arXiv ID, title, abstract, and author list.

### Journal papers — HTML meta tags (`fetch_journal_paper`)

Each journal URL is fetched individually. The HTML is capped at 50 KB (enough to reach the `<head>` section where metadata lives). The parser looks for standard `citation_*` meta tags used by Google Scholar and all major publishers:

```html
<meta name="citation_title" content="...">
<meta name="citation_author" content="...">   <!-- one tag per author -->
<meta name="citation_abstract" content="...">
```

Fallbacks in order: `<meta name="description">` for abstract, `<title>` for title. If a fetch fails entirely, the paper is recorded with empty fields so it doesn't block the rest of the pipeline.

---

## Stage 4 — Author frequency pre-computation (`compute_author_frequencies`)

Before calling Claude, Python counts how many papers each author name appears in across all fetched papers. The result is a sorted list passed directly to Claude:

```
Jane Smith: 5 paper(s)
Bob Jones: 3 paper(s)
Carol Lee: 1 paper(s)
...
```

**Why:** Author ranking by frequency is pure arithmetic — no LLM needed. Giving Claude the pre-computed counts means Claude only needs to handle the semantic tasks: deduplicating name variants ("J. Smith" vs "Jane Smith"), merging with the explicitly-followed list, and producing the final ranked author list.

---

## Stage 5 — Claude API call (`call_llm`)

A single, non-agentic call to `claude-sonnet-4-6`. No tools, no extended thinking.

**Input (user message) contains:**
- arXiv categories
- Free-text description of research interests
- Explicitly followed researchers
- Pre-computed author frequencies (top 40)
- Full list of papers: title, authors, arXiv ID / URL, abstract

**System prompt** (`prompts/profile_creator.txt`) instructs Claude to:
1. Identify emphasis markers in the free-text to calibrate importance
2. Find topics that recur across multiple paper abstracts
3. Produce ranked keywords (8–15) and research areas (3–6)
4. Build a ranked author list using the provided frequency counts + explicitly followed names, deduplicating name variants
5. Write one `why_relevant` sentence per paper

**Output schema (compact — Claude does not repeat metadata Python already has):**
```json
{
  "keywords":         [{"keyword": "...", "grade": 1}, ...],
  "research_areas":   [{"area": "...",    "grade": 1}, ...],
  "authors":          [{"name": "...",    "rank": 1}, ...],
  "paper_assessments":[{"arxiv_id": "...", "url": null, "why_relevant": "..."}, ...]
}
```

Keywords and research areas use a **grade system** (1 = most relevant, 5 = tentative at creation). Multiple items may share the same grade. Authors retain a sequential rank (unique integers, rank 1 = highest priority).

`max_tokens` is set to 8192, though typical output is ~1200–1500 tokens.

**JSON parsing** uses a three-tier fallback in case Claude adds any preamble:
1. Direct `json.loads`
2. Strip markdown fences (```` ``` ````), then parse
3. Regex-extract the first `{...}` block, then parse

---

## Stage 6 — Profile assembly (`assemble_profile`)

Python merges Claude's compact rankings with the pre-fetched metadata to build the full `taste_profile.json`. Fields owned by Python (not Claude):

| Field | Source |
|---|---|
| `arxiv_categories` | User input (Part 1) |
| `interests_description` | User input (Part 2), verbatim |
| `liked_papers[].title` | Pre-fetched metadata |
| `liked_papers[].rating` | Hardcoded `"good"` at onboarding |
| `evolved_interests` | Empty string — populated later by profile updater agent |

Fields owned by Claude:

| Field | Source |
|---|---|
| `keywords` | Claude ranking |
| `research_areas` | Claude ranking |
| `authors` | Claude ranking + dedup |
| `liked_papers[].why_relevant` | Claude, one sentence per paper |

---

## Stage 7 — Review and edit loop

The draft profile is printed to the terminal. The user chooses:

- **`[a]` Accept** — writes `taste_profile.json` and exits
- **`[e]` Edit grades/rankings** — for keywords and research areas: user enters `"name: grade"` pairs (e.g. `"STM: 1"`) to reassign grades 1–5. For authors: user types a new comma-separated order; unlisted authors are appended at the end
- **`[q]` Quit** — exits without saving

---

## Output schema — `taste_profile.json`

```json
{
  "arxiv_categories":    ["cond-mat.str-el", "cond-mat.mes-hall"],
  "interests_description": "Free-text from user, verbatim",
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
      "rating": "good",
      "why_relevant": "..."
    }
  ],
  "evolved_interests": ""
}
```

Keywords and areas use grades 1–5 at creation. Grades 6–7 are assigned only by the monthly profile refiner as interest fades. Grade 7 keywords are removed at the next monthly run.

`evolved_interests` starts empty and is populated by the profile updater agent as the user rates papers over time.

---

## Cost

Typical run with ~30 papers: **~$0.05–0.08**

| Component | Tokens | Cost |
|---|---|---|
| Input (papers + free-text + system prompt) | ~14,000 | ~$0.04 |
| Output (rankings JSON) | ~1,300 | ~$0.02 |

The previous design used extended thinking + an agentic tool-use loop, which cost ~$1.40 for the same input. The current design is ~20× cheaper by having Python handle all I/O and passing only clean structured data to Claude.
