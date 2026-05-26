# Prompt Caching Architecture

[[Home]] | [[AI Pipeline]] | [[Pipeline Overview]]

---

## Why Caching?

Triage sends ~80–200 papers per field to Claude Haiku. The paper list is **identical** for all users in the same field — only the taste profile differs. Anthropic's prompt caching charges ~10% of normal input token cost for cache hits, so the first user pays full price and each subsequent user in the same field pays ~10%.

With 5 users in a field, the effective per-user triage cost drops from ~$0.004 to ~$0.001.

---

## Cache Structure

Each triage call has two parts:

```
[system prompt]           ← cache_control: ephemeral  (shared, cached)
[papers block]            ← cache_control: ephemeral  (shared, cached)
[user profile block]      ← no cache_control          (per-user suffix)
```

The system prompt and papers block are identical for all users → cached. The profile block varies per user → never cached.

`_call_cached()` in `run_pipeline.py` implements this:
```python
content = [
    {"type": "text", "text": chunk, "cache_control": {"type": "ephemeral"}}
    for chunk in papers_blocks
]
content.append({"type": "text", "text": profile_block})  # uncached suffix
```

---

## Rate Limit: 50k Input Tokens/Minute

The cached API (non-Batch) has a **50k input-token/minute** shared limit across all cached calls. With ~40k tokens per triage call and multiple users per field, concurrent calls would hit the limit.

### Solution: Staggered User Launches

Users in a field are launched **61 seconds apart** (`i × 61s` delay). Since each call uses ≤40k tokens and the window is 60 seconds, no two cached calls overlap within the same minute window.

Only the **first user** in a field incurs the cache-write cost (full ITPM). Subsequent users pay only cache-read cost (which is **free ITPM** — doesn't count against the limit).

### TokenBucketOrchestrator

`run_all_users.py` implements a token bucket that governs cached API calls:
- `acquire(tokens, is_cache_write=True)` — blocks until the current minute's budget allows the call
- Cache-write calls (first user per field) consume the ITPM budget
- Cache-read calls (subsequent users) are free, `acquire()` returns immediately

---

## Multi-Chunk Caching

When the papers block exceeds 40k tokens, it's split into multiple chunks. Each chunk gets its own `cache_control` breakpoint:

```python
papers_blocks = split_papers_block(papers_block, n_chunks)
# → ["header + papers 1–50", "papers 51–100", ...]
```

For `n_chunks > 1`, the first user runs **warming calls** before the actual triage call:
- Warming call 1: sends chunks 1..1 with `max_tokens=1` (cheap) — establishes cache entry for chunk 1
- Warming call 2: sends chunks 1..2 with `max_tokens=1` — establishes cache entry for chunk 2
- Actual call: sends all chunks — all but the last are cache reads (free ITPM)

Subsequent users pay only cache-read cost on all chunks.

---

## Batch API Fallback for Overflow

If a triage call would exceed the 40k token safety threshold, it is **automatically routed to the Batch API** instead of the cached API. The Batch API has no rate limit, so overflow calls don't interfere with cached calls.

Per-call routing is set independently:
- `use_batch_arxiv` — force Batch for arXiv triage if arXiv papers alone exceed 40k
- `use_batch_journals` — force Batch for journal triage if journals alone exceed 40k

Fields with fewer than 4 users always use Batch for triage (caching isn't worth it).

---

## Execution Order Guarantee

Within each user's triage thread:
> **Cached call always fires before the Batch call** to hit the cache while it is still warm (warmed by the previous user in the field).

```python
arxiv_first = not batch_arxiv or batch_journals
if arxiv_first:
    # cached arXiv → cached/batch journals
else:
    # cached journals → batch arXiv
```

---

## API Keys for Triage

Triage uses a **shared API key per field** (not per user). This is required for the cache to be shared — each user's triage call must use the same API key.

Root `.env` keys:
```
ANTHROPIC_API_KEY_COND_MAT=sk-ant-...
ANTHROPIC_API_KEY_QUANTUM_SENSING=sk-ant-...
```

Key format: `ANTHROPIC_API_KEY_` + field name uppercased, hyphens → underscores.

Per-user `ANTHROPIC_API_KEY` is used only for **scoring** (Batch API, not cached).

---

## Summary: When Each Mode Is Used

| Scenario | Mode |
|---|---|
| Field has ≥4 users, papers ≤40k tokens | Cached API (shared key) |
| Field has <4 users | Batch API |
| Papers exceed 40k tokens | Batch API (for that call only) |
| `--no-batch` flag | Cached API (direct, no Batch anywhere) |
| Papers exceed 40k AND `--no-batch` | Multi-chunk cached API |
