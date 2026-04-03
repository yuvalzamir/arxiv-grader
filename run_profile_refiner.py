#!/usr/bin/env python3
"""
run_profile_refiner.py — Monthly taste profile refiner.

Reads the last 30 days of ratings from archive.json, calls Claude Sonnet to
recommend interest-shift adjustments, then applies the changes to taste_profile.json.

Grade rules applied by Python (not by Claude):
  - Grade changes are ±1 per month maximum (Claude signals direction only)
  - Grade is clamped to 1–7 after adjustment
  - Keywords/areas that were already at grade 7 before this run and are still at grade 7
    after are removed. Items that only reached grade 7 this run are kept — they get one
    more month before removal (natural ~3-month trial period for newly added keywords).

Usage:
    python run_profile_refiner.py
    python run_profile_refiner.py --days 30 --dry-run
    python run_profile_refiner.py --archive archive.json --profile taste_profile.json
"""

import argparse
import json
import logging
import os
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()  # load root .env first; user .env loaded in main() after arg parsing

PROMPTS_DIR    = Path(__file__).parent / "prompts"
ARCHIVE_PATH   = Path(__file__).parent / "archive.json"
PROFILE_PATH   = Path(__file__).parent / "taste_profile.json"
REFINER_MODEL       = "claude-sonnet-4-6"
WINDOW_DAYS         = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def load_json(path: Path) -> list | dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
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
# Batch API helper
# ---------------------------------------------------------------------------

def _call_direct(client: Anthropic, model: str, max_tokens: int,
                 system: str, user_message: str, label: str):
    """Call the Messages API directly (synchronous). Returns the Message object."""
    log.info("%s: sending request...", label)
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[
            {"role": "user", "content": user_message},
        ],
    )
    log.info(
        "%s done. (input: %d tokens, output: %d tokens)",
        label, msg.usage.input_tokens, msg.usage.output_tokens,
    )
    if msg.usage.output_tokens >= max_tokens * 0.9:
        log.warning(
            "%s: output tokens (%d) close to max_tokens (%d) — response may be truncated.",
            label, msg.usage.output_tokens, max_tokens,
        )
    return msg


# ---------------------------------------------------------------------------
# Archive filtering
# ---------------------------------------------------------------------------

def filter_recent(archive: list[dict], days: int) -> list[dict]:
    """Return archive entries from the last `days` days (inclusive)."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return [e for e in archive if e.get("date", "") >= cutoff]


# ---------------------------------------------------------------------------
# Message builder
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


def _paper_entry(entry: dict, include_abstract: bool = False) -> str:
    """Format one archive entry for the refiner message."""
    score = entry.get("score")
    score_str = f"  pipeline score: {score}/10" if score else "  pipeline score: (not triaged / no score)"
    tags_str = f"  tags: {', '.join(entry['tags'])}" if entry.get("tags") else ""
    just_str = f"  justification: {entry['justification']}" if entry.get("justification") else ""
    authors_str = f"  authors: {', '.join(entry['authors'])}" if entry.get("authors") else ""
    abstract_str = ""
    if include_abstract and entry.get("abstract"):
        abstract_str = f"  abstract: {entry['abstract'][:300]}{'...' if len(entry.get('abstract','')) > 300 else ''}"
    lines = [
        f"  [{entry.get('paper_id', '?')}] {entry.get('title', '(no title)')}",
        authors_str,
        score_str,
        just_str,
        tags_str,
        abstract_str,
    ]
    return "\n".join(l for l in lines if l.strip())


def _get_score(entry: dict) -> int | None:
    """Return numeric score, or None if the paper wasn't triaged/scored."""
    s = entry.get("score")
    if s is None or s == 0:
        return None
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def build_discrepancy_section(recent_ratings: list[dict]) -> str:
    """
    Identify papers where the pipeline score and user rating diverged significantly.
    Returns a formatted text section for the refiner message.
    """
    overconfident_high: list[dict] = []   # score ≥ 7, rated irrelevant
    overconfident_mild: list[dict] = []   # score ≥ 8, rated good
    missed_excellent:   list[dict] = []   # no score or score ≤ 3, rated excellent
    missed_good:        list[dict] = []   # no score or score ≤ 3, rated good
    underscored:        list[dict] = []   # score 4–6, rated excellent

    for entry in recent_ratings:
        rating = entry.get("rating", "").lower()
        score  = _get_score(entry)

        if rating == "irrelevant" and score is not None and score >= 7:
            overconfident_high.append(entry)
        elif rating == "good" and score is not None and score >= 8:
            overconfident_mild.append(entry)
        elif rating in ("excellent", "good") and (score is None or score <= 3):
            if rating == "excellent":
                missed_excellent.append(entry)
            else:
                missed_good.append(entry)
        elif rating == "excellent" and score is not None and 4 <= score <= 6:
            underscored.append(entry)

    def disc_section(label: str, entries: list[dict], include_abstract: bool = False) -> str:
        if not entries:
            return f"{label} (0 papers): (none)"
        lines = [f"{label} ({len(entries)} papers):"]
        for e in entries:
            lines.append(_paper_entry(e, include_abstract=include_abstract))
        return "\n".join(lines)

    total = len(overconfident_high) + len(overconfident_mild) + len(missed_excellent) + len(missed_good) + len(underscored)

    parts = [
        f"SCORE-RATING DISCREPANCIES ({total} total)",
        "=" * 42,
        "Papers where the pipeline's score and the user's rating diverged significantly.",
        "The justification field shows which keyword/signal drove the pipeline's score.",
        "",
        disc_section(
            "OVERCONFIDENT — scored ≥7 but user said IRRELEVANT (strongest negative signal)",
            overconfident_high,
        ),
        "",
        disc_section(
            "OVERCONFIDENT — scored ≥8 but user said only GOOD (mild overconfidence)",
            overconfident_mild,
        ),
        "",
        disc_section(
            "MISSED — not triaged or scored ≤3, but user said EXCELLENT (must fix)",
            missed_excellent,
            include_abstract=True,
        ),
        "",
        disc_section(
            "MISSED — not triaged or scored ≤3, but user said GOOD (consider new keyword)",
            missed_good,
            include_abstract=True,
        ),
        "",
        disc_section(
            "UNDERSCORED — scored 4–6 but user said EXCELLENT (signal present but underweighted)",
            underscored,
        ),
    ]
    return "\n".join(parts)


def build_refiner_message(profile: dict, recent_ratings: list[dict]) -> str:
    # Group by rating.
    by_rating: dict[str, list[dict]] = {"excellent": [], "good": [], "irrelevant": []}
    for entry in recent_ratings:
        r = entry.get("rating", "").lower()
        if r in by_rating:
            by_rating[r].append(entry)

    # Pre-compute tag frequency across excellent + good papers (positive signal).
    positive_tags: Counter = Counter()
    for entry in by_rating["excellent"] + by_rating["good"]:
        for tag in entry.get("tags", []):
            positive_tags[tag] += 1

    negative_tags: Counter = Counter()
    for entry in by_rating["irrelevant"]:
        for tag in entry.get("tags", []):
            negative_tags[tag] += 1

    tag_summary = ""
    if positive_tags:
        top_pos = ", ".join(f"{t} ({n})" for t, n in positive_tags.most_common(6))
        tag_summary += f"Top tags in Excellent + Good papers: {top_pos}\n"
    if negative_tags:
        top_neg = ", ".join(f"{t} ({n})" for t, n in negative_tags.most_common(4))
        tag_summary += f"Top tags in Irrelevant papers: {top_neg}\n"

    def section(label: str, entries: list[dict]) -> str:
        if not entries:
            return f"{label} (0 papers): (none)"
        lines = [f"{label} ({len(entries)} papers):"]
        for e in entries:
            lines.append(_paper_entry(e))
        return "\n".join(lines)

    evolved = profile.get("evolved_interests", "").strip()
    evolved_label = (
        "LAST MONTH'S NARRATIVE (written by the previous run of this refiner — "
        "use as a corroborating signal for borderline decisions this month):\n"
        + (evolved if evolved else "(not yet set — this is the first run)")
    )

    profile_block = (
        f"CURRENT TASTE PROFILE\n"
        f"=====================\n"
        f"Monitored categories: {profile.get('field', 'unknown')}\n\n"
        f"Research interests:\n{profile.get('interests_description', '(not provided)')}\n\n"
        f"Keywords (grade 1 = most relevant, grade 7 = fading):\n{_keywords_str(profile.get('keywords', []))}\n\n"
        f"Research areas (grade 1 = most relevant, grade 7 = fading):\n{_areas_str(profile.get('research_areas', []))}\n\n"
        f"Followed authors (rank 1 = highest priority):\n{_authors_str(profile.get('authors', []))}\n\n"
        f"{evolved_label}"
    )

    ratings_block = (
        f"30-DAY RATING HISTORY\n"
        f"=====================\n"
        f"Total rated papers: {len(recent_ratings)}\n"
        f"{tag_summary}\n"
        f"{section('EXCELLENT', by_rating['excellent'])}\n\n"
        f"{section('GOOD', by_rating['good'])}\n\n"
        f"{section('IRRELEVANT', by_rating['irrelevant'])}"
    )

    discrepancy_block = build_discrepancy_section(recent_ratings)

    return f"{profile_block}\n\n---\n\n{ratings_block}\n\n---\n\n{discrepancy_block}"


# ---------------------------------------------------------------------------
# JSON parsing — same three-tier fallback as run_pipeline.py
# ---------------------------------------------------------------------------

import re

def parse_json_response(text: str) -> dict:
    for candidate in [
        text,
        "\n".join(l for l in text.splitlines() if not l.startswith("```")).strip(),
    ]:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    m = re.search(r"(\{[\s\S]*\})", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    log.error("Failed to parse Claude JSON response. Raw (first 800 chars):\n%s", text[:800])
    sys.exit(1)


# ---------------------------------------------------------------------------
# Grade application — Python owns the ±1 rule
# ---------------------------------------------------------------------------

def apply_keyword_changes(
    keywords: list[dict],
    changes: list[dict],
    label: str = "keyword",
) -> tuple[list[dict], list[str]]:
    """
    Apply grade ±1 changes to keywords or areas. Returns (updated_list, change_log).
    Items that reach grade 7 are flagged; caller removes them after logging.
    """
    change_log = []
    key_field = "keyword" if label == "keyword" else "area"

    for item in keywords:
        matched = [c for c in changes if c[key_field].strip().lower() == item[key_field].strip().lower()]
        if not matched:
            continue
        change = matched[0]
        old_grade = item["grade"]
        delta = -1 if change["direction"] == "up" else +1
        new_grade = max(1, min(7, old_grade + delta))
        item["grade"] = new_grade
        reason = change.get("reason", "")
        change_log.append(
            f"  {label} '{item[key_field]}': grade {old_grade} → {new_grade} "
            f"({'↑' if delta < 0 else '↓'})  — {reason}"
        )

    return keywords, change_log


def add_new_keywords(existing: list[dict], new_items: list[dict]) -> tuple[list[dict], list[str]]:
    existing_names = {kw["keyword"].strip().lower() for kw in existing}
    log_lines = []
    for item in new_items:
        name = item.get("keyword", "").strip()
        if not name:
            continue
        if name.lower() in existing_names:
            log.info("  New keyword '%s' already exists — skipping.", name)
            continue
        grade = max(3, min(5, item.get("suggested_grade", 4)))  # clamp to 3–5
        existing.append({"keyword": name, "grade": grade})
        existing_names.add(name.lower())
        log_lines.append(f"  + NEW keyword '{name}' (grade {grade}) — {item.get('reason', '')}")
    return existing, log_lines


def add_new_areas(existing: list[dict], new_items: list[dict]) -> tuple[list[dict], list[str]]:
    """If Claude accidentally suggests new areas via keyword changes, handle gracefully."""
    return existing, []


def add_new_authors(existing: list[dict], new_authors: list[dict]) -> tuple[list[dict], list[str]]:
    existing_names = {a["name"].strip().lower() for a in existing}
    next_rank = max((a["rank"] for a in existing), default=0) + 1
    log_lines = []
    for item in new_authors:
        name = item.get("name", "").strip()
        if not name:
            continue
        if name.lower() in existing_names:
            log.info("  Author '%s' already followed — skipping.", name)
            continue
        existing.append({"name": name, "rank": next_rank})
        existing_names.add(name.lower())
        log_lines.append(f"  + NEW author '{name}' (rank {next_rank}) — {item.get('reason', '')}")
        next_rank += 1
    return existing, log_lines


def remove_pre_existing_grade_7(
    items: list[dict], key_field: str, pre_run_grade_7: set[str]
) -> tuple[list[dict], list[str]]:
    """
    Remove items that were already at grade 7 before this run and are still at grade 7.
    Items that only reached grade 7 during this run are kept — they get at least one
    more month before removal, giving newly added keywords a natural trial period.
    """
    log_lines = []
    kept = []
    for item in items:
        name = item[key_field]
        if item["grade"] >= 7 and name in pre_run_grade_7:
            log_lines.append(f"  - REMOVED {key_field} '{name}' (was grade 7 before this run, still grade 7)")
        else:
            kept.append(item)
    return kept, log_lines


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Monthly taste profile refiner — updates taste_profile.json."
    )
    parser.add_argument(
        "--user-dir", default=None,
        help="User directory (e.g. users/alice). Sets default paths for --archive and --profile.",
    )
    parser.add_argument(
        "--days", type=int, default=WINDOW_DAYS,
        help=f"Number of days of ratings to consider (default: {WINDOW_DAYS})",
    )
    parser.add_argument(
        "--archive", default=None,
        help="Path to archive.json (default: derived from --user-dir or next to this script)",
    )
    parser.add_argument(
        "--profile", default=None,
        help="Path to taste_profile.json (default: derived from --user-dir or next to this script)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print proposed changes without writing taste_profile.json",
    )
    args = parser.parse_args()

    # Resolve paths: --user-dir overrides defaults; explicit --archive/--profile override further.
    if args.user_dir:
        user_dir = Path(args.user_dir)
        load_dotenv(user_dir / ".env", override=True)
        default_archive = user_dir / "archive.json"
        default_profile = user_dir / "taste_profile.json"
    else:
        default_archive = ARCHIVE_PATH
        default_profile = PROFILE_PATH

    archive_path = Path(args.archive) if args.archive else default_archive
    profile_path = Path(args.profile) if args.profile else default_profile

    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.error(
            "ANTHROPIC_API_KEY is not set.\n"
            "  Create a .env file in this directory with:\n"
            "      ANTHROPIC_API_KEY=sk-ant-..."
        )
        sys.exit(1)

    # Load inputs.
    archive = load_json(archive_path)
    profile = load_json(profile_path)
    system_prompt = load_prompt("profile_refiner.txt")

    recent = filter_recent(archive, args.days)
    log.info(
        "Archive: %d total entries; %d in the last %d days.",
        len(archive), len(recent), args.days,
    )

    if not recent:
        log.warning("No ratings in the last %d days — nothing to refine.", args.days)
        sys.exit(0)

    # Count by rating type.
    counts: Counter = Counter(e.get("rating", "").lower() for e in recent)
    log.info(
        "Rating breakdown — excellent: %d, good: %d, irrelevant: %d",
        counts["excellent"], counts["good"], counts["irrelevant"],
    )

    # Count discrepancy classes for the log.
    disc_counts = {"overconfident_high": 0, "overconfident_mild": 0,
                   "missed_excellent": 0, "missed_good": 0, "underscored": 0}
    for entry in recent:
        rating = entry.get("rating", "").lower()
        score  = _get_score(entry)
        if rating == "irrelevant" and score is not None and score >= 7:
            disc_counts["overconfident_high"] += 1
        elif rating == "good" and score is not None and score >= 8:
            disc_counts["overconfident_mild"] += 1
        elif rating == "excellent" and (score is None or score <= 3):
            disc_counts["missed_excellent"] += 1
        elif rating == "good" and (score is None or score <= 3):
            disc_counts["missed_good"] += 1
        elif rating == "excellent" and score is not None and 4 <= score <= 6:
            disc_counts["underscored"] += 1
    log.info(
        "Discrepancies — overconfident(high): %d, overconfident(mild): %d, "
        "missed(excellent): %d, missed(good): %d, underscored: %d",
        disc_counts["overconfident_high"], disc_counts["overconfident_mild"],
        disc_counts["missed_excellent"], disc_counts["missed_good"], disc_counts["underscored"],
    )

    # Snapshot which keywords/areas are already at grade 7 before the refiner runs.
    # Only these will be eligible for removal — items that reach grade 7 during this
    # run get at least one more month before they can be removed.
    pre_run_kw_grade_7  = {kw["keyword"] for kw in profile.get("keywords", [])       if kw["grade"] >= 7}
    pre_run_area_grade_7 = {a["area"]    for a  in profile.get("research_areas", []) if a["grade"]  >= 7}
    if pre_run_kw_grade_7 or pre_run_area_grade_7:
        log.info("Pre-run grade-7 items (eligible for removal): keywords=%s, areas=%s",
                 pre_run_kw_grade_7, pre_run_area_grade_7)

    # Build user message and call Claude.
    user_message = build_refiner_message(profile, recent)

    client = Anthropic()
    response = _call_direct(
        client,
        model=REFINER_MODEL,
        max_tokens=4096,
        system=system_prompt,
        user_message=user_message,
        label="refiner",
    )

    raw = response.content[0].text.strip()
    changes = parse_json_response(raw)

    # ---------------------------------------------------------------------------
    # Apply changes — Python owns the rules
    # ---------------------------------------------------------------------------

    all_log: list[str] = []

    # 1. Keyword grade changes.
    kw_changes = changes.get("keyword_grade_changes", [])
    if kw_changes:
        profile["keywords"], kw_log = apply_keyword_changes(
            profile.get("keywords", []), kw_changes, label="keyword"
        )
        all_log.extend(kw_log)

    # 2. Area grade changes.
    area_changes = changes.get("area_grade_changes", [])
    if area_changes:
        profile["research_areas"], area_log = apply_keyword_changes(
            profile.get("research_areas", []), area_changes, label="area"
        )
        all_log.extend(area_log)

    # 3. New keywords.
    new_kws = changes.get("new_keywords", [])
    if new_kws:
        profile["keywords"], nkw_log = add_new_keywords(profile.get("keywords", []), new_kws)
        all_log.extend(nkw_log)

    # 4. New authors.
    new_authors = changes.get("new_authors", [])
    if new_authors:
        profile["authors"], na_log = add_new_authors(profile.get("authors", []), new_authors)
        all_log.extend(na_log)

    # 5. Remove keywords/areas that were already at grade 7 before this run and still are.
    profile["keywords"], rem_kw_log = remove_pre_existing_grade_7(
        profile.get("keywords", []), "keyword", pre_run_kw_grade_7
    )
    all_log.extend(rem_kw_log)

    profile["research_areas"], rem_area_log = remove_pre_existing_grade_7(
        profile.get("research_areas", []), "area", pre_run_area_grade_7
    )
    all_log.extend(rem_area_log)

    # 6. Update evolved_interests.
    old_evolved = profile.get("evolved_interests", "").strip()
    new_evolved = changes.get("evolved_interests", "").strip()
    if new_evolved and new_evolved != old_evolved:
        profile["evolved_interests"] = new_evolved
        all_log.append(f"  evolved_interests updated.")

    # ---------------------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------------------

    print()
    print("=" * 60)
    print("  Profile refiner — proposed changes")
    print("=" * 60)
    if all_log:
        for line in all_log:
            print(line)
    else:
        print("  No changes recommended.")
    print()

    if new_evolved:
        print("  New evolved_interests:")
        for line in new_evolved.split(". "):
            print(f"    {line.strip()}.")
        print()

    if args.dry_run:
        log.info("Dry run — taste_profile.json NOT updated.")
        return

    # Write updated profile.
    profile_path.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("taste_profile.json updated successfully.")


if __name__ == "__main__":
    main()
