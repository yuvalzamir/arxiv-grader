# Scaling Analysis — incomingscience.xyz

*Written 2026-03-25. Re-evaluate if user count grows significantly.*

---

## Current infrastructure

| Component | Spec |
|---|---|
| Server | Hetzner CX23 — 2 vCPU (shared), 4GB RAM, 40GB SSD |
| Email | Free Gmail SMTP (`incomingscience@gmail.com`) |
| API | Anthropic Batch API — one key per user, billed to owner |
| Concurrency | `ThreadPoolExecutor` — all users run in parallel |

---

## Bottlenecks, in order of which hits first

### 1. Gmail SMTP — hard wall ~100 users
Free Gmail SMTP allows ~100 automated emails/day. At 1 email per user per day (Tue–Sat), this is the first hard ceiling.

**Fix:** Switch to a transactional email provider:
- **Mailgun** — 1,000/day free tier
- **Postmark** — reliable, paid but cheap
- **SendGrid** — 100/day free, affordable paid plans

One-line change to the SMTP config in `run_daily.py`.

---

### 2. Server RAM — soft wall ~30–40 users
`run_all_users.py` launches all users concurrently. Each user subprocess loads Python + reportlab + anthropic SDK ≈ 100–200MB. At 30 users: ~4–6GB → likely OOM on a 4GB machine.

**Fixes (pick one):**
- Cap `max_workers` in `run_all_users.py` (e.g. `max_workers=10`) — users run in rolling batches; wall time barely increases since they mostly wait on the Batch API.
- Upgrade to Hetzner CX33 (8GB, ~€6.50/mo) or CX43 (16GB, ~€13/mo).

---

### 3. Disk storage — soft wall ~100 users (long term)
~2–3MB of PDFs per user per day, kept 14 days. At 50 users: ~2GB for PDFs alone.

**Fix:** Reduce `--keep-days` to 7, or attach a Hetzner volume.

---

### 4. Flask rating server — minor concern at 50+ users
Single Gunicorn worker. Fine for occasional clicks; could queue under burst load when all users receive their digest simultaneously.

**Fix:** Bump workers in the systemd service file: `--workers 4`.

---

### 5. Anthropic Batch API — not a real bottleneck
Each user has their own key with its own rate limits. Batch API supports 10,000 requests/batch. At ~100 requests/user/day, you'd need 1,000+ users to approach the ceiling.

---

### 6. Single point of failure
No redundancy. If the VPS goes down, all users miss their digest. Acceptable for a small research tool — Hetzner uptime is reliable. At commercial scale, consider a backup/failover strategy.

---

## Admin burden at scale

Current onboarding: SSH in, create directory, write `.env`, run `create_profile.py` interactively. ~15–20 min per user. Fine at 5–10 users, painful at 30+.

**To scale admin:**
- Build a web form that collects profile info and triggers `create_profile.py` automatically.
- Add a simple admin dashboard to check daily run status (currently requires tailing per-user logs).
- Automate API key provisioning if Anthropic exposes it via API.

---

## Summary

| Limit | Breaks at | Severity | Fix effort |
|---|---|---|---|
| Gmail SMTP | ~100 users | Hard | Low — swap SMTP provider |
| Server RAM | ~30–40 users | Hard | Low — cap `max_workers` or upgrade VPS |
| Disk | ~100 users (long term) | Soft | Trivial |
| Onboarding admin | ~20 users | Practical | Medium — needs a web form |
| Flask concurrency | ~50+ users | Soft | Trivial — bump Gunicorn workers |
| Anthropic Batch API | >1,000 users | None | N/A |

**Bottom line:** Fine as-is up to ~20 users. At 30–50, cap `max_workers` and swap Gmail for a real SMTP provider. Beyond that, admin overhead becomes the dominant constraint.

---

## Future architectural steps (deferred)

### Separate Flask server from pipeline runner (#43)
Currently Flask (rating endpoint + website) and the cron pipeline run on the same machine. At 50+ users, the 30-minute pipeline window may saturate the CPU and slow Flask responses (rating clicks arriving during the morning pipeline window). Move Flask to a separate small VPS (Hetzner CX11, ~€4/month). No code changes — just a deployment split and a DNS/proxy update.

**When to do it:** When the pipeline window regularly exceeds 15 minutes, or if rating latency complaints arise from users.

### Job queue to replace ThreadPoolExecutor (#44)
Replace `ThreadPoolExecutor` with Redis + RQ (or Celery). Enables: distributing work across machines, retrying individual failed jobs without re-running all users, monitoring queue depth, graceful shutdown. Currently `ThreadPoolExecutor` is simple, sufficient, and has no operational overhead.

**When to do it:** At ~50 concurrent users, or when per-job retry granularity becomes important (e.g., a single Batch API timeout shouldn't require re-running all users).
