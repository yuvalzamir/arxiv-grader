# Journal Sources — Implementation Plan

*Written 2026-03-25. Branch: `journal_grader`.*
*Architecture reference: `docs/journal_sources_design.md`.*

---

## Goal

Add journal papers to the daily digest via a field-based, scrape-then-filter architecture:
1. One shared scraping pass fetches all journals for all active fields
2. A per-field Python filter applies subject tag rules to the scraped results
3. Each user's triage receives their field's filtered list merged with arXiv papers

Only `cond-mat` is implemented now. Adding a new field requires only a new entry in `fields.json` and setting `"field"` in user profiles — no code changes.

---

## Files to create or modify

| File | Change |
|---|---|
| `fields.json` | **Create** — global field registry |
| `fetch_journals.py` | **Create** — unified scraping pass (all active fields, all journals) |
| `run_all_users.py` | Add shared scrape step + per-field filter step before user loop |
| `run_daily.py` | Accept and forward `--journals` arg |
| `run_pipeline.py` | Accept `--journals`, merge before triage, add `source` to paper blocks |
| `prompts/triage.txt` | Add SOURCE FIELD section |
| `prompts/scoring.txt` | Add SOURCE FIELD section + "top venue" tag |
| `build_digest_pdf.py` | DOI-aware URL helper + rate URL encoding + source badge |
| `environment.yml` | Add `beautifulsoup4` and `lxml` |
| `taste_profile.json` (each user) | Add `"field": "cond-mat"` key |

---

## Step 1 — `fields.json` (new file)

Create at project root. The full cond-mat entry with all 11 journals. Tag filter values must match the human-readable subject strings returned by `meta[name="dc.subject"]` on Nature article pages (case-insensitive substring match is applied at filter time).

Key structural rules:
- `"tag_filter": null` — field-specific journal, no filtering, keep all research articles
- `"tag_filter": [...]` — general journal, keep only papers whose scraped `subject_tags` overlap with the list
- Science has `"tag_filter": null` despite being a general journal — Science.org is Cloudflare-protected, subject tags cannot be scraped; Science publishes ~3–4 papers/day so passing all to triage is acceptable

---

## Step 2 — `fetch_journals.py` (new file)

### CLI

```
python fetch_journals.py --fields cond-mat --output data/YYYY-MM-DD/scraped_journals.json
python fetch_journals.py --fields cond-mat hep-th --output data/YYYY-MM-DD/scraped_journals.json
```

### Internal flow

```
1. Load fields.json
2. Union all journals across --fields, deduplicate by URL
3. For each journal:
   a. feedparser.parse(url)
   b. Publisher editorial filter (per-publisher rules — see design doc)
   c. For each surviving entry:
      i.  requests.get("https://doi.org/{doi}", timeout=15, headers={"User-Agent": "..."})
      ii. Extract abstract (per-publisher CSS selector)
      iii.Extract subject_tags from meta[name="dc.subject"] (Nature only; [] for others)
      iv. If scraping fails: keep paper with RSS snippet, subject_tags=[], log warning
      v.  Normalise: {arxiv_id: doi, title, abstract, authors, subcategories: [], source, subject_tags}
   d. time.sleep(0.5) between HTTP requests
4. Write full list to --output as JSON array
```

### Output: `scraped_journals.json`

Includes `subject_tags` field per paper. This field is used by the filter step and then stripped — it is never passed to Claude.

### Per-publisher editorial filter rules

- **APS**: Keep if URL matches `journals.aps.org/.*/abstract/10\.\d{4}/`. Exclude titles containing "Erratum" or "Publisher's Note".
- **Nature**: Keep if URL contains `/articles/`. Excludes `/news/`, `/comment/`, `/correspondence/`, `/perspective/`.
- **Science**: Keep if DOI matches `10.1126/science.` pattern.
- **ACS**: Keep all (Nano Letters feed = research articles only).

### Per-publisher selectors

| Publisher | Abstract CSS | Subject tags |
|---|---|---|
| APS | `section.abstract p` | `[]` — not available |
| Nature | `div#Abs1-content p` | `meta[name="dc.subject"]` — confirmed present |
| Science | `div.abstract p` | `[]` — Cloudflare blocks scraping |
| ACS | `p.articleBody_abstractText` | `[]` — not available |

Subject tag extraction (Nature only):
```python
tags = [m.get("content", "") for m in soup.find_all("meta", {"name": "dc.subject"})]
```
Example values: `"Condensed matter physics"`, `"Materials science"`, `"Superconductivity"`.

---

## Step 3 — `run_all_users.py` (modify) — multi-field tension resolution

This is the most structurally significant change. It orchestrates: dynamic field discovery → unified scrape → per-field filter → parallel user pipelines.

### Active field discovery — dynamic from user profiles, not a static list

```python
from collections import defaultdict

fields_to_users: dict[str, list[Path]] = defaultdict(list)
for user_dir in users:
    try:
        profile = json.loads((user_dir / "taste_profile.json").read_text(encoding="utf-8"))
        field = profile.get("field", "cond-mat")
    except Exception:
        field = "cond-mat"
    fields_to_users[field].append(user_dir)

active_fields = list(fields_to_users.keys())
```

**Why dynamic, not a static active-fields file:**
- `fields.json` defines what fields *can* exist; active fields are always derived from current users
- Adding a user with `"field": "hep-th"` automatically includes that field's journals in the scrape
- Removing all users of a field automatically stops scraping it — no stale state, no manual maintenance

### Unified scrape step

```python
scraped_path = BASE_DIR / "data" / today_str / "scraped_journals.json"
scraped_path.parent.mkdir(parents=True, exist_ok=True)

result = subprocess.run(
    [sys.executable, str(BASE_DIR / "fetch_journals.py"),
     "--fields", *active_fields,
     "--output", str(scraped_path)],
    cwd=str(BASE_DIR),
)
scrape_ok = result.returncode == 0
if not scrape_ok:
    log.warning("fetch_journals.py failed — all users get arXiv-only digest today.")
```

### Per-field filter step (pure Python — no subprocess)

```python
def filter_for_field(scraped_papers: list[dict], field_config: dict) -> list[dict]:
    journal_tag_filters = {j["name"]: j["tag_filter"] for j in field_config["journals"]}
    result = []
    for paper in scraped_papers:
        tag_filter = journal_tag_filters.get(paper.get("source", ""))
        if tag_filter is None:
            result.append(paper)  # field-specific journal — keep all
        else:
            paper_tags = [t.lower() for t in paper.get("subject_tags", [])]
            if any(f.lower() in tag for f in tag_filter for tag in paper_tags):
                result.append(paper)
    # Strip subject_tags before writing — internal detail, not for Claude
    return [{k: v for k, v in p.items() if k != "subject_tags"} for result_paper in result
            for p in [result_paper]]
```

Run once per active field, write `data/YYYY-MM-DD/<field>_journals.json`:

```python
field_journal_paths: dict[str, Path | None] = {}
if scrape_ok:
    fields_config = json.loads((BASE_DIR / "fields.json").read_text(encoding="utf-8"))
    scraped = json.loads(scraped_path.read_text(encoding="utf-8"))
    for field in active_fields:
        if field not in fields_config:
            log.warning("Field '%s' not found in fields.json — skipping journal papers.", field)
            field_journal_paths[field] = None
            continue
        filtered = filter_for_field(scraped, fields_config[field])
        out = BASE_DIR / "data" / today_str / f"{field}_journals.json"
        out.write_text(json.dumps(filtered, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("Field '%s': %d journal papers after filtering.", field, len(filtered))
        field_journal_paths[field] = out
else:
    field_journal_paths = {f: None for f in active_fields}
```

### Per-user extra_args injection

```python
def extra_args_for_user(user_dir: Path) -> list[str]:
    profile = json.loads((user_dir / "taste_profile.json").read_text(encoding="utf-8"))
    field = profile.get("field", "cond-mat")
    args = [...]  # existing: --date, --no-email, etc.
    jpath = field_journal_paths.get(field)
    if jpath and jpath.exists():
        args += ["--journals", str(jpath)]
    return args
```

**Failure isolation:** if the scrape fails, all users fall back to arXiv-only. If a specific field's filter step fails, only that field's users are affected.

### New flags

- `--no-journals` — skip the entire journal fetch and filter step
- `--journals <path>` — supply a pre-built field-journals path for single-user re-runs

---

## Step 4 — `run_pipeline.py` (modify)

Add `--journals` argument:
```python
parser.add_argument("--journals", default=None,
    help="Path to field-filtered journal papers JSON. Merged with arXiv papers before triage.")
```

Merge before triage (arXiv first):
```python
if args.journals:
    journal_papers = load_json(args.journals)
    papers = papers + journal_papers
    log.info("Merged %d journal papers. Total: %d papers for triage.", len(journal_papers), len(papers))
```

Add `source` line to `_paper_block()` if present:
```python
if paper.get("source"):
    lines.append(f"source: {paper['source']}")
```

No other changes — merged list flows through existing triage → scoring unchanged.

---

## Step 5 — `prompts/triage.txt` and `prompts/scoring.txt` (modify)

Add SOURCE FIELD section to each. Exact text in `docs/journal_sources_design.md` under "Triage and scoring prompt updates".

---

## Step 6 — `run_daily.py` (modify)

Add `--journals`, pass to `run_pipeline.py` if the file exists. One-liner change beyond adding the arg.

---

## Step 7 — `build_digest_pdf.py` (modify)

**DOI-aware URL helper:**
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
    ...
```
`server.py` requires no change — Flask auto-decodes query params.

**Source badge** — small pill in the title row for papers with a `source` field.

---

## Step 8 — `environment.yml`

Add `beautifulsoup4=4.12` and `lxml=5.3`.

---

## Step 9 — User profiles

Add `"field": "cond-mat"` to each existing user's `taste_profile.json`. Backward compatible — missing field defaults to `"cond-mat"`.

---

## Implementation order

1. `fields.json` — write full cond-mat config, verify tag_filter strings match real Nature subject tag values
2. `fetch_journals.py` — write and test per publisher in isolation
3. `run_pipeline.py` — `--journals` arg, merge logic, `source` in paper blocks
4. `prompts/triage.txt` + `prompts/scoring.txt` — SOURCE FIELD sections
5. `run_daily.py` — `--journals` forwarding
6. `run_all_users.py` — field discovery, unified scrape, per-field filter, per-user injection
7. `build_digest_pdf.py` — DOI URL, rate URL encoding, source badge
8. `environment.yml` — add beautifulsoup4 + lxml
9. Update user profiles with `"field"` key
10. End-to-end test and deploy

---

## Edge cases and error handling

| Scenario | Handling |
|---|---|
| `fetch_journals.py` errors | All users get arXiv-only; log warning |
| Individual publisher feed fails | Skip that publisher, log warning, continue |
| Abstract scraping fails for a paper | Keep with RSS snippet, `subject_tags=[]`, log warning |
| Paper with `subject_tags=[]` and non-null tag_filter | Filtered out (no overlap possible) — acceptable loss |
| Field in profile not in `fields.json` | Log error, no journal papers for that user |
| Science Cloudflare block | tag_filter is null — all Science papers pass through to triage |
| Multiple users same field | One scrape, one filter, shared result |
| `--no-journals` flag | Skip fetch and filter entirely |

---

## Testing checklist

- [ ] `fetch_journals.py --fields cond-mat --output /tmp/scraped.json` runs cleanly
- [ ] Output has `subject_tags` on Nature/NatComms papers; `[]` on APS/Science/ACS
- [ ] No errata or news items in output
- [ ] `filter_for_field()` correctly filters NatComms papers by subject tags
- [ ] `filter_for_field()` passes all PRL papers through (tag_filter: null)
- [ ] `<field>_journals.json` has no `subject_tags` field (stripped before writing)
- [ ] `run_pipeline.py --papers today_papers.json --journals /tmp/cond-mat.json` runs, logs merged count
- [ ] `scored_papers.json` has papers from both arXiv and journals
- [ ] PDF: journal papers show source badge; title links to `doi.org`
- [ ] Rating button URL is percent-encoded (`10.1103%2FPhysRevLett...`)
- [ ] `run_all_users.py --no-email --user yuval` — full end-to-end passes
- [ ] Kill `fetch_journals.py` mid-run — daily pipeline still completes arXiv-only
- [ ] Add fake second field to `fields.json` + user — two filter passes run, two output files written
