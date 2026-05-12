"""
test_aps_access.py — Test Harvest API access for APS journals via APSScraper.

Usage:
    python test_aps_access.py

Tests PRL, PRB, and PRX to confirm the Harvest API returns full abstracts.
Set APS_API_KEY env var to test authenticated access.
"""

import os
from scrapers.aps import APSScraper

TEST_URLS = [
    ("PRX", "https://journals.aps.org/prx/abstract/10.1103/bcq4-xw5q"),   # open access
    ("PRL", "https://journals.aps.org/prl/abstract/10.1103/gd4s-fgwt"),   # subscription
    ("PRB", "https://journals.aps.org/prb/abstract/10.1103/jydd-dsjm"),   # subscription
]

api_key = os.environ.get("APS_API_KEY", "")
print("Using APS_API_KEY from environment." if api_key else "No APS_API_KEY set — testing unauthenticated access.")

scraper = APSScraper()
for journal, url in TEST_URLS:
    result = scraper.scrape_article(url)
    abstract = result.get("abstract", "")
    tags = result.get("subject_tags", [])
    print(f"\n--- {journal} ---")
    print(f"Abstract ({len(abstract)} chars): {abstract[:200]}")
    print(f"Subject tags: {tags}")
