# How to add a new field

A "field" is a scientific discipline that groups one or more arXiv categories with a set of journals. All users in a field share the same arXiv fetch, journal scrape, and triage cache.

---

## Step 1 — Add the field to `fields.json`

Open `fields.json` and add a new top-level entry:

```json
{
  "cond-mat": { ... },

  "quant-ph": {
    "arxiv_categories": ["quant-ph"],
    "description": "Quantum physics and quantum information",
    "journals": [
      {
        "name": "PRL",
        "url": "https://feeds.aps.org/rss/tocsec/PRL-QuantumInformationetc.xml",
        "publisher": "aps",
        "tag_filter": null
      },
      {
        "name": "Nature",
        "url": "https://www.nature.com/nature.rss",
        "publisher": "nature",
        "tag_filter": ["quantum", "quantum computing", "quantum information"]
      },
      {
        "name": "PRXQuantum",
        "url": "http://feeds.aps.org/rss/recent/prxquantum.xml",
        "publisher": "aps",
        "tag_filter": null
      }
    ]
  }
}
```

**Required: `tree_path`**

Every field entry must include a `tree_path` array — a 4-level hierarchy used by the website's field selector tree browser. Without it, the field will be silently skipped in the UI.

```json
"tree_path": ["Natural Sciences", "Physics", "Condensed Matter", "Quantum Sensing"]
```

Level structure: `[domain, discipline, subfield_group, field_display_name]`

Existing tree paths for reference:
- `["Natural Sciences", "Physics", "Condensed Matter", "Condensed Matter"]`
- `["Natural Sciences", "Physics", "Condensed Matter", "Condensed Matter & Optics"]`
- `["Natural Sciences", "Physics", "Condensed Matter", "Quantum Sensing"]`
- `["Natural Sciences", "Physics", "Condensed Matter", "Soft Matter"]`
- `["Natural Sciences", "Physics", "Optics & Photonics", "Optics"]`
- `["Natural Sciences", "Physics", "Astrophysics & Cosmology", "Astrophysics"]`
- `["Natural Sciences", "Physics", "High Energy Physics", "High Energy Physics"]`
- `["Natural Sciences", "Physics", "Classical Physics", "Fluid Dynamics"]`
- `["Natural Sciences", "Biology", "Computational Biology", "Systems Biology"]`
- `["Natural Sciences", "Computer Science", "AI", "Vision"]`

**Key decisions:**

- `arxiv_categories`: list of arXiv category strings (e.g. `["quant-ph"]`, `["cond-mat", "physics.optics"]`). Papers are fetched for each category separately and deduplicated by `arxiv_id` before triage.
- `publisher`: must be one of `aps`, `nature`, `science`, `acs`, `wiley` — selects the scraper class in `scrapers/`.
- `tag_filter`:
  - `null` — field-specific journal; keep all papers from it.
  - `["term1", "term2"]` — general journal (e.g. Nature, Science); keep only papers whose `subject_tags` contain at least one case-insensitive substring match. Check the RSS feed's subject tag vocabulary to choose the right terms.
  - Note: `acs` and `wiley` scrapers return no subject tags, so `tag_filter` has no effect for them — always use `null`.

**Finding RSS feed URLs:**
- APS: `https://feeds.aps.org/rss/recent/<journal>.xml` (e.g. `prl.xml`, `prb.xml`, `prx.xml`, `prxquantum.xml`). For section-specific PRL feeds, browse `feeds.aps.org`.
- Nature journals: `https://www.nature.com/<shortname>.rss` (e.g. `nphys.rss`, `nmat.rss`, `nphoton.rss`).
- Science: `https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science`
- ACS journals: `https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=<code>` (e.g. `ancac3` for ACS Nano, `apchd5` for ACS Photonics, `nalefd` for Nano Letters).
- Wiley journals: `https://advanced.onlinelibrary.wiley.com/feed/<issn>/most-recent` or `https://onlinelibrary.wiley.com/feed/<issn>/most-recent` (use the journal's electronic ISSN, digits only).

**Publisher notes:**
- `aps`: truncated abstract from RSS (APS pages Cloudflare-blocked; Semantic Scholar has no APS abstracts).
- `nature`: full abstract scraped from article page + subject tags for `tag_filter`.
- `science`: full abstract from Semantic Scholar API (~50% hit rate); falls back to RSS summary.
- `acs`: no abstract available (ACS pages Cloudflare-blocked; no free API has ACS abstracts). Triage uses title + authors only.
- `wiley`: full abstract from RSS feed — no HTTP requests to article pages needed.

---

## Step 2 — Add a triage API key to root `.env`

Triage uses a shared Anthropic API key per field (so the paper list can be cached across all users in the field). Add to the root `.env`:

```
ANTHROPIC_API_KEY_QUANT_PH=sk-ant-...
```

The key name is `ANTHROPIC_API_KEY_` + the field name uppercased with hyphens replaced by underscores:
- `cond-mat` → `ANTHROPIC_API_KEY_COND_MAT`
- `quant-ph` → `ANTHROPIC_API_KEY_QUANT_PH`
- `quantum-sensing` → `ANTHROPIC_API_KEY_QUANTUM_SENSING`
- `hep-th` → `ANTHROPIC_API_KEY_HEP_TH`

---

## Step 3 — Onboard a user in the new field

Run the interactive onboarding script:

```bash
python create_profile.py --user-dir users/<name>
```

During onboarding, when prompted for arXiv categories, enter the new field's categories (e.g. `quant-ph`, or `cond-mat, physics.optics` for a multi-category field). The script saves `taste_profile.json` with `"field": "<field-name>"` — this is what `run_all_users.py` uses to group users by field.

---

## Step 4 — Deploy

SCP the updated files to the server:

```bash
scp fields.json root@116.203.255.222:/opt/arxiv-grader/
# If new publisher scrapers were added:
scp scrapers/*.py root@116.203.255.222:/opt/arxiv-grader/scrapers/
```

Also update the root `.env` on the server with the new API key. The new field will be picked up automatically on the next cron run.

---

## Notes

- If the new arXiv category has very few daily submissions (niche field), the pipeline skips that field on empty days without affecting other fields.
- If all fields are empty simultaneously (arXiv holiday), the pipeline exits before the journal scraper runs — journal watermarks are not advanced.
- New journal URLs not yet in `journal_watermarks.json` default to a 2-day lookback on first run; the watermark is then set automatically.
- To test the new field without email: `python run_all_users.py --user <name> --no-email`
- To test triage only: `python run_all_users.py --user <name> --triage-only`
