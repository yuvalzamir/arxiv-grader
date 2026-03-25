#!/usr/bin/env python3
"""
fetch_papers.py — Daily arXiv cond-mat paper fetcher.

Pulls the arXiv cond-mat RSS feed, filters to new submissions only
(no cross-listings, no replacements), and writes today_papers.json.

Usage:
    python fetch_papers.py                     # writes to ./today_papers.json
    python fetch_papers.py -o /path/to/out.json
    python fetch_papers.py --category cond-mat.str-el  # specific subcategory
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone

import feedparser

RSS_BASE_URL = "https://rss.arxiv.org/rss/"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def extract_abstract(description: str) -> str:
    """
    The RSS <description> field contains the arXiv ID, announce type,
    and abstract as a single HTML/text blob. Example:

        arXiv:2603.12345v1 Announce Type: new
        Abstract: We study the ...

    We strip everything before 'Abstract:' and clean up whitespace.
    """
    # The abstract follows "Abstract:" (case-insensitive, sometimes with
    # extra whitespace or <p> tags in the HTML version).
    match = re.search(r"Abstract:\s*", description, re.IGNORECASE)
    if match:
        abstract = description[match.end():]
    else:
        # Fallback: use the whole description if no marker found.
        abstract = description

    # Strip residual HTML tags (the feed sometimes wraps in <p>).
    abstract = re.sub(r"<[^>]+>", "", abstract)
    # Collapse whitespace.
    abstract = re.sub(r"\s+", " ", abstract).strip()
    return abstract


def extract_announce_type(description: str) -> str:
    """
    Pull the announce type from the description blob.
    Returns one of: 'new', 'cross', 'replace', 'replace-cross', or 'unknown'.
    """
    match = re.search(r"Announce Type:\s*(\S+)", description, re.IGNORECASE)
    if match:
        return match.group(1).strip().lower()
    return "unknown"


def extract_arxiv_id(entry) -> str:
    """
    Get a clean arXiv ID from the entry.
    The <link> field is like 'https://arxiv.org/abs/2603.12345v1'.
    The <guid> is like 'oai:arXiv.org:2603.12345v1'.
    We prefer the link-based ID, falling back to guid.
    """
    link = entry.get("link", "")
    match = re.search(r"arxiv\.org/abs/(.+)", link)
    if match:
        return match.group(1).strip()

    guid = entry.get("id", "")
    match = re.search(r"arXiv\.org:(.+)", guid)
    if match:
        return match.group(1).strip()

    return link or guid


def parse_authors(creator: str) -> list[str]:
    """
    The <dc:creator> field is a comma-separated author string.
    Some names contain parenthetical affiliations — we strip those.

    Examples:
        "Jane Smith, John Doe"
        "Jane Smith (1), John Doe (2) ((1) MIT, (2) ETH)"
    """
    if not creator:
        return []

    # First, remove the trailing affiliation block: ((1) MIT, (2) ETH Zurich)
    # This is a double-paren block typically at the end of the string.
    creator = re.sub(r"\(\(.*$", "", creator)

    # Remove remaining inline affiliation markers like (1), (CNRS), etc.
    creator = re.sub(r"\([^)]*\)", "", creator)

    authors = [a.strip() for a in creator.split(",") if a.strip()]
    return authors


def parse_categories(entry) -> list[str]:
    """
    Extract all <category> tags from the entry.
    feedparser stores them in entry.tags as [{'term': 'cond-mat.str-el', ...}, ...]
    """
    tags = entry.get("tags", [])
    return [t["term"] for t in tags if "term" in t]


# ---------------------------------------------------------------------------
# Main fetch logic
# ---------------------------------------------------------------------------

def fetch_papers(category: str = "cond-mat") -> list[dict]:
    """
    Fetch today's RSS feed for the given arXiv category and return a list
    of paper dicts for new (non-cross-listed) submissions only.
    """
    url = f"{RSS_BASE_URL}{category}"
    log.info("Fetching RSS feed: %s", url)

    feed = feedparser.parse(url)

    if feed.bozo and not feed.entries:
        log.error("Feed parse error: %s", feed.bozo_exception)
        sys.exit(1)

    log.info("Feed contains %d total entries", len(feed.entries))

    papers = []
    skipped = {"cross": 0, "replace": 0, "replace-cross": 0, "unknown": 0}

    for entry in feed.entries:
        description = entry.get("summary", entry.get("description", ""))
        announce_type = extract_announce_type(description)

        # Keep only genuinely new submissions.
        if announce_type != "new":
            skipped[announce_type] = skipped.get(announce_type, 0) + 1
            continue

        arxiv_id = extract_arxiv_id(entry)
        title = re.sub(r"\s+", " ", entry.get("title", "").strip())
        abstract = extract_abstract(description)
        authors = parse_authors(entry.get("author", ""))
        categories = parse_categories(entry)

        papers.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "subcategories": categories,
        })

    log.info(
        "Kept %d new papers. Skipped: %s",
        len(papers),
        ", ".join(f"{k}={v}" for k, v in skipped.items() if v > 0) or "none",
    )
    return papers


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Fetch today's new arXiv cond-mat papers."
    )
    parser.add_argument(
        "-o", "--output",
        default="today_papers.json",
        help="Path for the output JSON file (default: today_papers.json)",
    )
    parser.add_argument(
        "-c", "--category",
        default="cond-mat",
        help="arXiv category to fetch (default: cond-mat). "
             "Can be a subcategory like cond-mat.str-el.",
    )
    args = parser.parse_args()

    papers = fetch_papers(category=args.category)

    if not papers:
        log.warning("No new papers found. The feed may be empty (weekend/holiday).")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(papers, f, indent=2, ensure_ascii=False)

    log.info("Wrote %d papers to %s", len(papers), args.output)


if __name__ == "__main__":
    main()
