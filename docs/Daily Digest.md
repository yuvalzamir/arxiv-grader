# Daily Digest

[[Home]] | [[Pipeline Overview]] | [[Weekly Digest]] | [[Infrastructure]]

---

## PDF Structure

Built by `build_digest_pdf.py` using ReportLab. Font: DejaVu Sans (broad Unicode coverage for LaTeX-heavy titles, via `pylatexenc`).

**Layout:**
```
Header: date + paper counts (arXiv: N, journals: M)
─────────────────────────────
Scored section (sorted by score descending):
  ┌──────────────────────────────┐
  │ [Title hyperlink]             │ ← links to arxiv.org or doi.org
  │ Authors · source badge        │
  │ Score badge (1–10)            │
  │ Justification text            │
  │ [Abstract]                    │
  │ [★ Excellent] [◆ Good] [✕ Irrelevant] │ ← rating hyperlinks
  └──────────────────────────────┘
─────────────────────────────
Unscored section (remaining papers):
  Title + authors + rating buttons only (no abstract)
```

Within each section, **journal papers come first**, then arXiv papers.

**Author line truncation:** lists of more than 8 authors show the first 8, then `... <last author>` — the last author is always shown rather than being dropped behind a generic "et al." (`author_table()` in `build_digest_pdf.py`).

**Color palette:**
- Score 8–10: sage green badge
- Score 5–7: amber badge
- Score 1–4: muted red badge

---

## Rating Buttons

Each paper gets three clickable rating links embedded as hyperlinks in the PDF:

```
https://incomingscience.xyz/rate?
  paper_id=2301.12345
  &rating=excellent
  &date=2026-03-18
  &user=alice
```

- `paper_id` is percent-encoded (DOIs contain `/` which must be URL-encoded)
- `date` ensures late ratings are attributed to the correct day
- Tapping opens the browser briefly; the server records the rating and returns a confirmation page

The server (`server.py /rate`) auto-decodes percent-encoded query parameters via Flask.

---

## Paper Insights (Opt-In)

When `paper_insights: true` in `taste_profile.json`, scored papers include an `insights` object:
```json
"insights": {
  "claim": "What the paper claims",
  "novelty": "What makes it new",
  "relevance": "Why it's relevant to this user"
}
```

The PDF renders these as a three-row box **below the author band**, replacing the standard justification + tags layout. Papers with truncated/missing abstracts are excluded from insights (Python-enforced, not just prompt instruction).

→ See [[Paper Insights]] for the full feature spec.

---

## Email Delivery

Subject: `"Incoming Science — YYYY-MM-DD (arXiv: N, journals: M)"`

The PDF is attached. Delivery is skipped if:
- `--no-email` flag is passed
- `daily_digest: false` in the user's taste profile

**Mailing list:** `EMAIL_TO_DAILY` in user `.env` → fallback to `EMAIL_TO`.

Multiple recipients: `EMAIL_TO_DAILY=alice@lab.org,bob@lab.org`

---

## Delivery Modes

Each user independently controls their delivery:

| `daily_digest` | `weekly_digest` | Result |
|---|---|---|
| `true` | `false` | Daily PDF emailed every weekday |
| `false` | `true` | No daily email; weekly digest on chosen day |
| `true` | `true` | Both — daily and weekly emails |

The daily **pipeline** (scoring, PDF build) always runs regardless. The email is what's conditional.

→ See [[Weekly Digest]] for weekly mode details.

---

## Unsubscribe

Users can unsubscribe via `GET /unsubscribe?user=<name>`. This shows a confirmation page, then on `confirm=1`, sets both `daily_digest: false` and `weekly_digest: false` in the profile and notifies the operator.

---

## `build_digest_pdf.py` Key Details

**URL builder:**
```python
def paper_url(paper):
    if paper["arxiv_id"].startswith("10."):
        return f"https://doi.org/{paper['arxiv_id']}"
    return f"https://arxiv.org/abs/{paper['arxiv_id']}"
```

**DOI encoding in rating URLs:**
```python
quote(paper_id, safe="")  # encodes "/" in DOIs
```

**`KeepTogether`** wrapping prevents subsection headers from being orphaned at page breaks.
