# Journal Sources Upgrade — Design Document

*Written 2026-03-25. Updated with field-based architecture and scrape-then-filter design.*

---

## Overview

Extend the daily digest to include papers from top physics journals in addition to arXiv. The grading pipeline (triage + scoring) remains unchanged — journal papers are normalised to the same schema as arXiv papers before entering it.

The system is designed around **fields** (e.g. condensed matter, high-energy theory, astrophysics). Each field governs which arXiv category to fetch, which journals to include, and how to filter general journals before triage. Only condensed matter is implemented now, but the infrastructure supports any number of fields.

---

## Field-based architecture

### `fields.json` — global field registry

A single config file at the project root. Each key is a field name that matches the value of `"field"` in a user's `taste_profile.json`.

```json
{
  "cond-mat": {
    "arxiv_category": "cond-mat",
    "description": "Condensed matter physics",
    "journals": [
      {
        "name": "PRL",
        "url": "http://feeds.aps.org/rss/recent/prl.xml",
        "publisher": "aps",
        "tag_filter": null
      },
      {
        "name": "NatComms",
        "url": "https://www.nature.com/ncomms.rss",
        "publisher": "nature",
        "tag_filter": ["condensed matter physics", "materials science", "nanoscience and technology", "superconductivity"]
      }
    ]
  }
}
```

**`tag_filter`:** `null` means the journal is field-specific — take all research articles that pass the publisher editorial filter. A list of strings means the journal is general — after scraping the DOI page, keep only papers whose HTML subject tags contain at least one match. Tag matching is case-insensitive substring match against the `meta[name="dc.subject"]` values.

### `taste_profile.json` — one new field

```json
{
  "field": "cond-mat",
  ...
}
```

The field name must match a key in `fields.json`. If missing, defaults to `"cond-mat"` for backward compatibility.

---

## Condensed matter journal list

| Journal | RSS feed URL | Publisher | Tag filter | Update schedule |
|---|---|---|---|---|
| Physical Review Letters | `http://feeds.aps.org/rss/recent/prl.xml` | aps | null (cond-mat specific) | Continuous (Mon–Fri) |
| Physical Review B | `http://feeds.aps.org/rss/recent/prb.xml` | aps | null | Continuous (Mon–Fri) |
| Physical Review X | `http://feeds.aps.org/rss/recent/prx.xml` | aps | null | Continuous (Mon–Fri) |
| PRX Quantum | `http://feeds.aps.org/rss/recent/prxquantum.xml` | aps | null | Continuous (Mon–Fri) |
| Nature | `https://www.nature.com/nature.rss` | nature | `["condensed matter physics", "materials science", "nanoscience and technology"]` | Weekly (Thursday) |
| Nature Physics | `https://www.nature.com/nphys.rss` | nature | null | Monthly + AOP (any weekday) |
| Nature Materials | `https://www.nature.com/nmat.rss` | nature | null | Monthly + AOP (any weekday) |
| Nature Nanotechnology | `https://www.nature.com/nnano.rss` | nature | null | Monthly + AOP (any weekday) |
| Nature Communications | `https://www.nature.com/ncomms.rss` | nature | `["condensed matter physics", "materials science", "nanoscience and technology", "superconductivity"]` | Continuous (Mon–Fri) |
| Science | `https://feeds.science.org/rss/science.xml` | science | null | Weekly (Friday) |
| Nano Letters | `https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=nalefd` | acs | null | Continuous (multiple/week) |

**Tag filter rationale:**
- Field-specific journals (PRB, NatPhys, NatMat, NatNano, NanoLett, PRL, PRX, PRX Quantum) publish almost exclusively within their field — no tag filtering needed.
- Nature (main) and Nature Communications publish across all of science — tag filtering applied using HTML subject tags extracted from the article page.
- **Science is tag_filter: null** despite being a general journal. Science.org pages are protected by Cloudflare and cannot be reliably scraped with standard HTTP requests. Science publishes only ~3–4 research papers per day, so scraping all of them and letting triage handle relevance is acceptable.

**Publication schedule notes:**
- APS journals publish continuously as manuscripts are accepted (Mon–Fri).
- Nature publishes a new issue every Thursday.
- Science publishes weekly, issues dated Fridays.
- Nature sub-journals (Physics, Materials, Nanotechnology) have monthly issues but post AOP articles throughout the month on any weekday.
- Nature Communications and Nano Letters publish continuously.
- All journals are fetched every day. Empty feeds cost nothing (no scraping triggered).

All journals make full abstracts publicly available on their DOI landing pages.

---

## Architecture

### Three-layer design

```
[global config — static]
  fields.json
    defines: arxiv_category, journal list, tag_filter per field

[shared scraping layer — runs once per day, across ALL active fields]
  fetch_journals.py --fields cond-mat [hep-th ...]
    1. Union all journals across all active fields (deduplicated by URL)
    2. Fetch each journal's RSS feed
    3. Apply publisher editorial filter (drop errata, news, editorials)
    4. Scrape ALL surviving entries: extract abstract + subject tags from DOI page
    5. Write shared cache: data/YYYY-MM-DD/scraped_journals.json
       (includes subject_tags per paper — used by the filter step)

[per-field filter layer — runs once per active field, pure Python, no HTTP]
  filter_journals(scraped_papers, field_config) → field_papers
    1. Read scraped_journals.json
    2. For each paper: if journal's tag_filter is null → keep; else check subject_tags overlap
    3. Write data/YYYY-MM-DD/cond-mat_journals.json

[per-user layer — unchanged, runs in parallel]
  run_daily.py --journals data/YYYY-MM-DD/cond-mat_journals.json
    - arXiv papers + field journal papers → triage → scoring → PDF
```

### Why unified scraping

All active fields share a single scraping pass. If two fields both include a journal (e.g. PRL is relevant for both cond-mat and AMO physics), that journal is scraped only once. The per-field filter step is pure JSON processing — no HTTP, instantaneous.

### Active field discovery — dynamic from user profiles

`run_all_users.py` scans user profiles each morning to collect the set of unique active fields. No static "active fields" file to maintain.

```
run_all_users.py:
  1. Discover all users (as today)
  2. Read each user's taste_profile.json → collect unique field names
  3. Run fetch_journals.py --fields cond-mat [hep-th ...]  ← one shared scrape pass
     → writes data/YYYY-MM-DD/scraped_journals.json
     → if fails: log warning, all users get arXiv-only today
  4. For each unique field: run filter step (pure Python)
     → writes data/YYYY-MM-DD/<field>_journals.json
  5. Run all user pipelines in parallel (as today)
     → each user receives --journals data/YYYY-MM-DD/<field>_journals.json
```

**Why dynamic discovery, not a static active-fields list:**
- `fields.json` defines what fields *can* exist; which are *active* is derived from current users
- Adding a user with field `"hep-th"` automatically includes that field in the scrape
- Removing all users of a field automatically stops scraping it — no stale state

---

## `fetch_journals.py`

### CLI

```
python fetch_journals.py --fields cond-mat --output data/YYYY-MM-DD/scraped_journals.json
python fetch_journals.py --fields cond-mat hep-th --output data/YYYY-MM-DD/scraped_journals.json
```

### Internal flow

```
1. Load fields.json, union all journals for --fields (deduplicate by URL)
2. For each journal:
   a. feedparser.parse(url)
   b. Publisher editorial filter (drop errata, news, editorials)
   c. For each surviving entry:
      i.  requests.get(doi_url, timeout=15, headers={"User-Agent": "..."})
      ii. Extract abstract using per-publisher CSS selector
      iii.Extract subject_tags using meta[name="dc.subject"] (Nature) or [] (others)
      iv. If scraping fails: keep paper with RSS snippet, subject_tags=[], log warning
      v.  Normalise to schema
   d. time.sleep(0.5) between HTTP requests
3. Write all papers to --output as JSON array
```

### Output schema — `scraped_journals.json`

```json
[
  {
    "arxiv_id": "10.1038/s41467-025-56122-3",
    "title": "...",
    "abstract": "...",
    "authors": ["Jane Smith", "John Doe"],
    "subcategories": [],
    "source": "NatComms",
    "subject_tags": ["Condensed matter physics", "Materials science"]
  }
]
```

- `arxiv_id` holds the DOI — unique identifier throughout the pipeline and in rating URLs.
- `subcategories` is always `[]` for journal papers.
- `source` passed through to PDF digest and to triage/scoring agents.
- `subject_tags` used by the filter step only — not passed to Claude.

### Per-publisher editorial filter

| Publisher | Rule |
|---|---|
| APS | Keep if URL matches `journals.aps.org/.*/abstract/10\.\d{4}/`. Exclude if title contains "Erratum" or "Publisher's Note". |
| Nature | Keep if URL contains `/articles/`. Excludes `/news/`, `/comment/`, `/correspondence/`, `/perspective/`. |
| Science | Keep if DOI matches `10.1126/science.` pattern. |
| ACS | Keep all — Nano Letters feed contains only research articles. |

### Per-publisher abstract scraping (CSS selectors)

| Publisher | Abstract CSS selector | Subject tags |
|---|---|---|
| APS (journals.aps.org) | `section.abstract p` | Not available — `[]` |
| Nature (nature.com) | `div#Abs1-content p` | `meta[name="dc.subject"]` |
| Science (science.org) | `div.abstract p` | Not available (Cloudflare) — `[]` |
| ACS (pubs.acs.org) | `p.articleBody_abstractText` | Not available — `[]` |

**Subject tag extraction for Nature:** Confirmed present in HTML as `<meta name="dc.subject" content="Condensed matter physics"/>`. Extract with:
```python
tags = [m.get("content", "") for m in soup.find_all("meta", {"name": "dc.subject"})]
```
Values are human-readable strings like `"Condensed matter physics"`, `"Materials science"`, `"Superconductivity"`. The `tag_filter` values in `fields.json` are matched as case-insensitive substrings against these.

---

## Per-field filter step

Pure Python function in `run_all_users.py` (no subprocess needed — just JSON in, JSON out):

```python
def filter_for_field(scraped_papers: list[dict], field_config: dict) -> list[dict]:
    journal_tag_filters = {j["name"]: j["tag_filter"] for j in field_config["journals"]}
    result = []
    for paper in scraped_papers:
        source = paper.get("source", "")
        tag_filter = journal_tag_filters.get(source)
        if tag_filter is None:
            # Field-specific journal — keep all
            result.append(paper)
        else:
            # General journal — check subject_tags overlap
            paper_tags = [t.lower() for t in paper.get("subject_tags", [])]
            if any(f.lower() in tag for f in tag_filter for tag in paper_tags):
                result.append(paper)
    return result
```

Output written to `data/YYYY-MM-DD/<field>_journals.json`. The `subject_tags` field is stripped before writing — it is an internal implementation detail, not passed to Claude.

---

## Per-user pipeline changes

### `run_pipeline.py`

Accept `--journals`, merge with arXiv papers before triage (arXiv first). Add optional `source` line to `_paper_block()`.

### `run_daily.py`

Accept `--journals` argument, forward to `run_pipeline.py` if the file exists.

### `build_digest_pdf.py`

- Replace `arxiv_url()` with `paper_url()`: DOIs (`10.*`) → `https://doi.org/{doi}`, else arXiv URL
- URL-encode `paper_id` in `rate_url()` with `urllib.parse.quote(paper_id, safe="")` — DOIs contain `/`
- Add source badge (small pill, same row as score badge) for papers with a `source` field

---

## Triage and scoring prompt updates

### `_paper_block()` in `run_pipeline.py`

Add optional `source` line (only `source`, not `subject_tags` — that field is stripped before this point):

```
[12]
source: NatComms
arxiv_id: 10.1038/s41467-025-56122-3
title: ...
authors: ...
subcategories:
abstract: ...
```

### Addition to `prompts/triage.txt`

```
SOURCE FIELD
============
Some papers include a "source" field (e.g. "PRL", "Nature", "NatComms") — these are published journal articles.
Treat journal provenance as a mild positive quality signal, but it is not a substitute for a concrete anchor.
A keyword hit, author match, or subcategory+topic match is still required for "high" or "medium".
Journal papers have no subcategories — rely on keyword and author signals only.
```

### Addition to `prompts/scoring.txt`

```
SOURCE FIELD
============
Papers with a "source" field are published journal articles. Factor in publication venue:
a strong keyword match in Nature or PRL warrants a slightly higher score than the same match
in a less selective venue, reflecting peer-review quality.
Do not inflate scores for venue alone — profile relevance is the primary signal.
Add "top venue" as a tag when source is one of: Nature, NatPhys, NatMat, NatNano, Science, PRL, PRX, PRXQuantum.
```

---

## Cost implications

| Component | Cost impact |
|---|---|
| RSS fetching | $0 |
| Abstract scraping | $0 — one pass shared across all users and fields |
| Nature/NatComms tag filtering | $0 — pure Python after scraping |
| Haiku triage (journal papers added) | Small increase — ~10–30 journal papers added to context per user |
| Sonnet scoring (journal survivors, per user) | ~$0.01–0.02/user/day for ~5–10 survivors |
| **Total per user per day** | ~$0.065 (up from ~$0.05) |
| **At 30 users, one field** | ~$1.95/day — scraping runs once regardless of user count |

---

## Adding a new field in the future

1. Add an entry to `fields.json` with `arxiv_category`, `description`, and `journals` list
2. Set `"field": "<name>"` in any user's `taste_profile.json`
3. No code changes — `run_all_users.py` discovers the new field, includes its journals in the unified scrape, and runs the filter step automatically

---

## What does not change

- Triage and scoring prompts (except SOURCE FIELD addition above)
- `run_pipeline.py` core logic — merged papers enter the same pipeline
- `server.py` `/rate` endpoint — Flask auto-decodes URL params
- `archive.py`, `deduplicate_ratings.py` — handle DOI strings transparently
- `taste_profile.json` keywords/areas/authors schema
