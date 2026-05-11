# Plan: Add `music-theory` field

## Context

A new user interested in music theory needs a field. No music field exists yet.
The field covers music theory broadly — harmonic analysis, computational musicology,
music information retrieval, music cognition, and empirical approaches to musical structure.

**No arXiv categories** — pure music theory has no meaningful arXiv presence. This is a journals-only field (arxiv_categories: []).

---

## arXiv

None. `cs.SD` (Sound) was considered but excluded — it's dominated by audio deep learning and MIR, not music theory. No dedicated music theory arXiv category exists.

> Note: No dedicated preprint platform for music theory exists either (PsyArXiv has some content but no structured feed compatible with our system).

---

## Journals — all via `openalex`

No existing scrapers cover UC Press, SAGE, or OJS platforms. All journals use the `openalex` ISSN path. No new scrapers needed.

| name | openalex_issn | frequency | publisher platform |
|---|---|---|---|
| MusicPerception | `1533-8312` | 5x/year | UC Press |
| PsychologyOfMusic | `1741-3087` | 6x/year | SAGE |
| MusicTheoryOnline | `1067-3040` | 4x/year | SMT / OJS (open access) |
| EmpiricalMusicology | `1559-5749` | 4x/year | Ohio State / OJS (open access) |
| MusicTheorySpectrum | `1533-8339` | 2x/year | Oxford Academic (OUP) |
| JournalOfMusicTheory | `1941-7497` | 2x/year | Duke University Press |

---

## Proposed fields.json entry

```json
"music-theory": {
  "arxiv_categories": [],
  "description": "Music theory, computational musicology, and music cognition — harmonic analysis, music perception, empirical musicology, and quantitative approaches to musical structure",
  "journals": [
    { "name": "MusicPerception",    "openalex_issn": "1533-8312", "publisher": "openalex", "tag_filter": null },
    { "name": "PsychologyOfMusic",  "openalex_issn": "1741-3087", "publisher": "openalex", "tag_filter": null },
    { "name": "MusicTheoryOnline",  "openalex_issn": "1067-3040", "publisher": "openalex", "tag_filter": null },
    { "name": "EmpiricalMusicology","openalex_issn": "1559-5749", "publisher": "openalex", "tag_filter": null },
    { "name": "MusicTheorySpectrum","openalex_issn": "1533-8339", "publisher": "openalex", "tag_filter": null },
    { "name": "JournalOfMusicTheory","openalex_issn": "1941-7497", "publisher": "openalex", "tag_filter": null }
  ],
  "tree_path": ["Humanities & Arts", "Music", "Music Theory", "Music Theory & Musicology"]
}
```

**API key env var:** `ANTHROPIC_API_KEY_MUSIC_THEORY`

---

## Files to modify

- `Z:\arxiv_grader\fields.json` — insert before `"systems-biology"`
- `Z:\arxiv_grader\run_all_users.py` — three small fixes for journal-only fields (see below)

No scraper files to add.

---

## Code fix required — empty `arxiv_categories`

`run_all_users.py` has bugs when `arxiv_categories: []` because an empty list is falsy and
falls back to using the field name as an arXiv category, which doesn't exist.

### Fix A — `run_arxiv_fetch` (around line 282)

Replace:
```python
raw = field_config.get("arxiv_categories") or field_config.get("arxiv_category") or field
categories = [raw] if isinstance(raw, str) else list(raw)
```
With:
```python
raw = field_config.get("arxiv_categories")
if raw is None:
    raw = field_config.get("arxiv_category")
if not raw:
    output_path.write_text("[]")
    return output_path
categories = [raw] if isinstance(raw, str) else list(raw)
```

### Fix B — main loop skip guard (around line 807)

Replace:
```python
papers = json.loads(arxiv_path.read_text())
if not papers:
    log.info("Field '%s': no arXiv papers today — skipping field.", field)
    triage_failed.update(u.name for u in field_users)
    continue
```
With:
```python
papers = json.loads(arxiv_path.read_text())
field_cfg = fields_data.get(field, {})
has_arxiv = bool(field_cfg.get("arxiv_categories") or field_cfg.get("arxiv_category"))
if not papers and has_arxiv:
    log.info("Field '%s': no arXiv papers today — skipping field.", field)
    triage_failed.update(u.name for u in field_users)
    continue
```

### Fix C — holiday guard (around line 814)

Replace:
```python
fields_with_papers = list(arxiv_papers_by_field)
if not fields_with_papers:
    log.info("No arXiv papers in any field today — holiday or off-day. Skipping pipeline.")
    sys.exit(0)
```
With:
```python
fields_with_papers = list(arxiv_papers_by_field)
arxiv_enabled_with_papers = [f for f in fields_with_papers if arxiv_papers_by_field[f]]
arxiv_enabled = [f for f in active_fields
                 if fields_data.get(f, {}).get("arxiv_categories")
                 or fields_data.get(f, {}).get("arxiv_category")]
if arxiv_enabled and not arxiv_enabled_with_papers:
    log.info("No arXiv papers in any field today — holiday or off-day. Skipping pipeline.")
    sys.exit(0)
```

---

## Verification

```bash
python fetch_journals.py --fields music-theory --output debugging/journals_music_theory_test.json --since 2026-05-01 --no-advance-watermark
```

Every journal should return at least some papers. Flag any at 0.

---

## Deployment checklist

1. `scp fields.json run_all_users.py root@116.203.255.222:/opt/arxiv-grader/`
2. Add to server root `.env`: `ANTHROPIC_API_KEY_MUSIC_THEORY=sk-ant-...`
3. Onboard first user: `python create_profile.py --user-dir users/<name>`
