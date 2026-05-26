# Cost Model

[[Home]] | [[AI Pipeline]] | [[Prompt Caching]]

---

## Daily Cost Per User (~$0.05)

| Stage | Model | Mode | Input tokens | Output tokens | Cost |
|-------|-------|------|-------------|--------------|------|
| Triage (arXiv) | Haiku | Cached (10% rate) | ~20–30k | ~200 | ~$0.001 |
| Triage (journals) | Haiku | Cached | ~10–15k | ~100 | ~$0.0005 |
| Scoring | Sonnet | Batch (50% off) | ~5–10k | ~900 | ~$0.018 |
| **Total** | | | | | **~$0.02–0.05** |

*Caching multiplier: 10% cost for subsequent users in the same field on the papers block (~90% of triage input).*

---

## Caching Savings (Multi-User Fields)

With N users in a field, the first user pays full triage price. Subsequent users pay ~10% for the papers block (cache hit):

| Users in field | Avg triage cost/user | Savings vs no cache |
|---|---|---|
| 1 | $0.004 | 0% |
| 3 | ~$0.002 | ~50% |
| 5 | ~$0.0015 | ~63% |
| 10 | ~$0.0012 | ~70% |

---

## Batch API Savings (Scoring)

The Anthropic Message Batches API gives a 50% discount on all tokens. Scoring (Sonnet) is the largest daily cost:
- Direct API: ~$0.036/user/day
- Batch API: ~$0.018/user/day

When Batch times out and falls back to direct API, cost doubles for that user for that day.

---

## Monthly Cost (37 Users)

Assuming typical weekday mix (~22 working days/month):
- Daily pipeline: 37 users × $0.05 × 22 days ≈ **$40/month**
- Monthly refiner: 37 users × ~$0.007 × 2 runs ≈ **$0.50/month**
- Infrastructure (Hetzner CX23): **~$10/month**
- **Total: ~$50/month**

---

## Onboarding Cost

Each new user profile creation: **~$0.05–0.08**
- One Sonnet call (~14k input + ~1.3k output)
- Previous design (extended thinking + tools loop): ~$1.40 — current is ~20× cheaper

---

## Paper Insights (Opt-In Premium)

Users with `paper_insights: true` add ~2–3× output tokens for scoring:
- Standard scoring: ~$0.018/day
- With insights: ~$0.030–0.040/day

---

## Refiner (Monthly × 2)

| Step | Cost |
|------|------|
| Main refiner (Sonnet Batch) | ~$0.006/user/run |
| Area management (Haiku sync) | ~$0.00008/user/run |
| **Per user per month** | **~$0.012** |

---

## Rate Limits

| API | Limit | Impact |
|-----|-------|--------|
| Cached API (non-Batch) | 50k input tokens/minute | Governs triage stagger (61s between users) |
| Batch API | No rate limit | Concurrent scoring across all users |
| S2 API | Informal (~100 req/day casual) | Used for ACS abstract enrichment |
| CORE API | 1,000 req/day (registered key) | Used for SAGE/Tandfonline fallback |
| OpenAlex API | No auth, generous limit | Used widely for abstract enrichment |

---

## Cost Per Paper

At 100 papers processed per field per day:
- Triage: ~$0.002 total per field → **$0.00002/paper**
- Scoring (20 survivors): ~$0.018/user → **$0.0009/scored paper**

The 10:1 triage ratio keeps scoring costs bounded even on heavy arXiv days.
