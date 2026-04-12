#!/usr/bin/env python3
"""
server.py — Rating server for the scientific literature digest.

Handles GET /rate?paper_id=...&rating=...&date=YYYY-MM-DD
Enriches the rating with paper metadata and appends it to data/DATE/ratings.json.

Development:
    python server.py

Production (on Red Pitaya):
    gunicorn -w 1 -b 0.0.0.0:5000 server:app
"""

import json
import re
import threading
from datetime import date, datetime
from pathlib import Path

from flask import Flask, request, send_from_directory

app = Flask(__name__)

BASE_DIR          = Path(__file__).parent
USERS_DIR         = BASE_DIR / "users"
USERS_PENDING_DIR = BASE_DIR / "users_pending"
VALID_RATINGS     = {"excellent", "good", "irrelevant"}

REQUIRED_ONBOARDING_FIELDS = {"email", "field", "interests_description", "researchers"}

_write_lock = threading.Lock()   # guard concurrent writes to ratings.json


# ── Page template — mobile-first, matches digest palette ─────────────────────

_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, sans-serif;
      background: #F7F4EF;
      color: #2C2826;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }}
    .card {{
      background: #fff;
      border-radius: 8px;
      padding: 28px 24px;
      max-width: 480px;
      width: 100%;
      box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    }}
    .badge {{
      display: inline-block;
      padding: 5px 14px;
      border-radius: 20px;
      font-size: 0.85em;
      font-weight: bold;
      margin-bottom: 16px;
      color: #2C2826;
    }}
    .excellent  {{ background: #8FAF8F; }}
    .good       {{ background: #A8A890; }}
    .irrelevant {{ background: #B8A8A8; }}
    .error      {{ background: #C4967A; color: #fff; }}
    h2 {{ font-size: 1.05em; line-height: 1.4; margin-bottom: 10px; }}
    p  {{ color: #5C5550; font-size: 0.9em; line-height: 1.5; }}
  </style>
</head>
<body>
  <div class="card">
    {body}
  </div>
</body>
</html>"""

_RATING_META = {
    "excellent":  ("★ Very Relevant", "excellent"),
    "good":       ("◆ Interesting",   "good"),
    "irrelevant": ("✕ Not Relevant",  "irrelevant"),
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_user_data_dir(username: str) -> Path | None:
    """
    Validate username and return the user's data directory.
    Returns None if the username is invalid or the directory doesn't exist.
    """
    if not username or "/" in username or "\\" in username or ".." in username:
        return None
    user_dir = USERS_DIR / username
    if not user_dir.is_dir():
        return None
    return user_dir / "data"


def find_paper(paper_id: str, date_str: str, data_dir: Path) -> dict | None:
    """Look up paper metadata in scored_papers.json then today_papers.json."""
    folder = data_dir / date_str
    for filename in ("scored_papers.json", "today_papers.json"):
        path = folder / filename
        if not path.exists():
            continue
        try:
            for p in json.loads(path.read_text(encoding="utf-8")):
                if p.get("arxiv_id") == paper_id:
                    return p
        except (json.JSONDecodeError, OSError):
            continue
    return None


def append_rating(paper_id: str, rating: str, paper: dict | None, date_str: str, data_dir: Path):
    """Write an enriched rating entry to data/DATE/ratings.json."""
    folder = data_dir / date_str
    folder.mkdir(parents=True, exist_ok=True)
    ratings_path = folder / "ratings.json"

    entry = {
        "paper_id":  paper_id,
        "rating":    rating,
        "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "date":      date_str,
    }
    if paper:
        entry["title"]         = paper.get("title", "")
        entry["authors"]       = paper.get("authors", [])
        entry["abstract"]      = paper.get("abstract", "")
        entry["score"]         = paper.get("score")           # None for unscored
        entry["justification"] = paper.get("justification", "")
        entry["tags"]          = paper.get("tags", [])

    with _write_lock:
        try:
            existing = json.loads(ratings_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            existing = []
        existing.append(entry)
        ratings_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def render(title: str, body: str) -> str:
    return _PAGE.format(title=title, body=body)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/rate")
def rate():
    paper_id = request.args.get("paper_id", "").strip()
    rating   = request.args.get("rating",   "").strip().lower()
    date_str = request.args.get("date",     date.today().isoformat())
    username = request.args.get("user",     "").strip()

    # Validate inputs
    if not paper_id:
        body = '<span class="badge error">Error</span><h2>Missing paper ID.</h2>'
        return render("Error", body), 400

    if rating not in VALID_RATINGS:
        body = f'<span class="badge error">Error</span><h2>Unknown rating "{rating}".</h2>'
        return render("Error", body), 400

    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        body = '<span class="badge error">Error</span><h2>Invalid date format.</h2>'
        return render("Error", body), 400

    data_dir = get_user_data_dir(username)
    if data_dir is None:
        body = f'<span class="badge error">Error</span><h2>Unknown user "{username}".</h2>'
        return render("Error", body), 400

    paper = find_paper(paper_id, date_str, data_dir)
    append_rating(paper_id, rating, paper, date_str, data_dir)

    label, css_class = _RATING_META[rating]
    title_text = paper["title"] if paper else paper_id
    body = f"""
      <span class="badge {css_class}">{label}</span>
      <h2>{title_text}</h2>
      <p>Rating saved. You can close this tab.</p>
    """
    return render("Rated!", body), 200


@app.route("/")
def index():
    return send_from_directory(
        BASE_DIR / "website" / "stitch_platform_user_expansion" / "incoming_science_how_it_works_final",
        "code.html",
    )


@app.route("/signup")
def signup_step1():
    return send_from_directory(
        BASE_DIR / "website" / "stitch_platform_user_expansion" / "onboarding_identity_delivery_final",
        "code.html",
    )


@app.route("/signup/field")
def signup_step2():
    return send_from_directory(
        BASE_DIR / "website" / "stitch_platform_user_expansion" / "onboarding_research_field_final",
        "code.html",
    )


@app.route("/signup/interests")
def signup_step3():
    return send_from_directory(
        BASE_DIR / "website" / "stitch_platform_user_expansion" / "onboarding_signals_interests_final",
        "code.html",
    )


@app.route("/signup/papers")
def signup_step4():
    return send_from_directory(
        BASE_DIR / "website" / "stitch_platform_user_expansion" / "onboarding_seed_papers_final",
        "code.html",
    )


@app.route("/signup/done")
def signup_done():
    return send_from_directory(
        BASE_DIR / "website" / "stitch_platform_user_expansion" / "onboarding_success_final",
        "code.html",
    )


@app.route("/assets/<path:filename>")
def assets(filename):
    return send_from_directory(BASE_DIR / "website" / "assets", filename)


@app.route("/web/<path:filename>")
def website(filename):
    """Serve the static onboarding website from website/."""
    return send_from_directory(BASE_DIR / "website", filename)


@app.route("/logo.png")
def logo():
    return send_from_directory(BASE_DIR / "docs", "logo.png", mimetype="image/png")


@app.route("/onboarding")
def onboarding():
    return send_from_directory(
        BASE_DIR / "docs", "incoming_science_onboarding.docx",
        as_attachment=True,
        download_name="incoming_science_onboarding.docx",
    )


@app.route("/onboarding/submit", methods=["POST"])
def onboarding_submit():
    """
    Receive the completed onboarding JSON from the web flow and save it
    to users_pending/<email_slug>/onboarding.json for manual processing.
    """
    data = request.get_json(silent=True)
    if not data:
        return {"status": "error", "message": "Invalid JSON body."}, 400

    missing = REQUIRED_ONBOARDING_FIELDS - data.keys()
    if missing:
        return {"status": "error", "message": f"Missing fields: {', '.join(sorted(missing))}"}, 400

    email = str(data.get("email", "")).strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return {"status": "error", "message": "Invalid email address."}, 400

    # Sanitise email → directory slug (alphanumeric + hyphens only)
    slug = re.sub(r"[^a-z0-9]+", "-", email).strip("-")
    if not slug:
        return {"status": "error", "message": "Could not derive a valid slug from email."}, 400

    USERS_PENDING_DIR.mkdir(exist_ok=True)
    pending_dir = USERS_PENDING_DIR / slug
    pending_dir.mkdir(exist_ok=True)

    payload = dict(data)
    payload["submitted_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    out_path = pending_dir / "onboarding.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    return {"status": "ok"}, 200


@app.route("/health")
def health():
    """Liveness check — confirm the server is running."""
    return {"status": "ok", "date": date.today().isoformat()}, 200


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
