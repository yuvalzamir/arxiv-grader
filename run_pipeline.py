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
LIKED_PAPERS_WINDOW = 5   # how many recent liked papers to show the scoring agent
MAX_TRIAGE_PASS         = 20  # hard cap on arXiv papers forwarded to scoring
MAX_TRIAGE_PASS_JOURNAL = 10  # hard cap on journal papers forwarded to scoring

BATCH_POLL_INTERVAL = 15   # seconds between batch status checks
BATCH_TIMEOUT       = 3600 # give up after 1 hour

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
    lines += [
        f"arxiv_id: {paper['arxiv_id']}",
        f"title: {paper['title']}",
        f"authors: {', '.join(paper['authors']) if paper.get('authors') else 'unknown'}",
        f"subcategories: {', '.join(paper.get('subcategories', [])) or 'unknown'}",
        f"abstract: {paper.get('abstract', '(not available)')}",
    ]
    return "\n".join(lines)


def build_triage_message(papers: list[dict], profile: dict) -> str:
    categories = ", ".join(profile.get("arxiv_categories", [])) or "not specified"

    header = (
        f"TASTE PROFILE\n"
        f"=============\n"
        f"Monitored categories: {categories}\n\n"
        f"Keywords (grade 1 = most relevant, grade 7 = fading):\n{_keywords_str(profile.get('keywords', []))}\n\n"
        f"Research areas (grade 1 = most relevant, grade 7 = fading):\n{_areas_str(profile.get('research_areas', []))}\n\n"
        f"Followed authors (rank 1 = highest priority):\n{_authors_str(profile.get('authors', []))}"
    )

    paper_blocks = "\n\n".join(_paper_block(i + 1, p) for i, p in enumerate(papers))

    return (
        f"{header}\n\n"
        f"---\n\n"
        f"PAPERS TO TRIAGE ({len(papers)} total)\n"
        f"{'=' * 30}\n\n"
        f"{paper_blocks}"
    )


def build_scoring_message(filtered_papers: list[dict], profile: dict) -> str:
    categories = ", ".join(profile.get("arxiv_categories", [])) or "not specified"
    evolved = profile.get("evolved_interests", "").strip() or "(not yet populated)"

    # Last N liked papers (most recent signal).
    recent_liked = profile.get("liked_papers", [])[-LIKED_PAPERS_WINDOW:]
    liked_str = "\n".join(
        f"  - [{p.get('arxiv_id') or 'journal'}] {p['title']} — {p.get('why_relevant', '')}"
        for p in recent_liked
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
        f"Recently liked papers (most recent {LIKED_PAPERS_WINDOW}):\n{liked_str}"
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
        batch = client.messages.batches.retrieve(batch.id)
        if batch.processing_status == "ended":
            break
        if time.time() > deadline:
            log.error("%s: batch timed out after %d seconds.", label, BATCH_TIMEOUT)
            sys.exit(1)
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

def run_triage(papers: list[dict], profile: dict, system_prompt: str) -> list[dict]:
    """
    Run the triage agent. Returns only high- and medium-classified papers,
    with a 'triage' field added.
    """
    client = Anthropic()
    user_message = build_triage_message(papers, profile)

    log.info("Running triage on %d papers (model: %s)...", len(papers), TRIAGE_MODEL)

    response = _submit_and_poll(
        client, "triage", TRIAGE_MODEL, 4096, system_prompt, user_message, "Triage",
    )

    # Parse "N: label" lines in output order — output order is the ranking.
    # First occurrence of each paper index wins; duplicates are ignored.
    ranked_labels: list[tuple[int, str]] = []
    seen_indices: set[int] = set()
    counts = {"high": 0, "medium": 0, "low": 0}
    for line in response.content[0].text.strip().splitlines():
        m = re.match(r"\[?(\d+)\]?\s*[-:]\s*(high|medium|low)", line.strip(), re.IGNORECASE)
        if m:
            idx, label = int(m.group(1)), m.group(2).lower()
            if idx in seen_indices:
                continue
            seen_indices.add(idx)
            ranked_labels.append((idx, label))
            counts[label] = counts.get(label, 0) + 1

    if not ranked_labels:
        log.error("Triage output contained no parseable labels. Raw response:\n%s",
                  response.content[0].text[:800])
        sys.exit(1)

    log.info(
        "Triage results — high: %d, medium: %d, low: %d",
        counts["high"], counts["medium"], counts["low"],
    )

    # Build index lookup: paper number (1-based) → paper dict.
    paper_by_index = {i + 1: paper for i, paper in enumerate(papers)}

    # Walk ranked output in order; apply separate caps for arXiv and journal papers.
    # A paper is a journal paper if it has a non-empty "source" field.
    filtered = []
    arxiv_count = journal_count = 0
    for idx, label in ranked_labels:
        if label not in ("high", "medium"):
            continue
        if idx not in paper_by_index:
            continue
        paper = paper_by_index[idx]
        if paper.get("source"):
            if journal_count >= MAX_TRIAGE_PASS_JOURNAL:
                continue
            journal_count += 1
        else:
            if arxiv_count >= MAX_TRIAGE_PASS:
                continue
            arxiv_count += 1
        filtered.append({**paper, "triage": label})

    qualifying = counts["high"] + counts["medium"]
    log.info(
        "%d papers passed triage (arXiv: %d/%d, journals: %d/%d; %d qualifying not forwarded).",
        len(filtered),
        arxiv_count, MAX_TRIAGE_PASS,
        journal_count, MAX_TRIAGE_PASS_JOURNAL,
        qualifying - len(filtered),
    )
    return filtered


# ---------------------------------------------------------------------------
# Stage 2 — Scoring (Sonnet)
# ---------------------------------------------------------------------------

def run_scoring(filtered_papers: list[dict], profile: dict, system_prompt: str) -> list[dict]:
    """
    Run the scoring agent. Returns filtered_papers with score, justification,
    and tags merged in, sorted by score descending.
    """
    client = Anthropic()
    user_message = build_scoring_message(filtered_papers, profile)

    log.info("Scoring %d papers (model: %s)...", len(filtered_papers), SCORING_MODEL)

    response = _submit_and_poll(
        client, "scoring", SCORING_MODEL, 8192, system_prompt, user_message, "Scoring",
    )

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
    args = parser.parse_args()

    # Check API key before doing anything.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.error(
            "ANTHROPIC_API_KEY is not set.\n"
            "  Create a .env file in this directory with:\n"
            "      ANTHROPIC_API_KEY=sk-ant-..."
        )
        sys.exit(1)

    # Load inputs.
    papers  = load_json(args.papers)
    profile = load_json(args.profile)
    log.info("Loaded %d papers from %s", len(papers), args.papers)

    if not papers:
        log.warning("No papers found in %s. Exiting.", args.papers)
        sys.exit(0)

    # Load prompts.
    triage_prompt  = load_prompt("triage.txt")
    scoring_prompt = load_prompt("scoring.txt")

    # --- Stage 1: triage ---
    filtered = run_triage(papers, profile, triage_prompt)

    with open(args.filtered, "w", encoding="utf-8") as f:
        json.dump(filtered, f, indent=2, ensure_ascii=False)
    log.info("Wrote %d filtered papers to %s", len(filtered), args.filtered)

    if not filtered:
        log.warning("No papers passed triage. Nothing to score.")
        sys.exit(0)

    # --- Stage 2: scoring ---
    scored = run_scoring(filtered, profile, scoring_prompt)

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
