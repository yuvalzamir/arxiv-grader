# FlareSolverr Integration Plan

## Problem

Tandfonline, Sage, Wiley, and Chicago Journals RSS feeds are blocked by Cloudflare bot
protection when fetched from the Hetzner VPS (datacenter IP range). Cloudflare returns
a 200 OK HTML challenge page instead of XML, which feedparser fails to parse with:

```
feed parse error — <unknown>:2:1326: not well-formed (invalid token)
```

The same URLs work fine from residential IPs. The User-Agent is irrelevant — Cloudflare
blocks datacenter IP ranges regardless.

**Affected publishers (confirmed 2026-06-11):**

| Publisher | Journals |
|-----------|----------|
| Tandfonline | EduEconomics, JEconEducation, SchoolLeadership, JEdWork, PoliticalComm, JEdPolicy, ComparativeEdu, StudiesHigherEdu, OxfordReviewEdu |
| Sage | EduAdminQ, EducationalPolicy, EduEvalPolicyAnalysis, AmEdResJournal, ReviewEdResearch, EducationalResearcher, JTeacherEducation, EduMgmtAdminLeadership, GenderSociety, FeministTheory, AmericanSocReview |
| Wiley | Econometrica, AJPS |
| Chicago | JoP |

---

## Solution: FlareSolverr (implemented 2026-06-11)

FlareSolverr runs as a Docker container on the VPS, exposing a local HTTP API on
`localhost:8191`. When `feedparser` fails with a Cloudflare HTML challenge response,
the pipeline falls back to FlareSolverr.

**How it works (confirmed by testing):**

1. POST to FlareSolverr → headless Chrome solves the JS challenge and fetches the URL
2. FlareSolverr returns `solution.response` — the page Chrome rendered
3. Chrome wraps RSS/XML URLs in its built-in XML viewer (`<html>` with `<div id="webkit-xml-viewer-source-xml">` containing the raw XML as HTML-escaped entities)
4. Regex-extract the div content, `html.unescape()` it → valid RSS XML
5. Pass to `feedparser.parse()` as normal

**What didn't work:**
- Using `solution.cookies` + `requests.get()` → 403 (Cloudflare ties `cf_clearance` to Chrome's TLS fingerprint; `requests` has a different fingerprint)
- `BeautifulSoup.get_text()` on the hidden div → strips XML tags, returns plain text only
- `feedparser` on the raw Chrome HTML → 0 entries

**Trigger condition:** Only fires when `urlparse(url).hostname in _CLOUDFLARE_HOSTS`.
This avoids touching non-blocked publishers and is precise (e.g. JoP uses publisher=`plos`
in fields.json but hostname `www.journals.uchicago.edu` correctly identifies it).

**Verified working (2026-06-11):** Tandfonline (34 entries), Sage (20), Wiley (15), Chicago JoP (83).

The fallback is fully automatic — no `fields.json` changes, no publisher flags.

---

## Step 1 — Install FlareSolverr on the VPS

```bash
# Install Docker if not present
apt-get update && apt-get install -y docker.io
systemctl enable --now docker

# Run FlareSolverr (bound to localhost only — not exposed externally)
docker run -d \
  --name=flaresolverr \
  -p 127.0.0.1:8191:8191 \
  -e LOG_LEVEL=info \
  --restart unless-stopped \
  ghcr.io/flaresolverr/flaresolverr:latest

# Verify it's running
curl -s http://localhost:8191/health
# Expected: {"status":"ok"}
```

Resource footprint: FlareSolverr runs headless Chrome, ~300–500 MB RAM idle.
CX23 has 4 GB — fine.

---

## Step 2 — Code changes to `scrapers/sources.py`

See `scrapers/sources.py` for the actual implementation. Key points:
- `_CLOUDFLARE_HOSTS` frozenset gates the retry (hostname-based, not publisher-based)
- `_fetch_rss_via_flaresolverr()` POSTs to FlareSolverr, extracts XML from Chrome's viewer div via regex + `html.unescape()`
- Retry is inserted in the `feed.bozo and not feed.entries` block in `fetch_from_rss()`

---

## Step 3 — No `.env` changes needed

`FLARESOLVERR_URL` defaults to `http://localhost:8191/v1`. Only override if
FlareSolverr moves to a different host or port.

---

## Step 4 — Test

Local machine is not blocked, so the FlareSolverr path won't trigger locally.
Test that normal feeds still work:

```bash
python run_all_users.py --user kfite1207msw-gmail-com --no-email --no-batch
```

The real verification is the first server run after deployment. Look for:

```
<journal>: retrying parse via FlareSolverr
```

in the daily log.

---

## Step 5 — Deploy

```bash
scp scrapers/sources.py root@116.203.255.222:/opt/arxiv-grader/scrapers/sources.py
```

---

## Caveats

| Item | Detail |
|------|--------|
| Challenge solve time | 10–60s per domain. With `_RSS_SEMAPHORE(2)`, blocked feeds serialize — adds ~2–5 min to the journal scrape phase |
| Cookie lifetime | `cf_clearance` lasts 30 min–2 hrs; sufficient for a single run |
| Restarts | `--restart unless-stopped` handles VPS reboots and container crashes |
| FlareSolverr down | Graceful degradation — logs a warning, returns `None`, pipeline continues with 0 papers from that journal (same behavior as today) |
| Cloudflare Turnstile (v3) | FlareSolverr v1 handles standard CF challenges. If a publisher upgrades to Turnstile, FlareSolverr may need updating — monitor for continued failures after an upgrade |
