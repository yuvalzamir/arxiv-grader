# SSRN Access

Investigation 2026-09-17 (re-examination of the parked `feature/ssrn-integration` branch, 2026-04-30). Verdict: **discovery is now solved** via an undocumented JSON API; **abstracts remain the hard part** (FlareSolverr required); **licensing exposure is Elsevier-class** (user accepted 2026-09-17).

**Status: DEPLOYED 2026-09-17** in `fetch_preprints.py` (`fetch_ssrn_preprints`), not the old branch — see [[Preprint Sources]] for the operational details (config schema, watermark format, enabled fields, shared-source cache). All server-side verification passed same day: listing via FlareSolverr XML fallback, session-based abstract scraping (43–45/46 on WGSRN test runs), prefetch cache consumed by the fetch path in seconds. Prefetch cron (Sun–Thu 22:30 ET) installed and cache warmed for all six networks. Remaining: confirm SSRN lines in the first production daily log (2026-09-18), then routine.

## History

- 2026-04-30: branch `feature/ssrn-integration` parked — `papers.ssrn.com` returned 403/Cloudflare from both Hetzner and ICFO. Discovery approach then was JEL-code HTML pages (`JELJOUR_Results.cfm`), now fully Cloudflare-walled. Branch contains a working page-scraper (`scrapers/ssrn.py`: `citation_abstract` meta tag + `div.abstract-text` + OpenAlex fallback), `test_ssrn_access.py`, `platform` field plumbing, prompt updates.
- 2026-06-11: [[Journal Scrapers|FlareSolverr]] deployed for Tandfonline/SAGE/Wiley/Chicago — the original blocker class is now routinely bypassed for other publishers.

## Discovery — unauthenticated JSON API (verified working 2026-09-17, local IP)

```
GET https://api.ssrn.com/content/v1/bindings/{binding_id}/papers?index=0&count=100&sort=0
```

- **No auth**; plain `requests` with a browser User-Agent works **from residential IPs only** — from the Hetzner datacenter IP Cloudflare returns a plain 403 (confirmed 2026-09-17 on the server). `fetch_preprints.py` therefore tries direct first and falls back to routing the listing through FlareSolverr (`_flaresolverr_get_json`, unwraps Chrome's `<pre>` JSON wrapper) — 1–3 extra solves per network per day.
- Returns newest-first JSON: `title`, `authors` (structured), `id` (abstract_id), `approved_date` ("17 Sep 2026" format), `url`, `page_count`, `downloads`, `publication_status`. **No abstract field.**
- `total` + `index`/`count` pagination.
- Per-paper endpoint (`/content/v1/papers/{id}`) and `/topics`, `/networks` return 401 — listing is the only open route.

### Binding ids

Binding id = SSRN research-network id. Found on each network landing page (`www.ssrn.com/index.cfm/en/<slug>/` — reachable via plain curl) in the `data-url` attribute of `<div id="network-papers">`. Verified ids:

| Network | slug | binding id | total papers | daily volume (Sep 2026) |
|---|---|---|---|---|
| Education (EduRN) | `edurn` | 3118597 | 62k | ~25–40/day |
| Women & Gender Studies (WGSRN) | `wgsrn` | 948113 | 42k | ~10–20/day |
| Political Science (PSN) | `psn` | 998398 | 356k | ~30–70/day |
| Economics (ERN) | `ern` | 205 | 717k | high |
| Law (LSN) | `lsn` | 201 | 431k | ~90/day (measured 2026-09-17; superseded 2026-09-18 by per-eJournal bindings for `international-law` and `tech-law`) |
| Financial Economics (FEN) | — | 203 | 277k | high |
| Accounting (ARN) | — | 204 | 60k | — |

- **CORRECTION 2026-09-18: eJournal-level ids DO work as bindings** — the 2026-09-17 test hit a dead legacy EduRN id (Pedagogy 312293) and over-generalized. All 26 LSN eJournal ids tested on 2026-09-18 return live papers via the same bindings API, including old ids (Cyberspace Law, id 225). Both law fields now use targeted eJournal bindings instead of whole-LSN (201): `international-law` 9 eJournals (~9 unique papers/day vs ~90), `tech-law` 6 eJournals (~29/day). Ids and weekly volumes in [[Preprint Sources]].
- eJournal ids are discovered via `www.ssrn.com/rest/rn/subject-areas/{subject_area_id}` (no auth) — note the id is NOT the binding id: it's in the `data-url` of the network landing page (LSN → 267308). Each listed eJournal's `journal_id` **is** usable as a binding id.
- Watermarking: `approved_date` fits the existing date-watermark pattern ([[Preprint Sources]], bioRxiv-style); the numeric `id` is a usable tiebreaker.

## Abstracts — the open problem

Checked empirically 2026-09-17:

- **Listing API**: no abstract.
- **Crossref** (SSRN DOI = `10.2139/ssrn.{id}`): no abstracts deposited.
- **OpenAlex**: 8/8 sampled recent SSRN works have `abstract_inverted_index: null`; 3/8 not indexed at all. Not a viable channel (unlike for [[Abstract Enrichment]] publishers).
- **Paper pages** (`papers.ssrn.com/sol3/papers.cfm?abstract_id=`): Cloudflare-walled → would go through **FlareSolverr**, like T&F/SAGE. The parked `scrapers/ssrn.py` parser applies unchanged. Unverified from the server — needs a one-off test.
- Cost of scraping: at network volumes (~10–70/day/field) FlareSolverr can fetch every paper's abstract pre-triage, same pattern as Tandfonline. Alternatively titles-only triage → scrape abstracts only for survivors (cheaper, some triage quality loss).

## Licensing

SSRN is Elsevier. Per [[Licensing Audit]], Elsevier T&C prohibit AI-input use without a license, with no abstract/metadata carve-out — same exposure class as the existing Tandfonline/SAGE/Wiley use, compounded by FlareSolverr circumvention. The safer-channel workaround (S2/OpenAlex/CORE abstracts) is **not available** here since none of them carry SSRN abstracts. A decision to add SSRN accepts Elsevier-class exposure for the abstract scrapes; the api.ssrn.com metadata listing itself is lower-exposure (metadata only).

**Server-side verification PASSED 2026-09-17:** FlareSolverr on the Hetzner box solves the SSRN paper-page challenge (13.8 s cold solve, `citation_abstract` present). Three lessons from server testing, all handled in `fetch_preprints.py`:
1. **Listing API 403s from the datacenter IP** → falls back to FlareSolverr, where Chrome's Accept header makes the API return **XML** (Chrome xml-viewer wrapper, HTML named entities like `&eacute;` that break ElementTree) — `_flaresolverr_get_json` unwraps and neutralizes entities.
2. **Sessionless scraping triggers Cloudflare escalation**: ~15 back-to-back challenge solves (~20 s each), then hard timeouts. Fix: one FlareSolverr **session** per run (`sessions.create`) so cf_clearance is reused, 1.5 s pacing, 45 s cool-down + one retry pass for failures, abort after 3 consecutive failures per pass.
3. Successful page fetches are silent → progress line every 10 pages so the daily log doesn't look hung.

Expected steady-state: ~2–5 s per paper with a session → ~5–15 min of serialized scraping per day across the three networks, before journal scraping starts (preprint scrape runs first; no FlareSolverr contention).

## Server-side verification commands (for reference)

```bash
# 1. Is api.ssrn.com reachable from the Hetzner IP?
curl -s -m 20 -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36" \
  "https://api.ssrn.com/content/v1/bindings/3118597/papers?index=0&count=3&sort=0" | head -c 400

# 2. Can FlareSolverr fetch an SSRN abstract page?
curl -s -X POST http://127.0.0.1:8191/v1 -H "Content-Type: application/json" \
  -d '{"cmd":"request.get","url":"https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5220598","maxTimeout":60000}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['status'], d.get('solution',{}).get('status')); print('citation_abstract' in d.get('solution',{}).get('response',''))"
```

If both pass: deploy the 2026-09-17 implementation (see [[Preprint Sources]]):

```bash
scp fetch_preprints.py run_pipeline.py build_digest_pdf.py run_all_users.py fields.json \
    root@116.203.255.222:/opt/arxiv-grader/
scp prompts/triage.txt prompts/scoring_insights.txt root@116.203.255.222:/opt/arxiv-grader/prompts/
```

Notes for the first run after deploy:
- The triage prompt changed → one-time shared-cache rewrite for every field (small cost bump that day).
- First SSRN run is bounded to a 2-day lookback; expect `SSRN EduRN: N new papers` lines and a burst of FlareSolverr page fetches (~1–10 min per network, serialized).
- If `api.ssrn.com` turns out to be blocked from the Hetzner IP, the fetch degrades gracefully (`SSRN <net>: listing fetch failed` warning, no papers) — the pipeline is unaffected otherwise.
