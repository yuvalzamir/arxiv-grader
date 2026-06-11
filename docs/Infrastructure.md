# Infrastructure & Deployment

[[Home]] | [[Operations]] | [[Pipeline Overview]]

Server access policy: `server_access.md`

---

## Stack

| Layer | Technology |
|-------|-----------|
| VPS | Hetzner CX23, Ubuntu 24.04, `116.203.255.222` |
| Server root | `/opt/arxiv-grader/` |
| HTTPS | Caddy (auto Let's Encrypt) → Gunicorn (systemd) → Flask (`server.py`) |
| Scheduling | System cron, TZ=America/New_York |
| Email | Shared SMTP (Gmail app password) via root `.env` |
| LLM (triage) | Anthropic API — Haiku, cached, shared per-field key |
| LLM (scoring) | Anthropic API — Sonnet, Batch API, per-user key |
| Cloudflare bypass | FlareSolverr Docker container, `localhost:8191` (bound to loopback only) |

---

## Cron Schedule

System timezone is `America/New_York` → DST-aware automatically.

```cron
# Daily pipeline: Mon–Fri 00:30 ET
30 0 * * 1-5  cd /opt/arxiv-grader && python run_all_users.py >> /var/log/arxiv-grader/daily.log 2>&1

# Weekend weekly digest: Sat/Sun 01:30 ET
30 1 * * 0,6  cd /opt/arxiv-grader && python run_weekly_only.py >> /var/log/arxiv-grader/weekly.log 2>&1

# Monthly refiner: 2nd of month 01:30 ET (offset +1h to avoid archive.json race)
30 1 2 * *    cd /opt/arxiv-grader && python run_all_users.py --refine >> /var/log/arxiv-grader/refiner.log 2>&1

# Monthly refiner: 16th of month 01:30 ET (mid-month run)
30 1 16 * *   cd /opt/arxiv-grader && python run_all_users.py --refine >> /var/log/arxiv-grader/refiner.log 2>&1
```

---

## Deployment

**The server does not pull from git.** Files must be copied manually via SCP:

```bash
scp <file1> <file2> root@116.203.255.222:/opt/arxiv-grader/

# Common examples:
scp fields.json root@116.203.255.222:/opt/arxiv-grader/
scp scrapers/*.py root@116.203.255.222:/opt/arxiv-grader/scrapers/
scp prompts/*.txt root@116.203.255.222:/opt/arxiv-grader/prompts/
scp server.py run_all_users.py run_pipeline.py root@116.203.255.222:/opt/arxiv-grader/
```

**Never SSH into the server to run the pipeline** — always provide commands for the user to run themselves.

---

## FlareSolverr

Runs as a Docker container on the VPS (installed 2026-06-11). Bypasses Cloudflare bot protection for Tandfonline, Sage, Wiley, and Chicago Journals RSS feeds. See [[Journal Scrapers]] for full details of the bypass mechanism.

**Bound to loopback only** — not exposed externally.

```bash
# Check status
docker ps --filter name=flaresolverr
curl -s http://localhost:8191/health   # → {"status":"ok"}

# View logs
docker logs flaresolverr --tail 50

# Restart if needed
docker restart flaresolverr

# Initial install (already done)
docker run -d \
  --name=flaresolverr \
  -p 127.0.0.1:8191:8191 \
  -e LOG_LEVEL=info \
  --restart unless-stopped \
  ghcr.io/flaresolverr/flaresolverr:latest
```

**Resource footprint:** ~300–500 MB RAM idle (headless Chrome). CX23 has 4 GB — fine.

**`--restart unless-stopped`** handles VPS reboots automatically.

**`FLARESOLVERR_URL` env var:** defaults to `http://localhost:8191/v1`. Override only if port changes.

---

## Flask Server (`server.py`)

Runs under Gunicorn (systemd service), behind Caddy reverse proxy.

**Routes:**
| Route | Purpose |
|-------|---------|
| `GET /` | Landing page |
| `GET /signup` | Onboarding step 1 |
| `GET /signup/field` | Onboarding step 2 |
| `GET /signup/interests` | Onboarding step 3 |
| `GET /signup/papers` | Onboarding step 4 |
| `GET /signup/done` | Onboarding success |
| `POST /onboarding/submit` | Receives completed onboarding JSON |
| `GET /rate` | Records paper rating |
| `GET /unsubscribe` | Self-service unsubscribe |
| `GET /manage` | User self-service profile page |
| `POST /manage/lookup` | Email lookup → returns current delivery settings |
| `POST /manage/update-frequency` | Updates daily/weekly/weekly_day in taste_profile.json |
| `POST /manage/submit-feedback` | Queues free-text interest update for operator review |
| `GET /fields.json` | Serves fields.json for field-selector UI |
| `GET /assets/<filename>` | Static assets |
| `GET /legal` | Legal page |
| `GET /sources` | Sources page |
| `GET /health` | Liveness check |
| `GET /robots.txt` | Crawler exclusion |
| `GET /sitemap.xml` | Sitemap |

---

## Logs

```
/var/log/arxiv-grader/daily.log    — Daily pipeline (Mon–Fri)
/var/log/arxiv-grader/weekly.log   — Weekend weekly digest
/var/log/arxiv-grader/refiner.log  — Monthly refiner
/var/log/arxiv-grader/server.log   — Flask/Gunicorn server
```

→ See [[Operations]] for how to read and interpret logs.

---

## Root `.env` on Server

```
RATING_BASE_URL=https://incomingscience.xyz
EMAIL_FROM=sender@gmail.com
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_SMTP_USER=sender@gmail.com
EMAIL_SMTP_PASSWORD=your-app-password

# Per-field triage API keys:
ANTHROPIC_API_KEY_COND_MAT=sk-ant-...
ANTHROPIC_API_KEY_QUANTUM_SENSING=sk-ant-...
ANTHROPIC_API_KEY_OPTICS=sk-ant-...
# ... one per field, naming: ANTHROPIC_API_KEY_<FIELD_UPPER_WITH_UNDERSCORES>

# For processing new user signups:
ANTHROPIC_API_KEY_ONBOARDING=sk-ant-...
```

---

## Website

6 static HTML pages under `website/stitch_platform_user_expansion/`:
```
incoming_science_how_it_works_final/code.html   → /
onboarding_identity_delivery_final/code.html    → /signup
onboarding_research_field_final/code.html       → /signup/field
onboarding_signals_interests_final/code.html    → /signup/interests
onboarding_seed_papers_final/code.html          → /signup/papers
onboarding_success_final/code.html              → /signup/done
manage_final/code.html                          → /manage
```

Built with Tailwind CSS (CDN). Mobile-responsive. All inter-page links use absolute URLs (served by Flask routes, not relative paths).

Static assets at `website/assets/`, served at `/assets/<filename>`.
