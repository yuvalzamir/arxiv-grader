# New Field: `library-science` — Library & Information Science + Archival Studies

> **STATUS: IMPLEMENTED + FULLY VERIFIED 2026-08-21** (local + server runs; all 23 journals yield papers). Server verification (60-day window) returned 275 papers; all six remaining FlareSolverr-gated journals worked (JASIST 13, JInformationScience 38, JLibrarianshipInfoSci 23, IFLAJournal 11, LibraryQuarterly 6, CatalogingClassificationQ 4 — all full/truncated abstracts, JLSC/Elsevier gaps as noted below). Deployment pending: re-scp fields.json, API key, onboarding. Deltas vs this plan:
> - **ArchivesRecords switched T&F feed → `openalex` ISSN `2325-7962`**: the `cjsa20` RSS feed returned nothing on the server even though CrossRef showed Aug 2026 articles (stale/empty feed); OpenAlex has it with day-granularity dates + full abstracts (2 articles in the 60-day window after the switch).
> - **Library Trends MUSE jid = 334** (was TBD).
> - **`id_pattern: "pii/S(\\d+)"` added** to both `elsevier_general` entries (JAcadLib, LISResearch) — required for ScienceDirect ID-based watermarks, omitted in this draft.
> - **+LIBER Quarterly** (`openalex` ISSN `2213-056X`) — European research-library angle for the first user (UPC academic librarian).
> - **American Archivist DROPPED**: OpenAlex *and* CrossRef both carry year-granularity dates (`2026-01-01`) for it, which a date watermark can never see as new; its Allen Press Meridian platform (Silverchair) is bot-walled (403). Archival studies remains covered by Archivaria, Archival Science, Archives & Records.
> - Final count: **23 journals** (this draft's "22" undercounted its own 23-row list).
>
> **Local verification 2026-08-21** (`--since 2026-06-22`, wide check `--since 2026-03-01`): all 16 non-Cloudflare journals yield papers with mostly full abstracts. 60-day yield ≈ 180 papers (~3/day). Notes:
> - Elsevier pair (JAcadLib 43/61, LISResearch 5/8 missing abstracts) — known ScienceDirect abstract restriction; CORE API fallback (TODO) would lift it.
> - JLSC 21/22 abstracts missing — its OA platform (Iowa State Digital Press, Janeway) is behind an Anubis bot-wall; OpenAlex has works but no inverted index. CORE would fix (OA journal).
> - Code4Lib publishes ~1 issue/year in a burst (last: 2025-10-21, 30 articles) — 0 in any recent window is normal, feed healthy.
> - The 7 FlareSolverr-gated journals (T&F ×2, SAGE ×3, JASIST, LibraryQuarterly) can only be verified on the server.

## Context

Add a new field to Incoming Science serving **professional librarians** (academic librarianship first) **and archivists**. Built per `.claude/skills/new-field.md` and `docs/add_new_field.md`. This is a practitioner-oriented, journals-heavy field in the mold of `music-theory`/`gender-studies` — low daily volume, many small journals, several publishers reached via OpenAlex-ISSN instead of RSS.

## Field overview (Step 2)

Library and information science (LIS) studies how information is organized, described, discovered, preserved, and delivered to communities of users. Its practitioner core covers academic and research librarianship (collections, reference, instruction, assessment), cataloging and metadata standards (RDA, MARC, BIBFRAME, linked data), scholarly communication and open access, information literacy, library technology and systems, and digital curation. Archival science — a sibling discipline serving archivists — adds appraisal, provenance, arrangement and description, records management, and digital preservation of unique materials. The field's current hot topics include AI in libraries, research-data services, and equitable access. It borders on (but is distinct from) technical information retrieval and bibliometrics research, which serve computer scientists more than working librarians.

## arXiv categories (Step 3)

| Category | Justification |
|---|---|
| `cs.DL` (Digital Libraries) | Scholarly communication, digital library systems, bibliometrics, institutional repositories — the one arXiv category where LIS-relevant work appears (confirmed: LIS scientometrics papers post there). Low volume (~0–5/day), which the pipeline handles. |

No other categories — `cs.IR` is technical IR research, out of practitioner scope.

## Proposed journals (Steps 4–6) — 22 journals, no new scrapers needed

All feeds use **existing publisher keys**. FlareSolverr already covers the Cloudflare-walled hosts (tandfonline, sagepub, wiley, uchicago). OJS/WordPress open-access journals reuse the `plos` scraper (precedent: JAIR via OJS gateway, Quantum via WordPress feed). Emerald has no RSS → `openalex` ISSN path (precedent: music-theory field).

### Academic librarianship (core)
| Journal | Publisher key | Feed | Notes |
|---|---|---|---|
| College & Research Libraries | `plos` | `https://crl.acrl.org/index.php/crl/gateway/plugin/WebFeedGatewayPlugin/rss2` | **Feed verified live, has abstracts** |
| portal: Libraries and the Academy | `muse` | `https://muse.jhu.edu/feeds/latest_articles?jid=159` | **Feed verified live** (truncated abstracts — normal for muse) |
| Journal of Academic Librarianship | `elsevier_general` | `https://rss.sciencedirect.com/publication/science/00991333` | Standard sciencedirect pattern |
| The Library Quarterly | `oup` | `https://www.journals.uchicago.edu/action/showFeed?type=etoc&feed=rss&jc=lq` | Chicago rides `oup` key (precedent: JPE); FlareSolverr host |
| Library Trends | `muse` | `https://muse.jhu.edu/feeds/latest_articles?jid=<TBD>` | **jid must be looked up during implementation** (159=portal confirmed; 197/84 are other journals) |
| Evidence Based Library & Information Practice | `plos` | `https://journals.library.ualberta.ca/eblip/index.php/EBLIP/gateway/plugin/WebFeedGatewayPlugin/rss2` | OJS gateway; verify in Step 10 |
| Journal of the Medical Library Association | `plos` | `https://jmla.pitt.edu/ojs/jmla/gateway/plugin/WebFeedGatewayPlugin/rss2` | OJS gateway; verify in Step 10 |

### LIS research core
| Journal | Publisher key | Feed | Notes |
|---|---|---|---|
| JASIST | `wiley` | `https://onlinelibrary.wiley.com/feed/23301643/most-recent` | Wiley eISSN pattern; FlareSolverr |
| Library & Information Science Research | `elsevier_general` | `https://rss.sciencedirect.com/publication/science/07408188` | |
| Journal of Documentation | `openalex` | ISSN `0022-0418` | Emerald — no RSS |
| Journal of Librarianship & Information Science | `sage` | `https://journals.sagepub.com/action/showFeed?ui-bandeau-element=journalFeed&type=etoc&feed=rss&jc=lis` | FlareSolverr |
| Journal of Information Science | `sage` | same pattern, `jc=jis` | FlareSolverr |
| IFLA Journal | `sage` | same pattern, `jc=ifl` | OA, international practitioner |

### Cataloging, metadata, scholarly communication, technology
| Journal | Publisher key | Feed | Notes |
|---|---|---|---|
| Cataloging & Classification Quarterly | `tandfonline` | `https://www.tandfonline.com/feed/rss/wccq20` | FlareSolverr |
| Journal of Librarianship & Scholarly Communication | `openalex` | ISSN `2162-3309` | OA; platform feed unclear → ISSN path |
| Code4Lib Journal | `plos` | `https://journal.code4lib.org/feed` | WordPress feed (Quantum precedent) |
| In the Library with the Lead Pipe | `plos` | `https://www.inthelibrarywiththeleadpipe.org/feed/` | OA practitioner journal |
| Reference Services Review | `openalex` | ISSN `0090-7324` | Emerald |
| Library Hi Tech | `openalex` | ISSN `0737-8831` | Emerald |

### Archival studies
| Journal | Publisher key | Feed | Notes |
|---|---|---|---|
| American Archivist | `openalex` | ISSN `0360-9081` | Allen Press platform, no RSS found |
| Archival Science | `springer` | `https://link.springer.com/search.rss?facet-journal-id=10502&query=*&content-type=Article` | Springer search-RSS pattern |
| Archivaria | `plos` | `https://archivaria.ca/index.php/archivaria/gateway/plugin/WebFeedGatewayPlugin/rss2` | OJS gateway; verify in Step 10, fallback `openalex` ISSN `0318-6954` |
| Archives and Records | `tandfonline` | `https://www.tandfonline.com/feed/rss/cjsa20` | FlareSolverr |

All `tag_filter: null` (every journal is field-specific; no Nature/Science-style general journals in this field). All OpenAlex ISSNs and unverified feed URLs get checked in the verification run; any that fail get diagnosed and switched (RSS→openalex or corrected code).

## Dropped journals (Step 9b — mandatory table)

| Journal | Publisher | Reason dropped |
|---|---|---|
| Information Processing & Management | Elsevier | Out of scope — technical IR/data science for CS researchers, not librarians |
| Scientometrics | Springer | Out of scope — researcher-oriented bibliometrics; high volume would crowd triage |
| Knowledge Organization | Ergon/Nomos | No RSS, no reliable OpenAlex coverage found; paywalled platform |
| Library Management | Emerald | Low value-add — overlaps Emerald cluster already included (JDoc, RSR, LHT) |
| Digital Library Perspectives | Emerald | Same — overlap with Library Hi Tech |
| The Serials Librarian / Serials Review | T&F | Low volume, niche; CCQ + scholarly-comm coverage handles the territory |
| College & Research Libraries News | ACRL | News/announcements organ, not research/practice articles |
| Information Research | (OA) | Platform migration in progress (informationr.net → new host); irregular metadata — revisit later via openalex `1368-1613` |
| Journal of eScience Librarianship | (OA) | Very low volume, narrow niche |
| Archives and Manuscripts | (was T&F) | Left T&F for open platform in 2022; feed/metadata unstable — revisit via openalex `0157-6895` |
| D-Lib Magazine | CNRI | Ceased publication 2017 |

**Blocked-publisher note:** none of the included journals is *newly* blocked — the Cloudflare-walled ones (T&F ×2, SAGE ×3, Wiley ×1, Chicago ×1) all go through the existing FlareSolverr path. Licensing caveat (see `docs/Licensing Audit.md`): Elsevier/Wiley/T&F/SAGE prohibit AI-input use without license — same standing exposure as the existing econ/gender/edu fields, no new category of risk.

## fields.json entry (Step 9) — to be added

```json
"library-science": {
  "arxiv_categories": ["cs.DL"],
  "description": "Library and information science, academic librarianship, and archival studies",
  "journals": [ ...the 22 entries above, tag_filter null... ],
  "tree_path": ["Social Sciences", "Library & Information Science", "Librarianship & Archives", "Library Science & Archival Studies"]
}
```

## Implementation steps

1. Resolve Library Trends' MUSE jid (browse muse.jhu.edu search / journal listing).
2. Add the `library-science` entry to `fields.json` (only file that changes — **no new scrapers needed**).
3. Verification (Step 10, local — no watermark advance, no server interaction):
   ```bash
   python fetch_journals.py --fields library-science --since 2026-07-14 --no-advance-watermark --output debugging/scraped_library_science.json
   ```
   Then analyze: papers per journal, abstract quality (full/truncated/missing). Diagnose any 0-paper source: bad feed URL → fix; OJS gateway 404 → switch to openalex ISSN; low-frequency journal (many LIS quarterlies publish in bursts) → widen `--since` to ~60 days before concluding failure.
4. Report verification results and get user confirmation.

## Deployment checklist (after user confirms verification)

1. `scp fields.json root@116.203.255.222:/opt/arxiv-grader/`
2. Add `ANTHROPIC_API_KEY_LIBRARY_SCIENCE=sk-ant-...` to server root `.env` (user provides key)
3. Onboard first user: `python create_profile.py --user-dir users/<name>` (categories: `cs.DL`, field: `library-science`)
4. Vault: update `docs/Home.md` + `docs/Journal Scrapers.md` publisher-counts table; note the field plan in `docs/`.

## Expected volume & cost

LIS journals are mostly quarterlies/biannuals — expect ~5–20 journal papers/day across all 22 sources plus 0–5 cs.DL arXiv papers, well under triage caps. Cost: standard ~$0.02–0.05/user/day; OpenAlex path adds no API cost.
