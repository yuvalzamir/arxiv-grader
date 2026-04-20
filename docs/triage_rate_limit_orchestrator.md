# Triage Rate-Limit Orchestrator — Implementation Plan

## Background

The triage pipeline uses the Anthropic cached API for Haiku triage calls. The rate limit
is **50,000 input tokens per minute, shared across the entire organisation** (all API keys,
all fields). Only `input_tokens` + `cache_creation_input_tokens` count toward the limit;
`cache_read_input_tokens` are free.

The previous approach staggered users within each field independently. This failed because
multiple fields fire their user-0 cache-creation calls simultaneously, exhausting the shared
org bucket across fields.

The fix is a single central `TokenBucketOrchestrator` that serialises all cached API calls
across all fields and all users. Batch API calls are unaffected.

---

## Design

### Token bucket model

- **Capacity:** 50,000 tokens
- **Refill rate:** 50,000 / 60 ≈ 833 tokens/second (continuous, token-bucket algorithm)
- **Extra buffer:** 5 seconds added to every computed wait to absorb estimation error

### Call classification

Every cached API call is pre-classified as one of:

| Type | Condition | ITPM cost |
|---|---|---|
| `cache_write` | First user in the field (`i == 0`) | Full `estimated_tokens` |
| `cache_read` | Any subsequent user (`i > 0`) | 0 (free ITPM) |

`is_first_user = (i == 0)` is set in `_triage_one()` and passed through to `run_triage()`.

### `acquire()` behaviour

**`cache_write` call:**
1. Acquire lock (briefly).
2. Refill bucket based on elapsed time.
3. If `bucket >= tokens`: deduct tokens, release lock, return immediately.
4. Else: compute `wait = (tokens - bucket) / refill_rate + 5s`, release lock, sleep `wait`.
5. Loop and re-check (another thread may have consumed tokens during sleep).

**`cache_read` call:**
1. Acquire lock.
2. Refill bucket (keeps internal clock accurate).
3. Sleep 1 second **with lock held** — gives Claude time to register the preceding
   cache_write before the cache_read request arrives.
4. Release lock, return.

The 1-second hold prevents racing: if multiple cache_read threads queue up, they dispatch
1 second apart, ensuring Claude has processed the previous request before the next arrives.

---

## Files to change

### `run_all_users.py`

#### 1. Add `TokenBucketOrchestrator` class (top of file, after imports)

```python
class TokenBucketOrchestrator:
    CAPACITY        = 50_000
    REFILL_RATE     = 50_000 / 60   # tokens/second
    BUFFER_SECS     = 5.0
    CACHE_READ_HOLD = 1.0           # seconds to hold lock for cache reads

    def __init__(self):
        self.bucket      = self.CAPACITY
        self.last_update = time.monotonic()
        self.lock        = threading.Lock()

    def _refill(self):
        """Must be called with lock held."""
        now = time.monotonic()
        self.bucket = min(self.CAPACITY,
                          self.bucket + (now - self.last_update) * self.REFILL_RATE)
        self.last_update = now

    def acquire(self, tokens: int, is_cache_write: bool) -> None:
        if not is_cache_write:
            # Hold lock for 1s so Claude can register the preceding cache_write
            # before this cache_read request is dispatched.
            with self.lock:
                self._refill()
                time.sleep(self.CACHE_READ_HOLD)
            return

        # cache_write: wait until bucket has enough tokens, then deduct.
        while True:
            with self.lock:
                self._refill()
                if self.bucket >= tokens:
                    self.bucket -= tokens
                    return
                deficit   = tokens - self.bucket
                wait_secs = deficit / self.REFILL_RATE + self.BUFFER_SECS
            log.info("Orchestrator: bucket low (%d tokens), waiting %.1fs.",
                     int(self.bucket), wait_secs)
            time.sleep(wait_secs)
            # Loop — re-check after sleep; another thread may have consumed tokens.
```

#### 2. Instantiate orchestrator once before all triage

```python
orchestrator = TokenBucketOrchestrator()
```

#### 3. Replace per-field `_triage_field_users()` with a flat loop

Remove `_triage_field_users()` and all stagger logic. Build a flat list of all users
across all fields and dispatch them simultaneously:

```python
triage_tasks = []
for field, user_dirs in field_users.items():
    for i, user_dir in enumerate(user_dirs):
        triage_tasks.append((field, user_dir, i == 0))  # is_first_user = i == 0

with ThreadPoolExecutor(max_workers=len(triage_tasks)) as executor:
    futures = [
        executor.submit(_triage_one, field, user_dir, is_first_user, orchestrator)
        for field, user_dir, is_first_user in triage_tasks
    ]
```

#### 4. Remove entirely

- `split_cached_pause`
- `inner_gap`
- `split_cached` detection logic
- `needs_stagger`
- `_delay_for()` function
- Pre-thread-start `time.sleep(i * delay)`
- `inter_call_min_gap` parameter passed to `run_triage()`

#### 5. Keep

- `use_batch_arxiv` / `use_batch_journals` routing (cached vs. batch decision)
- `base_batch` logic (fields with < 4 users still use batch by default)

#### 6. Update log messages

Replace stagger-related startup logs with:
```
Field 'cond-mat': 5 user(s) — triage mode: arXiv=cached  journals=cached  (orchestrator-managed)
```
The orchestrator logs waits inline, so timing is still visible.

---

### `run_pipeline.py`

#### 1. Add `orchestrator` and `is_first_user` parameters to `run_triage()`

Both parameters thread through from `_triage_one()` in `run_all_users.py`.

#### 2. Call `orchestrator.acquire()` before each cached API call

Applies to both the arXiv cached call and the journals cached call. **Does not apply to
batch API calls** — those fire immediately regardless of bucket state.

```python
estimated_tokens = len(json.dumps(papers)) // 4
orchestrator.acquire(estimated_tokens, is_cache_write=is_first_user)
response = _call_cached(...)
```

#### 3. Remove `inter_call_min_gap` sleep

The sleep between the arXiv and journals calls is removed. The orchestrator naturally
enforces the correct gap when the journals cache_write needs tokens the bucket doesn't yet have.

---

## What disappears vs. what replaces it

| Removed | Replaced by |
|---|---|
| Per-field `_triage_field_users()` with stagger | Single flat `ThreadPoolExecutor` over all users |
| `split_cached_pause`, `inner_gap`, `_delay_for()` | `TokenBucketOrchestrator.acquire()` |
| Pre-thread-start `time.sleep(i * delay)` | Removed — all threads start immediately |
| `inter_call_min_gap` sleep between arXiv and journals | Removed — orchestrator handles it |
| "Triage in Xs" stagger log messages | Orchestrator wait logs (only when a wait is needed) |

Batch API calls are completely unaffected.
