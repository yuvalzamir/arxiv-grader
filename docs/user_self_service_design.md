# User Self-Service Profile Page — Design Document

*Related vault notes: [[Manage Profile]] · [[User Onboarding]] · [[Taste Profile]] · [[Infrastructure]]*

Status: **implemented** (2026-05-28) — live at `incomingscience.xyz/manage`.

---

## Overview

A new page at `incomingscience.xyz/manage` lets existing users update their delivery frequency and submit free-text interest changes, identified by email only (no password). The operator handles profile edits manually via the existing `/edit-profile` skill.

---

## User Flow

```
User visits /manage
  → enters email
  → server looks up users/<slug>/taste_profile.json
  → if found: renders current delivery settings + text box
  → if not found: shows "email not recognised" message

User sees:
  [Frequency section]
    - daily toggle (on/off)
    - weekly toggle (on/off)
    - day-of-week picker (only visible if weekly is on)
    - "Revert" button (restores original values loaded from server)
    - "Save frequency" button → POST /manage/update-frequency

  [Profile feedback section]
    - free-text box: "Describe what has changed in your research interests"
    - "Send feedback" button → POST /manage/submit-feedback
    - on success: text box becomes read-only, button disabled, confirmation shown
```

---

## Backend Design

### Identity lookup

User submits their email. Server derives the directory slug using the same sanitisation function used at signup (`re.sub(r'[^a-z0-9-]', '-', email.lower())`). Scans `users/` for a matching directory with a `taste_profile.json`.

**Endpoint:** `GET /manage?email=<email>` — or a POST form to avoid email appearing in server logs.

### Frequency update

`POST /manage/update-frequency`
- Body: `{ email, daily_digest, weekly_digest, weekly_day }`
- Server validates inputs, writes directly to `users/<slug>/taste_profile.json` (no separate script needed — Flask can do this in 5 lines)
- Returns 200 on success

### Feedback submission

`POST /manage/submit-feedback`
- Body: `{ email, feedback_text }`
- Server writes to `users/<slug>/pending_profile_update.txt` (timestamped, appended if file exists)
- Sends a notification email to the operator
- Returns 200 on success — frontend locks the text box

### Operator processing of feedback

Two scripts, both run manually from the project root:

**Script 1 — frequency changes:** Not needed. Flask handles these directly and atomically at request time. No queue, no script.

**Script 2 — profile feedback:** Invoke the existing `/edit-profile` Claude Code skill:
```bash
# Operator sees notification email, then runs:
/edit-profile <slug>
# Skill reads pending_profile_update.txt, applies changes to taste_profile.json,
# prints a patch summary, waits for operator confirmation, then deploys.
```

The skill already handles the full flow (pull from server → patch → confirm → SCP back). The only addition needed: the skill should check for `pending_profile_update.txt` and use its contents as the feedback text, then delete the file after successful deployment.

---

## Data layout

```
users/<slug>/
  pending_profile_update.txt   ← created by /manage/submit-feedback
                                  format: one timestamped block per submission
                                  deleted by edit-profile skill after processing
```

No new directories needed.

---

## Challenges and Alternatives

### 1. Identity: email lookup with no password

**Risk:** Anyone who knows a user's email can view their delivery preferences and submit fake interest changes. Delivery preferences (daily/weekly, day of week) are low-sensitivity. Interest feedback is higher-stakes: a malicious submission could pollute a user's profile.

**Mitigations:**
- Frequency changes are harmless to expose — worst case someone toggles a stranger's digest off for a day
- Feedback goes into a file that the operator reads and confirms before any change is made — so a malicious submission gets caught before it touches the profile
- Don't enumerate: always return the same response whether the email is found or not ("if your email is registered, your settings will appear" — avoids leaking which emails are in the system)

**Alternative: magic link** — user enters email, server sends a one-time link. Much more secure, but adds email infrastructure complexity and a second round-trip UX. Probably overkill given the low sensitivity of what's exposed. Revisit if the platform grows.

**Alternative: operator-only profile edit** — don't build a self-service page at all; users email the operator and the operator runs `/edit-profile`. Already works today. The self-service page is purely about reducing operator burden and improving user experience.

---

### 2. Frequency section: "Revert" button

**Risk:** The revert button needs to know the original values. If the frontend stores them in JS variables on page load, a page refresh loses them. The button would have to reload from the server.

**Recommendation:** On page load, store original values in hidden form fields (or a JS `const`). The revert button resets the visible toggles to those values. No server call needed for revert — it's purely a frontend reset. The server is only called on "Save".

**Alternative:** No revert button — just reload the page. Simpler, but loses any other unsaved state (e.g. if the user has typed in the feedback box).

---

### 3. Frequency update: direct Flask write vs. queued script

**Decision:** Flask writes directly to `taste_profile.json`. No separate script needed — the endpoint handles it in ~5 lines.

**Risk:** If the pipeline is running at exactly the same moment, there is a file write race condition. In practice, the pipeline reads `taste_profile.json` once at scoring time (~00:32 ET); a user visiting `/manage` at that exact moment is extremely unlikely. Acceptable risk.

**Risk 2:** Flask runs as a different process than the pipeline. Both use plain `json.dump` — no file locking. On Linux this is safe for small files (atomic rename pattern would be safer but is overkill here).

---

### 4. Feedback submission: "makes that part uneditable"

**Decision:** Lock the text box and disable the button only on a confirmed 200 response. On any error, show an inline message ("Submission failed — please try again") and keep the box editable.

Submissions are appended to `pending_profile_update.txt` with a timestamp — never overwritten. Each block is clearly delimited. On the next page load, if `pending_profile_update.txt` already exists for this user, show a notice: "You have a pending feedback request being processed." and hide the text box entirely until the operator clears it (i.e. after the edit-profile skill deletes the file).

---

### 5. Operator notification

**Risk:** Feedback arrives in `pending_profile_update.txt` but the operator never sees it.

**Recommendation:** `submit-feedback` endpoint sends a notification email to the operator (same SMTP config already used for run summaries). Subject: `[Incoming Science] Profile feedback from <slug>`. Body includes the submitted text.

**Alternative:** Operator polls `pending_profile_update.txt` files manually. Fragile — easy to miss.

---

### 6. Edit-profile skill integration

The current skill expects the operator to paste feedback text interactively. To consume `pending_profile_update.txt` automatically, the skill needs a small addition: if invoked as `/edit-profile <slug>` and `users/<slug>/pending_profile_update.txt` exists, read that file as the feedback text (Step 4 of the skill). After successful SCP deploy (Step 8), delete the file.

**Risk:** The skill is a Claude Code skill, not a script — it requires the operator to be present for the confirmation step (Step 6). This is intentional and desirable: the operator reviews every profile change before it goes live.

**Alternative: fully automated profile patching** — Claude patches and deploys with no confirmation. Risky: a poorly-worded user submission could introduce garbage keywords or wrong grade shifts. The human-in-the-loop is worth keeping.

---

### 7. Page location and navigation

**Proposed:** `incomingscience.xyz/manage` — linked from the landing page.

**Alternative:** Link from the digest email itself ("Manage your preferences" button at the bottom of the PDF or email body). This is better UX — user is already authenticated by virtue of having received the email — but requires changes to the PDF/email builder. A good follow-on improvement, not needed for v1.

---

## What is deliberately out of scope (v1)

- No password / token auth — trust email input
- No ability to change email address
- No ability to see or change keywords/grades directly (that stays operator-only)
- No ability to cancel the service (operator handles offboarding)
- No mobile-specific layout pass (reuse onboarding CSS patterns)

---

## Implementation order (recommended)

1. Flask endpoints (`/manage`, `/manage/update-frequency`, `/manage/submit-feedback`) — ~1h
2. Update edit-profile skill to read `pending_profile_update.txt` — ~15 min
3. Build the HTML page (reuse onboarding design system) — ~2h
4. Link from landing page — 5 min
5. Test end-to-end with a real user slug

---

## Decided

- **Field display:** Show current field as read-only text — informational only, not editable.
- **Rate limiting:** One feedback submission per 24h per user. Enforced server-side: if `pending_profile_update.txt` exists and its last timestamp is less than 24h ago, return 429. No extra storage — the timestamp is already in the file.
- **Both toggles off warning:** If the user toggles off both `daily_digest` and `weekly_digest`, show an inline warning before allowing save: "Turning off both options will unsubscribe you from all digests." The Save button still works — it's a warning, not a block.
- **Feedback lock:** Text box and Send button lock only on confirmed 200. Error keeps the box editable with an inline error message.
- **Frequency script:** No separate script — Flask handles directly.
- **Edit-profile skill:** Will be updated to auto-read `pending_profile_update.txt` when invoked with a slug, and delete it after successful deploy.
- **Feedback format:** Appended with timestamps, never overwritten.

## Open questions

- None remaining — ready for implementation.
