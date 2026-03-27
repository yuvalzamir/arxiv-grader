# Journal Triage Tuning Log

## Problem

Initial journal triage pass rate was ~4% (4–6/104 papers). Target: ~10 papers/day.

Root cause: journals have no subcategory field, so the original `triage.txt` signal 3
(subcategory + topic overlap) never fired. Only keyword hits and author matches worked,
making journal triage far harsher than arXiv triage.

## Solution: separate prompt for journals

Created `prompts/triage_journals.txt` — a journal-specific triage prompt that:
1. Drops the subcategory signal entirely (journals have none)
2. Adds **signal 4: abstract content match** — if the abstract describes experiments,
   phenomena, materials, or methods that fall within a grade 1–5 research area, even
   without a verbatim keyword match, the paper qualifies as `medium`.
   Example: a tunneling spectroscopy paper on a 2D heterostructure qualifies even if
   "STM" or "moiré" don't appear in the title.

## Cap adjustments (`run_pipeline.py`)

| Constant | Before | After |
|---|---|---|
| `MAX_TRIAGE_PASS` (arXiv) | 20 | 15 |
| `MAX_TRIAGE_PASS_JOURNAL` (journals) | 10 | 15 |

arXiv cap lowered because 15 is plenty for daily scoring cost. Journal cap raised to
give the new signal room.

## Observed results (2026-03-26 test runs)

| Run | Prompt | arXiv passed | Journal passed | Journal input |
|-----|--------|-------------|----------------|---------------|
| 1 (baseline) | original triage.txt for both | 11 | 4 | 104 |
| 2 | triage_journals.txt, signal 4 grade 1–3 | 5 | 5 | 104 |
| 3 | signal 4 grade 1–4 | 7 | 0 | 56 (only NatComms+Science — APS watermark exhausted) |
| 4 | signal 4 grade 1–5, caps 15/15 | — | 5 | 56 (same issue) |

Run 3 and 4 low journal counts were **not a triage regression** — the APS journals
(PRL, PRB, PRX) had their watermarks already at 2026-03-25 from the previous run and
returned 0 new papers. Only NatComms (16) and Science (40) had content, and Science
covers all fields so ~0 pass is expected.

arXiv variance (11→7) is normal Haiku stochasticity across identical paper sets.

## Final configuration (deployed 2026-03-27)

- `prompts/triage_journals.txt`: signal 4 = abstract content, grade 1–5
- `MAX_TRIAGE_PASS = 15`, `MAX_TRIAGE_PASS_JOURNAL = 15`

## Deploy notes (2026-03-27)

Files copied to server via `scp` from inside `Z:/arxiv_grader/`:

```bash
scp build_digest_pdf.py create_profile.py fetch_journals.py fields.json run_all_users.py run_daily.py run_pipeline.py run_profile_refiner.py requirements.txt root@116.203.255.222:/opt/arxiv-grader/
scp prompts/scoring.txt prompts/triage_journals.txt root@116.203.255.222:/opt/arxiv-grader/prompts/
scp -r scrapers root@116.203.255.222:/opt/arxiv-grader/
scp journal_watermarks.json root@116.203.255.222:/opt/arxiv-grader/
ssh root@116.203.255.222 "cd /opt/arxiv-grader && source venv/bin/activate && pip install beautifulsoup4 lxml matplotlib"
```

New pip dependencies on server: `beautifulsoup4`, `lxml`, `matplotlib`.
(`matplotlib` is used by `build_digest_pdf.py` to locate the DejaVu Sans font.)
`reportlab` and `pylatexenc` were already installed from main branch.
