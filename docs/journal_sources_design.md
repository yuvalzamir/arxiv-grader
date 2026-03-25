# Journal Sources Upgrade — Design Document

*Written 2026-03-25. Planned future implementation.*

---

## Overview

Extend the daily digest to include papers from top physics journals in addition to arXiv. The grading pipeline (triage + scoring) remains unchanged — journal papers are normalised to the same format as arXiv papers before entering it.

---

## New sources

| Journal | RSS feed URL | Abstract in feed? |
|---|---|---|
| Physical Review Letters | `http://feeds.aps.org/rss/recent/prl.xml` | Truncated |
| Physical Review B | `http://feeds.aps.org/rss/recent/prb.xml` | Truncated |
| Physical Review X | `http://feeds.aps.org/rss/recent/prx.xml` | Truncated |
| Nature | `https://www.nature.com/nature.rss` | 1-sentence summary |
| Nature Physics | `https://www.nature.com/nphys.rss` | 1-sentence summary |
| Nature Communications | `https://www.nature.com/ncomms.rss` | 1-sentence summary |
| Science | `https://feeds.science.org/rss/science.xml` | 1-sentence summary |
| Nano Letters | `https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=nalefd` | None |

All journals make full abstracts publicly available on their DOI landing pages, regardless of whether the full text is paywalled.

---

## Architecture

### Two-layer design

```
[shared layer — runs once per day, before any user pipeline]
  fetch_journals.py
    1. Fetch all journal RSS feeds
    2. Scrape full abstract from each paper's DOI page
    3. Write shared cache: data/YYYY-MM-DD/journal_papers.json

[per-user layer — unchanged, runs in parallel for all users]
  run_daily.py / run_pipeline.py
    - Reads arXiv papers (as today)
    - Reads journal_papers.json (new)
    - Feeds both into existing triage → scoring pipeline
```

### Why this split

Journal papers are the same for all users. Fetching RSS and scraping abstracts once and caching the result avoids N redundant HTTP requests (one per user). Everything Claude touches — triage, scoring — still runs per user because each user has a different taste profile.

---

## Shared layer: `fetch_journals.py`

**Inputs:** list of configured journal RSS feed URLs (could be hardcoded or in a config file)

**Steps:**
1. Fetch each RSS feed via `feedparser`
2. Filter to research articles only (exclude corrections, errata, news, editorials — identified by article type fields or URL patterns per publisher)
3. For each paper, scrape the abstract from the DOI page using `requests` + `BeautifulSoup`
4. Add a small delay between requests (`time.sleep(0.5)`) to avoid burst patterns
5. Normalise each paper to the same schema as arXiv papers (see below)
6. Write to `data/YYYY-MM-DD/journal_papers.json`

**Output schema** — same as `today_papers.json`:
```json
[
  {
    "arxiv_id": "10.1103/PhysRevLett.136.123401",
    "title": "...",
    "abstract": "...",
    "authors": ["Jane Smith", "John Doe"],
    "subcategories": ["cond-mat.str-el"],
    "source": "PRL"
  }
]
```

The `arxiv_id` field holds the DOI for journal papers — it is used as a unique identifier throughout the pipeline and in rating URLs. The `source` field is new and passed through to the PDF digest for display.

**Abstract scraping — per-publisher HTML selectors:**

| Publisher | CSS selector for abstract |
|---|---|
| APS (journals.aps.org) | `section.abstract p` |
| Nature (nature.com) | `div#Abs1-content p` |
| Science (science.org) | `div.abstract p` |
| ACS (pubs.acs.org) | `p.articleBody_abstractText` |

These should be verified and may need updating if publishers change their HTML.

---

## Per-user pipeline changes

### `run_all_users.py`
Add one step before the user loop:
```
1. Run fetch_journals.py   ← new (runs once, shared)
2. Run all users in parallel (as today)
```
If `fetch_journals.py` fails, log a warning and continue — users still get their arXiv digest.

### `run_daily.py`
Pass the journal papers path to `run_pipeline.py`:
```
--journals data/YYYY-MM-DD/journal_papers.json
```

### `run_pipeline.py`
- Accept new optional `--journals` argument
- If provided, load journal papers and merge with arXiv papers before triage
- Both sources go through the existing triage → scoring pipeline unchanged
- No prompt changes needed — journal papers have full abstracts by this point, same as arXiv

### `build_digest_pdf.py`
- Display the `source` field (e.g. "PRL", "Nature Physics") as a small badge on each paper card
- No other changes needed

---

## Triage prompt note

The existing triage prompt works unchanged. The only consideration: journal papers from Nature/Science/PRL are already peer-reviewed and published in top venues, so the triage prompt may naturally pass more of them than typical arXiv submissions. This is appropriate behaviour — no prompt tuning needed.

---

## Cost implications

| Component | Cost impact |
|---|---|
| RSS fetching + scraping | $0 — pure Python/HTTP |
| Haiku triage (journal papers added to existing call) | Small increase proportional to extra papers in context |
| Sonnet scoring (per user, journal survivors added) | ~$0.01–0.02/user/day for ~10 journal papers |
| **Total per user per day** | ~$0.065 (up from ~$0.05) |
| **At 30 users** | ~$1.95/day (up from ~$1.50/day) |

---

## Implementation order

1. Write `fetch_journals.py` — RSS fetch + scraping + normalisation
2. Test abstract scraping per publisher (verify CSS selectors)
3. Add `--journals` argument to `run_pipeline.py` and merge logic
4. Update `run_daily.py` to pass journal path
5. Update `run_all_users.py` to run shared fetch step first
6. Add `source` badge to `build_digest_pdf.py`
7. Update `taste_profile.json` schema if users want to configure which journals to include per user (optional — could also be global)

---

## Open questions

- **Per-user journal configuration:** Should users be able to opt in/out of specific journals, or are all journals enabled for everyone? If per-user, journal list moves to `taste_profile.json`. If global, it stays hardcoded in `fetch_journals.py`.
- **Nature/Science content filtering:** These feeds mix news, editorials, and research articles. Need robust filtering logic — likely a combination of URL pattern and article type metadata in the feed.
- **Holiday handling:** Journal feeds don't have a concept of "no papers today" the way arXiv does. `fetch_journals.py` should handle empty or near-empty feeds gracefully without erroring.
- **APS feed URL pattern:** Other APS journals follow `http://feeds.aps.org/rss/recent/[journal].xml` — PRX Quantum would be `prxquantum`, PRA would be `pra`, etc. Easy to extend.
