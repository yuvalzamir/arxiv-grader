# Refiner v2 — Design & Implementation Plan

Captures all design decisions made in the April 2026 planning session.
Implement when ready; this document is the single source of truth.

---

## Overview of changes

Three independent improvements bundled into one refiner overhaul:

1. **Structured outputs** — replace `parse_json_response()` with Anthropic's native JSON schema enforcement for the main refiner call.
2. **Area management as a separate Haiku call** — keyword-driven area grade changes and new area suggestions, completely decoupled from paper ratings.
3. **Remove area grade changes from the main refiner** — the main refiner (Sonnet, paper-driven) no longer touches research areas at all. Areas are exclusively managed by the keyword-driven area management step.

---

## Files

### Created
| File | Purpose |
|---|---|
| `schemas/refiner_output_schema.json` | JSON schema for main refiner structured output |
| `schemas/area_management_schema.json` | JSON schema for area management structured output |
| `prompts/area_management.txt` | New Haiku prompt for keyword-driven area management |

### Modified
| File | Change |
|---|---|
| `run_profile_refiner.py` | See detailed section below |
| `prompts/profile_refiner.txt` | Remove `area_grade_changes` from output spec; remove "Return ONLY a JSON object" line |
| `create_profile.py` | Build initial `area_keyword_map` at profile creation |
| `taste_profile.json` (schema) | New field: `area_keyword_map` |

---

## Design decisions

### Why separate area management?

Areas and keywords operate at different granularities:
- **Keywords** (fine-grained): updated monthly based on paper ratings
- **Areas** (coarse-grained): should reflect structural clusters of keywords, not month-to-month paper noise

Mixing both in one prompt causes areas to fluctuate with individual paper ratings, which is wrong. The area management step sees only the keyword list (with grades) and the stored keyword→area map — no papers, no ratings, no archive.

### Why Haiku for area management?

The area management input is tiny: just the current keyword list, area list, pre-computed support ratios, and the stored map. Haiku is sufficient for gap detection and new area judgment, and costs ~10× less than Sonnet.

### Bidirectional area grade changes

The area management prompt can recommend both UP and DOWN (one recommendation per run):
- **DOWN**: area's support ratio is clearly the weakest relative to peers (excluding grade-1 areas — see below)
- **UP**: area's support ratio is well above areas at a higher importance level (lower grade number); only valid for areas at grade ≥ 2

**Grade-1 areas are never UP candidates** — they are already at maximum importance and recommending UP wastes the one slot with no effect. More importantly, grade-1 areas naturally tend to have high support ratios (they attract many keywords by design), which would distort the gap detection and make lower-grade areas appear as outliers unfairly. **Grade-1 areas are therefore excluded entirely from the gap calculation.**

---

## `area_keyword_map` — static field in `taste_profile.json`

The mapping of keywords to areas is **not recomputed on every refiner run**. It is:

1. **Built once** at profile creation (`create_profile.py`) — Claude or interactive step assigns each initial keyword to one or more areas
2. **Updated incrementally** whenever the main refiner adds new keywords — each new keyword includes an `areas` field specifying which existing area(s) it belongs to (or empty if unmatched)
3. **Stored persistently** in `taste_profile.json` under the key `area_keyword_map`
4. **Read by the area management step** — Python pre-computes support ratios using this map before calling Haiku; Haiku receives the ratios as input and only makes the judgment call

This means the Haiku call does **not** produce or return `area_keyword_map`. It only returns `area_grade_changes` and `new_areas`.

### Structure in `taste_profile.json`

```json
"area_keyword_map": [
  {
    "area": "Scanning probe microscopy of quantum materials",
    "keywords": ["quantum twisting microscope (QTM)", "scanning tunneling microscopy (STM/STS)", "photocurrent imaging and spectroscopy", "ARPES and momentum-resolved spectroscopy"]
  },
  {
    "area": "Correlated and topological phases in moiré 2D materials",
    "keywords": ["moiré systems and van der Waals heterostructures", "magic-angle twisted bilayer graphene (MATBG)", "correlated electron phases in 2D materials", "rhombohedral graphene multilayers", "topological Chern insulators and quantum anomalous Hall effect", "transition metal dichalcogenides (TMDs)", "Wigner crystals in 2D systems"]
  },
  ...
]
```

A keyword may appear in multiple areas (non-exclusive). Every area must have an entry, even if `"keywords": []`.

### Updating the map when new keywords are added

The main refiner's `new_keywords` output includes an `areas` field per item. Python reads this and appends the new keyword to the corresponding area entries in `area_keyword_map`. If `areas` is empty, the keyword is left unmatched (will count toward new area threshold).

### Building the map at profile creation

`create_profile.py` needs a new step after the initial keyword/area list is built: call Claude (or use a simple interactive prompt) to assign each keyword to the areas it semantically belongs to. Write the result to `area_keyword_map` in `taste_profile.json`. This is a one-time cost.

---

## Support ratio formula

Python pre-computes these before calling Haiku. The ratios are passed as part of the area management message so Haiku only needs to interpret them.

### Step 1 — Keyword weight

```
keyword_weight = (8 - keyword_grade) / 7
```

| Keyword grade | Weight |
|---|---|
| 1 (core) | 1.000 |
| 2 | 0.857 |
| 3 | 0.714 |
| 4 | 0.571 |
| 5 | 0.429 |
| 6 | 0.286 |
| 7 (fading) | 0.143 |

### Step 2 — Effective support

Sum weights of all keywords listed in `area_keyword_map` for this area:

```
effective_support = sum(keyword_weight for each keyword in area_keyword_map[area])
```

### Step 3 — Relative support

Normalize by total keyword count:

```
relative_support = effective_support / total_keywords
```

### Step 4 — Support ratio

```
support_ratio = relative_support / (8 - area_grade) ^ 1.5
```

The exponent **1.5** was chosen empirically on Yuval's profile. Rankings at ^1 and ^1.5 are identical for that profile; ^2 causes unintuitive rank swaps (grade-4 areas jump over grade-1 areas).

### Grade-1 exclusion

**Grade-1 areas are excluded from the support ratio ranking used for gap detection.** Their ratios are still computed and logged (useful for diagnostics), but Haiku is instructed to ignore them when identifying the strongest and weakest areas for grade change recommendations. This prevents naturally keyword-rich grade-1 areas from distorting the gap.

### Calibration on Yuval's profile (April 2026, 15 keywords, 6 areas)

| Area | Grade | Rel. support | Support ratio | Included in gap? |
|---|---|---|---|---|
| Correlated/topo phases in moiré 2D | 1 | 0.390 | 0.02108 | **no** |
| Scanning probe microscopy of quantum materials | 1 | 0.238 | 0.01286 | **no** |
| Electronic structure & spectroscopy of 2D | 2 | 0.286 | 0.01944 | yes |
| Unconventional superconductivity | 4 | 0.095 | 0.01190 | yes |
| THz and IR photonics in condensed matter | 3 | 0.105 | 0.00937 | yes |
| Kondo physics and heavy fermion systems | 3 | 0.057 | 0.00511 | yes |

Among the 4 included areas, Kondo (0.00511) is the clear outlier — roughly 2× below THz (0.00937). Haiku would recommend downgrading Kondo (grade 3→4).

Electronic structure (0.01944) is the top-ranked included area. It is well above Unconventional superconductivity (0.01190, grade 4) — gap of ~1.6×. This is borderline for an UP recommendation and would likely not trigger in the first run; it would require a clearer gap or corroboration from the main refiner.

---

## Gap detection — no fixed threshold

Python passes the pre-computed support ratios to Haiku. Haiku identifies whether there is a **clear gap**:

- **DOWN candidate**: bottom-ranked included area has a ratio roughly 2× below the next weakest → recommend DOWN
- **UP candidate**: top-ranked included area has a ratio well above areas one grade higher → recommend UP
- **Borderline** (gap is ambiguous): return empty array

This is purely relative — no magic numbers. Claude's judgment defines "clear gap." When in doubt, do nothing.

---

## Caps per run

- **At most 1 area grade change** (up or down) per run
- **At most 1 new area suggestion** per run
- Both can coexist in the same run (one grade change AND one new area)
- If multiple candidates qualify, pick only the clearest one; note others in the reason field

---

## New area logic

A new area is suggested only when:
1. **≥3 current keywords** are unmatched (not listed in `area_keyword_map` for any area)
2. Those unmatched keywords share a **genuinely coherent, distinct theme** not already captured by existing areas
3. Only the **strongest cluster** is suggested per run

**Conservative default**: 3 keywords is the minimum, not a sufficient condition alone. Claude should only suggest a new area if the cluster is obvious and self-contained. Thematic adjacency to an existing area is not enough — the topic must be clearly distinct. If in doubt, do not suggest.

Suggested grade: 3–5 (never 1–2 for something not yet established). The schema enforces this with `"enum": [3, 4, 5]`.

**Current profile note**: `altermagnetism` (grade 4) is the only unmatched keyword. 1 keyword does not trigger a new area.

---

## Area removal safety check

When an area reaches grade 7 (from any source — area management or pre-existing), Python checks before deleting using the stored `area_keyword_map`:

1. **Condition A**: ≤2 keywords are associated with this area in `area_keyword_map`
2. **Condition B**: None of those keywords has a grade ≤3 (no active keyword still supports the area)

If **both** conditions are met → auto-remove.
If either condition fails → keep at grade 7 for another month.

```python
def _safe_to_remove_area(area_name: str, profile: dict) -> bool:
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
```

The pre-run grade-7 snapshot (existing logic) still applies: areas that only reach grade 7 during the current run are not eligible for removal this run.

---

## `schemas/refiner_output_schema.json`

Two changes from original:
- **No `area_grade_changes`** — removed entirely from main refiner
- **`new_keywords` items include `areas`** — list of existing area names this keyword belongs to (may be empty if unmatched)

```json
{
  "type": "object",
  "properties": {
    "keyword_grade_changes": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "keyword":   {"type": "string"},
          "direction": {"type": "string", "enum": ["up", "down"]},
          "reason":    {"type": "string"}
        },
        "required": ["keyword", "direction", "reason"],
        "additionalProperties": false
      }
    },
    "new_keywords": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "keyword":         {"type": "string"},
          "suggested_grade": {"type": "integer", "enum": [3, 4, 5]},
          "areas":           {"type": "array", "items": {"type": "string"}},
          "reason":          {"type": "string"}
        },
        "required": ["keyword", "suggested_grade", "areas", "reason"],
        "additionalProperties": false
      }
    },
    "new_authors": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "name":   {"type": "string"},
          "reason": {"type": "string"}
        },
        "required": ["name", "reason"],
        "additionalProperties": false
      }
    },
    "evolved_interests": {"type": "string"}
  },
  "required": ["keyword_grade_changes", "new_keywords", "new_authors", "evolved_interests"],
  "additionalProperties": false
}
```

The `areas` field instructs Claude to name which existing areas this keyword belongs to. Python uses this to update `area_keyword_map` in the profile. Claude should use exact area names from the profile; empty array if the keyword doesn't match any area.

---

## `schemas/area_management_schema.json`

**No `area_keyword_map` output** — the map is stored in the profile and passed as input, not recomputed each run.

```json
{
  "type": "object",
  "properties": {
    "area_grade_changes": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "area":      {"type": "string"},
          "direction": {"type": "string", "enum": ["up", "down"]},
          "reason":    {"type": "string"}
        },
        "required": ["area", "direction", "reason"],
        "additionalProperties": false
      }
    },
    "new_areas": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "area":                {"type": "string"},
          "suggested_grade":     {"type": "integer", "enum": [3, 4, 5]},
          "supporting_keywords": {"type": "array", "items": {"type": "string"}},
          "reason":              {"type": "string"}
        },
        "required": ["area", "suggested_grade", "supporting_keywords", "reason"],
        "additionalProperties": false
      }
    }
  },
  "required": ["area_grade_changes", "new_areas"],
  "additionalProperties": false
}
```

Notes:
- `area_grade_changes`: max 1 entry (enforced by prompt instruction, not schema)
- `new_areas`: max 1 entry (enforced by prompt instruction, not schema)
- Both may be empty arrays

---

## `prompts/area_management.txt` — design spec

The prompt receives a pre-formatted message built by `build_area_management_message(profile)` containing:
- All current areas with grades and their pre-computed support ratios (grade-1 areas flagged as excluded from gap)
- All unmatched keywords (those not in `area_keyword_map` for any area) with grades
- Total keyword count

Claude does **not** need to do keyword→area mapping (that's stored). It only needs to interpret the pre-computed ratios and make judgment calls.

### Prompt instructions (to be written in full when implementing)

1. **Gap detection for grade changes** (`area_grade_changes`, max 1):
   - You are given pre-computed support ratios for each area
   - **Ignore all grade-1 areas entirely** — do not include them in gap analysis, do not recommend UP or DOWN for them
   - Among the remaining areas (grade 2+): identify the bottom-ranked (DOWN candidate) and top-ranked (UP candidate)
   - DOWN: recommend only if the bottom-ranked area's ratio is roughly 2× below the next weakest — a clear gap, not a borderline case
   - UP: recommend only if the top-ranked area's ratio is well above areas one grade higher — and only for areas at grade ≥ 2
   - If multiple candidates qualify, pick only the clearest one
   - Borderline → empty array
   - Note: Python applies ±1 per run; your direction signal is sufficient

2. **New area suggestion** (`new_areas`, max 1):
   - You are given the list of unmatched keywords (not associated with any existing area)
   - If ≥3 unmatched keywords share a genuinely coherent, distinct theme not captured by existing areas → suggest one new area
   - Be conservative: 3 keywords is the minimum bar, not a sufficient condition. Only suggest if the cluster is obvious and self-contained. Thematic adjacency to an existing area is not grounds for a new area.
   - Suggest grade 3–5 only
   - Include the unmatched keywords that support this new area in `supporting_keywords`
   - If in doubt, return empty array

3. **Spread constraint**: Before emitting any recommendation, verify it would not leave all included areas (grade 2+) within 2 grades of each other. If the change would collapse the spread, skip it.

4. **Conservative default**: When in doubt, do nothing. Empty arrays are always correct.

---

## `prompts/profile_refiner.txt` — changes

Three changes:

1. Remove the `area_grade_changes` array from the OUTPUT section (both the JSON template and the instruction that mentions it)
2. Add instruction for `new_keywords.areas` field: *"For each new keyword, list the exact names of any existing research areas it belongs to. Use empty array if it doesn't match any area. This is used to keep the keyword-area map up to date."*
3. Remove the line: `Return ONLY a JSON object. No preamble, no explanation, no markdown fences.`

---

## `run_profile_refiner.py` — changes

### New constants

```python
SCHEMAS_DIR  = Path(__file__).parent / "schemas"
AREA_MODEL   = "claude-haiku-4-5-20251001"
```

### New helper: `load_schema(name)`

```python
def load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))
```

### Updated `_submit_and_poll()` — add `output_schema` param

Add `output_schema: dict | None = None` parameter. When provided, inject into batch request params:

```python
"params": {
    "model": model,
    "max_tokens": max_tokens,
    "system": system,
    "messages": [{"role": "user", "content": user_message}],
    "output_config": {
        "format": {"type": "json_schema", "schema": output_schema}
    },
}
```

### Delete `parse_json_response()`

Replace its call site with:
```python
changes = json.loads(response.content[0].text)
```
Structured outputs guarantees valid JSON — no fallback needed.

### New: `_keyword_weight(grade)` and `_compute_support_ratios(profile)`

Python pre-computes support ratios before calling Haiku:

```python
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
```

### New: `_unmatched_keywords(profile)`

```python
def _unmatched_keywords(profile: dict) -> list[dict]:
    """Return keywords not listed in any area's keyword list."""
    area_keyword_map = profile.get("area_keyword_map", [])
    all_mapped = {k.lower() for e in area_keyword_map for k in e["keywords"]}
    return [kw for kw in profile.get("keywords", [])
            if kw["keyword"].lower() not in all_mapped]
```

### New: `build_area_management_message(profile, support_ratios, unmatched)`

Formats the Haiku input. Python provides:
- Areas table with pre-computed support ratios (grade-1 flagged as excluded)
- Unmatched keywords list
- Total keyword count

No keyword→area matching needed from Claude.

### New: `_call_area_management(client, profile, schema)`

Synchronous call (not batch):

```python
def _call_area_management(client: Anthropic, profile: dict, schema: dict) -> dict:
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
```

### New: `_update_area_keyword_map(profile, new_keywords_output)`

Called after applying new keywords from the main refiner:

```python
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
                log.warning("  new keyword '%s' references unknown area '%s' — skipping map update", kw_name, area_name)
    profile["area_keyword_map"] = list(area_map.values())
    return log_lines
```

### New: `add_new_areas(existing, new_items)`

Fill in the current stub (lines 414–416). Also adds the new area to `area_keyword_map` with its `supporting_keywords`:

```python
def add_new_areas(existing: list[dict], new_items: list[dict], profile: dict) -> tuple[list[dict], list[str]]:
    existing_names = {a["area"].strip().lower() for a in existing}
    log_lines = []
    for item in new_items:
        name = item.get("area", "").strip()
        if not name or name.lower() in existing_names:
            continue
        grade = max(3, min(5, item.get("suggested_grade", 4)))
        existing.append({"area": name, "grade": grade})
        existing_names.add(name.lower())
        # Add to area_keyword_map
        profile.setdefault("area_keyword_map", []).append({
            "area": name,
            "keywords": item.get("supporting_keywords", []),
        })
        log_lines.append(f"  + NEW area '{name}' (grade {grade}) — {item.get('reason', '')}")
    return existing, log_lines
```

### Updated area removal

```python
def remove_grade_7_areas(
    areas: list[dict],
    pre_run_grade_7: set[str],
    profile: dict,
) -> tuple[list[dict], list[str]]:
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
                # Also remove from area_keyword_map
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
```

---

## `main()` — updated sequencing

```
1.  Load archive, profile, recent ratings
2.  Snapshot pre-run grade-7 keywords and areas
3.  Load schemas: refiner_output_schema.json, area_management_schema.json
4.  Build user message; call main refiner (Batch API, Sonnet, structured outputs)
    → returns: keyword_grade_changes, new_keywords (with areas field), new_authors, evolved_interests
    → does NOT return area_grade_changes
5.  Apply main refiner changes to profile in memory:
    - keyword grade changes (±1 per keyword)
    - new keywords → also update area_keyword_map via _update_area_keyword_map()
    - new authors
    - evolved_interests update
6.  Call area management (synchronous, Haiku, structured outputs)
    - Python pre-computes support ratios and unmatched keywords from updated profile
    - Haiku receives: area table with ratios, unmatched keywords list
    → returns: area_grade_changes (max 1), new_areas (max 1)
7.  Apply area management changes to profile in memory:
    - area grade changes (±1, clamped 1–7)
    - new areas → also add to area_keyword_map via add_new_areas()
8.  Grade-7 keyword removal (existing logic — pre-run grade-7 snapshot)
9.  Grade-7 area removal (updated: _safe_to_remove_area using profile's area_keyword_map;
    also removes the area from area_keyword_map on deletion)
10. Print summary of all changes
11. Write profile to disk (skip for --dry-run)
```

---

## `create_profile.py` — new step

After the initial keyword and area lists are built interactively, add a step to populate `area_keyword_map`. Two options:

- **Option A (Claude call)**: Send the keyword list and area list to Claude with a simple prompt: *"For each area, list which of these keywords semantically belong to it. A keyword may belong to multiple areas."* Write the result to `taste_profile.json`.
- **Option B (interactive)**: During the onboarding interview, ask the user to assign keywords to areas manually.

Option A is simpler and consistent with the rest of the system. Use a cheap model (Haiku) since the task is straightforward. This happens once and is never expensive.

---

## What does NOT change

- `_submit_and_poll()` polling logic
- `apply_keyword_changes()`, `add_new_keywords()`, `add_new_authors()`
- Archive filtering and discrepancy analysis (`build_discrepancy_section`)
- `build_refiner_message()` (except area_grade_changes removed from the prompt it feeds)
- Grade-7 keyword removal (`remove_pre_existing_grade_7` for keywords)
- `run_all_users.py`, `run_daily.py` — refiner is invoked identically
- The Batch API for the main refiner call — no change

---

## Known edge cases

**Keyword appears in multiple areas**: allowed. `area_keyword_map` is non-exclusive. A keyword like "moiré systems" can support both "Correlated phases" and "Electronic structure."

**New keywords from step 5 feed into step 6**: The area management call sees the post-step-5 profile, including newly added keywords and their updated `area_keyword_map` entries. A new keyword tagged to an area increases that area's support ratio; a new unmatched keyword counts toward the new-area threshold.

**Area management cap enforcement**: The schema allows arrays of any length; the cap (max 1 per field) is enforced by the prompt instruction only. If Claude returns more than 1 entry, Python applies only the first and logs a warning.

**Stale `area_keyword_map` entries**: If a keyword is removed (grade-7 pruning), it may still appear in `area_keyword_map`. Python should clean up: when a keyword is deleted, remove it from all area entries in the map. Add this as a cleanup step after grade-7 keyword removal.

**Grade-1 area that loses keyword support**: Although grade-1 areas are excluded from gap detection, they can still accumulate `area_grade_changes` from the main refiner (paper-driven, which is now removed). If a grade-1 area genuinely loses all keyword support, it will never be auto-downgraded by the area management step. This is acceptable — grade-1 areas should only change through explicit keyword evolution, not automated area management. Monitor manually if needed.

---

## Cost impact

| Step | Model | Type | Est. tokens (Yuval) | Est. cost |
|---|---|---|---|---|
| Main refiner | Sonnet | Batch (50% off) | ~8k in / ~500 out | ~$0.006 |
| Area management | Haiku | Synchronous | ~400 in / ~200 out | ~$0.00008 |

Area management adds negligible cost. Structured outputs carry no pricing overhead.
