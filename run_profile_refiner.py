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
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()  # load root .env first; user .env loaded in main() after arg parsing

PROMPTS_DIR    = Path(__file__).parent / "prompts"
SCHEMAS_DIR    = Path(__file__).parent / "schemas"
ARCHIVE_PATH   = Path(__file__).parent / "archive.json"
PROFILE_PATH   = Path(__file__).parent / "taste_profile.json"
REFINER_MODEL       = "claude-sonnet-4-6"
AREA_MODEL          = "claude-haiku-4-5-20251001"
WINDOW_DAYS         = 30
BATCH_POLL_INTERVAL = 15    # seconds between batch status checks
BATCH_TIMEOUT       = 3600  # give up after 1 hour

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


def load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / name
    if not path.exists():
        log.error("Schema file not found: %s", path)
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Batch API helper
# ---------------------------------------------------------------------------

def _submit_and_poll(client: Anthropic, custom_id: str, model: str, max_tokens: int,
                     system: str, user_message: str, label: str,
                     output_schema: dict | None = None):
    """Submit a single-request batch, poll until complete, return the Message object."""
    params: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_message}],
    }
    if output_schema is not None:
        params["output_config"] = {
            "format": {"type": "json_schema", "schema": output_schema}
        }

    batch = client.messages.batches.create(
        requests=[{"custom_id": custom_id, "params": params}]
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
            if msg.usage.output_tokens >= max_tokens * 0.9:
                log.warning(
                    "%s: output tokens (%d) close to max_tokens (%d) — response may be truncated.",
                    label, msg.usage.output_tokens, max_tokens,
                )
            return msg
        else:
            error = getattr(result.result, "error", None)
            log.error("%s: batch request failed with type '%s'. Error: %s",
                      label, result.result.type, error)
            sys.exit(1)

    log.error("%s: no results returned by batch.", label)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Archive filtering
# ---------------------------------------------------------------------------

def filter_recent(archive: list[dict], days: int) -> list[dict]:
    """Return archive entries from the last `days` days (inclusive)."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return [e for e in archive if e.get("date", "") >= cutoff]


# ---------------------------------------------------------------------------
# Message builder — main refiner
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


def add_new_areas(existing: list[dict], new_items: list[dict], profile: dict) -> tuple[list[dict], list[str]]:
    """Add new areas and register them in area_keyword_map."""
    existing_names = {a["area"].strip().lower() for a in existing}
    log_lines = []
    for item in new_items[:1]:  # cap: max 1 new area per run
        name = item.get("area", "").strip()
        if not name or name.lower() in existing_names:
            continue
        grade = max(3, min(5, item.get("suggested_grade", 4)))
        existing.append({"area": name, "grade": grade})
        existing_names.add(name.lower())
        profile.setdefault("area_keyword_map", []).append({
            "area": name,
            "keywords": item.get("supporting_keywords", []),
        })
        log_lines.append(f"  + NEW area '{name}' (grade {grade}) — {item.get('reason', '')}")
    if len(new_items) > 1:
        log.warning("  Area management returned %d new areas; only the first was applied.", len(new_items))
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


def remove_grade_7_areas(
    areas: list[dict], pre_run_grade_7: set[str], profile: dict
) -> tuple[list[dict], list[str]]:
    """
    Remove areas that were already at grade 7 before this run, subject to the
    _safe_to_remove_area keyword-support safety check.
    """
    log_lines = []
    kept = []
    for area in areas:
        name = area["area"]
        if area["grade"] >= 7 and name in pre_run_grade_7:
            if _safe_to_remove_area(name, profile):
                log_lines.append(
                    f"  - REMOVED area '{name}' "
                    f"(grade 7 before this run, keyword support confirms removal)"
                )
                # Clean up area_keyword_map entry.
                profile["area_keyword_map"] = [
                    e for e in profile.get("area_keyword_map", [])
                    if e["area"] != name
                ]
            else:
                kept.append(area)
                log_lines.append(
                    f"  ~ KEPT area '{name}' at grade 7 "
                    f"(removal blocked: active keyword support still present)"
                )
        else:
            kept.append(area)
    return kept, log_lines


# ---------------------------------------------------------------------------
# Area management helpers
# ---------------------------------------------------------------------------

def _keyword_weight(grade: int) -> float:
    return (8 - grade) / 7


def _compute_support_ratios(profile: dict) -> list[dict]:
    """Compute support ratio for each area using the stored area_keyword_map."""
    keywords = profile.get("keywords", [])
    areas = profile.get("research_areas", [])
    area_keyword_map = profile.get("area_keyword_map", [])
    total_keywords = len(keywords)

    kw_grade = {kw["keyword"].lower(): kw["grade"] for kw in keywords}
    map_lookup = {e["area"]: e["keywords"] for e in area_keyword_map}

    result = []
    for area in areas:
        name = area["area"]
        grade = area["grade"]
        associated = map_lookup.get(name, [])
        effective = sum(_keyword_weight(kw_grade.get(k.lower(), 4)) for k in associated)
        relative = effective / total_keywords if total_keywords else 0
        ratio = relative / ((8 - grade) ** 1.5) if grade < 8 else 0
        result.append({
            "area": name,
            "grade": grade,
            "support_ratio": round(ratio, 5),
            "keyword_count": len(associated),
            "excluded_from_gap": grade == 1,
        })
    return sorted(result, key=lambda x: x["support_ratio"], reverse=True)


def _unmatched_keywords(profile: dict) -> list[dict]:
    """Return keywords not listed in any area's keyword list."""
    area_keyword_map = profile.get("area_keyword_map", [])
    all_mapped = {k.lower() for e in area_keyword_map for k in e["keywords"]}
    return [kw for kw in profile.get("keywords", [])
            if kw["keyword"].lower() not in all_mapped]


def _safe_to_remove_area(area_name: str, profile: dict) -> bool:
    """Return True if the area can be safely removed (no active keyword support)."""
    area_keyword_map = profile.get("area_keyword_map", [])
    all_keywords = profile.get("keywords", [])
    entry = next((e for e in area_keyword_map if e["area"] == area_name), None)
    if entry is None:
        return True  # not mapped → no active support → safe to remove
    associated = entry["keywords"]
    if len(associated) > 2:
        return False  # too many supporting keywords
    kw_grades = {kw["keyword"].lower(): kw["grade"] for kw in all_keywords}
    for kw_name in associated:
        grade = kw_grades.get(kw_name.lower())
        if grade is not None and grade <= 3:
            return False  # active keyword still supports this area
    return True


def _update_area_keyword_map(profile: dict, new_keywords_output: list[dict]) -> list[str]:
    """Append new keywords to their designated areas in area_keyword_map."""
    area_map = {e["area"]: e for e in profile.get("area_keyword_map", [])}
    log_lines = []
    for item in new_keywords_output:
        kw_name = item.get("keyword", "").strip()
        for area_name in item.get("areas", []):
            if area_name in area_map:
                if kw_name not in area_map[area_name]["keywords"]:
                    area_map[area_name]["keywords"].append(kw_name)
                    log_lines.append(f"  map: '{kw_name}' → '{area_name}'")
            else:
                log.warning(
                    "  new keyword '%s' references unknown area '%s' — skipping map update",
                    kw_name, area_name,
                )
    profile["area_keyword_map"] = list(area_map.values())
    return log_lines


def _cleanup_removed_keywords_from_map(profile: dict, removed_names: set[str]) -> None:
    """Remove deleted keywords from all area_keyword_map entries."""
    removed_lower = {n.lower() for n in removed_names}
    for entry in profile.get("area_keyword_map", []):
        entry["keywords"] = [
            k for k in entry["keywords"]
            if k.lower() not in removed_lower
        ]


def build_area_management_message(
    profile: dict, support_ratios: list[dict], unmatched: list[dict]
) -> str:
    areas_lines = []
    for r in support_ratios:
        excl = " [EXCLUDED — grade 1, ignore in gap analysis]" if r["excluded_from_gap"] else ""
        areas_lines.append(
            f"  grade {r['grade']}: {r['area']}"
            f"  (support_ratio={r['support_ratio']:.5f}, keywords={r['keyword_count']}){excl}"
        )

    unmatched_lines = (
        "\n".join(f"  grade {kw['grade']}: {kw['keyword']}" for kw in unmatched)
        or "  (none)"
    )

    return (
        f"RESEARCH AREAS (sorted by support ratio, highest first)\n"
        f"=========================================================\n"
        f"Total keywords: {len(profile.get('keywords', []))}\n\n"
        + "\n".join(areas_lines)
        + f"\n\nUNMATCHED KEYWORDS (not associated with any area)\n"
        f"==================================================\n"
        + unmatched_lines
    )


def _call_area_management(client: Anthropic, profile: dict, schema: dict) -> dict:
    """Synchronous Haiku call for keyword-driven area management."""
    support_ratios = _compute_support_ratios(profile)
    unmatched = _unmatched_keywords(profile)
    system = load_prompt("area_management.txt")
    user_msg = build_area_management_message(profile, support_ratios, unmatched)

    response = client.messages.create(
        model=AREA_MODEL,
        max_tokens=512,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    log.info(
        "Area management done. (input: %d tokens, output: %d tokens)",
        response.usage.input_tokens, response.usage.output_tokens,
    )
    return json.loads(response.content[0].text)


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
    refiner_schema = load_schema("refiner_output_schema.json")
    area_schema    = load_schema("area_management_schema.json")

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
    pre_run_kw_grade_7   = {kw["keyword"] for kw in profile.get("keywords", [])       if kw["grade"] >= 7}
    pre_run_area_grade_7 = {a["area"]     for a  in profile.get("research_areas", []) if a["grade"]  >= 7}
    if pre_run_kw_grade_7 or pre_run_area_grade_7:
        log.info("Pre-run grade-7 items (eligible for removal): keywords=%s, areas=%s",
                 pre_run_kw_grade_7, pre_run_area_grade_7)

    # ---------------------------------------------------------------------------
    # Step 4 — Main refiner call (Sonnet, Batch API, structured outputs)
    # ---------------------------------------------------------------------------

    user_message = build_refiner_message(profile, recent)
    client = Anthropic()

    response = _submit_and_poll(
        client,
        custom_id="profile-refiner",
        model=REFINER_MODEL,
        max_tokens=4096,
        system=system_prompt,
        user_message=user_message,
        label="refiner",
        output_schema=refiner_schema,
    )
    changes = json.loads(response.content[0].text)

    # ---------------------------------------------------------------------------
    # Step 5 — Apply main refiner changes
    # ---------------------------------------------------------------------------

    all_log: list[str] = []

    # 1. Keyword grade changes.
    kw_changes = changes.get("keyword_grade_changes", [])
    if kw_changes:
        profile["keywords"], kw_log = apply_keyword_changes(
            profile.get("keywords", []), kw_changes, label="keyword"
        )
        all_log.extend(kw_log)

    # 2. New keywords → also update area_keyword_map.
    new_kws = changes.get("new_keywords", [])
    if new_kws:
        profile["keywords"], nkw_log = add_new_keywords(profile.get("keywords", []), new_kws)
        all_log.extend(nkw_log)
        map_log = _update_area_keyword_map(profile, new_kws)
        all_log.extend(map_log)

    # 3. New authors.
    new_authors = changes.get("new_authors", [])
    if new_authors:
        profile["authors"], na_log = add_new_authors(profile.get("authors", []), new_authors)
        all_log.extend(na_log)

    # 4. Update evolved_interests.
    old_evolved = profile.get("evolved_interests", "").strip()
    new_evolved = changes.get("evolved_interests", "").strip()
    if new_evolved and new_evolved != old_evolved:
        profile["evolved_interests"] = new_evolved
        all_log.append("  evolved_interests updated.")

    # ---------------------------------------------------------------------------
    # Step 6 — Area management call (Haiku, synchronous, structured outputs)
    # ---------------------------------------------------------------------------

    area_changes_raw = _call_area_management(client, profile, area_schema)

    area_grade_changes = area_changes_raw.get("area_grade_changes", [])
    if len(area_grade_changes) > 1:
        log.warning("Area management returned %d grade changes; only the first will be applied.",
                    len(area_grade_changes))
        area_grade_changes = area_grade_changes[:1]

    if area_grade_changes:
        profile["research_areas"], area_log = apply_keyword_changes(
            profile.get("research_areas", []), area_grade_changes, label="area"
        )
        all_log.extend(area_log)

    new_areas = area_changes_raw.get("new_areas", [])
    if new_areas:
        profile["research_areas"], na_log = add_new_areas(
            profile.get("research_areas", []), new_areas, profile
        )
        all_log.extend(na_log)

    # ---------------------------------------------------------------------------
    # Step 7 — Grade-7 pruning
    # ---------------------------------------------------------------------------

    # Keywords: simple removal (no safety check needed).
    profile["keywords"], rem_kw_log = remove_pre_existing_grade_7(
        profile.get("keywords", []), "keyword", pre_run_kw_grade_7
    )
    all_log.extend(rem_kw_log)

    # Clean up removed keywords from area_keyword_map.
    removed_kw_names = {
        line.split("'")[1] for line in rem_kw_log if "REMOVED keyword" in line
    }
    if removed_kw_names:
        _cleanup_removed_keywords_from_map(profile, removed_kw_names)

    # Areas: safety check using area_keyword_map.
    profile["research_areas"], rem_area_log = remove_grade_7_areas(
        profile.get("research_areas", []), pre_run_area_grade_7, profile
    )
    all_log.extend(rem_area_log)

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
