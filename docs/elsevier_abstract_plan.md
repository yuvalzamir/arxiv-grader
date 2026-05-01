# Elsevier Abstract Solution (Scopus API)

## Problem

Elsevier journals (Speech Communication, CS&L, Pattern Recognition, Neural Networks, etc.)
publish via ScienceDirect RSS with no abstracts. The `elsevier_general` scraper uses
CrossRef PII→DOI → OpenAlex, but OpenAlex abstracts are missing for most Elsevier CS/speech
journals (20–40% coverage). This blocks those journals from being useful.

## Root Cause

OpenAlex receives Elsevier abstracts only for Open Access papers or those deposited under
Elsevier's open metadata agreement. Subscription-only Elsevier journals typically have
null `abstract_inverted_index` in OpenAlex.

## Proposed Solution: Scopus API in the Retry Bank

Scopus (Elsevier's own database) has 100% abstract coverage for all Elsevier journals.
Scopus indexes new Elsevier papers within 1–7 days of online publication. This lag is
handled by the existing abstract retry bank (`abstract_bank.json`, TTL 7 days):

- **Day 1**: paper appears in RSS → CrossRef→OpenAlex misses abstract → added to bank
- **Day 2–7**: retry bank fires → Scopus now has it → abstract retrieved → paper enriched
  and re-injected into that day's paper list

## Prerequisites

1. **Scopus API key**: free from dev.elsevier.com (register with institutional email)
2. **insttoken**: institution token from ICFO library — required for API calls from
   non-ICFO IPs (Hetzner server). Without it, calls only work from ICFO IPs.

## Files to Change

| File | Change |
|------|--------|
| `retry_abstracts.py` | Add `_fetch_scopus(doi)` function; insert into retry chain |
| Root `.env` (local + server) | Add `SCOPUS_API_KEY`, `SCOPUS_INST_TOKEN` |

## Implementation

### `retry_abstracts.py`

Add at top:
```python
import os
_SCOPUS_ABSTRACT_URL = "https://api.elsevier.com/content/abstract/doi/{doi}"
```

Add new function (after `_fetch_openalex`):
```python
def _fetch_scopus(doi: str) -> str:
    """Fetch abstract from Scopus Abstract Retrieval API.
    Only attempted for Elsevier DOIs (10.1016/) — no-op otherwise.
    Requires SCOPUS_API_KEY in env; SCOPUS_INST_TOKEN for non-institutional IPs.
    """
    api_key = os.getenv("SCOPUS_API_KEY", "")
    if not api_key or not doi.startswith("10.1016/"):
        return ""
    params = {"apiKey": api_key, "httpAccept": "application/json"}
    inst_token = os.getenv("SCOPUS_INST_TOKEN", "")
    if inst_token:
        params["insttoken"] = inst_token
    try:
        r = requests.get(
            _SCOPUS_ABSTRACT_URL.format(doi=doi),
            params=params,
            headers=_HEADERS,
            timeout=15,
        )
        if r.status_code == 200:
            core = r.json().get("abstracts-retrieval-response", {}).get("coredata", {})
            return core.get("dc:description", "") or ""
        log.debug("Scopus returned %d for DOI %s", r.status_code, doi)
    except Exception as e:
        log.warning("Scopus request failed for DOI %s: %s", doi, e)
    return ""
```

In `retry_bank()`, update the retry line:
```python
# Before:
abstract = _fetch_europepmc(doi) or _fetch_openalex(doi)

# After:
abstract = _fetch_scopus(doi) or _fetch_europepmc(doi) or _fetch_openalex(doi)
```

Scopus goes first for Elsevier DOIs (best coverage). For non-Elsevier DOIs, `_fetch_scopus`
returns "" immediately (10.1016/ guard), so the existing chain is unchanged.

## Elsevier Journals to Add (once Scopus is working)

### To `ai-speech` field:
- **Speech Communication** (ISSN 0167-6393): `rss.sciencedirect.com/publication/science/01676393`
- **Computer Speech & Language** (ISSN 0885-2308): `rss.sciencedirect.com/publication/science/08852308`

### Potentially to other fields:
- `ai-vision`: Pattern Recognition (0031-3203), Neural Networks (0893-6080), CVIU (1077-3142)

## Verification

```python
# Quick test with a known Speech Communication DOI
from dotenv import load_dotenv; load_dotenv()
from retry_abstracts import _fetch_scopus
result = _fetch_scopus("10.1016/j.specom.2024.103069")
print(repr(result[:200] if result else "EMPTY"))
```

Once Scopus is confirmed working, add Elsevier journals to the relevant fields and
SCP `retry_abstracts.py` + updated `.env` to server.
