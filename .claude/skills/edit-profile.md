# Edit Taste Profile Skill

## Description
Use this skill when a digest user provides free-text feedback about their interests that should be incorporated into their `taste_profile.json`. Claude reads the feedback, extracts what is new or changed, and patches the profile accordingly — never replacing existing information, only expanding or adjusting it.

Trigger on phrases like "user feedback on profile", "update profile from feedback", "incorporate user input into profile", "edit profile", "/edit-profile".

---

## Instructions

### Step 1 — Identify the user

Use `Glob` to list all `users/*/taste_profile.json` paths and extract the user directory names. If the user was named in the invocation command, use that name directly. Otherwise ask with `AskUserQuestion`.

---

### Step 2 — Pull the authoritative profile from the server

**Never run scp or ssh yourself. Always print commands and ask the operator to run them.**

The server copy is authoritative (the monthly refiner updates it in place). Ask the operator to run this command and confirm when done:

```
scp root@116.203.255.222:/opt/arxiv-grader/users/<name>/taste_profile.json users/<name>/taste_profile.json
```

Wait for the operator's confirmation before reading the file.

---

### Step 3 — Read the profile

Read `users/<name>/taste_profile.json` in full. Note the current:
- `interests_description` (existing text)
- `keywords` list with grades
- `research_areas` list with grades
- `authors` list with ranks
- `evolved_interests`

---

### Step 4 — Get the user feedback

If the free-text feedback was provided in the invocation command (after the skill name), use that text directly.

If not, suggest fetching it from the server and ask the operator to run this command and confirm when done:

```
scp root@116.203.255.222:/opt/arxiv-grader/users/<name>/pending_profile_update.txt users/<name>/pending_profile_update.txt
```

Then read `users/<name>/pending_profile_update.txt`. If the file doesn't exist on the server (scp fails), ask the operator to paste the feedback manually.

The feedback is the digest user's own words about what they find interesting, what they want more or less of, or what has changed in their research. Treat it as the ground truth about their current interests.

---

### Step 5 — Analyze the feedback and produce a patch

Read the feedback carefully against the current profile. Produce a structured patch covering three categories:

**A. New items to add**

Extract topics, techniques, authors, and phenomena mentioned in the feedback that are not already present in the profile. For each:
- Decide whether it belongs in `keywords`, `research_areas`, or `authors`
- Assign a grade (keywords/areas: 1–5) or rank (authors) based on how the user expressed their interest:
  - "I work on / central to my research" → grade 1
  - "very interested in / actively following" → grade 2
  - "interested in / want to learn more about" → grade 3
  - "curious about / tangentially relevant" → grade 4
  - "mentioned in passing / not sure yet" → grade 5
- New authors: rank them after the existing lowest rank (append to end)

**B. Grade adjustments to existing items**

If the feedback explicitly signals a change in interest level for something already in the profile, adjust the grade. Rules:
- Only adjust if the feedback clearly references that topic or author
- Maximum shift: ±3 grades per update
- Clamp to allowed range: 1–7 (do not go below 1 or above 7)
- Shift size reflects phrasing strength:
  - "now central to my work / main focus" → shift toward 1 by 2–3
  - "much more interested than before" → shift toward 1 by 1–2
  - "less relevant now / losing interest" → shift toward 7 by 1–2
  - "no longer relevant / moved away from" → shift toward 7 by 2–3
- Do NOT adjust anything not explicitly mentioned in the feedback
- For each adjustment, record the exact phrase or sentence from the feedback that justifies it — this will be shown in the summary

**C. Interests description update**

Append the raw feedback text to `interests_description`, separated by a blank line and a date stamp:

```
<existing text>

---
[2026-05-27] <feedback text verbatim>
```

Do not rewrite or summarize the existing description — only append.

**area_keyword_map updates:**
- For each new keyword added: assign it to the most appropriate existing research area(s) in `area_keyword_map`, or note that a new area may be needed.
- For each new research area added: create a new entry in `area_keyword_map` with the keywords that belong to it.
- For removed items (grade adjustments only — do not remove any item unless the feedback says to): no change to `area_keyword_map`.

---

### Step 6 — Print a full change summary

Before writing anything, print a detailed summary of every change. Use this exact format:

```
Profile patch for users/<name>/taste_profile.json
==================================================

KEYWORDS
  + added:   "optical tweezer arrays"                      grade 2  (new)
  + added:   "cavity QED"                                  grade 3  (new)
  ~ adjusted: "altermagnetism"              grade 4 → 2  | "altermagnetism is now a main focus of my lab"
  ~ adjusted: "Wigner crystals in 2D systems"  grade 4 → 6  | "I've moved away from Wigner crystal work"

RESEARCH AREAS
  + added:   "Quantum optics and light-matter interaction"  grade 3  (new)

AUTHORS
  + added:   "Jun Ye"                                       rank 30 (appended)

INTERESTS DESCRIPTION
  ~ appended [2026-05-27] block (verbatim feedback, N chars)

AREA_KEYWORD_MAP
  ~ "optical tweezer arrays" → added to "Scanning probe microscopy of quantum materials"
  + new area entry: "Quantum optics and light-matter interaction" → ["cavity QED", "optical tweezer arrays"]

NO CHANGES to: <list any existing keywords/areas/authors not modified>
```

Ask the operator to confirm or request adjustments before writing.

---

### Step 7 — Write the updated profile

On confirmation, write the patched JSON to `users/<name>/taste_profile.json`. Preserve:
- All fields not touched by this update
- Original key ordering
- `liked_papers`, `evolved_interests`, delivery flags, `field`, `arxiv_categories`, `created_at`

After writing, validate the file is valid JSON:

```bash
python -c "import json; json.load(open('users/<name>/taste_profile.json'))" && echo "Valid JSON"
```

If validation fails, fix the syntax error before proceeding. Common cause: unescaped double quotes inside string values (e.g. `"wet" biology` must be written as `'wet' biology` or `\"wet\" biology`).

---

### Step 8 — Print the deploy command

**Never run this yourself. Print it and ask the operator to run it.**

```
scp users/<name>/taste_profile.json root@116.203.255.222:/opt/arxiv-grader/users/<name>/taste_profile.json
```
