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
import os
import re
import smtplib
import threading
from datetime import date, datetime, timedelta, timezone
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, request, render_template_string, send_from_directory, url_for

load_dotenv()

app = Flask(__name__)

BASE_DIR          = Path(__file__).parent
USERS_DIR         = BASE_DIR / "users"
USERS_PENDING_DIR = BASE_DIR / "users_pending"
VALID_RATINGS     = {"excellent", "good", "irrelevant"}

REQUIRED_ONBOARDING_FIELDS = {"email", "field", "interests_description", "researchers"}

_write_lock = threading.Lock()   # guard concurrent writes to ratings.json

_SMTP_HOST     = os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")
_SMTP_PORT     = int(os.environ.get("EMAIL_SMTP_PORT", "587"))
_SMTP_USER     = os.environ.get("EMAIL_SMTP_USER", "")
_SMTP_PASSWORD = os.environ.get("EMAIL_SMTP_PASSWORD", "")
_EMAIL_FROM    = os.environ.get("EMAIL_FROM", "")


_UNSUBSCRIBE_CONFIRM_HTML = """<!DOCTYPE html>
<html><body style="font-family:sans-serif;max-width:480px;margin:60px auto;padding:0 20px">
<h2>Unsubscribe from Incoming Science</h2>
<p>Stop receiving digests for <strong>{{ username }}</strong>?</p>
<p><a href="{{ confirm_url }}"
   style="background:#c0392b;color:#fff;padding:10px 20px;text-decoration:none;border-radius:4px">
   Yes, unsubscribe me</a></p>
<p style="margin-top:24px;font-size:13px;color:#666">To re-subscribe, reply to any previous digest email.</p>
</body></html>"""

_UNSUBSCRIBE_DONE_HTML = """<!DOCTYPE html>
<html><body style="font-family:sans-serif;max-width:480px;margin:60px auto;padding:0 20px">
<h2>You've been unsubscribed</h2>
<p><strong>{{ username }}</strong> will no longer receive digest emails.</p>
<p style="font-size:13px;color:#666">To re-subscribe, reply to any previous digest email.</p>
</body></html>"""


def _send_unsubscribe_notification(username: str) -> None:
    """Notify operator when a user unsubscribes."""
    if not _SMTP_USER or not _SMTP_PASSWORD:
        return
    msg = MIMEText(f"User '{username}' has unsubscribed from Incoming Science digests.")
    msg["Subject"] = f"Incoming Science — unsubscribed: {username}"
    msg["From"]    = _EMAIL_FROM
    msg["To"]      = _EMAIL_FROM
    try:
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=15) as s:
            s.ehlo(); s.starttls(); s.ehlo()
            s.login(_SMTP_USER, _SMTP_PASSWORD)
            s.sendmail(_EMAIL_FROM, [_EMAIL_FROM], msg.as_string())
    except Exception:
        pass


def _send_signup_notification(slug: str, field: str, submitted_at: str) -> None:
    """Send a signup notification email to the operator account."""
    if not _SMTP_USER or not _SMTP_PASSWORD:
        return
    msg = MIMEText(f"New signup\n\nSlug:  {slug}\nField: {field}\nTime:  {submitted_at}\n")
    msg["Subject"] = f"Incoming Science — new signup: {slug}"
    msg["From"]    = _EMAIL_FROM
    msg["To"]      = _EMAIL_FROM  # send to itself
    try:
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(_SMTP_USER, _SMTP_PASSWORD)
            server.sendmail(_EMAIL_FROM, [_EMAIL_FROM], msg.as_string())
    except Exception:
        pass  # notification failure must never break the signup response


def _send_welcome_email(to_email: str) -> None:
    """Send a welcome email with how-to instructions to the new user.

    The digest example image is embedded inline via CID so it appears in the
    email body regardless of whether the client blocks external images.
    """
    if not _SMTP_USER or not _SMTP_PASSWORD:
        return
    html = """\
<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;max-width:650px;margin:0 auto;color:#222;">
<p>Hello,</p>
<p>Welcome to <strong>Incoming Science</strong>! It's great to have you, and we hope you find the
daily (or weekly) digests helpful in the never-ending chase after the academic wave-front.
Your request will be processed soon — probably by tomorrow you'll receive your first email
(according to the schedule you chose).</p>

<p><strong>Quick How-To (1 minute read)</strong></p>
<ul>
  <li>The digests look like the image below. Notice the paper score — this is the main feature. 
  Generally speaking: <strong>9–10</strong> are a must-read,
  <strong>6–8</strong> are interesting, and below 5 it becomes noise.</li>
  <li>At the bottom of each paper block there is a rating panel
  You don't need to rate many papers —
  <strong>1–3 per day</strong> is more than enough. Focus on papers with a
  discrepancy between the received score and your interest level: if an only OK paper
  got a 10, rate it down to <em>Interesting</em>.</li>
</ul>

<p><img src="cid:welcome_image" alt="Digest example"
     style="max-width:400px;width:100%;border:1px solid #ddd;"></p>

<p>Incoming Science is a non-profit project, but there are operating costs (~$1/month per user).
We don't ask for payment, but if you'd like to support the project, feel free to get in touch.</p>

<p>Good day,<br><strong>Incoming Science</strong></p>
</body>
</html>"""

    # "related" allows CID image references inside the HTML part
    msg = MIMEMultipart("related")
    msg["Subject"] = "Welcome to Incoming Science"
    msg["From"]    = _EMAIL_FROM
    msg["To"]      = to_email
    msg.attach(MIMEText(html, "html"))

    image_path = BASE_DIR / "website" / "assets" / "Welcome_Email.png"
    if image_path.exists():
        with open(image_path, "rb") as f:
            img = MIMEImage(f.read())
        img.add_header("Content-ID", "<welcome_image>")
        img.add_header("Content-Disposition", "inline", filename="Welcome_Email.png")
        msg.attach(img)

    try:
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(_SMTP_USER, _SMTP_PASSWORD)
            server.sendmail(_EMAIL_FROM, [to_email], msg.as_string())
    except Exception:
        pass  # welcome email failure must never break the signup response


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


@app.route("/unsubscribe")
def unsubscribe():
    username = request.args.get("user", "").strip()
    confirm  = request.args.get("confirm", "")

    if not username:
        return "Missing user parameter.", 400

    profile_path = USERS_DIR / username / "taste_profile.json"
    if not profile_path.exists():
        return "User not found.", 404

    if confirm != "1":
        confirm_url = url_for("unsubscribe", user=username, confirm="1")
        return render_template_string(_UNSUBSCRIBE_CONFIRM_HTML,
                                      username=username, confirm_url=confirm_url)

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    already_off = (not profile.get("daily_digest", True)
                   and not profile.get("weekly_digest", False))

    profile["daily_digest"]  = False
    profile["weekly_digest"] = False
    with _write_lock:
        profile_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False),
                                encoding="utf-8")
    app.logger.info("Unsubscribed user: %s", username)

    if not already_off:
        _send_unsubscribe_notification(username)

    return render_template_string(_UNSUBSCRIBE_DONE_HTML, username=username)


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
    if request.content_length and request.content_length > 50_000:
        return {"status": "error", "message": "Payload too large."}, 413

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

    _send_signup_notification(slug, data.get("field", ""), payload["submitted_at"])
    _send_welcome_email(email)

    return {"status": "ok"}, 200


@app.route("/fields.json")
def fields_json():
    return send_from_directory(BASE_DIR, "fields.json", mimetype="application/json")


@app.route("/robots.txt")
def robots():
    return send_from_directory(BASE_DIR / "website", "robots.txt", mimetype="text/plain")


@app.route("/legal")
def legal():
    return send_from_directory(
        BASE_DIR / "website" / "stitch_platform_user_expansion" / "legal_final",
        "code.html",
    )


@app.route("/sources")
def sources():
    return send_from_directory(
        BASE_DIR / "website" / "stitch_platform_user_expansion" / "sources_final",
        "code.html",
    )


@app.route("/sitemap.xml")
def sitemap():
    return send_from_directory(BASE_DIR / "website", "sitemap.xml", mimetype="application/xml")


@app.route("/health")
def health():
    """Liveness check — confirm the server is running."""
    return {"status": "ok", "date": date.today().isoformat()}, 200


# ── /manage — user self-service ───────────────────────────────────────────────

VALID_DAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
_FEEDBACK_RATE_LIMIT_HOURS = 24


def _email_to_slug(email: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", email.strip().lower()).strip("-")


def _find_user_by_email(email: str) -> tuple[str, Path] | None:
    """Return (slug, profile_path) for a registered user, or None if not found.

    Checks two things:
    1. Slug derived from email matches a user directory (fast path).
    2. Any EMAIL_TO / EMAIL_TO_DAILY / EMAIL_TO_WEEKLY in any user's .env matches.
    """
    email = email.strip().lower()
    if not email:
        return None

    # Fast path: slug match
    slug = _email_to_slug(email)
    if slug:
        profile_path = USERS_DIR / slug / "taste_profile.json"
        if profile_path.exists():
            return slug, profile_path

    # Fallback: scan all .env files for matching email addresses
    for env_path in USERS_DIR.glob("*/.env"):
        try:
            env_emails = set()
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith(("EMAIL_TO=", "EMAIL_TO_DAILY=", "EMAIL_TO_WEEKLY=")):
                    val = line.split("=", 1)[1]
                    for addr in val.split(","):
                        addr = addr.strip().lower()
                        if addr:
                            env_emails.add(addr)
            if email in env_emails:
                user_dir = env_path.parent
                profile_path = user_dir / "taste_profile.json"
                if profile_path.exists():
                    return user_dir.name, profile_path
        except OSError:
            continue

    return None


def _send_feedback_notification(slug: str, feedback_text: str) -> None:
    if not _SMTP_USER or not _SMTP_PASSWORD:
        return
    body = f"Profile feedback submitted by: {slug}\n\n{feedback_text}\n\nRun: /edit-profile-from-file {slug}"
    msg = MIMEText(body)
    msg["Subject"] = f"[Incoming Science] Profile feedback from {slug}"
    msg["From"]    = _EMAIL_FROM
    msg["To"]      = _EMAIL_FROM
    try:
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=15) as s:
            s.ehlo(); s.starttls(); s.ehlo()
            s.login(_SMTP_USER, _SMTP_PASSWORD)
            s.sendmail(_EMAIL_FROM, [_EMAIL_FROM], msg.as_string())
    except Exception:
        pass


def _get_last_feedback_time(pending_path: Path) -> datetime | None:
    """Parse the most recent timestamp from pending_profile_update.txt."""
    if not pending_path.exists():
        return None
    text = pending_path.read_text(encoding="utf-8")
    # Timestamps are written as [YYYY-MM-DDTHH:MM:SSZ] at the start of each block
    matches = re.findall(r"\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\]", text)
    if not matches:
        return None
    try:
        return datetime.fromisoformat(matches[-1].replace("Z", "+00:00"))
    except ValueError:
        return None


@app.route("/manage")
def manage():
    return send_from_directory(
        BASE_DIR / "website" / "stitch_platform_user_expansion" / "manage_final",
        "code.html",
    )


@app.route("/manage/lookup", methods=["POST"])
def manage_lookup():
    """Look up a user by email and return their current delivery settings."""
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    if not email:
        return {"status": "error", "message": "Email required."}, 400

    result = _find_user_by_email(email)
    if result is None:
        # Always return the same message to avoid enumerating registered emails
        return {"status": "not_found"}, 200

    slug, profile_path = result
    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"status": "error", "message": "Could not read profile."}, 500

    pending_path = USERS_DIR / slug / "pending_profile_update.txt"

    return {
        "status": "ok",
        "slug": slug,
        "daily_digest":  profile.get("daily_digest", False),
        "weekly_digest": profile.get("weekly_digest", False),
        "weekly_day":    profile.get("weekly_day", "friday"),
        "field":         profile.get("field", ""),
        "has_pending_feedback": pending_path.exists(),
    }, 200


@app.route("/manage/update-frequency", methods=["POST"])
def manage_update_frequency():
    """Update delivery frequency settings for a user identified by email."""
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    if not email:
        return {"status": "error", "message": "Email required."}, 400

    result = _find_user_by_email(email)
    if result is None:
        return {"status": "not_found"}, 200

    slug, profile_path = result

    daily_digest  = bool(data.get("daily_digest", False))
    weekly_digest = bool(data.get("weekly_digest", False))
    weekly_day    = str(data.get("weekly_day", "friday")).strip().lower()

    if weekly_day not in VALID_DAYS:
        return {"status": "error", "message": f"Invalid weekly_day: {weekly_day}"}, 400

    try:
        with _write_lock:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["daily_digest"]  = daily_digest
            profile["weekly_digest"] = weekly_digest
            profile["weekly_day"]    = weekly_day
            profile_path.write_text(
                json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8"
            )
    except (json.JSONDecodeError, OSError) as e:
        app.logger.error("manage_update_frequency: %s", e)
        return {"status": "error", "message": "Failed to update profile."}, 500

    app.logger.info("manage: updated frequency for %s (daily=%s weekly=%s day=%s)",
                    slug, daily_digest, weekly_digest, weekly_day)
    return {"status": "ok"}, 200


@app.route("/manage/submit-feedback", methods=["POST"])
def manage_submit_feedback():
    """Append free-text interest feedback to pending_profile_update.txt."""
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    feedback_text = str(data.get("feedback_text", "")).strip()

    if not email:
        return {"status": "error", "message": "Email required."}, 400
    if not feedback_text:
        return {"status": "error", "message": "Feedback text required."}, 400
    if len(feedback_text) > 5000:
        return {"status": "error", "message": "Feedback too long (max 5000 characters)."}, 400

    result = _find_user_by_email(email)
    if result is None:
        return {"status": "not_found"}, 200

    slug, _ = result
    pending_path = USERS_DIR / slug / "pending_profile_update.txt"

    # Rate limit: one submission per 24h
    last_time = _get_last_feedback_time(pending_path)
    if last_time is not None:
        now = datetime.now(tz=timezone.utc)
        if (now - last_time) < timedelta(hours=_FEEDBACK_RATE_LIMIT_HOURS):
            return {"status": "rate_limited",
                    "message": "You can submit feedback once every 24 hours."}, 429

    timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    block = f"[{timestamp}]\n{feedback_text}\n\n---\n"

    with _write_lock:
        with open(pending_path, "a", encoding="utf-8") as f:
            f.write(block)

    _send_feedback_notification(slug, feedback_text)
    app.logger.info("manage: feedback received from %s", slug)
    return {"status": "ok"}, 200


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
