# Journal Feature — Code Guide

This document explains how the journal pipeline works at the code level.
For architecture decisions and design rationale, see `journal_sources_design.md`.
For triage prompt tuning history, see `journal_triage_tuning.md`.

---

## End-to-end data flow

Every morning `run_all_users.py` orchestrates the following sequence:

```
1. Discover active fields from user profiles
        ↓
2. fetch_journals.py — shared scrape (one pass, all fields)
        writes: data/YYYY-MM-DD/scraped_journals.json
        updates: journal_watermarks.json
        ↓
3. filter_for_field() — pure Python, per field
        writes: data/YYYY-MM-DD/cond-mat_journals.json
        ↓
4. [parallel, per user] run_daily.py --journals cond-mat_journals.json
        ↓
5. run_pipeline.py --journals cond-mat_journals.json --archive archive.json
        → triage (arXiv batch + journals batch, separately)
        → scoring (merged survivors)
        → scored_papers.json
        ↓
6. build_digest_pdf.py → digest.pdf
        ↓
7. Email sent
        ↓
8. Shared data/YYYY-MM-DD/ folder deleted (cleanup)
```

---

## `fields.json`

Global registry at the project root. Maps a field name (matching `"field"` in
`taste_profile.json`) to:
- `arxiv_category` — which arXiv RSS category to fetch
- `journals` — list of journals to scrape for this field, each with:
  - `name` — short label (used as `source` throughout the pipeline)
  - `url` — RSS feed URL (also the watermark key)
  - `publisher` — selects which scraper class to use (`"aps"`, `"nature"`, `"science"`)
  - `tag_filter` — `null` for field-specific journals; list of subject strings for
    general journals (Nature, NatComms) that need subject-tag filtering

---

## `journal_watermarks.json`

Tracks the most recent publication date seen for each RSS feed, keyed by RSS URL.
Prevents re-scraping the same papers across multiple runs.

**How watermarks advance** (in `fetch_journals.py`):

```python
# After scraping a journal:
max_entry_date = max(entry["date"] for entry in new_entries)
yesterday = date.today() - timedelta(days=1)
new_watermark = min(max_entry_date, yesterday)
watermarks[rss_url] = new_watermark
```

The `min(..., yesterday)` guard prevents today's papers from being watermarked
away before tomorrow's run can pick them up — important for feeds that publish
continuously (APS).

The `--since DATE` flag overrides watermark logic for manual re-runs, without
writing back to `journal_watermarks.json`.

---

## `fetch_journals.py` — the scraper CLI

**Entry point:** `main()` in `fetch_journals.py`

1. Loads `fields.json` and `journal_watermarks.json`
2. Unions all journals across all `--fields` (deduplicates by RSS URL)
3. For each journal, calls `scraper.scrape(journal, watermark, since_override)`
4. Deduplicates all results by DOI (same paper can appear in multiple feeds)
5. Writes `scraped_journals.json` (includes `subject_tags`)
6. Writes back updated `journal_watermarks.json`

---

## `scrapers/` — publisher scraper classes

### Class hierarchy

```
BaseScraper (scrapers/base.py)
  ├── APSScraper (scrapers/aps.py)
  ├── NatureScraper (scrapers/nature.py)
  └── ScienceScraper (scrapers/science.py)
```

`BaseScraper` provides:
- A shared `requests.Session` with a `User-Agent` header
- `_get(url)` with 1.5s inter-request delay and timeout handling
- Abstract methods: `editorial_filter(entry)` and `scrape_article(url)`

### `APSScraper`

`editorial_filter`: keeps entries whose link matches
`journals.aps.org/.*/abstract/10\.\d{4}/`. Drops errata and publisher's notes
by title keyword. Handles both `link.aps.org/doi/` redirect URLs and direct
`journals.aps.org` URLs.

`scrape_article`: fetches the APS article page, extracts abstract from
`section.abstract p`. No subject tags available from APS.

### `NatureScraper`

`editorial_filter`: keeps entries whose URL contains `/articles/`. Drops DOIs
starting with `d41586` (news, views, editorials). Also skips articles where
`div#Abs1-content` is absent from the article page (no abstract = non-research).

`scrape_article`: fetches the Nature article page, extracts:
- Abstract from `div#Abs1-content p`
- Authors from `<meta name="citation_author">` tags (Nature RSS has no author field)
- Subject tags from `<meta name="dc.subject">` tags (used for tag filtering)

### `ScienceScraper`

`editorial_filter`: keeps entries whose DOI matches `10.1126/science.*`.
Drops review articles, perspectives, and editorials by DOI pattern.

`scrape_article`: Science.org is protected by Cloudflare and cannot be scraped
reliably. Instead, uses the **Semantic Scholar API** (free, no key) to fetch
the abstract by DOI:

```
https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=title,abstract,authors
```

Falls back to the RSS `<summary>` field if Semantic Scholar has no record.

---

## `run_all_users.py` — shared scrape + per-field filter

**`filter_for_field(scraped_papers, field_config)`** (pure Python, no HTTP):

```python
for paper in scraped_papers:
    tag_filter = journal_tag_filters.get(paper["source"])
    if tag_filter is None:
        keep  # field-specific journal, no filtering needed
    else:
        keep if any(f.lower() in tag.lower()
                    for f in tag_filter
                    for tag in paper["subject_tags"])
```

`subject_tags` are stripped from the output before writing to
`cond-mat_journals.json` — they are an internal implementation detail and are
never passed to Claude.

**Shared data folder cleanup:** After all user pipelines complete, the shared
`data/YYYY-MM-DD/` folder is deleted. Per-user data under
`users/<name>/data/YYYY-MM-DD/` is kept.

---

## `run_pipeline.py` — triage and scoring

### Triage: two separate batches

Journal papers and arXiv papers are triaged in **separate Haiku batch calls**:

```python
arxiv_ranked  = _run_single_triage(arxiv_papers,   profile, triage_prompt,         "Triage-arXiv")
journal_ranked = _run_single_triage(journal_papers, profile, triage_journal_prompt, "Triage-journals")
```

Separate batches prevent cross-pool calibration effects — Haiku won't rank a
mediocre arXiv paper as "high" just because the journal papers in the same
context were weak.

**Caps applied independently:**
- arXiv: up to 15 papers forwarded to scoring
- Journals: up to 15 papers forwarded to scoring

### `prompts/triage_journals.txt` vs `prompts/triage.txt`

Journal papers have no subcategory field, so `triage_journals.txt` replaces the
subcategory+topic signal with an **abstract content signal** (signal 4):

> If the abstract describes experiments, phenomena, materials, or methods that
> fall squarely within a grade 1–5 research area, even without a verbatim
> keyword match, the paper qualifies as `medium`.

This is necessary because journal titles are often broader than arXiv titles and
may not contain field-specific keywords.

### Liked papers sampling (`_sample_liked_papers`)

The scoring prompt includes up to 5 example "liked papers" to calibrate the
scoring agent. These are sampled from the user's archive rather than always
using the original seed papers:

```python
def _sample_liked_papers(archive, seed_papers):
    sample = random.sample(archive, min(10, len(archive)))
    excellent = [e for e in sample if e["rating"] == "excellent"][:5]
    # pad with seed papers if fewer than 5 excellent
    seen_ids = {e["arxiv_id"] for e in excellent}
    padding = [p for p in seed_papers if p["arxiv_id"] not in seen_ids]
    return excellent + padding[:5 - len(excellent)]
```

- Randomly samples 10 archive entries → keeps up to 5 rated `"excellent"`
- Falls back to original seed papers (`liked_papers` in profile) if archive is
  sparse (new users, or few excellent ratings)
- Archive path is passed via `--archive` from `run_daily.py`

### `_paper_block()` — paper representation sent to Claude

Journal papers include a `source:` line; arXiv papers do not:

```
[12]
source: NatComms
arxiv_id: 10.1038/s41467-025-56122-3
title: ...
authors: ...
subcategories:
abstract: ...
```

`subject_tags` are never included — they are stripped before this point.

---

## `build_digest_pdf.py` — journal-aware PDF

**`paper_url(paper)`**: DOI-aware URL builder.
- If `arxiv_id` starts with `10.` → `https://doi.org/{arxiv_id}`
- Otherwise → `https://arxiv.org/abs/{arxiv_id}`

**`rate_url(paper_id, ...)`**: percent-encodes `paper_id` with
`urllib.parse.quote(paper_id, safe="")`. DOIs contain `/` which must be encoded
in query parameters. `server.py` needs no change — Flask auto-decodes.

**Layout**: scored section has two subsections (journals first, then arXiv),
each with a header. Unscored section follows the same layout. `keepWithNext`
applied to subsection headers to prevent orphaned headers at page breaks.

**Font**: uses DejaVu Sans from matplotlib's bundled fonts (broad Unicode
coverage for LaTeX-heavy titles, after conversion by `pylatexenc`).

---

## `server.py` — no changes required

The `/rate` endpoint receives `paper_id` as a URL query parameter. Flask
automatically URL-decodes query parameters, so DOIs (which are percent-encoded
in the PDF rating links) are decoded transparently. No code changes needed.

---

## Adding a new field

1. Add entry to `fields.json` (see design doc for schema)
2. If the publisher is new, add a scraper class in `scrapers/` extending `BaseScraper`
3. Register the new scraper in `scrapers/__init__.py`: `SCRAPERS["publisher"] = NewScraper`
4. Set `"field": "<name>"` in a user's `taste_profile.json`
5. No other changes — `run_all_users.py` discovers the new field automatically
