# Google Scholar profile import — implementation plan

## Goal

Allow new users to provide their Google Scholar profile URL during web onboarding. We extract their publication list, resolve each paper to a publisher URL or DOI, fetch the abstract using our existing scraper infrastructure, and feed the results (up to 60 papers) into the profile creation process.

Entry point: web onboarding only. The interactive `create_profile.py` flow is not being extended.

---

## Step 1 — Scrape the Scholar profile page

Scholar profile pages (`https://scholar.google.com/citations?user=XXXX&sortby=pubdate&pagesize=100`) are lightly protected compared to Scholar search — a browser User-Agent usually works from a server IP.

Parse each paper row (`<tr class="gsc_a_tr">`):
- Title — `<a class="gsc_a_at">`, also carries the relative URL to the Scholar citation detail page
- Authors + journal — `.gsc_a_e`
- Year — `.gsc_a_y`

Randomly sample up to 60 rows from however many are returned (max 100 per page).

**Failure modes:**
- 429 / CAPTCHA / empty response → log warning, raise `ScholarFetchError`, caller skips Scholar papers entirely and proceeds with any other seed papers
- Profile is private / returns 0 rows → same

---

## Step 2 — Resolve each paper to a publisher URL via the Scholar citation page

For each sampled paper, follow the Scholar citation detail URL:
```
https://scholar.google.com/citations?view_op=view_citation&citation_for_view=USERID:PAPERID
```

On that page, extract:
- Publisher link from `<div id="gsc_oci_title">` → the `<a>` href often points to the publisher article page or a DOI redirect (`https://doi.org/...`)
- DOI from a `doi.org` URL if present

This gives us a concrete URL to pass to our existing fetcher.

Add a 1–2 second delay between requests to avoid triggering Scholar rate limits.

**Failure modes:**
- Citation page returns 429 / blocked → include paper with title + authors only (still useful as author signal for the profile creator)
- No publisher link found on the citation page → same fallback

---

## Step 3 — Fetch abstract using existing infrastructure

Pass the resolved URL to **`fetch_journal_paper(url)`** in `create_profile.py`. That function already handles:
- arXiv URLs → arXiv API
- DOI redirects and journal URLs → page fetch with BeautifulSoup

If `fetch_journal_paper` raises an exception or returns no abstract (e.g. APS Cloudflare block, ACS block):
- **Fallback: OpenAlex title search**
  ```
  GET https://api.openalex.org/works?search=<title>&filter=type:article&per_page=3
  ```
  Match best result by normalised title similarity. If matched, reconstruct abstract from `abstract_inverted_index` (same pattern as `scrapers/optica.py`).
- If OpenAlex also misses → include paper with title + authors only.

The fallback is intentionally narrow — we only call OpenAlex when the publisher URL fetch has already failed. Papers without abstracts are still included because author names are a meaningful signal for the profile creator.

---

## Step 4 — New module: `scrapers/scholar.py`

A single public function:

```python
def fetch_scholar_papers(profile_url: str, max_papers: int = 60) -> list[dict]:
    """
    Fetch and resolve papers from a Google Scholar profile.

    Returns a list of paper dicts compatible with the liked_papers format:
      {arxiv_id, title, abstract, authors, url}
    Papers that could not be resolved carry empty abstract but are still included.
    Raises ScholarFetchError if the profile page itself cannot be fetched.
    """
```

Internal helpers (private):
- `_fetch_profile_rows(profile_url)` → list of `{title, authors, year, citation_url}`
- `_resolve_citation_url(citation_url)` → publisher URL or DOI URL, or `None`
- `_reconstruct_openalex_abstract(inverted_index)` → str (copied from optica.py)
- `_openalex_fallback(title)` → abstract str or `None`

The module has no dependency on the rest of the codebase except `fetch_journal_paper` from `create_profile.py` (passed in as a callable to avoid circular imports, or imported directly if structure allows).

---

## Step 5 — `process_pending.py` integration

When processing a web signup, before calling the profile creator:

```python
scholar_url = submission.get("scholar_url", "").strip()
if scholar_url:
    try:
        scholar_papers = fetch_scholar_papers(scholar_url)
        seed_papers = merge_and_deduplicate(seed_papers, scholar_papers)
        log(f"Added {len(scholar_papers)} Scholar papers")
    except ScholarFetchError as e:
        log(f"Scholar fetch failed, continuing without: {e}")
```

Deduplication: by `arxiv_id` where available; by normalised title otherwise.

---

## Step 6 — Website: optional Scholar URL field

On the seed papers screen (`/signup/papers`), add an optional text input below the existing paper URL / Excel section:

```
Google Scholar profile URL (optional)
[ https://scholar.google.com/citations?user=... ]
```

Stored as `scholar_url` in the onboarding JSON that gets POSTed to `/onboarding/submit`. No client-side validation beyond checking the string starts with `scholar.google.com`.

---

## What we are NOT doing

- Not extending the interactive `create_profile.py` CLI flow
- Not using the `scholarly` Python library (fragile, adds proxy dependency)
- Not implementing proxy rotation (Scholar profile pages usually work without it)
- Not fetching full text from publishers — abstract is sufficient

---

## Implementation order

1. `scrapers/scholar.py` — core fetch + resolve logic, testable in isolation
2. `process_pending.py` — wire in `fetch_scholar_papers`, handle `ScholarFetchError`
3. Website seed papers screen — add optional Scholar URL input, store in JSON

---

## Open questions

- What to do if the Scholar profile URL is malformed or points to search results instead of a profile? → Validate that `user=` is present in the URL before fetching; surface a clear error in the onboarding success page or process log.
- Should we cap the per-paper detail fetch to avoid very long processing times? Yes — hard cap of 60 citation-page fetches × ~1.5s delay = ~90 seconds max for the Scholar resolution phase.
