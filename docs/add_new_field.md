# How to add a new field

A "field" is a scientific discipline that groups one arXiv category with a set of journals. All users in a field share the same arXiv fetch, journal scrape, and triage cache.

---

## Step 1 — Add the field to `fields.json`

Open `fields.json` and add a new top-level entry:

```json
{
  "cond-mat": { ... },

  "quant-ph": {
    "arxiv_category": "quant-ph",
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

**Key decisions:**

- `arxiv_category`: the arXiv category string passed to `fetch_papers.py -c` (e.g. `quant-ph`, `hep-th`, `astro-ph`).
- `publisher`: must be one of `aps`, `nature`, `science` — this selects the scraper class in `scrapers/`.
- `tag_filter`:
  - `null` — field-specific journal; keep all papers from it.
  - `["term1", "term2"]` — general journal (e.g. Nature, Science); keep only papers whose `subject_tags` contain at least one case-insensitive substring match. Check the RSS feed's subject tag vocabulary to choose the right terms.

**Finding RSS feed URLs:**
- APS: `https://feeds.aps.org/rss/recent/<journal>.xml` (e.g. `prl.xml`, `prb.xml`, `prx.xml`, `prxquantum.xml`). For section-specific PRL feeds, browse `feeds.aps.org`.
- Nature journals: `https://www.nature.com/<shortname>.rss` (e.g. `nphys.rss`, `nmat.rss`).
- Science: `https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science`

---

## Step 2 — Add a triage API key to root `.env`

Triage uses a shared Anthropic API key per field (so the paper list can be cached across all users in the field). Add to the root `.env`:

```
ANTHROPIC_API_KEY_QUANT_PH=sk-ant-...
```

The key name is `ANTHROPIC_API_KEY_` + the field name uppercased with hyphens replaced by underscores:
- `cond-mat` → `ANTHROPIC_API_KEY_COND_MAT`
- `quant-ph` → `ANTHROPIC_API_KEY_QUANT_PH`
- `hep-th` → `ANTHROPIC_API_KEY_HEP_TH`

---

## Step 3 — Onboard a user in the new field

Run the interactive onboarding script:

```bash
python create_profile.py --user-dir users/<name>
```

During onboarding, when prompted for arXiv categories, enter the new field's category (e.g. `quant-ph`). The script saves `taste_profile.json` with `"field": "quant-ph"` — this is what `run_all_users.py` uses to group users by field.

---

## Step 4 — Deploy

SCP the updated files to the server:

```bash
scp fields.json root@116.203.255.222:/opt/arxiv-grader/
```

Also update the root `.env` on the server with the new API key. The new field will be picked up automatically on the next cron run.

---

## Notes

- If the new arXiv category has very few daily submissions (niche field), the pipeline skips that field on empty days without affecting other fields.
- If all fields are empty simultaneously (arXiv holiday), the pipeline exits before the journal scraper runs — journal watermarks are not advanced.
- To test the new field without email: `python run_all_users.py --user <name> --no-email`
- To test triage only: `python run_all_users.py --user <name> --triage-only`
