# New Field Skill

## Description
Use this skill whenever the user asks to add a new scientific field to the Incoming Science digest system. Trigger on phrases like "add a new field", "create a field for X", "I want to add Y as a field".

## Instructions

When this skill is invoked, enter plan mode and produce a structured plan before touching any files. Follow these steps exactly.

---

### Step 1 — Read the reference doc

Read `docs/add_new_field.md` in full before doing anything else. It contains the authoritative rules for fields.json structure, known RSS URL patterns, publisher notes, and deployment steps. Do not rely on memory alone.

---

### Step 2 — Identify arXiv categories

Search for the correct arXiv category codes for the field (e.g. `quant-ph`, `cond-mat.mes-hall`, `cs.CV`). List them. These go into `arxiv_categories` in fields.json.

---

### Step 3 — Identify leading journals

Perform web searches to find:
1. **General high-impact journals** that publish in this field (Nature, Science, PNAS, etc.) — these are broad journals that need `tag_filter`.
2. **Field-specific flagship journals** (e.g. PRXQuantum for quantum information, Physical Review B for condensed matter) — these get `tag_filter: null`.

For each journal found, note:
- Full journal name and publisher
- Whether it is field-specific or general

---

### Step 4 — Find RSS feeds (prefer sub-feeds)

For every journal identified, search for its RSS feed URL. Apply these known patterns first before searching:

- **APS** (PRL, PRB, PRX, PRXQuantum, PRD, PRE, PRA, PRMaterials): `https://feeds.aps.org/rss/recent/<journal>.xml`
  - PRL has **section-specific sub-feeds** — always prefer them over the full PRL feed. Browse `feeds.aps.org` or search "PRL RSS section feeds" to find the right section URL for this field.
  - PRA also has section sub-feeds (e.g. `PRA-Quantuminformation.xml`).
- **Nature portfolio** (Nature, NatPhys, NatComms, NatMat, NatNano, NatPhoton, npjQI, etc.): `https://www.nature.com/<shortname>.rss`
  - NatComms has **subject-specific sub-feeds** — always prefer them. Pattern: `https://www.nature.com/subjects/<subject>/ncomms.rss`. Search for relevant subjects (e.g. physics, optics-and-photonics, nanoscience-and-technology, mathematics-and-computing, astronomy-and-astrophysics, etc.).
  - Nature itself also has subject sub-feeds: `https://www.nature.com/subjects/<subject>/nature.rss`.
- **Science / ScienceAdvances**: `https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science` / `jc=sciadv`
- **ACS**: `https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=<code>`
- **Wiley**: `https://onlinelibrary.wiley.com/feed/<issn>/most-recent`
- **IOP** (ApJ, JCAP, QST, etc.): `https://iopscience.iop.org/journal/rss/<issn>`
- **Springer**: `https://link.springer.com/search.rss?facet-journal-id=<id>`

For any journal not covered by the above: search `"<journal name>" RSS feed` to find the URL.

If a journal has no RSS feed at all, note it and handle it in Step 6.

---

### Step 5 — Match journals to existing scrapers

For each journal with an RSS feed, check the `scrapers/` directory to determine which scraper to use. The existing publishers and their scrapers are:

| publisher key | scraper file | abstract source |
|---|---|---|
| `aps` | `scrapers/aps.py` | Truncated RSS (Cloudflare blocks page fetch) |
| `nature` | `scrapers/nature.py` | Full — fetches article page, extracts `dc.subject` tags |
| `science` | `scrapers/science.py` | Semantic Scholar → OpenAlex → RSS fallback |
| `acs` | `scrapers/acs.py` | Europe PMC → OpenAlex → empty (ACS blocks scrapers) |
| `wiley` | `scrapers/wiley.py` | Full abstract in RSS `dc:description` |
| `optica` | `scrapers/optica.py` | OpenAlex → RSS fallback |
| `iop` | `scrapers/iop.py` | Full abstract in RSS feed |
| `pnas` | `scrapers/pnas.py` | Semantic Scholar → empty |
| `cell` | `scrapers/cell.py` | Page fetch |
| `plos` | `scrapers/plos.py` | RSS |
| `edp` | `scrapers/edp.py` | Page fetch → OpenAlex fallback |
| `oup` | `scrapers/oup.py` | OpenAlex → RSS fallback |
| `elsevier` | `scrapers/elsevier.py` | CrossRef → INSPIRE-HEP → OpenAlex (HEP-specific) |
| `elsevier_general` | `scrapers/elsevier.py` | CrossRef → OpenAlex |
| `scipost` | `scrapers/scipost.py` | OpenAlex via DOI |
| `ieee` | `scrapers/ieee.py` | Two feed types: abstract in RSS (TIP) or OpenAlex via DOI (TPAMI) |
| `springer` | `scrapers/springer.py` | OpenAlex primary → RSS fallback |
| `acm` | `scrapers/acm.py` | Inherits springer, overrides DOI extraction |
| `cambridge` | `scrapers/cambridge.py` | OpenAlex → RSS fallback (must pass custom User-Agent) |
| `openalex` | (inline) | `scrape_journal_openalex()` in fetch_journals.py — for journals with no RSS |

**Important check:** Even if a publisher is known, read the relevant scraper to verify the RSS structure matches. Journals from the same publisher can have different feed formats. If the existing scraper won't work for this specific journal (different HTML structure, different abstract location, different feed format), note that a new scraper or subclass is needed.

---

### Step 6 — Plan new scrapers (if needed)

For any journal that needs a new or modified scraper, plan it following these rules:

1. **Inherit from `BaseScraper`** (or subclass an existing scraper if the logic is mostly shared). No code duplication.
2. **Abstract priority order:**
   a. Extract from RSS feed directly if the abstract is present in the feed (check `<description>`, `<content:encoded>`, `dc:description`, etc.)
   b. Fetch the article page and parse with BeautifulSoup
   c. Try OpenAlex by DOI
   d. Try Semantic Scholar by DOI
   e. Try Europe PMC by DOI
   f. Try any other major academic database (Unpaywall, Crossref, INSPIRE-HEP if HEP field)
3. Show the planned class name, which existing scraper to inherit from, and which methods to override.
4. Read the relevant existing scraper code before drafting any new scraper to ensure consistent patterns.

---

### Step 7 — Handle journals with no RSS (OpenAlex ISSN path)

For journals with no RSS feed, use the OpenAlex ISSN path:

```json
{
  "name": "JournalName",
  "publisher": "openalex",
  "openalex_issn": "XXXX-XXXX",
  "tag_filter": null
}
```

Find the journal's ISSN (print or electronic) via a web search or OpenAlex. This uses `scrape_journal_openalex()` in `fetch_journals.py` which queries OpenAlex by ISSN and date.

---

### Step 8 — Draft the fields.json entry

Produce the complete JSON block for the new field:

```json
"<field-slug>": {
  "arxiv_categories": ["..."],
  "description": "...",
  "journals": [ ... ],
  "tree_path": ["Natural Sciences", "<Discipline>", "<SubfieldGroup>", "<DisplayName>"]
}
```

Rules:
- `tag_filter: null` for field-specific journals; use tag_filter only for general journals (Nature, Science) — but per project policy, Nature and Science themselves always get `tag_filter: null` (triage handles filtering). Tag filters are appropriate for NatComms, NatPhys, ScienceAdvances, PNAS, and similar semi-general journals.
- `tree_path` must be a 4-level array: `[domain, discipline, subfield_group, display_name]`. Check existing tree paths in `docs/add_new_field.md` for the correct grouping.
- Field slug should be lowercase, hyphen-separated (e.g. `quantum-info`, `soft-matter`, `ai-vision`).

---

### Step 8b — Dropped journals table

After drafting the fields.json entry, include a table of **every journal that was considered and dropped** during research. This is mandatory — do not skip it even if the final list looks complete.

For each dropped journal, record:

| Journal | Publisher | Reason dropped |
|---|---|---|
| ... | ... | ... |

Reason categories:
- **Blocked (Cloudflare)** — RSS or page fetch is blocked from the server IP. State this explicitly. The user may want to investigate a workaround (institutional access, API token, alternative mirror).
- **No RSS / No OpenAlex coverage** — could not find a usable feed or ISSN with adequate coverage.
- **Low volume** — journal publishes too infrequently to be worth including.
- **Out of scope** — journal covers adjacent territory not central to the field.
- **Duplicate coverage** — another included journal covers the same papers.
- **Other** — describe briefly.

If a journal was dropped due to a blocker (Cloudflare, IP ban, paywalled API), make that **very clear** so the user can follow up manually.

---

### Step 9 — Verification plan

After all code and config changes are made, include a verification step:

1. Run the journal scraper for the new field over a recent date window:
   ```bash
   python fetch_journals.py --field <field-slug> --since <YYYY-MM-DD> --no-advance-watermark
   ```
   Save output to `debugging/scraped_journals_<field>.json`.

2. Analyze the output: count papers per source, check abstract quality (full / truncated / missing). Every configured journal should appear in the output with at least some papers (given a wide enough date window — use at least 7 days).

3. If any source has 0 papers, diagnose: check if the RSS URL is reachable, if the watermark is too recent, or if the scraper is failing silently.

4. Report findings to the user and ask for confirmation before proceeding to deployment.

---

### Step 10 — Deployment checklist

Present the user with the full deployment checklist:

1. `scp fields.json root@116.203.255.222:/opt/arxiv-grader/`
2. If new scrapers were written: `scp scrapers/*.py root@116.203.255.222:/opt/arxiv-grader/scrapers/`
3. Add `ANTHROPIC_API_KEY_<FIELD_SLUG_UPPER>` to the server root `.env`
4. Onboard first user: `python create_profile.py --user-dir users/<name>`

---

## Plan mode behavior

When this skill runs:
1. Call `EnterPlanMode` immediately.
2. Work through Steps 1–8 (research + planning), producing a concrete proposed fields.json entry and scraper plan.
3. Present the full plan to the user for approval before making any file changes.
4. On approval, exit plan mode and execute: write scrapers, edit fields.json, then run the verification (Step 9).
5. After verification passes, present the deployment checklist (Step 10).
