# Journal Scrapers

[[Home]] | [[Pipeline Overview]] | [[Abstract Enrichment]] | [[AI Pipeline]]

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

## Adding a New Journal/Field

See `add_new_field.md` for the full step-by-step guide.

Short version:
1. Add entry to `fields.json` with `arxiv_categories`, `description`, `tree_path`, `journals`
2. Add `ANTHROPIC_API_KEY_<FIELD_UPPER>` to root `.env`
3. Onboard a user in the new field
4. SCP updated files to server

If the publisher is new, add a scraper class in `scrapers/` extending `BaseScraper`, and register in `scrapers/__init__.py`.
