# Preprint Sources

[[Home]] | [[Pipeline Overview]] | [[Journal Scrapers]] | [[AI Pipeline]]

Code: `fetch_preprints.py`
Config: `fields.json` (`preprints`, `preprint_categories`, and `ssrn_networks` keys)
Watermarks: `preprint_watermarks.json`

---

## Shared-source fetch cache (2026-09-17)

Sources subscribed by multiple fields (NBER/CEPR by three econ/edu fields; EduRN by
`edu-policy` + `econ-education`) are fetched **once per run** and the cached result is
reused for later fields. Before this fix, the watermark advanced during the first
field's fetch, so **every later field silently received zero papers from the shared
source** — confirmed live in the 2026-09-07 log (first field: 33 NBER papers; second
and third: 0). Log line: `NBER: shared source — reusing 34 papers fetched earlier this run.`

---

## Three Types of Preprint Sources

### 1. bioRxiv / medRxiv (date-based watermarking)

Handled by `fetch_bio_preprints()` in `fetch_preprints.py`.

**Configured via `preprint_categories` in `fields.json`:**
```json
"preprint_categories": {
  "biorxiv": ["systems-biology", "bioinformatics", "genetics"],
  "medrxiv": []
}
```
Empty list = skip that server. Absent key = no bio preprints for this field.

**Feed URLs:**
- bioRxiv: `https://connect.biorxiv.org/biorxiv_xml.php?subject={subject}`
- medRxiv: `https://connect.medrxiv.org/medrxiv_xml.php?subject={subject}`

**Watermark key format:** `"{server}:{subject}"` → `"YYYY-MM-DD"` last date seen.
Stored in `preprint_watermarks.json`. Papers with `dc:date > watermark` are new.

**Paper schema:**
```json
{
  "arxiv_id": "10.64898/2026.05.24.727056",
  "title": "...",
  "abstract": "...",
  "authors": ["Smith J", "Jones A B"],
  "subcategories": [],
  "source": "bioRxiv",
  "preprint_date": "2026-05-27"
}
```
- `arxiv_id` holds the DOI — pipeline treats it as an opaque ID
- `source` = `"bioRxiv"` or `"medRxiv"` — used by PDF for the source badge
- `subcategories: []` — no arXiv-style codes; triage matches on keywords/authors/title only
- `preprint_date` is informational, not used by pipeline logic

**Author parsing:** bioRxiv dc:creator format is `"Bankole, K., McIntyre, L. M."`. Split at `, ` before capital+lowercase (last-name boundary). Output: `["Bankole K", "McIntyre LM"]`.

**Deduplication:** Papers from multiple subjects are deduplicated by DOI before writing output. A paper in both `systems-biology` and `bioinformatics` categories appears once.

**Triage routing:** `source ∈ PREPRINT_SOURCES` (`{"bioRxiv", "medRxiv", "SSRN"}`, defined in `fetch_preprints.py`, imported by `run_pipeline.py` and `build_digest_pdf.py`). These papers join the **arXiv triage pool** (not the journal pool), so they are ranked alongside arXiv preprints using the arXiv triage prompt and caps. Since 2026-09-17 they are also correctly presented to scoring as preprints (previously any paper with `source` set got the `source: journal` line) and are grouped under a "Preprints" PDF header instead of "Journals".

**Enabled fields:** `systems-biology` (bioRxiv: systems-biology, bioinformatics, genetics, immunology, physiology, cell-biology).

---

### 2. NBER / CEPR (numeric ID watermarking)

Handled by `fetch_field_preprints()` in `fetch_preprints.py`.

**Configured via `preprints` list in `fields.json`:**
```json
"preprints": [
  {
    "name": "NBER",
    "url": "https://www.nber.org/rss/new_working_papers.xml",
    "id_pattern": "w(\\d+)"
  }
]
```

**Watermark key:** source name (e.g. `"NBER"`) → integer max paper ID seen.
Stored in `preprint_watermarks.json`.

**Paper schema:** Uses `preprint_source` field (not `source`) so these join the arXiv triage pool via the existing split logic.

---

### 3. SSRN research networks (date+ids watermarking) — added 2026-09-17

Handled by `fetch_ssrn_preprints()` in `fetch_preprints.py`. Full investigation: [[SSRN Access]].

**Configured via `ssrn_networks` in `fields.json`:**
```json
"ssrn_networks": [
  {"name": "EduRN", "binding_id": 3118597}
]
```
No per-network cap (removed 2026-09-17 by user decision — triage's forward cap of 10
is the only selection bound). Backstop: the fetch never pages past 300 papers per
network per run (`SSRN_MAX_PAGES`); hitting it logs a loud warning since papers
beyond it are permanently skipped. Only reachable via a wiped watermark or a
multi-week gap, not normal operation.

**Discovery:** unauthenticated `api.ssrn.com/content/v1/bindings/{binding_id}/papers`
listing (newest first, browser User-Agent required, no Cloudflare). **Abstracts:** the
listing has none — each paper page is scraped through FlareSolverr (Cloudflare-walled),
serially, after the listing call; on 3 consecutive FlareSolverr failures the rest keep
`abstract_quality: "missing"` (triaged on title, excluded from insights).

**Watermark key:** `"ssrn:{name}"` → `{"date": "YYYY-MM-DD", "ids": [...]}` — max
approved_date seen plus the ids seen on that date, so same-date papers arriving in a
later run are neither duplicated nor lost. First run bounded to a 2-day lookback
(the bindings listing is unbounded).

**Abstract prefetch (evening cron, added 2026-09-17):** `fetch_preprints.py
--prefetch-ssrn` warms `ssrn_abstract_cache.json` (id → abstract, 7-day retention,
positive results only) for all configured networks, reading watermarks WITHOUT saving
them. SSRN approvals happen through the US-Eastern business day, so a 22:30 ET
prefetch catches essentially everything the 00:30 run lists — the pipeline run then
serves abstracts from the cache (`served from prefetch cache` log line) and scrapes
only late-evening stragglers, cutting ~10 min off the nightly critical path. The
daily run also writes what it scrapes back to the cache. If the prefetch cron ever
fails, the daily run silently scrapes everything itself, exactly as before.
Cron: `30 22 * * 0-4 /opt/arxiv-grader/venv/bin/python /opt/arxiv-grader/fetch_preprints.py --prefetch-ssrn >> /var/log/arxiv-grader/prefetch.log 2>&1`

**Paper schema:** `arxiv_id` = full SSRN paper URL (rating links percent-encode it, same
as NBER), `ssrn_id` numeric, `source: "SSRN"` (→ `[SSRN]` PDF badge, arXiv triage pool),
`subcategories: []`.

**Enabled fields/networks (survey of all humanities/soc-sci fields 2026-09-17, volumes measured then):**

| Field | Network | binding_id | daily volume |
|---|---|---|---|
| econ-political | PSN (Political Science) | 998398 | ~86 (remeasured 2026-09-18) |
| gender-studies | WGSRN (Women & Gender Studies) | 948113 | ~10 |
| comparative-literature, literature-and-culture | LIT (Literature) | 948057 | ~3 |
| music-theory | 3 MRCN eJournals (below) | — | ~1–2 |
| econ-education | 3 EduRN eJournals (below) | — | ~10 |
| edu-policy | 4 EduRN eJournals (below) | — | ~14 |
| library-science | 9 InfoSciRN eJournals (below) | — | ~9 |
| international-law | 9 LSN eJournals (below) | — | ~9/day deduped |
| tech-law | 6 LSN eJournals (below) | — | ~29/day deduped |

LSN was originally on the excluded list (high volume, no matching field); added 2026-09-17
as whole-network binding 201 (~90 papers/day) for `international-law`. **Replaced 2026-09-18
with per-eJournal bindings** (see [[SSRN Access]] correction — eJournal ids work after all):
~10× fewer FlareSolverr abstract scrapes and much cleaner triage input. Cross-posted papers
are deduped per field by `ssrn_id` in `fetch_ssrn_preprints`. The old `ssrn:LSN` watermark
key is orphaned; new keys start with the standard 2-day lookback.

LSN eJournal bindings (weekly unique volumes measured 2026-09-18):
- `international-law`: IntlEconLaw 898503 (20/wk), PILHumanRights 2417761 (9), IntlEnvironmentalLaw 1397291 (9), PILSources 2417756 (8), PILCourtsAdjudication 2417733 (5), PILForeignRelations 2417770 (5), IntlCriminalLaw 951682 (2), IntlEmploymentLaborLaw 887064 (2), PILOrganizations 2417749 (2)
- `tech-law`: AILawPolicyEthics 2874401 (103/wk), AIRoleApplicationsLaw 4860240 (34), CyberspaceLaw 225 (26), CybersecurityDataPrivacy 2704098 (21), InfoPrivacyLaw 1125502 (10), IPCopyrightLaw 1649832 (9)

**2026-09-18: the eJournal maneuver was applied to every SSRN field where the data
supported it.** Per-network 7-day measurements (whole network vs union of its eJournals)
decided each case:

Narrowed (eJournal classification near-complete, network broader than field):
- `music-theory` → MRCN eJournals MusicTheory 1802075 (3/wk), MusicPsychology 1802069 (6), Musicology 1802051 (2). MRCN union == whole network (0 uncategorized); drops off-field Music Education + Compositions.
- `econ-education` → EduRN eJournals ImpactEvaluation 3122965 (36/wk), SociologyOfEducation 3122892 (21), AdminLeadership 3122920 (17). EduRN is 190/wk whole with only 13/wk uncategorized.
- `edu-policy` → same three plus TeacherEducation 3128427 (22/wk). Drops Pedagogy (63/wk), EdTech (32), Psych & Cognition (28), discipline-specific teaching eJournals — all off-field for policy.
- `library-science` → 9 library-focused InfoSciRN eJournals (~63/wk raw, ~9/day unique). Kills the off-field Generative AI (76/wk) + Data Science (47/wk) flood that dominated InfoSciRN (207/wk whole). ~47/wk uncategorized papers are lost — accepted, as the flood suggests they skew data-science too.

Kept whole-network (narrowing would lose coverage):
- `econ-political` / PSN: only 50 of 600/wk network papers appear in ANY of PSN's 6 eJournals (no "Political Economy" grouping exists) — narrowing would discard 92% of the feed.
- `gender-studies` / WGSRN: network scope ≈ field scope; nothing to cut.
- `comparative-literature`, `literature-and-culture` / LIT: 7 of 20/wk papers are in no eJournal (35% loss) and volume is already tiny.

Deliberately excluded: ERN (205) — 100+/day with no matching field; SociologyRN
(3468848, ~20–40/day) as a weak match for `demography` (mostly off-topic volume);
CommRN (3390515, ~10–25/day) is a plausible *second* network for econ-political (media/
communication) — not added, revisit on demand; HistoryRN (3562549, ~8–20/day) likewise
for literature-and-culture. Other surveyed bindings (no matching field): PRN/philosophy
948087, LingRN 3413137, ArtsRN 3501900, CRN/classics 948047, RWRN/rhetoric 948098,
AARN/anthropology 2134420.

---

## Orchestration

`run_all_users.py` calls `run_preprint_scrape()` after arXiv fetch and before journal scraping. It runs for any field that has either `preprints` or `preprint_categories` configured.

If arXiv returns no papers (holiday), preprint fetching is skipped — prevents watermarks from advancing on days when no digest is sent.

**Test command (no watermark advance):**
```bash
python run_all_users.py --user <name> --no-email --no-advance-watermark
```

**Standalone test:**
```bash
python fetch_preprints.py --fields systems-biology --output-dir debugging/preprints_test --no-advance-watermark
```

**Log line to confirm bioRxiv papers flowing:**
```
Field 'systems-biology': X arXiv + Y preprints + Z journal = N total papers.
```

---

## Adding bioRxiv/medRxiv to a New Field

1. Add `preprint_categories` to the field entry in `fields.json`
2. No code changes needed — `run_all_users.py` and `fetch_preprints.py` are field-agnostic

---

## Feed Structure Differences vs arXiv

| Aspect | arXiv | bioRxiv/medRxiv |
|--------|-------|-----------------|
| RSS version | 2.0 | 1.0 (RDF) |
| Announce type | new/replace/cross | None — all items assumed new |
| Paper ID | arXiv ID | DOI (`10.1101/...`) |
| Date field | `pubDate` RFC 2822 | `dc:date` YYYY-MM-DD |
| Subcategories | multiple `<category>` tags | None |
| Abstract | in `<description>` | directly in `<description>` |
| Author format | "First Last (affil)" | "Last, F., Last2, F." |
| Items per feed | varies (100+) | ~30 most recent |
| Posts weekends | No (Fri → Mon gap) | Yes (7 days/week) |
