# Edit Taste Profile From File Skill

## Description
Use this skill when a user has submitted a free-text profile update via the `/manage` page. The feedback is stored in `users/<slug>/pending_profile_update.txt`. Claude reads the file, incorporates the feedback into `taste_profile.json`, and deletes the file after successful deployment.

Trigger on phrases like "/edit-profile-from-file", "process pending profile update", "apply profile feedback from file".

---

## Instructions

### Step 1 — Identify the user

The slug is provided in the invocation command (e.g. `/edit-profile-from-file john-doe-gmail-com`). If not provided, use `Glob` to list all `users/*/pending_profile_update.txt` paths and ask the operator which one to process.

---

### Step 2 — Pull the authoritative profile from the server

**Never run scp, ssh, or rm yourself. Always print commands and ask the operator to run them.**

The server copy is authoritative (the monthly refiner updates it in place). Ask the operator to run these two commands and confirm when done:

```
scp root@116.203.255.222:/opt/arxiv-grader/users/<slug>/taste_profile.json users/<slug>/taste_profile.json
scp root@116.203.255.222:/opt/arxiv-grader/users/<slug>/pending_profile_update.txt users/<slug>/pending_profile_update.txt
```

Wait for the operator's confirmation before proceeding.

---

### Step 3 — Read the profile

Read `users/<slug>/taste_profile.json` in full. Note the current:
- `interests_description` (existing text)
- `keywords` list with grades
- `research_areas` list with grades
- `authors` list with ranks
- `evolved_interests`

---

### Step 4 — Read the pending feedback file

Read `users/<slug>/pending_profile_update.txt` in full. The file contains one or more timestamped blocks in this format:

```
[2026-05-28T15:30:00Z]
<user's free-text feedback>

---
[2026-05-28T16:30:00Z]
<second submission if any>

---
```

Treat the concatenated content of all blocks as the feedback text. The most recent block takes priority if blocks contradict each other.

---

### Step 5 — Analyze the feedback and produce a patch

Follow the same logic as the `/edit-profile` skill (Steps 5–6 of that skill):

**A. New items to add** — extract topics, techniques, authors not already in the profile and assign grades/ranks.

**B. Grade adjustments** — adjust grades for existing items explicitly referenced, max ±3 per update.

**C. Interests description update** — append the raw feedback text verbatim with a date stamp:
```
---
[YYYY-MM-DD] <feedback text verbatim>
```

**D. area_keyword_map updates** — assign new keywords to existing areas or create new area entries.

---

### Step 6 — Print a full change summary

Use the same format as `/edit-profile` Step 6. Ask the operator to confirm or request adjustments before writing.

---

### Step 7 — Write the updated profile

On confirmation, write the patched JSON to `users/<slug>/taste_profile.json`. Preserve all untouched fields.

---

### Step 8 — Print the deploy commands

**Never run these yourself. Print them and ask the operator to run them.**

Ask the operator to run:
```
scp users/<slug>/taste_profile.json root@116.203.255.222:/opt/arxiv-grader/users/<slug>/taste_profile.json
```

After the operator confirms the SCP succeeded, ask them to run these two cleanup commands (the remote delete clears the pending flag so the `/manage` page no longer shows "feedback pending"):
```
ssh root@116.203.255.222 "rm /opt/arxiv-grader/users/<slug>/pending_profile_update.txt"
rm users/<slug>/pending_profile_update.txt
```
