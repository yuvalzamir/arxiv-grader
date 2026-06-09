# Triage Waste Analysis — ml, soft-eng, quantum-sensing
_Date: 2026-06-09_

## Summary

Three fields dominate triage API cost. Root causes: broken watermarks on 4 high-volume journals, plus genuinely large arXiv categories.

---

## Paper Counts per Run (from logs 2026-06-01, 06-02, 06-04)

| Field | arXiv | Journals | Total | Users |
|-------|-------|----------|-------|-------|
| ml | 193–490 | 199–202 | 392–689 | 1 (nadav) |
| soft-eng | 9–24 | 237–251 | 257–274 | 1 (jenny) |
| quantum-sensing | 89–155 | 32–59 | 148–187 | 2 (Ediz, guillermo) |

Triage cap: 15 arXiv + 15 journal → max 30 survive. Everything else is token waste.

---

## The Core Problem: 4 Journals with Broken Watermarks

Identical counts across all 3 observed days = same papers re-fetched every run:

| Journal | Field | URL | Count/day | Root cause |
|---------|-------|-----|-----------|------------|
| IEEE TPAMI | ml | https://csdl-api.computer.org/api/rss/periodicals/trans/tp/rss.xml | 98 | csdl-api RSS: no parseable dates → entry_date always None → watermark never advances |
| Neural Networks | ml | https://rss.sciencedirect.com/publication/science/08936080 | 100 | ScienceDirect RSS: date field not parsed by _entry_date() → watermark never advances |
| IEEE TSE | soft-eng | https://csdl-api.computer.org/api/rss/periodicals/trans/ts/rss.xml | 100 | Same as TPAMI |
| ACM TOSEM | soft-eng | https://dl.acm.org/action/showFeed?type=etoc&feed=rss&jc=tosem | 26 | ACM eTOC RSS: no parseable dates on individual entries |

**Combined ghost triage load: 324 redundant papers per day** (198 for ml, 126 for soft-eng).

---

## High-Volume Genuine Publishers (watermark working)

| Journal | Field | Count/day | Note |
|---------|-------|-----------|------|
| JSS | soft-eng | 39–57 | Elsevier, genuinely new each day |
| SCP | soft-eng | 34–37 | Elsevier, genuinely new — but PL-focused, low relevance to empirical SE |
| IST | soft-eng | 31–34 | Elsevier, genuinely new each day |

---

## arXiv — Large but Correct

| Category | Field | Count/day | Note |
|----------|-------|-----------|------|
| cs.LG | ml | 143–289 | Core ML category, unavoidable Monday spike |
| cs.AI | ml | 36–173 | Large overlap with cs.LG via cross-posts |
| quant-ph | quantum-sensing | 42–84 | Very broad; Monday spike |
| physics.optics | quantum-sensing | 22–24 | Also fetched for optics field (separate copy) |
| cs.SE | soft-eng | 9–24 | Small, fine |

---

## Actions Decided

### Remove from fields.json
- [ ] **IEEE TPAMI** (ml) — CV/pattern analysis, not ML theory. 98 ghost papers/day.
- [ ] **SCP** (soft-eng) — Programming languages, not empirical SE. 34–37 genuine papers/day.

### Fix RSS watermark bugs
- [ ] **Neural Networks** (ml) — Fix date parsing in _entry_date() or ScienceDirect scraper
- [ ] **IEEE TSE** (soft-eng) — Fix csdl-api date parsing or switch to ieee_rest scraper
- [ ] **ACM TOSEM** (soft-eng) — Fix date parsing in ACM eTOC feed

### Keep as-is
- JSS, IST (soft-eng) — genuine, relevant, watermark working
- All quantum-sensing sources — reasonably sized
- All ml arXiv categories — legitimate

---

## Estimated Impact After Fixes

| Field | Before | After (est.) |
|-------|--------|-------------|
| ml total/day | 392–689 | ~190–390 |
| soft-eng total/day | 257–274 | ~90–130 |
| quantum-sensing | 148–187 | unchanged |

ml and soft-eng triage costs expected to drop ~40–60%.
