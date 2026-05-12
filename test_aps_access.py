"""
test_aps_access.py — Test Harvest API access for APS journals.

Tests the DOI provided by APS support to confirm whether open-access
articles return a full abstract without authentication.

Usage:
    python test_aps_access.py

Two scenarios:
  - 200 + abstract → open access works; subscription articles may also work
  - 401/403        → subscription articles need APS_API_KEY env var
"""

import os
import re
import requests
from bs4 import BeautifulSoup

TEST_URLS = [
    "https://journals.aps.org/prx/abstract/10.1103/bcq4-xw5q",   # PRX (open access)
    "https://journals.aps.org/prl/abstract/10.1103/gd4s-fgwt",   # PRL (subscription)
    "https://journals.aps.org/prb/abstract/10.1103/jydd-dsjm",   # PRB (subscription)
]

_DOI_RE = re.compile(r"10\.\d{4}/\S+")

headers = {
    "Accept": "application/vnd.tesseract.article+json",
    "User-Agent": (
        "IncomingScience-Bot/1.0 (automated academic digest; "
        "https://incomingscience.xyz; not-for-profit; contact@incomingscience.xyz)"
    ),
}
api_key = os.environ.get("APS_API_KEY", "")
if api_key:
    headers["Authorization"] = f"Bearer {api_key}"
    print("Using APS_API_KEY from environment.")
else:
    print("No APS_API_KEY set — testing unauthenticated access.")

for url in TEST_URLS:
    doi = _DOI_RE.search(url).group(0)
    harvest_url = f"http://harvest.aps.org/v2/journals/articles/{doi}"
    print(f"\n--- {url.split('/')[4].upper()} | DOI: {doi} ---")
    print(f"GET {harvest_url}")
    resp = requests.get(harvest_url, headers=headers, timeout=15)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json().get("data", {})
        raw_abstract = data.get("abstract", {}).get("value", "") or ""
        abstract = BeautifulSoup(raw_abstract, "lxml").get_text() if raw_abstract else ""
        subject_areas = data.get("classificationSchemes", {}).get("subjectAreas", []) or []
        subject_tags = [item["label"] for item in subject_areas if item.get("label")]
        print(f"Abstract ({len(abstract)} chars): {abstract[:200]}")
        print(f"Subject tags: {subject_tags}")
    else:
        print(f"Response: {resp.text[:200]}")
