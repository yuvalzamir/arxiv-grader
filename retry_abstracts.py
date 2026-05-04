"""
retry_abstracts.py — Abstract retry bank for journal papers with missing abstracts.

Papers that arrive with abstract_quality="missing" are stored in abstract_bank.json
and retried daily for up to TTL_DAYS. Once an abstract is found, the enriched paper
is returned for injection into the day's paper list and removed from the bank.
Expired entries (older than TTL_DAYS) are also purged.

Note: API call logic is duplicated here (not via BaseScraper) because this is a
standalone utility, not part of the scraper hierarchy.
"""

import json
import logging
import re
import requests
from datetime import date, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

_BANK_PATH = Path(__file__).parent / "abstract_bank.json"
_OPENALEX_URL = "https://api.openalex.org/works/doi:{doi}"
_EUROPEPMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_HEADERS = {"User-Agent": "arxiv-grader/1.0 (mailto:contact@incomingscience.xyz)"}
_DOI_RE = re.compile(r"10\.\d{4}/[^\s?#]+")


def load_bank() -> dict:
    """Load abstract_bank.json. Returns {} if missing or unreadable."""
    if not _BANK_PATH.exists():
        return {}
    try:
        return json.loads(_BANK_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("Failed to load abstract bank: %s", e)
        return {}


def save_bank(bank: dict) -> None:
    """Write abstract_bank.json."""
    _BANK_PATH.write_text(json.dumps(bank, indent=2, ensure_ascii=False), encoding="utf-8")


def delete_from_bank(bank: dict, paper_id: str) -> None:
    """Remove entry by key. No-op if absent."""
    bank.pop(paper_id, None)


def add_to_bank(papers: list, field: str, bank: dict) -> int:
    """
    Add papers with abstract_quality=="missing" to the bank.
    Truncated abstracts are not banked (treated as a usable hit).
    Skips papers already in the bank. Returns count added.
    """
    today = date.today().isoformat()
    added = 0
    for paper in papers:
        if paper.get("abstract_quality") != "missing":
            continue
        paper_id = paper.get("arxiv_id", "")
        if not paper_id or paper_id in bank:
            continue
        bank[paper_id] = {**paper, "added_date": today, "field": field}
        added += 1
    return added


def _reconstruct_openalex_abstract(inverted_index: dict) -> str:
    tokens: dict[int, str] = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            tokens[pos] = word
    return " ".join(tokens[i] for i in sorted(tokens))


def _fetch_europepmc(doi: str) -> str:
    try:
        r = requests.get(
            _EUROPEPMC_URL,
            params={"query": f"DOI:{doi}", "format": "json", "resultType": "core"},
            headers=_HEADERS,
            timeout=15,
        )
        if r.status_code == 200:
            results = r.json().get("resultList", {}).get("result", [])
            if results:
                return results[0].get("abstractText", "") or ""
        else:
            log.debug("Europe PMC returned %d for DOI %s", r.status_code, doi)
    except Exception as e:
        log.warning("Europe PMC request failed for DOI %s: %s", doi, e)
    return ""


def _fetch_openalex(doi: str) -> str:
    try:
        r = requests.get(
            _OPENALEX_URL.format(doi=doi),
            headers=_HEADERS,
            timeout=15,
        )
        if r.status_code == 200:
            inverted = r.json().get("abstract_inverted_index")
            if inverted:
                return _reconstruct_openalex_abstract(inverted)
        else:
            log.debug("OpenAlex returned %d for DOI %s", r.status_code, doi)
    except Exception as e:
        log.warning("OpenAlex request failed for DOI %s: %s", doi, e)
    return ""


def retry_bank(bank: dict, ttl_days: int = 7) -> tuple[dict, dict]:
    """
    Retry abstract fetching for all banked papers.

    For each paper:
      - If older than ttl_days: expire and remove from bank.
      - Otherwise: try Europe PMC then OpenAlex by DOI.
      - If abstract found: enrich paper, queue for injection, remove from bank.
      - If not found: leave unchanged in bank.

    Returns (updated_bank, enriched_by_field) where enriched_by_field maps
    field -> list of fully enriched paper dicts ready for injection.
    """
    today = date.today()
    cutoff = (today - timedelta(days=ttl_days)).isoformat()

    log.info("[BANK] Retrying %d banked papers (TTL=%dd, cutoff=%s)", len(bank), ttl_days, cutoff)

    enriched_by_field: dict[str, list] = {}
    to_delete: list[str] = []

    for paper_id, paper in list(bank.items()):
        added_date = paper.get("added_date", "")

        # Expire old entries
        if added_date < cutoff:
            log.debug("[BANK] Expiring %s (added %s)", paper_id, added_date)
            to_delete.append(paper_id)
            continue

        # Extract DOI from the paper_id (which is the arxiv_id field for journal papers)
        m = _DOI_RE.search(paper_id)
        if not m:
            continue
        doi = m.group(0)

        # Try Europe PMC first, then OpenAlex
        abstract = _fetch_europepmc(doi) or _fetch_openalex(doi)
        if not abstract:
            continue

        # Found — enrich and queue for injection
        enriched = {**paper, "abstract": abstract, "abstract_quality": "full"}
        # Remove bank-only metadata before injecting back into the pipeline
        enriched.pop("added_date", None)
        enriched.pop("field", None)
        field = paper.get("field", "")
        enriched_by_field.setdefault(field, []).append(enriched)
        to_delete.append(paper_id)
        log.info("[BANK] Recovered abstract for %s (%s)", paper_id, paper.get("source", "?"))

    for paper_id in to_delete:
        delete_from_bank(bank, paper_id)

    return bank, enriched_by_field
