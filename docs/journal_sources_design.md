# Journal Sources Upgrade — Design Document

*Written 2026-03-25. Updated with field-based architecture.*

---

## Overview

Extend the daily digest to include papers from top physics journals in addition to arXiv. The grading pipeline (triage + scoring) remains unchanged — journal papers are normalised to the same schema as arXiv papers before entering it.

The system is designed around **fields** (e.g. condensed matter, high-energy theory, astrophysics). Each field governs which arXiv category to fetch, which journals to include, and how to pre-filter general journals before triage. Only condensed matter is implemented now, but the infrastructure supports any number of fields.

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
        "tag_filter": ["condensed-matter", "materials-science", "nanoscience-and-technology", "superconductivity"]
      }
    ]
  }
}
```

**`tag_filter`:** `null` means the journal is field-specific — take all research articles that pass the publisher's editorial filter. A list of strings means the journal is general — keep only RSS entries whose subject tags overlap with the list. Tag matching is done at RSS parse time, before any HTTP scraping.

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
| Nature | `https://www.nature.com/nature.rss` | nature | `["condensed-matter", "materials-science", "nanoscience-and-technology"]` | Weekly (Thursday) |
| Nature Physics | `https://www.nature.com/nphys.rss` | nature | null | Monthly + AOP (any weekday) |
| Nature Materials | `https://www.nature.com/nmat.rss` | nature | null | Monthly + AOP (any weekday) |
| Nature Nanotechnology | `https://www.nature.com/nnano.rss` | nature | null | Monthly + AOP (any weekday) |
| Nature Communications | `https://www.nature.com/ncomms.rss` | nature | `["condensed-matter", "materials-science", "nanoscience-and-technology", "superconductivity"]` | Continuous (Mon–Fri) |
| Science | `https://feeds.science.org/rss/science.xml` | science | `["physics", "materials-science"]` | Weekly (Friday) |
| Nano Letters | `https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=nalefd` | acs | null | Continuous (multiple/week) |

**Tag filter rationale:** Field-specific journals (PRB, NatPhys, NatMat, NatNano, NanoLett) are narrow enough that all research articles are relevant. General journals (Nature main, NatComms, Science) publish across all sciences — tag filtering keeps only condensed matter / materials entries, avoiding unnecessary scraping. PRL and PRX are technically broad but in practice almost entirely physics — no tag filter needed.

**Publication schedule notes:**
- APS journals publish continuously as manuscripts are accepted (Mon–Fri). RSS reflects this.
- Nature publishes a new issue every Thursday. RSS updates weekly.
- Science publishes weekly, issues dated Fridays.
- Nature sub-journals (Physics, Materials, Nanotechnology) have monthly issues but post AOP articles throughout the month on any weekday.
- Nature Communications and Nano Letters publish continuously.
- All journals are fetched daily. Empty feeds cost nothing (no scraping triggered).

All journals make full abstracts publicly available on their DOI landing pages, regardless of paywall status.

---

## Architecture

### Layered design

```
[global config — static]
  fields.json
    defines: arxiv_category, journal list, tag_filter per field

[shared per-field layer — runs once per active field, before user pipelines]
  fetch_journals.py --field cond-mat --output data/YYYY-MM-DD/cond-mat_journals.json
    1. Read journal list for this field from fields.json
    2. Fetch each journal's RSS feed
    3. Apply publisher editorial filter (drop errata, news, editorials)
    4. Apply tag_filter if set (drop entries with no matching subject tag)
    5. For remaining entries: scrape full abstract from DOI page
    6. Normalise to paper schema + source field
    7. Write output

[per-user layer — unchanged, runs in parallel]
  run_daily.py --journals data/YYYY-MM-DD/cond-mat_journals.json
    - Reads arXiv papers (as today)
    - Reads field journal papers (new)
    - Feeds both into triage → scoring pipeline
```

### Active field discovery — dynamic, not static

`run_all_users.py` scans all user profiles each morning to collect the set of unique active fields. It then runs one journal fetch per unique field before starting the user pipelines. Users sharing a field share that fetch result.

```
run_all_users.py:
  1. Discover all users (as today)
  2. Read each user's taste_profile.json → collect unique field names
  3. For each unique field: run fetch_journals.py --field <name>
     → output: data/YYYY-MM-DD/<field>_journals.json
     → if fails: log warning, that field's users get arXiv-only today
  4. Run all user pipelines in parallel (as today)
     → each user receives --journals data/YYYY-MM-DD/<field>_journals.json
```

**Why dynamic discovery, not a static active-fields list:**
- No second file to maintain alongside `fields.json`
- Adding a user with a new field automatically activates that field's journal fetch — no manual step
- Removing all users of a field automatically stops that fetch — no stale state
- `fields.json` defines what fields *can* exist; which ones are *active* is always derived from current users

**Failure isolation:** if one field's journal fetch fails, only that field's users fall back to arXiv-only. Other fields are unaffected.

---

## `fetch_journals.py`

### CLI

```
python fetch_journals.py --field cond-mat --output data/YYYY-MM-DD/cond-mat_journals.json
python fetch_journals.py --field cond-mat --output /tmp/test.json  # for testing
```

### Internal flow

```
1. Load fields.json, read config for --field
2. For each journal in field's journal list:
   a. feedparser.parse(url)
   b. Apply publisher editorial filter (URL/title pattern — excludes errata, news)
   c. Apply tag_filter if set (check RSS entry subject tags against filter list)
   d. For each surviving entry:
      i.  Scrape abstract from DOI page (requests + BeautifulSoup)
      ii. If scraping fails: keep paper with RSS snippet, log warning
      iii.Normalise to paper schema
   e. sleep(0.5) between HTTP requests
3. Write collected papers to output JSON
```

### Tag filtering detail

Nature Communications and Science include subject categories per RSS entry (in `<category>` tags or similar fields parsed by feedparser). The tag filter checks if any of the entry's categories contain a string from `tag_filter` (case-insensitive substring match). This runs before any scraping — entries failing the tag check are dropped with no HTTP cost.

### Output schema

```json
[
  {
    "arxiv_id": "10.1103/PhysRevLett.136.123401",
    "title": "...",
    "abstract": "...",
    "authors": ["Jane Smith", "John Doe"],
    "subcategories": [],
    "source": "PRL"
  }
]
```

- `arxiv_id` holds the DOI — used as unique identifier throughout the pipeline and in rating URLs.
- `subcategories` is always `[]` for journal papers.
- `source` is new — passed through to the PDF digest for display and to triage/scoring agents.

### Per-publisher editorial filter (research articles only)

| Publisher | Rule |
|---|---|
| APS | Keep if URL matches `journals.aps.org/.*/abstract/10\.\d{4}/`. Exclude if title contains "Erratum" or "Publisher's Note". |
| Nature | Keep if URL contains `/articles/`. Excludes `/news/`, `/comment/`, `/correspondence/`, `/perspective/`. |
| Science | Keep if DOI matches `10.1126/science.` pattern. Excludes news, editorials, and other DOI prefixes. |
| ACS | Keep all — Nano Letters feed contains only research articles. |

### Per-publisher abstract scraping (CSS selectors)

| Publisher | CSS selector |
|---|---|
| APS (journals.aps.org) | `section.abstract p` |
| Nature (nature.com) | `div#Abs1-content p` |
| Science (science.org) | `div.abstract p` |
| ACS (pubs.acs.org) | `p.articleBody_abstractText` |

These should be verified before deployment and may need updating if publishers change their HTML.

---

## Per-user pipeline changes

### `run_all_users.py`

Before the user loop, discover active fields and run one journal fetch per field:

```python
# Collect unique fields from all user profiles
fields_to_users = defaultdict(list)
for user_dir in users:
    profile = json.loads((user_dir / "taste_profile.json").read_text())
    field = profile.get("field", "cond-mat")
    fields_to_users[field].append(user_dir)

# Run one journal fetch per unique field
journal_paths = {}  # field -> Path or None
for field in fields_to_users:
    out = BASE_DIR / "data" / today_str / f"{field}_journals.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([sys.executable, "fetch_journals.py",
                             "--field", field, "--output", str(out)])
    journal_paths[field] = out if result.returncode == 0 else None

# Build extra_args per user (inject --journals if available)
# Each user's run_daily.py call receives its field's journal path
```

Add `--no-journals` flag to skip all journal fetches (testing). Add `--journals` flag to supply a pre-built path for single-field re-runs.

### `run_daily.py`

Accept `--journals` argument and forward to `run_pipeline.py`:

```python
parser.add_argument("--journals", default=None,
    help="Path to field journal papers JSON. If omitted, arXiv-only digest.")
```

No other logic changes.

### `run_pipeline.py`

Accept `--journals`, merge with arXiv papers before triage (arXiv first). Add `source` line to `_paper_block()` output if present.

### `build_digest_pdf.py`

Two fixes and one addition:
- Replace `arxiv_url()` with `paper_url()`: DOIs (`10.*`) → `https://doi.org/{doi}`, else arXiv URL
- URL-encode `paper_id` in `rate_url()` with `urllib.parse.quote(paper_id, safe="")` — DOIs contain `/`
- Add source badge (small pill, same row as score badge) for papers with a `source` field

---

## Triage and scoring prompt updates

### `_paper_block()` in `run_pipeline.py`

Add optional `source` line:

```
[12]
source: PRL
arxiv_id: 10.1103/PhysRevLett.136.123401
title: ...
authors: ...
subcategories:
abstract: ...
```

### Addition to `prompts/triage.txt`

```
SOURCE FIELD
============
Some papers include a "source" field (e.g. "PRL", "Nature", "PRB") — these are published journal articles.
Treat journal provenance as a mild positive quality signal.
However, source alone is NOT sufficient for "high" or "medium". A keyword hit, author match, or
subcategory+topic match is still required as the concrete anchor.
Journal papers have no subcategories — rely on keyword and author signals only.
```

### Addition to `prompts/scoring.txt`

```
SOURCE FIELD
============
Papers with a "source" field are published journal articles. Factor in publication venue:
a strong keyword match in Nature or PRL warrants a slightly higher score than the same match
in a less selective venue, reflecting peer-review quality and impact.
Do not inflate scores for venue alone — profile relevance is still the primary signal.
Add "top venue" as a tag when source is one of: Nature, Nature Physics, Nature Materials,
Nature Nanotechnology, Science, PRL, PRX, PRX Quantum.
```

---

## Cost implications

| Component | Cost impact |
|---|---|
| RSS fetching + tag filtering | $0 — pure Python/HTTP |
| Abstract scraping | $0 — pure Python/HTTP; tag filtering reduces volume for general journals |
| Haiku triage (journal papers added) | Small increase — ~10–30 journal papers added to context |
| Sonnet scoring (journal survivors added, per user) | ~$0.01–0.02/user/day for ~5–10 journal papers |
| **Total per user per day** | ~$0.065 (up from ~$0.05) |
| **At 30 users, single field** | ~$1.95/day — journal fetch runs once, not 30× |
| **At 30 users, two fields** | ~$1.95/day + marginal cost of second field's fetch |

Journal fetch is shared within a field — its cost does not scale with the number of users in that field.

---

## Adding a new field in the future

1. Add an entry to `fields.json` with `arxiv_category`, `description`, and `journals` list
2. Set `"field": "<name>"` in any user's `taste_profile.json`
3. No code changes needed — `run_all_users.py` discovers the new field automatically

---

## What does not change

- Triage and scoring prompts (except the SOURCE FIELD addition above)
- `run_pipeline.py` core logic — merged papers enter the same triage → scoring pipeline
- `server.py` `/rate` endpoint — Flask auto-decodes URL params; DOIs are handled transparently
- `archive.py`, `deduplicate_ratings.py` — work on `paper_id` strings, handle DOIs transparently
- `taste_profile.json` keywords/areas/authors — field selection has no effect on profile structure
