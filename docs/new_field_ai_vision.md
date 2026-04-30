# New Field Plan: AI & Computer Vision (`ai-vision`)

## Field Identity

**Field key:** `ai-vision`
**Description:** AI and computer vision — deep learning, image processing, generative models, representation learning.
**Target users:** Researchers working on computer vision, image processing, generative AI, multimodal models.

---

## arXiv Categories

```json
"arxiv_categories": ["cs.CV", "cs.LG", "eess.IV"]
```

- **cs.CV** — Computer Vision and Pattern Recognition (primary)
- **cs.LG** — Machine Learning (heavy cross-posting; most ICLR/NeurIPS vision papers)
- **eess.IV** — Image and Video Processing (signal processing angle: compression, restoration, super-resolution)

**Expected daily volume:** cs.CV alone runs 150–300 papers/day; cs.LG adds another 100–200. The triage cap (10) will handle this — just like cond-mat Monday feeds. Consider whether to fetch all three or just cs.CV + cs.LG, since eess.IV overlaps heavily.

---

## Journals to Add

### Tier 1 — Must Have

| Journal | Publisher | h5-index | Notes |
|---------|-----------|----------|-------|
| IEEE TPAMI | IEEE (ieeexplore) | 217 | Premier journal; spans CV + ML + robotics |
| IEEE TIP | IEEE (ieeexplore) | 165 | Transactions on Image Processing — most on-target |
| IJCV | Springer | 109 | International Journal of Computer Vision |
| Pattern Recognition | Elsevier | 126 | Solid, high volume |

### Tier 2 — Nice to Have

| Journal | Publisher | h5-index | Notes |
|---------|-----------|----------|-------|
| Neural Networks | Elsevier | 106 | Broad; worth adding with tag_filter |
| CVIU | Elsevier | 46 | Computer Vision and Image Understanding |
| Pattern Recognition Letters | Elsevier | 92 | Shorter papers, faster turnaround |

### Skipped (conference proceedings — already on arXiv)

CVPR (h5=450), ECCV (262), ICCV (256), NeurIPS (371), ICLR (362), ICML (272), WACV (131) — all post preprints to arXiv before the conference. No need for a separate feed.

---

## Scrapers Needed

This is the main implementation work. None of the Tier 1 journals are covered by existing scrapers.

### 1. `scrapers/ieee.py` — **New scraper** (blocks IEEE TPAMI + TIP)

IEEE journals are on ieeexplore.ieee.org. RSS feed URL pattern:
```
https://ieeexplore.ieee.org/rss/TOC{punumber}.XML
```
- TIP:   `https://ieeexplore.ieee.org/rss/TOC83.XML`
- TPAMI: `https://ieeexplore.ieee.org/rss/TOC34.XML`
- TNNLS: `https://ieeexplore.ieee.org/rss/TOC5962385.XML` (if adding later)

**Abstract access:** IEEE Xplore article pages are accessible (no Cloudflare block reported). Target selector: `div.abstract-text` or meta `citation_abstract`. Authors: `meta[name="citation_author"]`. Also worth trying OpenAlex DOI fallback since DOIs are in the RSS.

**Verify first:** Run a quick HTTP test against an ieeexplore.ieee.org article page from the Hetzner server before building the scraper. APS (another IEEE-adjacent publisher) was blocked — confirm IEEE Xplore is not.

### 2. `scrapers/springer.py` — **New scraper** (blocks IJCV)

Springer journals are on link.springer.com. RSS feed URL pattern:
```
https://link.springer.com/search.rss?facet-journal-id={id}&query=
```
- IJCV: journal id `11263` → `https://link.springer.com/search.rss?facet-journal-id=11263&query=`

**Abstract access:** Springer article pages are generally accessible. OpenAlex DOI fallback is a reliable alternative since Springer has good OpenAlex coverage.

### 3. Elsevier journals — **Extend existing `scrapers/elsevier.py`**

Current `elsevier.py` is wired for HEP (PLB, NPB) and uses INSPIRE-HEP as a fallback, which is HEP-specific. For Pattern Recognition and Neural Networks:
- Strip the INSPIRE-HEP fallback for non-HEP journals
- Use OpenAlex DOI fallback instead (already in BaseScraper)
- RSS feed URLs (ScienceDirect format):
  - Pattern Recognition: `https://rss.sciencedirect.com/publication/science/00313203`
  - Neural Networks: `https://rss.sciencedirect.com/publication/science/08936080`
  - CVIU: `https://rss.sciencedirect.com/publication/science/10773142`

**Option:** Either generalize `elsevier.py` to accept a `fallback` parameter (openalex vs. inspire), or create a separate `elsevier_general.py` for non-HEP Elsevier journals.

---

## fields.json Entry (draft)

```json
"ai-vision": {
  "tree_path": ["Computer Science", "Artificial Intelligence", "Computer Vision"],
  "arxiv_categories": ["cs.CV", "cs.LG", "eess.IV"],
  "description": "AI and computer vision — deep learning, image processing, generative models",
  "ssrn_ejournals": [],
  "journals": [
    {
      "name": "IEEE TPAMI",
      "url": "https://ieeexplore.ieee.org/rss/TOC34.XML",
      "publisher": "ieee",
      "tag_filter": null
    },
    {
      "name": "IEEE TIP",
      "url": "https://ieeexplore.ieee.org/rss/TOC83.XML",
      "publisher": "ieee",
      "tag_filter": null
    },
    {
      "name": "IJCV",
      "url": "https://link.springer.com/search.rss?facet-journal-id=11263&query=",
      "publisher": "springer",
      "tag_filter": null
    },
    {
      "name": "Pattern Recognition",
      "url": "https://rss.sciencedirect.com/publication/science/00313203",
      "publisher": "elsevier",
      "tag_filter": null
    },
    {
      "name": "Neural Networks",
      "url": "https://rss.sciencedirect.com/publication/science/08936080",
      "publisher": "elsevier",
      "tag_filter": ["deep learning", "neural network", "image", "vision", "convolutional", "generative", "representation"]
    }
  ]
}
```

---

## Implementation Order

1. **Verify IEEE Xplore accessibility** from Hetzner — test one article page before writing the scraper (`test_ieee_access.py`, analogous to `test_ssrn_access.py`)
2. **Verify Springer accessibility** — same check for link.springer.com
3. **Implement `scrapers/ieee.py`** — RSS parse + article page scrape + OpenAlex fallback
4. **Implement `scrapers/springer.py`** — RSS parse + article page scrape + OpenAlex fallback
5. **Generalize `scrapers/elsevier.py`** for non-HEP use (replace INSPIRE fallback with OpenAlex for non-HEP journals)
6. **Add `fields.json` entry** for `ai-vision`
7. **Register new scrapers** in `scrapers/__init__.py`
8. **Test locally:** `python fetch_journals.py --fields ai-vision --output /tmp/test_journals.json`
9. **Onboard first user** via `create_profile.py`
10. **Deploy:** SCP changed files + add `ANTHROPIC_API_KEY_AI_VISION` to server `.env`

---

## Open Questions

- **cs.LG volume:** cs.LG alone can push 200+ papers/day. Consider fetching cs.CV + eess.IV only, since most impactful cs.LG vision papers cross-post to cs.CV anyway. Decide per first-user preference.
- **IEEE Xplore block risk:** APS (also IEEE-adjacent) was Cloudflare-blocked from Hetzner. Verify IEEE Xplore separately before committing to the IEEE scraper.
- **Elsevier scraper refactor:** Cleanest option is a `use_inspire` flag on `ElsevierScraper.__init__()` — defaults False, set to True for PLB/NPB in fields.json. Avoids code duplication.
- **OpenReview (future):** ICLR/NeurIPS/ICML papers appear on OpenReview 3+ months before the conference. Worth a dedicated fetcher eventually — has a free public API at `https://api.openreview.net`. Not needed for launch.

---

## Reference: Existing `docs/add_new_field.md`

Read `docs/add_new_field.md` before starting implementation — it has the full checklist for onboarding a new field including the API key setup, cron verification, and watermark initialization steps.
