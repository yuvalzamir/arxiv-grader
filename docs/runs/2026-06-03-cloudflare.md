# Cloudflare IP block — 37 journals

[[Home]] | [[Journal Scrapers]]

**Discovered:** 2026-06-03
**Status:** Mitigated (blocklist until 2026-06-10)

---

## Symptom

37 journals across OUP, Tandfonline, SAGE, Wiley, and PLOS returned RSS parse errors:

```
feed parse error — <unknown>:2:1326: not well-formed (invalid token)
```

All failures were in publisher groups that route through Cloudflare's CDN. Publishers fetching directly (APS, Nature, IOP, Elsevier, etc.) were unaffected.

---

## Root cause

The parallel scraper introduced 2026-05-28 fires all publisher threads simultaneously. With 8 workers, all RSS requests hit Cloudflare-proxied endpoints at `t=0`. The burst triggered Cloudflare's bot-score system, which flagged the server IP (116.203.255.222) with a **managed challenge** (`cType: 'managed'`).

Confirmed via direct curl from server:
```bash
curl -s -A "Mozilla/5.0..." "https://www.tandfonline.com/feed/rss/cced20" | head -5
# Returns: <!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title>...
```

The semaphore (`Semaphore(2)` around `feedparser.parse()`) limits burst but does not fix an existing IP-level reputation block.

---

## Mitigation

Added `publisher_blocklist.json` with 7-day pause for all five affected publishers (until 2026-06-10). `fetch_journals.py` skips blocked publishers entirely, allowing IP reputation to recover.

After 2026-06-10: test with curl. If clean XML is returned, remove entries from blocklist (or let dates expire naturally). If still blocked, extend the dates.

---

## Long-term fix

Replace RSS fetches for Cloudflare-proxied publishers with OpenAlex-by-ISSN queries. OpenAlex returns papers by journal ISSN + date range — same data, no Cloudflare exposure. This is the permanent solution if the block recurs after IP recovery.
