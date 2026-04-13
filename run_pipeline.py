#!/usr/bin/env python3
"""
run_pipeline.py — Daily arXiv grading pipeline.

Reads today_papers.json and taste_profile.json, runs two sequential
Claude calls (triage → scoring), and writes filtered_papers.json and
scored_papers.json.

Usage:
    python run_pipeline.py
    python run_pipeline.py --papers today_papers.json --profile taste_profile.json
"""

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

PROMPTS_DIR = Path(__file__).parent / "prompts"
TRIAGE_MODEL  = "claude-haiku-4-5-20251001"
SCORING_MODEL = "claude-sonnet-4-6"
LIKED_MAX         = 5   # max liked papers shown to scoring agent
LIKED_SAMPLE_SIZE = 10  # how many archive entries to randomly sample from
MAX_TRIAGE_PASS         = 15  # hard cap on arXiv papers forwarded to scoring
MAX_TRIAGE_PASS_JOURNAL = 15  # hard cap on journal papers forwarded to scoring

BATCH_POLL_INTERVAL = 15   # seconds between batch status checks
BATCH_TIMEOUT       = 3600 # give up after 1 hour

ALERT_EMAIL = "yuval.zamir@icfo.eu"  # recipient for batch-timeout alerts


class BatchTimeoutError(Exception):
    """Raised when the Batch API job exceeds BATCH_TIMEOUT."""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------

def load_json(path: str) -> list | dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        log.error("File not found: %s", path)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        log.error("Invalid JSON in %s: %s", path, exc)
        sys.exit(1)


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    if not path.exists():
        log.error("Prompt file not found: %s", path)
        sys.exit(1)
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------

def _keywords_str(keywords: list[dict]) -> str:
    return "\n".join(
        f"  grade {kw['grade']}: {kw['keyword']}"
        for kw in sorted(keywords, key=lambda x: x["grade"])
    ) or "  (none)"


def _areas_str(areas: list[dict]) -> str:
    return "\n".join(
        f"  grade {a['grade']}: {a['area']}"
        for a in sorted(areas, key=lambda x: x["grade"])
    ) or "  (none)"


def _authors_str(authors: list[dict]) -> str:
    return "\n".join(
        f"  {a['rank']:2d}. {a['name']}"
        for a in sorted(authors, key=lambda x: x["rank"])
    ) or "  (none)"


def _paper_block(i: int, paper: dict, include_triage: bool = False) -> str:
    lines = [f"[{i}]"]
    if include_triage:
        lines.append(f"triage: {paper.get('triage', 'unknown')}")
        if paper.get("source"):
            lines.append("source: journal")
    lines += [
        f"arxiv_id: {paper['arxiv_id']}",
        f"title: {paper['title']}",
        f"authors: {', '.join(paper['authors']) if paper.get('authors') else 'unknown'}",
        f"subcategories: {', '.join(paper.get('subcategories', [])) or 'unknown'}",
        f"abstract: {paper.get('abstract', '(not available)')}",
    ]
    return "\n".join(lines)


def build_triage_papers_block(papers: list[dict]) -> str:
    """Cacheable prefix: the paper list (identical for all users in a field)."""
    paper_blocks = "\n\n".join(_paper_block(i + 1, p) for i, p in enumerate(papers))
    return (
        f"PAPERS TO TRIAGE ({len(papers)} total)\n"
        f"{'=' * 30}\n\n"
        f"{paper_blocks}"
    )


def build_triage_profile_block(profile: dict) -> str:
    """Non-cached suffix: the user's taste profile (varies per user)."""
    subcategories = profile.get("arxiv_subcategories", [])
    categories = ", ".join(subcategories) if subcategories else profile.get("field", "not specified")
    return (
        f"TASTE PROFILE\n"
        f"=============\n"
        f"Monitored categories: {categories}\n\n"
        f"Keywords (grade 1 = most relevant, grade 7 = fading):\n{_keywords_str(profile.get('keywords', []))}\n\n"
        f"Research areas (grade 1 = most relevant, grade 7 = fading):\n{_areas_str(profile.get('research_areas', []))}\n\n"
        f"Followed authors (rank 1 = highest priority):\n{_authors_str(profile.get('authors', []))}"
    )


def _sample_liked_papers(archive: list[dict], seed_papers: list[dict]) -> list[dict]:
    """
    Build the liked-papers list for the scoring prompt:
    1. Randomly sample LIKED_SAMPLE_SIZE entries from the archive.
    2. Keep those rated 'excellent', up to LIKED_MAX.
    3. Pad with seed_papers from the profile if still under LIKED_MAX.
    4. Return however many we have (may be fewer than LIKED_MAX).
    """
    sample = random.sample(archive, min(LIKED_SAMPLE_SIZE, len(archive))) if archive else []
    excellent = [e for e in sample if e.get("rating", "").lower() == "excellent"][:LIKED_MAX]

    if len(excellent) >= LIKED_MAX:
        return excellent

    seen_ids = {e.get("arxiv_id") for e in excellent}
    padding = [p for p in seed_papers if p.get("arxiv_id") not in seen_ids]
    return excellent + padding[:LIKED_MAX - len(excellent)]


def build_scoring_message(filtered_papers: list[dict], profile: dict, archive: list[dict] | None = None) -> str:
    categories = profile.get("field", "not specified")
    evolved = profile.get("evolved_interests", "").strip() or "(not yet populated)"

    # Liked papers: sample from archive (excellent-rated), pad with seed papers.
    seed_papers = profile.get("liked_papers", [])
    liked = _sample_liked_papers(archive or [], seed_papers)
    liked_str = "\n".join(
        f"  - [{p.get('arxiv_id') or 'journal'}] {p['title']} — {p.get('why_relevant', '')}"
        for p in liked
    ) or "  (none)"

    header = (
        f"TASTE PROFILE\n"
        f"=============\n"
        f"Monitored categories: {categories}\n\n"
        f"Research interests:\n{profile.get('interests_description', '(not provided)')}\n\n"
        f"Keywords (grade 1 = most relevant, grade 7 = fading):\n{_keywords_str(profile.get('keywords', []))}\n\n"
        f"Research areas (grade 1 = most relevant, grade 7 = fading):\n{_areas_str(profile.get('research_areas', []))}\n\n"
        f"Followed authors (rank 1 = highest priority):\n{_authors_str(profile.get('authors', []))}\n\n"
        f"Recent trajectory (evolved interests):\n{evolved}\n\n"
        f"Recently liked papers (up to {LIKED_MAX}, sampled from ratings):\n{liked_str}"
    )

    paper_blocks = "\n\n".join(
        _paper_block(i + 1, p, include_triage=True)
        for i, p in enumerate(filtered_papers)
    )

    return (
        f"{header}\n\n"
        f"---\n\n"
        f"PAPERS TO SCORE ({len(filtered_papers)} total)\n"
        f"{'=' * 30}\n\n"
        f"{paper_blocks}"
    )


# ---------------------------------------------------------------------------
# JSON parsing — three-tier fallback, handles arrays and objects
# ---------------------------------------------------------------------------

def parse_json_response(text: str, label: str) -> list | dict:
    """Parse a Claude response expected to be valid JSON (array or object)."""
    # Try 1: direct parse.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try 2: strip markdown fences then parse.
    stripped = "\n".join(
        line for line in text.splitlines()
        if not line.startswith("```")
    ).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # Try 3: extract first [...] or {...} block (handles leading prose).
    m = re.search(r"(\[[\s\S]*\]|\{[\s\S]*\})", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    log.error("%s: failed to parse JSON. Raw response (first 800 chars):\n%s", label, text[:800])
    sys.exit(1)


# ---------------------------------------------------------------------------
# Batch API helper
# ---------------------------------------------------------------------------

def _record_fallback(debug_dir: Path, stage: str, no_batch_succeeded: bool) -> None:
    """Append a fallback event to batch_fallback.json in the data folder."""
    fallback_path = debug_dir / "batch_fallback.json"
    events = json.loads(fallback_path.read_text()) if fallback_path.exists() else []
    events.append({"stage": stage, "no_batch_succeeded": no_batch_succeeded})
    fallback_path.write_text(json.dumps(events, indent=2))


def _call_direct(client: Anthropic, model: str, max_tokens: int,
                 system: str, user_message: str, label: str):
    """Call the messages API directly (synchronous, no batch queue). Used for scoring fallback."""
    log.info("%s: calling API directly (no-batch mode)...", label)
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    log.info("%s done. (input: %d tokens, output: %d tokens)",
             label, msg.usage.input_tokens, msg.usage.output_tokens)
    return msg


def _call_cached(client: Anthropic, model: str, max_tokens: int,
                 system: str, papers_block: str, profile_block: str, label: str):
    """Call the messages API with prompt caching (synchronous).

    The system prompt and papers block are marked for caching — they are identical
    for all users in the same field, so the first call warms the cache and subsequent
    users pay only the cache-read rate (~10% of normal input cost).
    The profile block is the non-cached per-user suffix.
    """
    log.info("%s: calling cached API...", label)
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": papers_block,
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": profile_block,
                },
            ],
        }],
    )
    cache_read    = getattr(msg.usage, "cache_read_input_tokens",    0) or 0
    cache_created = getattr(msg.usage, "cache_creation_input_tokens", 0) or 0
    log.info(
        "%s done. (input: %d tokens, output: %d tokens, cache_read: %d, cache_created: %d)",
        label, msg.usage.input_tokens, msg.usage.output_tokens, cache_read, cache_created,
    )
    return msg


def _submit_and_poll(client: Anthropic, custom_id: str, model: str, max_tokens: int,
                     system: str, user_message: str, label: str):
    """Submit a single-request batch, poll until complete, return the Message object."""
    batch = client.messages.batches.create(
        requests=[{
            "custom_id": custom_id,
            "params": {
                "model": model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user_message}],
            },
        }]
    )
    log.info("%s: batch submitted (id: %s). Polling every %ds...", label, batch.id, BATCH_POLL_INTERVAL)

    deadline = time.time() + BATCH_TIMEOUT
    while True:
        for attempt in range(3):
            try:
                batch = client.messages.batches.retrieve(batch.id)
                break
            except json.JSONDecodeError as e:
                if attempt == 2:
                    log.error("%s: batch retrieve returned empty/malformed body after 3 attempts: %s", label, e)
                    sys.exit(1)
                log.warning("%s: batch retrieve returned empty body (attempt %d), retrying in 5s...", label, attempt + 1)
                time.sleep(5)
        if batch.processing_status == "ended":
            break
        if time.time() > deadline:
            log.error("%s: batch timed out after %d seconds.", label, BATCH_TIMEOUT)
            raise BatchTimeoutError(label)
        time.sleep(BATCH_POLL_INTERVAL)

    for result in client.messages.batches.results(batch.id):
        if result.result.type == "succeeded":
            msg = result.result.message
            log.info(
                "%s done. (input: %d tokens, output: %d tokens)",
                label, msg.usage.input_tokens, msg.usage.output_tokens,
            )
            return msg
        else:
            log.error("%s: batch request failed with type '%s'.", label, result.result.type)
            sys.exit(1)

    log.error("%s: no results returned by batch.", label)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Stage 1 — Triage (Haiku)
# ---------------------------------------------------------------------------

def _run_single_triage(
    papers: list[dict], profile: dict, system_prompt: str, label: str,
    debug_dir: Path | None = None, api_key: str | None = None,
    use_batch: bool = False,
) -> list[tuple[dict, str]]:
    """
    Run triage for one paper list.
    Returns a list of (paper, triage_label) pairs in ranked order (best first),
    including all labels (high, medium, low).

    use_batch: if True, use the Batch API (50% cost discount, async).
               if False (default), use the cached synchronous API.
    api_key: if provided, used directly (centralized field key); otherwise reads from env.
    """
    client = Anthropic(api_key=api_key) if api_key else Anthropic()
    papers_block  = build_triage_papers_block(papers)
    profile_block = build_triage_profile_block(profile)

    if debug_dir:
        slug = label.lower().replace("-", "_")
        debug_path = debug_dir / f"{slug}_input.txt"
        mode = "batch" if use_batch else "cached"
        debug_path.write_text(
            f"=== SYSTEM ({mode}) ===\n{system_prompt}\n\n"
            f"=== USER BLOCK 1: PAPERS ===\n{papers_block}\n\n"
            f"=== USER BLOCK 2: PROFILE ===\n{profile_block}",
            encoding="utf-8",
        )
        log.info("%s: prompt saved to %s", label, debug_path)

    log.info("%s: running on %d papers (model: %s, mode: %s)...",
             label, len(papers), TRIAGE_MODEL, "batch" if use_batch else "cached")
    if use_batch:
        custom_id = label.lower().replace(" ", "-")
        user_message = f"{papers_block}\n\n{profile_block}"
        try:
            response = _submit_and_poll(client, custom_id, TRIAGE_MODEL, 4096, system_prompt, user_message, label)
        except BatchTimeoutError:
            log.warning("%s: batch timed out — falling back to cached API.", label)
            response = _call_cached(client, TRIAGE_MODEL, 4096, system_prompt, papers_block, profile_block, label)
    else:
        response = _call_cached(client, TRIAGE_MODEL, 4096, system_prompt, papers_block, profile_block, label)

    ranked: list[tuple[dict, str]] = []
    seen: set[int] = set()
    counts = {"high": 0, "medium": 0, "low": 0}
    paper_by_index = {i + 1: p for i, p in enumerate(papers)}

    for line in response.content[0].text.strip().splitlines():
        m = re.match(r"\[?(\d+)\]?\s*[-:]\s*(high|medium|low)", line.strip(), re.IGNORECASE)
        if m:
            idx, lbl = int(m.group(1)), m.group(2).lower()
            if idx in seen or idx not in paper_by_index:
                continue
            seen.add(idx)
            ranked.append((paper_by_index[idx], lbl))
            counts[lbl] = counts.get(lbl, 0) + 1

    if not ranked:
        log.error("%s: output contained no parseable labels. Raw response:\n%s",
                  label, response.content[0].text[:800])
        sys.exit(1)

    log.info("%s results — high: %d, medium: %d, low: %d",
             label, counts["high"], counts["medium"], counts["low"])
    return ranked


def run_triage(
    papers: list[dict], profile: dict,
    system_prompt: str, journal_system_prompt: str,
    debug_dir: Path | None = None, api_key: str | None = None,
    use_batch: bool = False,
    use_batch_arxiv: bool | None = None,
    use_batch_journals: bool | None = None,
) -> list[dict]:
    """
    Run triage in two separate calls (arXiv and journals) to avoid
    cross-pool calibration effects. Returns only high/medium papers with
    'triage' field added, capped independently per source type.

    use_batch_arxiv / use_batch_journals: per-call overrides. If not set,
    both fall back to use_batch. This allows the token-budget check in
    run_all_users.py to force Batch API for whichever call exceeds 45k tokens
    without affecting the other call.
    """
    arxiv_papers  = [p for p in papers if not p.get("source")]
    journal_papers = [p for p in papers if p.get("source")]

    batch_arxiv   = use_batch_arxiv   if use_batch_arxiv   is not None else use_batch
    batch_journals = use_batch_journals if use_batch_journals is not None else use_batch

    arxiv_ranked:  list[tuple[dict, str]] = []
    journal_ranked: list[tuple[dict, str]] = []

    # Always run the cached call before the batch call so the cache is still
    # warm (warmed by the previous user in the field) when it fires. Batch calls
    # are not subject to the 50k token/minute cached-API limit and can run after.
    arxiv_first = not batch_arxiv or batch_journals  # cached arXiv goes first unless journals is also cached (default order)
    if arxiv_first:
        if arxiv_papers:
            arxiv_ranked = _run_single_triage(
                arxiv_papers, profile, system_prompt, "Triage-arXiv", debug_dir, api_key, batch_arxiv
            )
        if journal_papers:
            journal_ranked = _run_single_triage(
                journal_papers, profile, journal_system_prompt, "Triage-journals", debug_dir, api_key, batch_journals
            )
    else:
        # arXiv is batch, journals is cached — run journals first
        if journal_papers:
            journal_ranked = _run_single_triage(
                journal_papers, profile, journal_system_prompt, "Triage-journals", debug_dir, api_key, batch_journals
            )
        if arxiv_papers:
            arxiv_ranked = _run_single_triage(
                arxiv_papers, profile, system_prompt, "Triage-arXiv", debug_dir, api_key, batch_arxiv
            )

    # Apply caps independently for each source type.
    filtered = []
    arxiv_count = journal_count = 0
    arxiv_qualifying = journal_qualifying = 0

    for paper, label in arxiv_ranked:
        if label in ("high", "medium"):
            arxiv_qualifying += 1
            if arxiv_count < MAX_TRIAGE_PASS:
                filtered.append({**paper, "triage": label})
                arxiv_count += 1

    for paper, label in journal_ranked:
        if label in ("high", "medium"):
            journal_qualifying += 1
            if journal_count < MAX_TRIAGE_PASS_JOURNAL:
                filtered.append({**paper, "triage": label})
                journal_count += 1

    not_forwarded = (arxiv_qualifying - arxiv_count) + (journal_qualifying - journal_count)
    log.info(
        "%d papers passed triage (arXiv: %d/%d, journals: %d/%d; %d qualifying not forwarded).",
        len(filtered),
        arxiv_count, MAX_TRIAGE_PASS,
        journal_count, MAX_TRIAGE_PASS_JOURNAL,
        not_forwarded,
    )
    return filtered


# ---------------------------------------------------------------------------
# Stage 2 — Scoring (Sonnet)
# ---------------------------------------------------------------------------

def run_scoring(filtered_papers: list[dict], profile: dict, system_prompt: str, archive: list[dict] | None = None, debug_dir: Path | None = None, use_batch: bool = True) -> list[dict]:
    """
    Run the scoring agent. Returns filtered_papers with score, justification,
    and tags merged in, sorted by score descending.
    """
    client = Anthropic()
    user_message = build_scoring_message(filtered_papers, profile, archive)

    if debug_dir:
        debug_path = debug_dir / "scoring_input.txt"
        debug_path.write_text(
            f"=== SYSTEM ===\n{system_prompt}\n\n=== USER ===\n{user_message}",
            encoding="utf-8",
        )
        log.info("Scoring: prompt saved to %s", debug_path)

    log.info("Scoring %d papers (model: %s)...", len(filtered_papers), SCORING_MODEL)

    no_batch_succeeded = None
    try:
        if use_batch:
            response = _submit_and_poll(
                client, "scoring", SCORING_MODEL, 8192, system_prompt, user_message, "Scoring",
            )
        else:
            response = _call_direct(client, SCORING_MODEL, 8192, system_prompt, user_message, "Scoring")
    except BatchTimeoutError:
        log.warning("Scoring: batch timed out — retrying with direct API...")
        try:
            response = _call_direct(client, SCORING_MODEL, 8192, system_prompt, user_message, "Scoring")
            no_batch_succeeded = True
        except Exception as e:
            no_batch_succeeded = False
            if debug_dir:
                _record_fallback(debug_dir, "Scoring", no_batch_succeeded)
            log.error("Scoring: direct API also failed: %s", e)
            sys.exit(1)
    if no_batch_succeeded is not None and debug_dir:
        _record_fallback(debug_dir, "Scoring", no_batch_succeeded)

    scores = parse_json_response(response.content[0].text.strip(), "scoring")
    if not isinstance(scores, list):
        log.error("Scoring output is not a JSON array.")
        sys.exit(1)

    # Build lookup: arxiv_id → scoring fields.
    score_map = {item["arxiv_id"]: item for item in scores}

    scored = []
    for paper in filtered_papers:
        s = score_map.get(paper["arxiv_id"], {})
        scored.append({
            **paper,
            "score": s.get("score", 0),
            "justification": s.get("justification", ""),
            "tags": s.get("tags", []),
        })

    # Sort highest score first.
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run the daily arXiv grading pipeline (triage → scoring)."
    )
    parser.add_argument(
        "--papers", default="today_papers.json",
        help="Input papers JSON (default: today_papers.json)",
    )
    parser.add_argument(
        "--profile", default="taste_profile.json",
        help="User taste profile JSON (default: taste_profile.json)",
    )
    parser.add_argument(
        "--filtered", default="filtered_papers.json",
        help="Output path for triage results (default: filtered_papers.json)",
    )
    parser.add_argument(
        "--scored", default="scored_papers.json",
        help="Output path for scoring results (default: scored_papers.json)",
    )
    parser.add_argument(
        "--journals", default=None,
        help="Optional path to filtered journal papers JSON to merge before triage.",
    )
    parser.add_argument(
        "--archive", default=None,
        help="Optional path to archive.json for sampling excellent-rated papers.",
    )
    parser.add_argument(
        "--no-batch", action="store_true",
        help="Use synchronous API for scoring instead of Batch API (faster, no queue, 2x cost).",
    )
    parser.add_argument(
        "--skip-triage", action="store_true",
        help="Skip triage stage — assume --filtered file already exists (written by centralized triage).",
    )
    args = parser.parse_args()

    # Load inputs.
    papers  = load_json(args.papers)
    profile = load_json(args.profile)
    archive = load_json(args.archive) if args.archive and Path(args.archive).exists() else []
    log.info("Loaded %d arXiv papers from %s", len(papers), args.papers)

    if args.journals:
        journal_papers = load_json(args.journals)
        log.info("Loaded %d journal papers from %s", len(journal_papers), args.journals)
        papers = papers + journal_papers  # arXiv first

    if not papers:
        log.warning("No papers found in %s. Exiting.", args.papers)
        sys.exit(0)

    # Load prompts.
    triage_prompt         = load_prompt("triage.txt")
    triage_journal_prompt = load_prompt("triage_journals.txt")
    scoring_prompt        = load_prompt("scoring.txt")

    # --- Stage 1: triage ---
    debug_dir = Path(args.filtered).parent
    if args.skip_triage:
        filtered = load_json(args.filtered)
        log.info("Triage skipped — loaded %d pre-filtered papers from %s", len(filtered), args.filtered)
    else:
        filtered = run_triage(papers, profile, triage_prompt, triage_journal_prompt, debug_dir)
        with open(args.filtered, "w", encoding="utf-8") as f:
            json.dump(filtered, f, indent=2, ensure_ascii=False)
        log.info("Wrote %d filtered papers to %s", len(filtered), args.filtered)

    if not filtered:
        log.warning("No papers passed triage. Nothing to score.")
        sys.exit(0)

    # --- Stage 2: scoring ---
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.error(
            "ANTHROPIC_API_KEY is not set.\n"
            "  Create a .env file in this directory with:\n"
            "      ANTHROPIC_API_KEY=sk-ant-..."
        )
        sys.exit(1)
    use_batch = not args.no_batch
    scored = run_scoring(filtered, profile, scoring_prompt, archive, debug_dir, use_batch)

    with open(args.scored, "w", encoding="utf-8") as f:
        json.dump(scored, f, indent=2, ensure_ascii=False)
    log.info("Wrote %d scored papers to %s", len(scored), args.scored)

    # Print a quick summary of the top results.
    print()
    print("=" * 60)
    print(f"  Grading complete — {len(scored)} papers scored")
    print("=" * 60)
    for paper in scored[:5]:
        tags_str = f"  [{', '.join(paper['tags'])}]" if paper["tags"] else ""
        print(f"  {paper['score']:2d}/10  {paper['title'][:52]}{tags_str}")
    if len(scored) > 5:
        print(f"  ... and {len(scored) - 5} more. Full results in {args.scored}")
    print()


if __name__ == "__main__":
    main()
