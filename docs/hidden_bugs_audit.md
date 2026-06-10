# Hidden Bug Audit — Silent Quality Degraders

> Identified 2026-06-09. These bugs produce no errors or warnings but silently degrade digest quality, waste cost, or corrupt profile refinement.

---

## Bug 1: Late Ratings Become Phantom Refiner Signals

**Location:** `server.py:243-256` (`find_paper`), `run_profile_refiner.py:220-248`

**Mechanism:** When a user rates a paper after `KEEP_DAYS` (21 days), the data folder (`data/YYYY-MM-DD/`) has been deleted. `find_paper()` fails to locate `scored_papers.json` or `today_papers.json`, so the rating is saved with `score: null`. The refiner then sees `score is None` and classifies it as `missed-excellent` (a paper the system scored low but the user liked). This phantom discrepancy inflates the refiner's keyword/area grade adjustments in the wrong direction.

**Impact:** Users who rate papers weeks after delivery generate false "missed-excellent" signals, causing the refiner to boost keywords the system was already handling correctly. Slow accumultion over months.

**Fix idea:** Store `score` in the rating record at PDF-build time (embed in the rating URL or write a lightweight score cache that outlives data folder cleanup). Alternatively, the refiner should ignore ratings where `score is None` rather than treating them as missed-excellent.

---

## Bug 2: Scoring ID Mismatch → Score Defaults to 0

**Location:** `run_pipeline.py:688`

**Mechanism:** `score_map = {item["arxiv_id"]: item for item in scores}` joins scored results back to filtered papers by `arxiv_id`. If the scoring agent returns a slightly different ID, the join silently fails — the paper gets `score=0`, `justification=""`, `tags=[]`. It is still written to `scored_papers.json` and appears in the digest, but at the very bottom with a score of 0.

**Mitigating factors (verified 2026-06-09):**
- `scoring.txt` line 59 explicitly instructs: *"Use the arxiv_id exactly as given in the input."* Sonnet is reliable at this.
- Mismatched papers are not dropped — they appear with score=0, so the user still sees them.

**Real version of this bug:** Truncated JSON output from the Batch API (observed 2026-06-04) causes the last N papers to be absent from the response entirely — those papers get score=0. This is already tracked in TODO (retry-on-truncated-JSON).

**Impact:** Low in normal operation. Score=0 papers sink to the bottom of the digest and could generate false "missed-excellent" refiner signals if the user rates them. Actual ID mismatch from Sonnet is rare given the explicit prompt instruction.

**Fix idea:** Log a warning if any paper in `filtered_papers` has no matching entry in `score_map` after joining. This would surface both truncation and any genuine ID mismatch.

---

## Bug 3: feedparser.parse() Has No Timeout

**Location:** `scrapers/sources.py:159`

**Mechanism:** `feedparser.parse(url)` uses urllib internally with no socket timeout. If a publisher's server is slow or hangs (observed: ScienceDirect took 5:38 for Neural Networks), the call blocks indefinitely. Since RSS fetches use `_RSS_SEMAPHORE = Semaphore(2)`, one hung feed blocks a semaphore slot. If two feeds from the same publisher hang, the entire publisher group stalls, and all downstream fields waiting for that publisher are delayed or blocked.

**Impact:** A single slow publisher can cascade into a full pipeline stall. The daily cron has no external timeout, so it would just hang until the server kills it or the connection eventually drops. No error logged — just silence.

**Fix idea:** Wrap `feedparser.parse()` in a `socket.setdefaulttimeout()` context or use `requests.get()` with `timeout=60` and feed the response content to `feedparser.parse()`. Log a warning if a feed takes >30s.

---

## Bug 4: Stale Liked-Paper Sampling in Scoring

**Location:** `run_pipeline.py:193-209` (`_sample_liked_papers`)

**Mechanism:** The scoring prompt includes up to 10 liked papers as few-shot examples to calibrate Sonnet's grading. These are sampled randomly from the entire archive (all time, all topics). For users with broad interests, this means the scoring agent might see liked astrophysics papers when grading today's NLP batch — providing irrelevant calibration signal.

**Impact:** Scoring accuracy degrades as user archives grow and diversify. The agent receives few-shot examples that don't match the current batch's topic distribution, leading to miscalibrated scores. This is the existing TODO item #32 (topic-aware selection), but documenting here as a confirmed quality bug, not just a nice-to-have.

**Fix idea:** Select liked papers with highest keyword overlap to today's triage survivors. Simple Python set intersection on title/abstract tokens — no embeddings needed.

---

## Bug 5: Triage Format Parsing Silently Drops Papers

**Location:** `run_pipeline.py:521`

**Mechanism:** Triage results are parsed with regex `r"\[?(\d+)\]?\s*[-:]\s*(high|medium|low)"`. If Haiku outputs a slightly different format (e.g., `"Paper 7 - High"` with capital H, or `"7. high"` with a period instead of dash/colon, or `"#7: high"`), the line is silently skipped. The paper is treated as unclassified and excluded from scoring.

**Impact:** Any triage response format variation causes papers to vanish. Since triage uses `re.IGNORECASE` flag this handles capitalization, but delimiter variations (period, comma, no delimiter) still cause drops. Frequency depends on Haiku's output stability — likely rare but non-zero, especially after model updates.

**Fix idea:** Add a post-parse check: if `parsed_count < total_papers * 0.5`, log a warning and retry. Consider a more permissive regex or structured output (JSON mode) for triage.

---

## Bug 6: Area-Keyword Map Staleness in Refiner

**Location:** `run_profile_refiner.py:530-556` (`_compute_support_ratios`), `run_profile_refiner.py:584-601` (`_update_area_keyword_map`)

**Mechanism:** The refiner maintains an `area_keyword_map` that tracks which keywords belong to which research areas. This map is only updated by the refiner itself — manual profile edits (adding/removing keywords or areas) don't update it. Additionally, `_compute_support_ratios()` uses `kw_grade.get(k.lower(), 4)` which assigns a phantom grade of 4 to deleted keywords still lingering in the map. This means deleted keywords continue to influence area-level grade decisions as medium-priority phantom entries.

**Impact:** After manual profile edits, the area_keyword_map diverges from reality. Deleted keywords haunt area grade calculations. Added keywords have no area association until the next refiner run. The phantom grade of 4 biases support ratios toward the middle, making the refiner less responsive to user preferences.

**Fix idea:** Rebuild `area_keyword_map` from scratch at the start of each refiner run by scanning current keywords. Use `kw_grade.get(k.lower())` with a `None` check to skip unknown keywords instead of defaulting to 4.

---

## Priority Assessment

| Bug | Frequency | Impact | Fix Complexity |
|-----|-----------|--------|----------------|
| #1 Late ratings | Medium (any rating >21 days) | High (corrupts refiner) | Medium |
| #2 ID mismatch | Low-Medium (journal papers) | High (papers vanish) | Low |
| #3 No timeout | Rare (publisher outage) | Critical (pipeline stall) | Low |
| #4 Stale sampling | Every run | Medium (score drift) | Low |
| #5 Format drops | Rare (model update) | High (papers vanish) | Low |
| #6 Map staleness | After manual edits | Medium (refiner drift) | Low |

Recommended fix order: #3 (low effort, prevents critical failure) → #2 (low effort, high impact) → #1 (medium effort, high impact) → #6 → #4 → #5.
