#!/usr/bin/env python3
"""
server.py — Rating server for the arXiv digest.

Handles GET /rate?paper_id=...&rating=...&date=YYYY-MM-DD
Enriches the rating with paper metadata and appends it to data/DATE/ratings.json.

Development:
    python server.py

Production (on Red Pitaya):
    gunicorn -w 1 -b 0.0.0.0:5000 server:app
"""

import json
import threading
from datetime import date, datetime
from pathlib import Path

from flask import Flask, request, send_from_directory

app = Flask(__name__)

BASE_DIR      = Path(__file__).parent
USERS_DIR     = BASE_DIR / "users"
VALID_RATINGS = {"excellent", "good", "irrelevant"}

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
    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Incoming Science</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700&display=swap" rel="stylesheet">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Nunito', -apple-system, BlinkMacSystemFont, sans-serif;
      background: #F7F4EF;
      color: #2C2826;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 32px 24px;
    }
    .card {
      background: #fff;
      border-radius: 12px;
      padding: 48px 40px;
      max-width: 580px;
      width: 100%;
      box-shadow: 0 2px 12px rgba(44,40,38,0.10);
      text-align: center;
    }
    .logo {
      width: 180px;
      height: auto;
      margin-bottom: 8px;
      border: 2px solid #DDD5C8;
      border-radius: 12px;
      padding: 12px;
      background: #FAFCF6;
    }
    h1 {
      font-size: 1.7em;
      font-weight: 700;
      letter-spacing: -0.5px;
      color: #2C2826;
      margin-bottom: 6px;
    }
    .tagline {
      font-size: 0.9em;
      color: #9C9288;
      margin-bottom: 28px;
    }
    .divider {
      border: none;
      border-top: 2px solid #EAE4DB;
      margin: 28px 0;
    }
    p {
      color: #5C5550;
      font-size: 0.95em;
      line-height: 1.75;
      margin-bottom: 16px;
      text-align: left;
    }
    .steps {
      background: #F7F4EF;
      border: 2px solid #DDD5C8;
      border-radius: 8px;
      padding: 20px 24px;
      text-align: left;
      margin: 24px 0;
    }
    .steps ol {
      padding-left: 20px;
      color: #5C5550;
      font-size: 0.95em;
      line-height: 2;
    }
    .steps ol li strong {
      color: #2C2826;
    }
    .btn {
      display: inline-block;
      background: #DDD5C8;
      color: #2C2826;
      font-family: inherit;
      font-size: 0.95em;
      font-weight: 700;
      padding: 12px 28px;
      border-radius: 8px;
      text-decoration: none;
      margin-top: 8px;
      transition: background 0.15s;
    }
    .btn:hover { background: #CEC5B6; }
    .contact {
      margin-top: 24px;
      font-size: 0.88em;
      color: #9C9288;
    }
    .contact a {
      color: #6A8FAF;
      text-decoration: none;
      font-weight: 600;
    }
    .contact a:hover { text-decoration: underline; }
    .footer {
      margin-top: 32px;
      font-size: 0.78em;
      color: #B8B0A8;
    }
  </style>
</head>
<body>
  <div class="card">
    <img src="/logo.png" alt="Incoming Science logo" class="logo">
    <p class="tagline">Your daily arXiv digest, personalised by AI.</p>

    <hr class="divider">

    <p>Incoming Science fetches the latest papers in your field every morning, ranks them
    by relevance to your research interests, and delivers a scored PDF to your inbox &mdash;
    ready to read on your phone.</p>
    <p>Rate papers with one tap. Ratings feed back into an evolving taste profile that
    sharpens recommendations over time.</p>

    <hr class="divider">

    <div class="steps">
      <ol>
        <li><strong>Download</strong> the onboarding form below.</li>
        <li><strong>Fill it in</strong> &mdash; your research interests, keywords, and a few representative papers.</li>
        <li><strong>Email it back</strong> to get set up.</li>
      </ol>
    </div>

    <a href="/onboarding" class="btn">&#8659;&nbsp; Download onboarding form</a>

    <div class="contact">
      Send the completed form to
      <a href="mailto:yuval.zamir@icfo.eu">yuval.zamir@icfo.eu</a>
    </div>

    <p class="footer">Built for researchers, by a researcher.</p>
  </div>
</body>
</html>"""
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


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


@app.route("/health")
def health():
    """Liveness check — confirm the server is running."""
    return {"status": "ok", "date": date.today().isoformat()}, 200


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
