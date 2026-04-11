# Systems Biology Field — Implementation Plan

**Branch:** `systems-biology`
**First user:** Yael
**arXiv:** all of `q-bio` (top-level category, covering all subcategories: CB, MN, GN, BM, NC, QM, SC, TO, PE, OT)

---

## Journal roster

| Journal | Publisher key | RSS URL | Abstract source |
|---|---|---|---|
| Cell | `cell` (new) | `https://www.cell.com/cell/inpress.rss` | Page scrape |
| Cell Systems | `cell` (new) | `https://www.cell.com/cell-systems/inpress.rss` | Page scrape |
| iScience | `cell` (new) | `https://www.cell.com/iscience/inpress.rss` | Page scrape |
| Immunity | `cell` (new) | `https://www.cell.com/immunity/inpress.rss` | Page scrape |
| Science Immunology | `science` (extend) | `https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=sciimmunol` | Semantic Scholar |
| Science Advances | `science` (extend) | `https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=sciadv` | Semantic Scholar |
| PNAS | `pnas` (new) | `https://www.pnas.org/action/showFeed?type=etoc&feed=rss&jc=PNAS` | Semantic Scholar |
| PLOS Computational Biology | `plos` (new) | `http://feeds.plos.org/ploscompbiol/NewArticles` | In RSS (open access) |
| Nature Computational Science | `nature` (exists) | `https://www.nature.com/natcomputsci.rss` | Page scrape |
| Nature Communications | `nature` (exists) | `https://www.nature.com/ncomms.rss` | Page scrape |
| Nature | `nature` (exists) | `https://www.nature.com/nature.rss` | Page scrape |
| Science | `science` (exists) | `https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=sci` | Semantic Scholar |

---

## Scraper work

### 1. `scrapers/plos.py` — new (easy)

PLOS is fully open access. Full abstracts are in the RSS `<description>` field as HTML.

- **`editorial_filter`**: skip by title — corrections, retractions, and expressions of concern (same title-regex pattern as ACS scraper).
- **`scrape_article`**: extract abstract from `entry.summary` via BeautifulSoup; no HTTP requests to article pages.
- **`subject_tags`**: not available in RSS; return `[]`.
- **`skip_rss_fallback`**: set to `True` in the return dict — the caller's RSS fallback would re-use the same summary we already parsed, causing duplication.

### 2. Update `scrapers/science.py` — extend (easy)

Current editorial filter accepts only `10.1126/science.*` DOIs, rejecting Science Immunology (`10.1126/sciimmunol.*`) and Science Advances (`10.1126/sciadv.*`).

**Change:** relax the DOI regex from `r"10\.1126/science\."` to `r"10\.1126/"` — this accepts all AAAS journals via the same Semantic Scholar abstract pipeline. No other changes needed. Science Immunology and Science Advances use `publisher="science"` in `fields.json`.

### 3. `scrapers/pnas.py` — new (medium)

PNAS uses the same AAAS-style eTOC RSS format. Article pages are likely scrapeable, but Semantic Scholar is the preferred no-scrape path.

- **`editorial_filter`**: accept entries whose DOI matches `10.1073/pnas.`; this filters out PNAS editorials, commentaries, letters, and corrections which use different DOI patterns.
- **`scrape_article`**: call Semantic Scholar (`api.semanticscholar.org/graph/v1/paper/DOI:{doi}`) with `fields=abstract`. Fall back to empty string (RSS summary will be used by caller).
- **Cover date handling**: PNAS RSS entries carry both `published` (online-first date) and `prism:coverDate` (official issue date). The user notes to use the later of the two. This requires a small change in `fetch_journals.py:_entry_date()`: check `getattr(entry, "prism_coverdate", None)` alongside `published_parsed`/`updated_parsed` and return the maximum date found. This fix benefits PNAS and any other journal with the same metadata pattern. The `pnas` publisher key signals that cover-date logic should be applied — or the fix can be made globally in `_entry_date()`.

### 4. `scrapers/cell.py` — new (medium-hard)

Cell Press (`cell.com`) serves article pages that are not known to be Cloudflare-blocked, so page scraping should work. The `inpress.rss` feeds are already research-article-only (no editorials or news), which simplifies the editorial filter.

- **`editorial_filter`**: skip by title (corrections, retractions, expressions of concern). Feed is otherwise research-only so filter can be permissive.
- **`scrape_article`**: fetch article URL, parse with BeautifulSoup. **CSS selector for the abstract is unknown and must be confirmed by inspecting a live Cell article page before writing the scraper.** Candidate selectors to test:
  - `div.abstract p`
  - `section[data-testid="abstract"] p`
  - `div[class*="abstract"] p`
  - `p[class*="abstract"]`
- **Authors**: extract from `meta[name="citation_author"]` if not already present in the RSS entry.
- **`subject_tags`**: extract from `meta[name="dc.subject"]` if present (same pattern as NatureScraper).
- **Rate limiting**: `SLEEP_BETWEEN_REQUESTS = 1.5s` (inherited from `BaseScraper`) is sufficient; add note to monitor for 429 responses.

### 5. `scrapers/nature_computational_science` — no new scraper

`ncs` = **Nature Computational Science** (`https://www.nature.com/natcomputsci.rss`). This is a Nature Portfolio journal — fully handled by the existing `NatureScraper` with `publisher="nature"`. Just add the URL to `fields.json`. The existing editorial filter (`/articles/` in URL, not `d41586`) already works correctly for this journal.

---

## `fetch_journals.py` change — cover date support

`_entry_date()` currently checks `published_parsed` then `updated_parsed`. Add a third check for `prism_coverdate` (feedparser parses PRISM metadata and exposes it as a string `YYYY-MM-DD`):

```python
def _entry_date(entry) -> date | None:
    parsed = (getattr(entry, "published_parsed", None)
              or getattr(entry, "updated_parsed", None))
    pub_date = date(parsed.tm_year, parsed.tm_mon, parsed.tm_mday) if parsed else None

    cover_str = getattr(entry, "prism_coverdate", None)
    cover_date = date.fromisoformat(cover_str) if cover_str else None

    candidates = [d for d in (pub_date, cover_date) if d is not None]
    return max(candidates) if candidates else None
```

This is a safe global change — it has no effect on feeds that don't carry `prism:coverDate`.

---

## `fields.json` addition

```json
"systems-biology": {
  "arxiv_categories": ["q-bio"],
  "description": "Systems biology, computational biology, immunology, cell biology",
  "journals": [
    { "name": "Cell",                     "url": "https://www.cell.com/cell/inpress.rss",                                                                  "publisher": "cell",    "tag_filter": null },
    { "name": "Cell Systems",             "url": "https://www.cell.com/cell-systems/inpress.rss",                                                           "publisher": "cell",    "tag_filter": null },
    { "name": "iScience",                 "url": "https://www.cell.com/iscience/inpress.rss",                                                               "publisher": "cell",    "tag_filter": null },
    { "name": "Immunity",                 "url": "https://www.cell.com/immunity/inpress.rss",                                                               "publisher": "cell",    "tag_filter": null },
    { "name": "Science Immunology",       "url": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=sciimmunol",                                "publisher": "science", "tag_filter": null },
    { "name": "Science Advances",         "url": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=sciadv",                                    "publisher": "science", "tag_filter": ["Systems biology", "Computational biology", "Immunology", "Cell biology", "Bioinformatics", "Genomics", "Proteomics"] },
    { "name": "PNAS",                     "url": "https://www.pnas.org/action/showFeed?type=etoc&feed=rss&jc=PNAS",                                         "publisher": "pnas",    "tag_filter": null },
    { "name": "PLOS Computational Biology","url": "http://feeds.plos.org/ploscompbiol/NewArticles",                                                         "publisher": "plos",    "tag_filter": null },
    { "name": "Nature Computational Science","url": "https://www.nature.com/natcomputsci.rss",                                                              "publisher": "nature",  "tag_filter": null },
    { "name": "Nature Communications",    "url": "https://www.nature.com/ncomms.rss",                                                                       "publisher": "nature",  "tag_filter": ["systems biology", "computational biology", "cell biology", "immunology", "genomics", "proteomics", "bioinformatics"] },
    { "name": "Nature",                   "url": "https://www.nature.com/nature.rss",                                                                       "publisher": "nature",  "tag_filter": ["systems biology", "computational biology", "cell biology", "immunology", "genomics"] },
    { "name": "Science",                  "url": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=sci",                                       "publisher": "science", "tag_filter": null }
  ]
}
```

**Note on `tag_filter`:** Journals shared with other fields (Nature, Nature Communications, Science Advances) need a `tag_filter` to avoid flooding Yael with physics papers. Field-specific journals (Cell Press, PLOS Comp Bio, Science Immunology, PNAS, Nature Computational Science) have `null` — all papers from those feeds are relevant.

---

## Root `.env` addition (server)

```
ANTHROPIC_API_KEY_SYSTEMS_BIOLOGY=sk-ant-...
```

---

## Implementation order

1. [ ] `scrapers/plos.py` — no unknowns, write and test immediately
2. [ ] Update `scrapers/science.py` — one-line regex change
3. [ ] Update `fetch_journals.py:_entry_date()` — cover date support
4. [ ] `scrapers/pnas.py` — write and test (Semantic Scholar coverage for PNAS is good)
5. [ ] `scrapers/cell.py` — **inspect a live Cell article page first** to confirm abstract CSS selector, then write scraper
6. [ ] Add `systems-biology` to `fields.json`
7. [ ] Register new scrapers in `scrapers/__init__.py`
8. [ ] End-to-end test with `--no-email --user Yael`
9. [ ] Onboard Yael: `python create_profile.py --user-dir users/Yael`
10. [ ] Add `ANTHROPIC_API_KEY_SYSTEMS_BIOLOGY` to server `.env`
11. [ ] SCP all changed files to server
12. [ ] Update TODO.md

---

## Open questions

- **Science Advances `tag_filter`**: Science Advances publishes across all disciplines. The tag list above is a first guess — needs tuning after first live runs.
- **Nature Communications `tag_filter`**: Same — broad journal, needs tuning.
- **Cell abstract selector**: Must be confirmed by inspecting a live article page (Step 5 above).
- **PNAS Semantic Scholar coverage**: Expected to be good (PNAS is open-access-friendly), but verify in testing.
- **Cell inpress feed frequency**: Cell journals post to the inpress feed continuously (not weekly like Science eTOC). Watermark will handle incremental updates correctly.
