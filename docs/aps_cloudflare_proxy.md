# APS Abstract Scraping via Cloudflare Worker Proxy

## Problem

APS (`link.aps.org`, `journals.aps.org`) blocks HTTP requests originating from
Hetzner datacenter IPs with a 403 Forbidden response. This prevents the server
from scraping full paper abstracts for APS journals (PRB, PRL, PRX, PRX Quantum).

External abstract APIs (Semantic Scholar, CrossRef, OpenAlex) cannot substitute:
APS does not license abstract text to these services, so the `abstract` field is
null even when the paper is indexed.

The RSS feed provides a truncated abstract (~2–3 sentences), which is sufficient
for keyword triage but not for the abstract-content signal in the triage prompt.

## Solution: Cloudflare Worker Proxy

Deploy a Cloudflare Worker that proxies HTTP GET requests on behalf of the server.
The request to APS originates from a Cloudflare edge IP, which APS treats as a
regular browser visit.

```
Server (Hetzner) ──► Cloudflare Worker ──► APS page ──► abstract HTML
                         (edge IP)
```

### Why this works

- Cloudflare edge nodes are not flagged as datacenter scrapers
- The Worker forwards a browser-like User-Agent to APS
- Free tier: 100,000 requests/day — far above our ~30 APS requests/day

---

## Implementation Plan

### Step 1 — Deploy the Worker

Create a Cloudflare account (free) and deploy a Worker with the following logic:

```javascript
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const target = url.searchParams.get("url");

    if (!target) {
      return new Response("Missing ?url= parameter", { status: 400 });
    }

    // Only allow APS domains
    const allowed = ["link.aps.org", "journals.aps.org"];
    const targetHost = new URL(target).hostname;
    if (!allowed.includes(targetHost)) {
      return new Response("Domain not allowed", { status: 403 });
    }

    const response = await fetch(target, {
      headers: {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xhtml+xml",
      },
    });

    return new Response(response.body, {
      status: response.status,
      headers: { "Content-Type": response.headers.get("Content-Type") || "text/html" },
    });
  },
};
```

Deploy via Cloudflare dashboard or Wrangler CLI. The Worker URL will be:
`https://<worker-name>.<your-subdomain>.workers.dev`

Optionally bind it to a custom route on `incomingscience.xyz` (e.g.
`proxy.incomingscience.xyz`) to avoid depending on the workers.dev URL.

### Step 2 — Update `scrapers/aps.py`

Add a `CLOUDFLARE_PROXY_URL` constant (read from `.env`). Change
`scrape_article()` to fetch the APS page via the proxy instead of directly.

```python
import os

CLOUDFLARE_PROXY_URL = os.getenv("CLOUDFLARE_PROXY_URL", "")

def scrape_article(self, url: str) -> dict:
    # 1. Try Semantic Scholar (fast, no blocking, but abstract often missing).
    doi_match = re.search(r"10\.\d{4}/\S+", url)
    if doi_match:
        try:
            resp = requests.get(_S2_API.format(doi=doi_match.group()), timeout=10)
            if resp.status_code == 200:
                abstract = resp.json().get("abstract") or ""
                if abstract:
                    return {"abstract": abstract, "subject_tags": []}
        except Exception:
            pass

    # 2. Fetch APS page via Cloudflare Worker proxy (bypasses 403 on datacenter IPs).
    fetch_url = f"{CLOUDFLARE_PROXY_URL}?url={url}" if CLOUDFLARE_PROXY_URL else url
    response = self.get(fetch_url)
    if response is not None:
        soup = BeautifulSoup(response.text, "lxml")
        section = soup.find("section", {"id": "abstract-section"})
        abstract = section.get_text(separator=" ", strip=True).removeprefix("Abstract").strip() if section else ""
        if abstract:
            return {"abstract": abstract, "subject_tags": []}

    return {"abstract": "", "subject_tags": []}
```

### Step 3 — Set the env variable on the server

Add to `/opt/arxiv-grader/.env`:
```
CLOUDFLARE_PROXY_URL=https://<worker-name>.<subdomain>.workers.dev
```

No code changes needed beyond the scraper update — the proxy URL is optional.
If the env var is absent, the scraper falls back to a direct request (current
behaviour for local testing).

---

## Security Notes

- The Worker only proxies requests to `link.aps.org` and `journals.aps.org` —
  no open proxy.
- The Worker URL should be treated as semi-private (not shared publicly) to
  avoid abuse of the free tier.
- No API key is needed for the Cloudflare free tier.

---

## Status

- [ ] Deploy Cloudflare Worker
- [ ] Set `CLOUDFLARE_PROXY_URL` in server `.env`
- [ ] Update `scrapers/aps.py` (Step 2 above)
- [ ] Test end-to-end: full APS abstract returned, no 403 warnings
- [ ] Commit and deploy
