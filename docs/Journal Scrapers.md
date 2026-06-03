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

The `min(..., yesterday)` guard prevents watermarking today's papers away before tomorrow can pick them up (important for APS which publishes continuously).

**Override for re-runs:** `--since YYYY-MM-DD` overrides watermark without writing back. `--no-advance-watermark` re-scrapes but doesn't update watermarks.

**Multi-field consistency rule:** A journal that appears in multiple fields must have **identical config** across all definitions — especially `id_pattern`. If one definition has `id_pattern` and another doesn't, the watermark type alternates between runs depending on field ordering, causing papers to re-appear in consecutive digests. See [[runs/2026-06-03-jpubEcon]].

**Recovery:** A snapshot is saved at the start of every run to `data/DATE/journal_watermarks_snapshot.json`. If watermarks are advanced incorrectly:
```bash
cp data/2026-04-14/journal_watermarks_snapshot.json journal_watermarks.json
```

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

### RSS Concurrency Limit

`scrapers/sources.py` enforces a `threading.Semaphore(2)` around every `feedparser.parse()` call. This limits concurrent RSS fetches to 2 at a time across all publisher threads, preventing CDN burst-detection (Cloudflare).

**Why:** With 8 parallel publisher workers, all RSS requests were firing simultaneously at `t=0`. OUP, Tandfonline, SAGE, Wiley, and PLOS all route through Cloudflare's CDN, which interpreted the burst as bot traffic and returned HTML block pages instead of XML — causing `feed parse error: not well-formed (invalid token)` on 37 journals simultaneously. Confirmed June 1–2 2026.

**Scope:** Applies only to RSS fetches. Article-page scrapes and API calls (OpenAlex, S2, CORE) are unaffected — those publishers either return abstracts from RSS directly or use non-Cloudflare APIs.

---

### Known slow publishers

- **Elsevier** (`elsevier_general`) — article-level page scraping; Neural Networks journal historically ~77s
- **IEEE** (`ieee`, `ieee_rest`) — TPAMI historically ~29s
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
