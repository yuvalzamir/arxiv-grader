# Hidden Bug Audit — Silent Quality Degraders

> Identified 2026-06-09. These bugs produce no errors or warnings but silently degrade digest quality, waste cost, or corrupt profile refinement.
>
> **Second audit round: 2026-07-20 — see bottom section** (multi-agent + manual review of the full daily path; 20+ new findings, 3 high-severity).

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

---

# Second Audit Round — 2026-07-20

Full daily-run path reviewed (orchestration, AI pipeline, fetch/scrapers, digest/ratings). Method: 4 parallel review agents (2 completed, 2 died on session limit; their slices re-reviewed manually). Findings verified against code unless marked *(unverified — from agent trace)*.

## High severity — ALL THREE FIXED 2026-07-20

H1: `run_daily.py` now sweeps dedup+archive over the last 3 days (Monday covers Fri–Sun; idempotent, missing folders are no-ops). H2: `_load_profile_safe()` guards every profile load in `run_all_users.py`; bad-profile users are excluded, logged, and reported FAILED in the summary. H3: `archive.py` backs up a corrupt archive to `archive.json.corrupt` and aborts instead of starting fresh, and writes via tmp-file + `os.replace`. Deploy: `run_daily.py`, `run_all_users.py`, `archive.py`.

### H1. Friday-digest ratings are never archived, then permanently deleted
`run_daily.py:257-258` — dedup/archive always process `yesterday = today − 1`. Cron is now Mon–Fri (was Tue–Sat), so no run ever has Friday as yesterday: Monday archives Sunday's (empty) folder. Ratings on Friday digests (clicked Fri–Sun) sit in `data/FRI/ratings.json`, are never appended to `archive.json`, and are deleted by the 21-day cleanup. The refiner reads only `archive.json` → **~20% of all user feedback silently lost since the cron change**. Fix: Monday's run should archive Fri+Sat+Sun (loop over all unarchived dates, or archive every folder with an unarchived ratings.json).

### H2. One malformed taste_profile.json aborts the entire run for all users
`run_all_users.py:172-175` (`_user_field`), called unguarded in all-users loops at 791 (daily, before any fetch), 737, 998, 1049. A truncated/hand-edited profile JSON for one user → `JSONDecodeError` → no user gets a digest, and the crash precedes the run-summary email. Fix: try/except per user, mark that user FAILED, continue.

### H3. Corrupted archive.json is silently wiped on the next run
`archive.py:22-29` — on `JSONDecodeError`, `load_archive` prints a warning and returns `[]` ("Starting fresh"); the day's ratings are then appended and `write_text` **overwrites the permanent history with only today's entries**. Combined with the non-atomic write at `archive.py:77-80`, a crash mid-write → corrupted file → next run destroys the user's entire ratings history. Fix: on parse failure, back up the corrupt file and abort the archive step (never overwrite); write via tmp file + `os.replace`.

## Medium severity

- **M1. `paper_insights` opt-in does not exist in code** — `run_pipeline.py:776` hardcodes `scoring_insights.txt` for every user; no `.py` file references the flag. Either an undocumented full rollout (CLAUDE.md + [[Paper Insights]] stale) or a lost feature. **Needs user ruling before fixing docs or code.**
- **M2. Triage caps are 10+10, not the documented 15+15** — `run_pipeline.py:35-36` vs CLAUDE.md/TODO.md. **Needs user ruling** (intentional tuning with stale docs?).
- **M3. Scoring join crashes on malformed entry** — `run_pipeline.py:688` `item["arxiv_id"]` raises KeyError if one returned score entry lacks the key; one bad entry kills the run post-billing. Use `.get()` + warn.
- **M4.** *(unverified — from agent trace)* Triage batch-timeout fallback never writes `batch_fallback.json` (`run_pipeline.py:479-513`) — only scoring does — so the alert-email scan misses triage fallbacks (silent 2× cost).
- **M5.** *(unverified — from agent trace)* Scoring fallback fires only on `BatchTimeoutError`; a batch ending `errored`/`expired` hits `sys.exit(1)` (`run_pipeline.py:403-416`) without trying the direct API that is the documented recovery.
- **M6. Liked-papers join-key mismatch** — archive entries key on `paper_id` but `_sample_liked_papers` dedups/renders by `arxiv_id` (`run_pipeline.py:207,227`): dedup vs. profile seeds never works (possible duplicate few-shots) and every archive-sampled liked paper renders as `[journal]`. (Irrelevant-papers block at line 234 uses the correct key.)
- **M7.** *(unverified — from agent trace)* Watermark snapshot overwritten on retry — `run_all_users.py:786-789` re-copies now-advanced watermarks over `journal_watermarks_snapshot.json` on every invocation incl. `run_failed_users` retries, destroying the recovery point exactly when it's needed (TODO #2's manual restore).
- **M8.** *(unverified — from agent trace)* `run_daily.py:180-189` cleanup cutoffs against `date.today()` (ignores `--date`) with a raw string compare and no date-format guard: rebuilding an old digest deletes the folder just created; any non-date dir sorting below cutoff is rmtree'd.
- **M9.** *(unverified — from agent trace)* Weekly phase triggers on retry runs (`run_all_users.py:1045-1074`) → duplicate weekly digest email when retrying a user on their weekly day.
- **M10. Rebuilt digests carry wrong rating dates** — `build_digest_pdf.py` has no `--date` flag; rating URLs and header use `date.today()` (lines 506, 534). A `--date` recovery rebuild emails a PDF whose rating links point at today's folder → ratings recorded against the wrong date, score enrichment misses (feeds known bug #1's phantom-signal path).
- **M11. Per-article scrape errors are permanently skipped** — `sources.py:331-334` logs and skips a failed article, but `max_date` still advances past it via later entries and the watermark moves on; the paper is never seen again. Frequent-but-transient publisher 50x errors = slow silent leak.
- **M12. `feedparser.parse()` timeout fix (bug #3) only landed in sources.py** — `fetch_papers.py:138` and `fetch_preprints.py:106,179` still call it bare; a hung arXiv/bioRxiv feed still stalls the pipeline indefinitely.

## Low severity

- **L1. Preprints presented as peer-reviewed** — `run_pipeline.py:108-109` emits `source: journal` for any truthy source incl. bioRxiv/medRxiv; scoring prompt tells Sonnet that means published+peer-reviewed.
- **L2.** *(unverified)* NO-RUN (None) results force exit 1 while summary email says all-OK (`run_all_users.py:1110`) — quiet days on journals-only fields look like cron failures.
- **L3.** *(unverified)* Legacy profiles without `"field"` are unretryable: `run_failed_users.py:114-116` doesn't apply the `cond-mat` default that `_user_field` does.
- **L4.** *(unverified)* Evening manual runs without `--date` straddle midnight: parent fixes date at start, `run_daily` recomputes → children look for next-day folders.
- **L5.** *(unverified)* `--date` reruns >3 days old: end-of-run `cleanup_old_shared_folders` deletes the shared folder the rerun just used (`run_all_users.py:209-224,1038`).
- **L6.** *(unverified)* Weekly-send failures appear in the email summary but not in the log block `run_failed_users.py` parses — the recovery tool can't see them.
- **L7.** *(unverified)* Best-effort batch cancel on timeout can double-bill (batch completes anyway + direct call).
- **L8. PDF build crash on null insight values** — `build_digest_pdf.py:406` `.strip()` on a None `claim/novelty/relevance` → AttributeError kills the digest.
- **L9. Tags not XML-escaped in PDF** — `build_digest_pdf.py:425` joins raw tag strings into Paragraph markup (justification *is* escaped); a model tag containing `&`/`<` can crash the build.
- **L10. Undated feed entries re-scraped every run** — `sources.py:279-283`: `entry_date is None` bypasses both the watermark and the same-day skip, and never advances `max_date` → papers from date-less feeds recur in consecutive digests.
- **L11. `fetch_preprints.py` exit code is vestigial** — `any_error` never set; blocked/403 feeds are indistinguishable from legitimately empty ones (same silent-death mode as the ACS outage).

## Recommended fix order

H1 → H3 → H2 (data loss, all small fixes) → M3/M12/L8 (crash-proofing, one-liners) → M10+M8 (recovery-run correctness) → M4/M5 (fallback robustness) → user rulings on M1/M2 → the rest opportunistically.
