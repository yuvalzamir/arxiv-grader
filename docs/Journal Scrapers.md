# Journal Scrapers

[[Home]] | [[Pipeline Overview]] | [[Abstract Enrichment]] | [[AI Pipeline]] | [[Preprint Sources]]

Code guide: `journal_code_guide.md`
Architecture rationale: `journal_sources_design.md`

---

## Overview

`fetch_journals.py` scrapes journals once per run (shared across all fields), writes `data/DATE/scraped_journals.json`, then `filter_for_field()` routes papers to the correct field.

---

## Scraper Class Hierarchy

```
BaseScraper (scrapers/base.py)
  ├─ APSScraper
  ├─ NatureScraper
  ├─ ScienceScraper
  ├─ ACSScraper
  ├─ WileyScraper
  ├─ OpticaScraper
  ├─ IOPScraper
  ├─ OUPScraper
  ├─ ElsevierScraper
  ├─ SpringerScraper
  ├─ CellScraper
  ├─ PLOSScraper
  ├─ PNASScraper
  ├─ SciPostScraper
  ├─ CambridgeScraper
  ├─ RoyalSocietyScraper
  ├─ AIPScraper
  ├─ EDPScraper
  ├─ SAGEScraper
  ├─ TandfonlineScraper
  └─ MuseScraper
```

`BaseScraper` provides: shared `requests.Session`, 1.5s inter-request delay, `_get(url)` with timeout.

---

## Abstract Availability by Publisher

| Publisher | Abstract source | Coverage |
|-----------|----------------|----------|
| **APS** (PRL, PRB, PRX, PRXQuantum) | `harvest.aps.org` Harvest API | Full, no auth required |
| **Nature** | Article page scrape (`div#Abs1-content`) | Full + subject tags |
| **Science** | OpenAlex by DOI (primary); S2 batch enrichment | ~50% via OpenAlex, gaps filled by S2 |
| **ACS** | ❌ Cloudflare-blocked | Title + authors only; S2 batch enrichment post-triage fills ~50% |
| **Wiley** | RSS feed (full abstract included) | Full, no page fetches |
| **IOP** | RSS feed | Full |
| **OUP** | RSS feed | Full |
| **Elsevier / ScienceDirect** | RSS feed | Full |
| **Springer** | RSS feed | Full |
| **Optica** | RSS + OpenAlex API for full abstract | High hit rate |
| **Cambridge** | RSS feed | Full |
| **Royal Society** | RSS feed | Full |
| **AIP** | RSS feed | Full |
| **Cell** | Article page | Full |
| **PLOS** | RSS / article page | Full |
| **PNAS** | Topic-specific RSS feeds | Full |
| **SciPost** | OpenAlex by DOI | Full (OA) |
| **SAGE** | OpenAlex / CORE fallback | Partial |
| **Tandfonline** | OpenAlex / CORE fallback | Partial |
| **Project MUSE** | S2 title search → OpenAlex title search | ~68% hit rate |

→ See [[Abstract Enrichment]] for the multi-tier fallback chain details.

---

## `fields.json` — Field/Journal Registry

```json
{
  "cond-mat": {
    "arxiv_categories": ["cond-mat"],
    "description": "Condensed matter physics",
    "tree_path": ["Natural Sciences", "Physics", "Condensed Matter", "Condensed Matter"],
    "journals": [
      {
        "name": "PRB",
        "url": "http://feeds.aps.org/rss/recent/prb.xml",
        "publisher": "aps",
        "tag_filter": null
      },
      {
        "name": "Nature",
        "url": "https://www.nature.com/nature.rss",
        "publisher": "nature",
        "tag_filter": ["condensed-matter physics", "superconducting"]
      }
    ]
  }
}
```

**`tag_filter`:**
- `null` — field-specific journal; keep all papers
- `["term1", "term2"]` — general journal (Nature, Science, PNAS); keep only papers whose `subject_tags` contain at least one substring match (case-insensitive)
- Note: ACS and Wiley return no subject tags → `tag_filter` has no effect; always use `null`

**Field routing** is by `feed_url` (the RSS URL), not by journal display name. The same journal can appear in multiple fields with different RSS subfeed URLs, and papers route correctly.

**`tree_path`** is a 4-level hierarchy required for the website's field selector. Without it, the field is silently skipped in the UI.

---

## Journal Watermarks

`journal_watermarks.json` tracks the most recent publication date seen per RSS feed URL. Prevents re-fetching papers across runs.

**Advance logic:**
```python
max_entry_date = max(entry["date"] for entry in new_entries)
yesterday = date.today() - timedelta(days=1)
watermarks[rss_url] = min(max_entry_date, yesterday)
```

Papers dated today are skipped at fetch time in `scrapers/sources.py` (all three strategies: RSS, OpenAlex, CrossRef). This means `max_entry_date` is always ≤ yesterday in normal operation, making the `min(..., yesterday)` guard a no-op — but it remains in place as a safety net. This fixes PNAS same-day re-fetch: PNAS publishes papers dated today in its RSS, and without the fetch-time filter they would appear in two consecutive digests.

**Science Advances same-day re-fetch (fixed):** `sciadv` papers (10.1126/sciadv.*) used to repeat in every user's digest for one extra day — ~37 papers per weekly issue, confirmed across all ~25 users in `server_backup_0602` (2026-06-02 snapshot; consecutive-run DOI overlap in `triage_journals_input.txt`, e.g. 2026-05-14 and 2026-05-15 had identical 36-paper sciadv sets). Root cause was the same as PNAS: no fetch-time skip for today-dated entries. `ScienceScraper` has no publisher-specific date handling — it goes through the same generic `fetch_from_rss()` as PNAS — so the fix in commit `e75d29e` (2026-06-04) resolved both simultaneously. Verified against production logs from 2026-06-08 through 2026-06-12: watermark advances cleanly each run with zero re-scraped duplicates.

**Override for re-runs:** `--since YYYY-MM-DD` overrides watermark without writing back. `--no-advance-watermark` re-scrapes but doesn't update watermarks.

**Multi-field consistency rule:** A journal that appears in multiple fields must have **identical config** across all definitions — especially `id_pattern`. If one definition has `id_pattern` and another doesn't, the watermark type alternates between runs depending on field ordering, causing papers to re-appear in consecutive digests. See [[runs/2026-06-03-jpubEcon]].

**Recovery:** A snapshot is saved at the start of every run to `data/DATE/journal_watermarks_snapshot.json`. If watermarks are advanced incorrectly:
```bash
cp data/2026-04-14/journal_watermarks_snapshot.json journal_watermarks.json
```

### ID-based watermarking for journals (`id_pattern`)

Some feeds lack reliable date fields. These use sequential numeric IDs instead, stored in `preprint_watermarks.json` under the journal name key.

Add `id_pattern` to the `fields.json` entry with a regex whose first capture group extracts the numeric ID from the entry link URL. The system stores `max(id_seen)` and skips entries with `id <= stored_max` on subsequent runs.

**IMPORTANT — multi-field consistency:** A journal that appears in multiple fields (e.g. JPubEcon in both `econ-political` and `econ-education`) must have **identical `id_pattern`** in every definition. If one definition has `id_pattern` and another doesn't, the watermark type alternates between runs, causing papers to reappear.

#### Fixed (id_pattern deployed)

All ScienceDirect RSS feeds (`rss.sciencedirect.com`) share the same bug: no per-entry date fields, only a channel-level `lastBuildDate`. The watermark never advances; the full RSS window (~50–100 papers) is re-fetched every run. Fix: `"id_pattern": "pii/S(\\d+)"` captures the full PII numeric string from the entry link URL.

ACM eTOC feeds have no date fields and a future `prism:coverDate` (set months ahead). Fix: `"id_pattern": "10\\.1145/(\\d+)"` captures the ACM DOI suffix.

| Journal | Field(s) | id_pattern | Repeats/day (pre-fix) |
|---------|----------|------------|----------------------|
| Neural Networks | ml | `/pii/S08936080(\d+)` | ~100 |
| JSS | soft-eng | `pii/S(\d+)` | ~56 |
| IST | soft-eng | `pii/S(\d+)` | ~50 |
| NLPJournal | nlp | `pii/S(\d+)` | ~13 |
| NeuroImage | computational-neuroscience | `pii/S(\d+)` | ~47 |
| WomensStudiesIntForum | gender-studies | `pii/S(\d+)` | ~54 |
| EconEdReview | edu-policy, econ-education | `pii/S(\d+)` | ~25 |
| TeachingTeacherEdu | edu-policy | `pii/S(\d+)` | ~18 |
| EarlyChildhoodResQ | edu-policy | `pii/S(\d+)` | ~67 |
| IntJEdDevelopment | edu-policy | `pii/S(\d+)` | ~58 |
| ComputersEdu | edu-policy | `pii/S(\d+)` | ~17 |
| LabourEcon | econ-education | `pii/S(\d+)` | ~35 |
| JDevEcon | econ-education | `pii/S(\d+)` | ~85 |
| JPubEcon | econ-political, econ-education | `pii/S(\d+)` | — |
| ACM TOSEM | soft-eng | `10\.1145/(\d+)` | ~26 |
| ACM TIST | nlp | `10\.1145/(\d+)` | ~16 |

**Note on CL (Computational Linguistics, nlp):** `direct.mit.edu` RSS feed has proper `published_parsed` dates — no `id_pattern` needed. The 6/6 repeats seen in test files were from back-to-back test runs (5 min apart), not a production bug.

**Why these journals need it:**
- **All ScienceDirect** (`rss.sciencedirect.com`): RSS entries have no date fields whatsoever — only a channel-level `lastBuildDate`. Date-based watermark never advances; same full RSS window scraped every run.
- **ACM eTOC feeds**: `prism:coverDate` is set to the future issue publication date (months ahead), which was previously picked by `max()` in `_entry_date()`. Now `_entry_date()` ignores future cover dates, but id_pattern is still preferred to avoid any future-date edge cases.

### `_entry_date()` — date parsing fallback chain (`scrapers/sources.py`)

`_entry_date()` extracts a publication date from an RSS entry with multiple fallbacks:

1. `entry.published_parsed` / `entry.updated_parsed` — standard feedparser-parsed dates
2. `entry.dc_date` raw string — ISO format, e.g. Wiley JSEP (`"2026-05-14T09:40:35-07:00"`)
3. `entry.published` raw string — MM/DD/YYYY format (e.g. IEEE csdl-api feeds: `"05/20/2026 11:01 pm PST"`, non-standard, feedparser cannot auto-parse)
4. `prism:coverDate` — used only when it is a **past** date; future cover dates are ignored

The future-cover-date guard (step 4) prevents ACM eTOC feeds from stalling: TOSEM pre-sets `prism:coverDate` to the issue date months ahead, which was previously causing `_entry_date()` to return a future date → no entries ever filtered → watermark stuck.

---

## `filter_for_field()` — Pure Python, No HTTP

After the global scrape, each field's journals are filtered by this function:

```python
for paper in scraped_papers:
    tag_filter = journal_tag_filters.get(paper["feed_url"])
    if tag_filter is None:
        keep  # field-specific journal
    else:
        keep if any(f.lower() in tag.lower()
                    for f in tag_filter
                    for tag in paper["subject_tags"])
```

`subject_tags` are stripped from the output before writing to `{field}_journals.json` — they are never passed to Claude.

---

## Preprint Sources (bioRxiv / medRxiv)

bioRxiv and medRxiv are handled by `fetch_preprints.py` alongside NBER/CEPR working papers.

**Feed URLs:**
- bioRxiv: `https://connect.biorxiv.org/biorxiv_xml.php?subject={subject}`
- medRxiv: `https://connect.medrxiv.org/medrxiv_xml.php?subject={subject}`

**`fields.json` config key:** `preprint_categories`
```json
"preprint_categories": {
  "biorxiv": ["systems-biology", "bioinformatics", "genetics"],
  "medrxiv": []
}
```
Empty list = skip that server. Absent key = no bio preprints.

**Watermarking:** date-based, stored in `preprint_watermarks.json` under `"{server}:{subject}"` keys (e.g. `"biorxiv:systems-biology": "2026-05-25"`). Papers with `dc:date > watermark` are new.

**Paper schema differences vs arXiv:**
- `arxiv_id` holds the DOI (e.g. `10.1101/2026.05.25.727716`)
- `source` = `"bioRxiv"` or `"medRxiv"` (not `preprint_source`)
- `subcategories: []` — no arXiv-style subcategory codes
- `preprint_date` field added (informational)

**Triage routing:** `source ∈ {"bioRxiv", "medRxiv"}` routes to the arXiv pool (`run_pipeline.py:PREPRINT_SOURCES`), not the journal pool. Papers match on keywords/authors/title only (no subcategory filter).

**Enabled fields:** `systems-biology` (bioRxiv: systems-biology, bioinformatics, genetics, immunology, physiology, cell-biology).

---

## Parallel Scraping (fetch_journals.py)

Implemented 2026-05-28 on branch `parallelize-journal-scraping`.

### Design

`fetch_journals.py` groups journals by `publisher` field, then runs each publisher group in a `ThreadPoolExecutor` (default 8 workers). Within each group, journals run sequentially — preserving per-publisher rate-limit safety. A single `threading.Lock` protects all watermark reads and writes.

```
publisher_groups = defaultdict(list)   # group by journal["publisher"]
ThreadPoolExecutor(max_workers=8)      # one thread per publisher
  └─ _scrape_publisher_group()         # sequential within group, lock-protected watermarks
main thread collects results via as_completed()
watermark file saves, dedup, S2 enrichment → all sequential after executor exits
```

New CLI flag: `--max-publisher-workers N` (default 8).

### Publisher journal counts by field (2026-05-28)

| Field | Journals | Publishers |
|-------|----------|------------|
| edu-policy | 27 | sage, tandfonline, elsevier_general, wiley, springer, oup, openalex, unknown |
| econ-education | 24 | elsevier_general, oup, tandfonline, openalex, sage, springer, unknown, wiley |
| quantum-computing | 20 | aps, nature, plos, iop, science, acs |
| literature-and-culture | 19 | openalex, muse, oup, cambridge, tandfonline |
| optics | 18 | aps, nature, science, pnas, optica, acs |
| systems-biology | 18 | cell, science, pnas, plos, nature |
| cond-mat | 16 | aps, nature, science, pnas, acs |
| quantum-info | 16 | aps, nature, plos, iop, science, acs |
| quantum-optics | 24 | aps, nature, science, pnas, optica, iop, plos, acs |
| quantum-phenomena | 15 | aps, nature, iop, acs, science, pnas |
| astrophysics | 14 | aps, iop, oup, edp, nature, science |
| econ-political | 13 | unknown, oup, wiley, elsevier_general, cambridge, plos, tandfonline |
| demography | 13 | openalex, wiley, tandfonline, springer, sage, oup |
| hep | 12 | aps, elsevier, edp, iop, scipost, nature, science |
| fluid-dynamics | 12 | aps, nature, science, cambridge, royalsociety, aip |
| computational-neuroscience | 10 | iop, cell, nature, plos, elsevier_general, springer, openalex |
| gender-studies | 12 | sage, oup, elsevier_general, openalex, tandfonline |
| soft-matter | 15 | aps, acs, nature, science |
| ml | 6 | openalex, springer, elsevier_general, ieee_rest, ieee, plos |
| soft-eng | 7 | ieee, acm, springer, elsevier_general, wiley |
| ai-vision | 5 | ieee, springer, nature, science |
| nlp | 7 | springer, openalex, cambridge, plos, elsevier_general, acm |
| cond-mat-optics | 15 | aps, nature, science, pnas, acs |
| quantum-sensing | 11 | acs, wiley, nature, pnas, science |
| music-theory | 6 | openalex |
| comparative-literature | 6 | openalex |
| ai-speech | 2 | springer, ieee |

### Publisher Blocklist

`publisher_blocklist.json` lets you temporarily skip publishers by setting an unblock date. `fetch_journals.py` reads this at startup and excludes blocked publishers from the scrape run entirely.

```json
{
  "tandfonline": "2026-06-10",
  "sage": "2026-06-10",
  "oup": "2026-06-10",
  "wiley": "2026-06-10",
  "plos": "2026-06-10"
}
```

Publishers with a future unblock date are silently skipped (logged at INFO level). Once `date.today() >= unblock_date`, they re-enable automatically — no code change needed.

**Block lifted 2026-06-10:** tandfonline, sage, oup, wiley, plos were blocked from 2026-06-03 (Cloudflare managed-challenge IP block, `cType: 'managed'`). The unblock date auto-expired 2026-06-10. Tandfonline, Sage, Wiley, and Chicago are now handled permanently via FlareSolverr (see Cloudflare Bypass section above) — the blocklist is no longer needed for them. See [[runs/2026-06-03-cloudflare]].

**To extend or remove the block:** edit `publisher_blocklist.json` on the server. To unblock immediately, delete the publisher entry or set the date to today.

---

### RSS Concurrency Limit

`scrapers/sources.py` enforces a `threading.Semaphore(2)` around every `feedparser.parse()` call. This limits concurrent RSS fetches to 2 at a time across all publisher threads, preventing CDN burst-detection (Cloudflare).

**Why:** With 8 parallel publisher workers, all RSS requests were firing simultaneously at `t=0`. OUP, Tandfonline, SAGE, Wiley, and PLOS all route through Cloudflare's CDN, which interpreted the burst as bot traffic and returned HTML block pages instead of XML — causing `feed parse error: not well-formed (invalid token)` on 37 journals simultaneously. Confirmed June 1–2 2026.

**Scope:** Applies only to non-Cloudflare RSS fetches. The Cloudflare-blocked publishers (Tandfonline, Sage, Wiley, Chicago) bypass this semaphore entirely — they go through FlareSolverr instead (see below).

---

### Cloudflare Bypass — FlareSolverr

**Problem (confirmed 2026-06-11):** Tandfonline, Sage, Wiley, and Chicago Journals RSS feeds return Cloudflare JS challenge pages (HTTP 403 / "Just a moment...") when fetched from the Hetzner VPS datacenter IP. `feedparser` cannot parse the HTML challenge page and logs `feed parse error — not well-formed (invalid token)`. Yield from these publishers was 0 since first deployment.

**Affected publishers and fields:**

| Publisher | Hostname | Fields |
|-----------|----------|--------|
| Tandfonline | `www.tandfonline.com` | econ-political, econ-education, edu-policy, gender-studies, literature-and-culture, demography |
| Sage | `journals.sagepub.com` | gender-studies, edu-policy, econ-education, demography |
| Wiley | `onlinelibrary.wiley.com` | econ-political, edu-policy, econ-education, soft-eng, quantum-sensing, demography |
| Chicago Journals | `www.journals.uchicago.edu` | econ-political, econ-education, gender-studies, literature-and-culture |

**Solution:** FlareSolverr Docker container running on `localhost:8191`. See [[Infrastructure]] for setup.

**How it works (`scrapers/sources.py`):**

1. `_CLOUDFLARE_HOSTS` frozenset contains the 4 blocked hostnames.
2. In `fetch_from_rss()`, if `urlparse(url).hostname in _CLOUDFLARE_HOSTS`, skip feedparser entirely and call `_fetch_rss_via_flaresolverr()` directly.
3. FlareSolverr POSTs to `localhost:8191/v1`, headless Chrome solves the JS challenge and fetches the URL.
4. Chrome wraps XML/RSS in its built-in viewer (`<html>` with a hidden `<div id="webkit-xml-viewer-source-xml">` containing the raw XML as HTML-escaped entities).
5. Regex extracts the div content; `html.unescape()` recovers valid RSS XML.
6. `feedparser.parse(content)` processes it normally.

**Serialization:** A `_FLARESOLVERR_SEMAPHORE(1)` ensures only one FlareSolverr request runs at a time — it can only run one Chrome session at a time, and concurrent calls produce `status=error`.

**What didn't work:**
- Using `solution.cookies` + `requests.get()` → still 403 (Cloudflare ties `cf_clearance` to Chrome's TLS fingerprint; `requests` has a different fingerprint)
- `BeautifulSoup.get_text()` on the hidden div → strips XML tags, returns plain text only

**Adding a new blocked domain:** Add its hostname to `_CLOUDFLARE_HOSTS` in `scrapers/sources.py` and redeploy. No `fields.json` changes needed.

**Graceful degradation:** If FlareSolverr is down, `_fetch_rss_via_flaresolverr()` returns `None`, and `fetch_from_rss()` returns 0 papers (same behavior as before the fix).

**Timing:** FlareSolverr solves one challenge at a time (~10–60s each). With ~30 blocked journals across 4 domains, Chrome reuses its session cookies per domain — in practice Cloudflare challenges only need solving once per domain per run. Adds ~2–5 min to the journal scrape phase.

Full implementation notes: `docs/flaresolverr_plan.md`.

---

### Known slow publishers

- **Elsevier** (`elsevier_general`) — article-level page scraping; Neural Networks journal historically ~77s
- **IEEE** (`ieee_rest`) — TNNLS historically ~20s
- **Tandfonline / SAGE** — OpenAlex fallback chain adds latency (~5–15s per journal)

Fields with the most parallelism benefit: `edu-policy`, `econ-education` (8 publishers each), `literature-and-culture` (5 publishers).

### Verification

```bash
# Parallel (default)
time python fetch_journals.py --fields edu-policy econ-education ai-vision ml \
  --since 2026-05-25 --output /tmp/journals_parallel_test.json

# Sequential (for comparison)
time python fetch_journals.py --fields edu-policy econ-education ai-vision ml \
  --since 2026-05-25 --output /tmp/journals_seq_test.json --max-publisher-workers 1
```

---

## Adding a New Journal/Field

See `add_new_field.md` for the full step-by-step guide.

Short version:
1. Add entry to `fields.json` with `arxiv_categories`, `description`, `tree_path`, `journals`
2. Add `ANTHROPIC_API_KEY_<FIELD_UPPER>` to root `.env`
3. Onboard a user in the new field
4. SCP updated files to server

If the publisher is new, add a scraper class in `scrapers/` extending `BaseScraper`, and register in `scrapers/__init__.py`.
