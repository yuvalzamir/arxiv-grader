# Abstract Enrichment

[[Home]] | [[Journal Scrapers]] | [[AI Pipeline]]

---

## Why Abstracts Matter

Both triage and scoring agents receive the abstract to make their judgments. A missing or truncated abstract degrades quality significantly. For ACS (Cloudflare-blocked), papers go to triage with title + authors only — then abstracts are back-filled via S2 before scoring.

---

## Per-Publisher Abstract Chain

### APS (PRL, PRB, PRX, PRXQuantum, PRMaterials)

Primary: **`harvest.aps.org` Harvest API**
```
GET https://harvest.aps.org/v2/journals/articles/{doi}
```
No authentication required. Returns full structured abstract. High coverage for all APS journals.

Fallback: RSS `<summary>` (often truncated).

---

### Nature Family (Nature, Nature Physics, Nature Materials, etc.)

Primary: **Article page scrape**
- URL from RSS `<link>`
- Extract from `div#Abs1-content p`
- Also scrapes `<meta name="dc.subject">` for subject tags (used by `tag_filter`)
- Authors from `<meta name="citation_author">` (Nature RSS has no author field)

Editorial filtering: drops DOIs starting with `d41586` (news/views/editorials).

---

### Science / Science Advances / Science Immunology

Primary: **OpenAlex by DOI**
```
GET https://api.openalex.org/works/doi:{doi}
```

Secondary: **Semantic Scholar (S2) batch API**
```
POST https://api.semanticscholar.org/graph/v1/paper/batch
```

Fallback: RSS `<summary>`.

---

### ACS (ACS Nano, ACS Photonics, ACS Sensors, Nano Letters)

**Primary source is unavailable** — ACS article pages are Cloudflare-blocked. No free API provides ACS abstracts.

Instead:
1. **Triage runs on title + authors only** (no abstract)
2. **Post-triage S2 batch enrichment** fills ~50% of abstracts before scoring

The S2 batch call submits all filtered paper DOIs at once:
```
POST https://api.semanticscholar.org/graph/v1/paper/batch
Body: {"ids": ["DOI:10.1021/...", ...], "fields": "title,abstract"}
```

---

### Wiley, IOP, OUP, Elsevier, Springer, Cambridge, Royal Society, AIP

**Full abstract in RSS feed** — no additional HTTP requests needed.

---

### Optica (Optica, Optics Letters, Optics Express)

Primary: RSS metadata for title/authors/DOI
Abstract: **OpenAlex API by DOI** (high hit rate for Optica journals as they are open-access-friendly)

---

### SciPost

All SciPost papers are open access.

Primary: **OpenAlex by DOI**

---

### SAGE Publications

Primary: **OpenAlex by DOI**
Fallback: **CORE API**
```
GET https://api.core.ac.uk/v3/works/doi:{doi}
Authorization: {CORE_API_KEY}
```
CORE API key: `HyQYgNwRSCc0Mtix1Xv7rJof9lpmOAkF` (1,000 req/day).

---

### Taylor & Francis (Tandfonline)

Primary: **OpenAlex by DOI**
Secondary: **CORE API** (same as SAGE)
Tertiary: S2 batch (for some journals)

---

### Project MUSE

MUSE article pages are CAPTCHA-blocked.

1. **S2 title search**: `GET https://api.semanticscholar.org/graph/v1/paper/search?query={title}`
2. **OpenAlex title search**: `GET https://api.openalex.org/works?search={title}`

Combined hit rate: ~68%.

---

### Google Scholar (Onboarding Only)

`scrapers/scholar.py` is used during user onboarding (`process_pending.py`) to import seed papers from a Scholar profile URL:

1. Fetch Scholar profile page → list of paper titles + Scholar detail URLs
2. Follow each Scholar detail page → get publisher URL
3. Fetch abstract via citation meta tags from publisher page
4. Fallback to **OpenAlex title search** for Cloudflare-blocked publishers (APS, ACS)

Papers without resolvable abstracts are still included for author-frequency signal.

---

## Abstract Quality Flags

When a paper reaches triage/scoring with a degraded abstract, it is tagged:
```json
"abstract_quality": "truncated" | "missing"
```

- `truncated` — abstract is present but cut off (e.g. RSS snippet)
- `missing` — no abstract retrieved

These papers are excluded from the [[Paper Insights]] feature (insights require a full abstract of ≥100 characters).

---

## Retry Bank

`retry_abstracts.py` implements a persistent retry bank for papers that failed abstract retrieval. On each run, papers with missing/truncated abstracts are added to the bank. After `ABSTRACT_RETRY_TTL_DAYS = 21` days without a successful fetch, they are evicted.

The retry bank prevents hammering publishers on every run for papers that will never resolve.

---

## S2 Batch Enrichment Flow

After triage (for ACS papers), before scoring:

```python
# Collect DOIs of ACS papers that survived triage
dois = [p["arxiv_id"] for p in filtered if p.get("source") in ACS_JOURNALS]

# Batch request to S2
response = s2_batch(dois, fields=["title", "abstract"])

# Merge abstracts back into filtered papers
for paper in filtered:
    if paper["arxiv_id"] in s2_results:
        paper["abstract"] = s2_results[paper["arxiv_id"]]["abstract"]
```
