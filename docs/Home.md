# Incoming Science — Knowledge Vault

> AI-powered daily arXiv digest system. ~37 users, ~$0.05/user/day. Live at [incomingscience.xyz](https://incomingscience.xyz).

---

## 🗺 Navigation

### Core Pipeline
- [[Pipeline Overview]] — end-to-end data flow, daily schedule
- [[AI Pipeline]] — triage (Haiku) + scoring (Sonnet), two-stage design
- [[Prompt Caching]] — shared triage cache, rate-limit orchestrator, staggered launches
- [[Daily Digest]] — PDF build, rating buttons, email delivery
- [[Weekly Digest]] — weekly-only delivery mode, run_weekly_digest.py

### Data & Ingestion
- [[Journal Scrapers]] — publisher scrapers, watermarks, fields.json
- [[Preprint Sources]] — bioRxiv/medRxiv (date watermarked) + NBER/CEPR (ID watermarked); triage routing
- [[Abstract Enrichment]] — per-publisher fallback chain (OpenAlex → S2 → CORE)

### User & Profile
- [[Taste Profile]] — profile schema, grade system, liked_papers
- [[User Onboarding]] — web signup, process_pending.py, create_profile.py
- [[Monthly Refiner]] — rating analysis, keyword/area grade changes, area management
- [[Profile Edit Skill]] — free-text user feedback → manual profile patch (`.claude/skills/edit-profile.md`)
- [[Check Log Skill]] — diagnose a failed daily run: download log, match known bugs, recommend recovery (`.claude/skills/check-log.md`)
- [[Manage Profile]] — `/manage` self-service page: frequency toggles, interest feedback, email lookup
- [[Paper Insights]] — opt-in deep-analysis feature (`paper_insights: true`)

### Infrastructure & Ops
- [[Infrastructure]] — VPS, Caddy, Gunicorn, cron schedule
- [[Operations]] — monitoring, logs, common debugging commands
- [[Cost Model]] — per-user cost, Batch API savings, caching multiplier

### Quality & Debugging
- [[Hidden Bug Audit]] — 6 silent quality degraders identified 2026-06-09 (no errors thrown)


---

## System at a Glance

```
arXiv RSS ──┐
             ├─→ fetch + triage (Haiku, cached) ──→ scoring (Sonnet, Batch)
Journals ───┘                                              │
                                                           ▼
                                                     PDF digest ──→ Email
                                                           │
                                                    User rates paper
                                                           │
                                                    archive.json
                                                           │
                                              Monthly refiner (Sonnet)
                                                           │
                                              Updated taste_profile.json
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Run all users | `python run_all_users.py` |
| Single user test | `python run_all_users.py --user <name> --no-email` |
| Retry failed users | `python run_failed_users.py` |
| Monthly refiner | `python run_all_users.py --refine` |
| Process signups | `python process_pending.py --all` |
| Check logs | `scp root@116.203.255.222:/var/log/arxiv-grader/daily.log ./debugging/` |

---

## Key Files

| File | Role |
|------|------|
| `run_all_users.py` | Master orchestrator |
| `run_pipeline.py` | Triage + scoring |
| `build_digest_pdf.py` | PDF generator |
| `server.py` | Flask (rating endpoint + web) |
| `run_profile_refiner.py` | Monthly taste refiner |
| `fields.json` | Field/journal registry |
| `journal_watermarks.json` | Dedup state per journal feed |

---

## Existing Design Docs (`docs/`)

**Architecture:**
- `grading_pipeline_design.md` — triage classification rules, cost table
- `journal_sources_design.md` — journal architecture rationale
- `journal_code_guide.md` — scraper class hierarchy, filter_for_field
- `journal_implementation_plan.md` — original journal integration plan (steps 1–10)
- `triage_rate_limit_orchestrator.md` — TokenBucketOrchestrator design
- `refiner_v2_design.md` — area management, structured outputs, support ratios
- `weekly_digest_design.md` — weekly delivery design
- `multi_user_plan.md` — parallel user execution design
- `elsevier_abstract_plan.md` — Elsevier abstract fallback strategy

**Operations & Infrastructure:**
- `add_new_field.md` — step-by-step field addition checklist
- `server_access.md` — server access rules, deploy procedure
- `scaling_analysis.md` — cost/user scaling analysis
- `journal_triage_tuning.md` — triage cap tuning
- `flaresolverr_plan.md` — Cloudflare bypass via FlareSolverr (Tandfonline, Sage, Wiley, Chicago; implemented 2026-06-11)

**User Experience:**
- `website_onboarding.md` — onboarding web pages, state management
- `create_profile_logic.md` — profile creation stages, Claude call design
- `scholar_import_plan.md` — Google Scholar import flow
- `improvement_brainstorm.md` — feature ideas and open questions
- `mobile_responsiveness_plan.md` — onboarding website mobile fixes
- `user_self_service_design.md` — `/manage` page design decisions, alternatives, and decided constraints

**Field Plans:**
- `systems_biology_plan.md` — systems-biology field (Cell, PLOS, PNAS scrapers)
- `new_field_ai_vision.md` — ai-vision field (IEEE, Springer scrapers needed)
- `plan_music_theory_field.md` — music-theory field (journals-only, OpenAlex)
