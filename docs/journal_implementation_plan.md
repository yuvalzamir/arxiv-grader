# Journal Sources — Implementation Plan

*Written 2026-03-25. Branch: `journal_grader`.*
*Architecture reference: `docs/journal_sources_design.md`.*

---

## Goal

Add journal papers to the daily digest via a field-based architecture. A **field** (e.g. `cond-mat`) governs which arXiv category to fetch, which journals to include, and how to pre-filter general journals before triage. Only `cond-mat` is implemented now; the infrastructure supports any future field with no code changes — only a new entry in `fields.json`.

---

## Files to create or modify

| File | Change |
|---|---|
| `fields.json` | **Create** — global field registry |
| `fetch_journals.py` | **Create** — shared fetch + tag-filter + scrape + normalise |
| `run_all_users.py` | Add per-field shared fetch step before user loop |
| `run_daily.py` | Accept and forward `--journals` arg |
| `run_pipeline.py` | Accept `--journals`, merge before triage, add `source` to paper blocks |
| `prompts/triage.txt` | Add SOURCE FIELD section |
| `prompts/scoring.txt` | Add SOURCE FIELD section + "top venue" tag |
| `build_digest_pdf.py` | DOI-aware URL helper + rate URL encoding + source badge |
| `environment.yml` | Add `beautifulsoup4` and `lxml` |
| `taste_profile.json` (each user) | Add `"field": "cond-mat"` key |

---

## Step 1 — `fields.json` (new file)

Create at project root. Define the full `cond-mat` entry with all 11 journals, tag filters, and publisher labels. See `docs/journal_sources_design.md` for the complete journal table including `tag_filter` values.

Key structural rule: `"tag_filter": null` = field-specific journal, no tag filtering. `"tag_filter": [...]` = general journal, apply tag check to RSS entries before scraping.

This file is the only thing that needs to change when adding a new field.

---

## Step 2 — `fetch_journals.py` (new file)

### CLI

```
python fetch_journals.py --field cond-mat --output data/YYYY-MM-DD/cond-mat_journals.json
```

### Internal flow

```
1. Load fields.json → read journal list for --field
2. For each journal:
   a. feedparser.parse(url)
   b. Publisher editorial filter (drop errata, news, editorials — per-publisher rules)
   c. Tag filter: if tag_filter is not null, check RSS entry's subject tags
      → drop entries with no tag overlap (case-insensitive substring match)
      → this runs before any HTTP scraping — zero cost for filtered-out entries
   d. For each surviving entry:
      i.  requests.get(doi_url) + BeautifulSoup → extract abstract
      ii. If fails: keep paper with RSS snippet, log warning — never drop a paper
      iii.Normalise to schema: {arxiv_id: doi, title, abstract, authors, subcategories: [], source}
   e. time.sleep(0.5) between HTTP requests
3. Write to --output as JSON array
```

### Testing this step

Test each publisher's filter and scraping independently before wiring into the pipeline:
```bash
python fetch_journals.py --field cond-mat --output /tmp/test.json
```
Inspect output: check source distribution, abstract quality, that no errata or news slipped through.

---

## Step 3 — `run_pipeline.py` (modify)

Add `--journals` argument:
```python
parser.add_argument("--journals", default=None,
    help="Path to field journal_papers JSON. Merged with arXiv papers before triage.")
```

Merge before triage (arXiv first, journals appended):
```python
if args.journals:
    journal_papers = load_json(args.journals)
    papers = papers + journal_papers
```

Add `source` line to `_paper_block()` — only if `paper.get("source")` is non-empty:
```python
if paper.get("source"):
    lines.append(f"source: {paper['source']}")
```

No other logic changes. Merged list flows through existing triage → scoring unchanged.

---

## Step 4 — `prompts/triage.txt` and `prompts/scoring.txt` (modify)

Add SOURCE FIELD section to each. Exact text in `docs/journal_sources_design.md` under "Triage and scoring prompt updates".

Key points:
- Triage: source is a mild positive quality signal but not an anchor — content match still required
- Scoring: venue quality can modestly lift the score; add "top venue" tag for the named high-impact journals

---

## Step 5 — `run_daily.py` (modify)

Add `--journals` argument and forward to `run_pipeline.py` if the file exists:
```python
parser.add_argument("--journals", default=None)

if args.journals and Path(args.journals).exists():
    pipeline_cmd += ["--journals", args.journals]
```

One-liner change beyond adding the arg.

---

## Step 6 — `run_all_users.py` (modify) — multi-field tension resolution

This is the most structurally significant change. The goal: run one journal fetch per unique active field, then pass each user their field's result.

### Active field discovery — dynamic from user profiles

```python
from collections import defaultdict

# 1. Read field from each user's profile
fields_to_users: dict[str, list[Path]] = defaultdict(list)
for user_dir in users:
    try:
        profile = json.loads((user_dir / "taste_profile.json").read_text(encoding="utf-8"))
        field = profile.get("field", "cond-mat")
    except Exception:
        field = "cond-mat"
    fields_to_users[field].append(user_dir)

# 2. Run one journal fetch per unique field
journal_paths: dict[str, Path | None] = {}
for field in fields_to_users:
    out = BASE_DIR / "data" / today_str / f"{field}_journals.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(BASE_DIR / "fetch_journals.py"),
         "--field", field, "--output", str(out)],
        cwd=str(BASE_DIR),
    )
    if result.returncode == 0:
        journal_paths[field] = out
        log.info("Journal fetch OK for field '%s': %d papers", field, ...)
    else:
        journal_paths[field] = None
        log.warning("Journal fetch FAILED for field '%s' — arXiv-only for these users.", field)

# 3. Build per-user extra_args including --journals
def extra_args_for_user(user_dir: Path) -> list[str]:
    profile = json.loads((user_dir / "taste_profile.json").read_text(encoding="utf-8"))
    field = profile.get("field", "cond-mat")
    args = [...]  # existing extra_args (--date, --no-email, etc.)
    jpath = journal_paths.get(field)
    if jpath:
        args += ["--journals", str(jpath)]
    return args
```

**Why dynamic discovery, not a static "active fields" file:**
- `fields.json` defines what fields *can* exist
- Which fields are *active* is always derived from current user profiles — one source of truth
- No second file to maintain; adding a user with field `"hep-th"` automatically activates that fetch
- Removing all users of a field automatically stops that fetch — no stale state

**Failure isolation:** if `cond-mat` journal fetch fails, only `cond-mat` users fall back to arXiv-only. A hypothetical `hep-th` field's fetch and users are unaffected.

### New flags

- `--no-journals` — skip all journal fetches (pass through to skip-logic)
- `--journals <path>` — supply a pre-built journal path (for single-field re-runs, testing)

---

## Step 7 — `build_digest_pdf.py` (modify)

**DOI-aware URL helper** — replace `arxiv_url()`:
```python
def paper_url(paper_id: str) -> str:
    if paper_id.startswith("10."):
        return f"https://doi.org/{paper_id}"
    return f"https://arxiv.org/abs/{paper_id.split('v')[0]}"
```

**Rate URL encoding** — DOIs contain `/` which must be percent-encoded:
```python
from urllib.parse import quote

def rate_url(paper_id: str, rating: str, date_str: str) -> str:
    encoded_id = quote(paper_id, safe="")
    url = f"{RATE_BASE_URL}?paper_id={encoded_id}&rating={rating}&date={date_str}"
    if RATE_USER:
        url += f"&user={RATE_USER}"
    return url
```

Note: `server.py` requires no change — Flask auto-decodes URL params, so `request.args.get("paper_id")` already returns the decoded DOI.

**Source badge** — add small source pill in the title row for papers with a `source` field. Same row as the score badge. Unscored papers in the lower section also get the badge.

---

## Step 8 — `environment.yml` (modify)

Add:
```yaml
- beautifulsoup4=4.12
- lxml=5.3
```

---

## Step 9 — User profiles

Add `"field": "cond-mat"` to each existing user's `taste_profile.json`. Backward compatible — if the field is missing, code defaults to `"cond-mat"`.

---

## Implementation order

1. `fields.json` — write and review the full cond-mat config
2. `fetch_journals.py` — write and test in isolation per publisher
3. `run_pipeline.py` — add `--journals`, merge logic, `source` in paper blocks
4. `prompts/triage.txt` + `prompts/scoring.txt` — add SOURCE FIELD sections
5. `run_daily.py` — add `--journals` forwarding
6. `run_all_users.py` — add per-field discovery and shared fetch
7. `build_digest_pdf.py` — DOI URL, rate URL encoding, source badge
8. `environment.yml` — add beautifulsoup4 + lxml
9. Update user profiles with `"field"` key
10. End-to-end test and deploy

---

## Edge cases and error handling

| Scenario | Handling |
|---|---|
| `fetch_journals.py` errors for a field | Log warning; that field's users get arXiv-only digest |
| Individual publisher feed fails | Log warning, skip that publisher, continue |
| Tag filter drops all entries from a journal | Normal — log info, 0 papers from that source |
| Abstract scraping fails for a paper | Keep paper with RSS snippet, log warning |
| Field name in profile not in `fields.json` | Log error for that user, skip journal fetch, continue arXiv-only |
| Multiple users same field | One fetch, shared result — the common case |
| `--no-journals` flag | Skip all journal fetches entirely |

---

## Testing checklist

- [ ] `fetch_journals.py --field cond-mat --output /tmp/test.json` runs cleanly
- [ ] Output contains papers from multiple sources; `source` field present on all
- [ ] NatComms and Nature entries are condensed matter papers only (tag filter working)
- [ ] No errata or news items in APS/Nature/Science output
- [ ] `run_pipeline.py --papers today_papers.json --journals /tmp/test.json` — merged count logged
- [ ] `scored_papers.json` contains papers from both arXiv and journals
- [ ] PDF: journal papers show source badge; clicking title opens `doi.org` link
- [ ] Rating button URL for a journal paper is percent-encoded (`10.1103%2FPhysRevLett...`)
- [ ] `server.py` receives decoded DOI via `request.args.get("paper_id")` — verify with `curl`
- [ ] `run_all_users.py --no-email --user yuval` — full end-to-end passes
- [ ] Kill `fetch_journals.py` mid-run — daily pipeline still completes arXiv-only
- [ ] Add a second fake field to `fields.json` + user — two separate fetches run, two outputs written
