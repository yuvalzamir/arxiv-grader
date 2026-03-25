#!/usr/bin/env python3
"""
create_profile.py — One-time user onboarding for the arXiv grader.

Interviews the user across four areas, reads recent papers from an Excel
file of arXiv links, then runs an agentic Claude call (with web-fetch tools
and extended thinking) to build a ranked taste profile.

Usage:
    python create_profile.py                    # writes to ./taste_profile.json
    python create_profile.py -o /path/to/file.json
"""

import argparse
import json
import logging
import os
import re
import smtplib
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import openpyxl
import requests
from anthropic import Anthropic, AuthenticationError
from dotenv import load_dotenv

load_dotenv()  # loads credentials from .env if present

DEFAULT_OUTPUT = "taste_profile.json"
PROMPTS_DIR = Path(__file__).parent / "prompts"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Credential setup — runs once at startup, writes to .env
# ---------------------------------------------------------------------------

_DEFAULT_ENV_PATH = Path(__file__).parent / ".env"

# Shared sending account — same for all users, not user-configurable.
_SMTP_HOST     = "smtp.gmail.com"
_SMTP_PORT     = 587
_SMTP_USER     = "incomingscience@gmail.com"
_SMTP_PASSWORD = "vaobgxhkgxtlsdug"
_EMAIL_FROM    = "incomingscience@gmail.com"


def _read_env_file(env_path: Path) -> dict[str, str]:
    """Parse .env into a dict. Returns {} if file doesn't exist."""
    if not env_path.exists():
        return {}
    env: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def _write_env_file(env: dict[str, str], env_path: Path) -> None:
    """Write dict back to .env, preserving order."""
    lines = [f"{k}={v}" for k, v in env.items()]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _validate_api_key(key: str) -> str | None:
    """
    Attempt a minimal Anthropic API call to verify the key.
    Returns None on success, or an error string on failure.
    """
    try:
        client = Anthropic(api_key=key)
        client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=5,
            messages=[{"role": "user", "content": "hi"}],
        )
        return None
    except AuthenticationError:
        return "Authentication failed — check the key and try again."
    except Exception as exc:
        return f"API error: {exc}"


def _validate_smtp(host: str, port: int, user: str, password: str) -> str | None:
    """
    Connect and login to the SMTP server without sending anything.
    Returns None on success, or an error string on failure.
    """
    try:
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(user, password)
        return None
    except smtplib.SMTPAuthenticationError:
        return "SMTP login failed — check your username and password/app-password."
    except smtplib.SMTPConnectError as exc:
        return f"Could not connect to {host}:{port} — {exc}"
    except Exception as exc:
        return f"SMTP error: {exc}"


def setup_credentials(env_path: Path | None = None) -> None:
    """
    Ensure ANTHROPIC_API_KEY and EMAIL_TO are present and valid in .env.
    Prompts the user only for these two values — all SMTP settings are shared
    infrastructure (incomingscience@gmail.com) and are written silently.
    """
    if env_path is None:
        env_path = _DEFAULT_ENV_PATH
    env = _read_env_file(env_path)
    changed = False

    print()
    print("=" * 58)
    print("  arXiv Grader — Initial Setup")
    print("=" * 58)

    # ---- Anthropic API key ------------------------------------------------
    key = env.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        print()
        print("No ANTHROPIC_API_KEY found.")
        print("Get your key at https://console.anthropic.com/")
        while True:
            key = input("  Paste your Anthropic API key: ").strip()
            if not key:
                print("  Key cannot be empty.")
                continue
            print("  Validating...", end=" ", flush=True)
            err = _validate_api_key(key)
            if err:
                print(f"failed.\n  {err}")
            else:
                print("OK.")
                env["ANTHROPIC_API_KEY"] = key
                os.environ["ANTHROPIC_API_KEY"] = key
                changed = True
                break
    else:
        print()
        print("Checking API key...", end=" ", flush=True)
        err = _validate_api_key(key)
        if err:
            print(f"invalid.\n  {err}")
            while True:
                key = input("  Paste a valid Anthropic API key: ").strip()
                if not key:
                    continue
                print("  Validating...", end=" ", flush=True)
                err = _validate_api_key(key)
                if err:
                    print(f"failed.\n  {err}")
                else:
                    print("OK.")
                    env["ANTHROPIC_API_KEY"] = key
                    os.environ["ANTHROPIC_API_KEY"] = key
                    changed = True
                    break
        else:
            print("OK.")

    # ---- Recipient email --------------------------------------------------
    if not env.get("EMAIL_TO", "").strip():
        print()
        print("Your email address (where the daily digest will be sent):")
        while True:
            val = input("  Email address: ").strip()
            if not val or "@" not in val:
                print("  Please enter a valid email address.")
                continue
            env["EMAIL_TO"] = val
            changed = True
            break

    # ---- Write shared SMTP settings silently (same for all users) ---------
    smtp_fields = {
        "EMAIL_FROM":          _EMAIL_FROM,
        "EMAIL_SMTP_HOST":     _SMTP_HOST,
        "EMAIL_SMTP_PORT":     str(_SMTP_PORT),
        "EMAIL_SMTP_USER":     _SMTP_USER,
        "EMAIL_SMTP_PASSWORD": _SMTP_PASSWORD,
    }
    for field, value in smtp_fields.items():
        if env.get(field, "") != value:
            env[field] = value
            changed = True

    if changed:
        _write_env_file(env, env_path)
        print()
        print(f"  Setup complete. Credentials saved to {env_path}.")


# ---------------------------------------------------------------------------
# Excel reader
# ---------------------------------------------------------------------------

def normalize_paper_link(value: str) -> str | None:
    """
    Normalize a cell value to a canonical paper URL.

    arXiv URLs and bare IDs → https://arxiv.org/abs/{id}
    Bare DOIs (10.XXXX/...) → https://doi.org/{doi}
    Any other http(s) URL   → returned as-is
    Anything else           → None
    """
    value = value.strip()

    # arXiv URL (abs or pdf)
    match = re.search(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)", value, re.IGNORECASE)
    if match:
        return f"https://arxiv.org/abs/{match.group(1)}"

    # Plain arXiv ID
    match = re.fullmatch(r"([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)", value)
    if match:
        return f"https://arxiv.org/abs/{match.group(1)}"

    # Any HTTP(S) URL (journal pages, DOI redirects, etc.)
    if re.match(r"https?://", value, re.IGNORECASE):
        return value

    # Bare DOI: 10.xxxx/...
    match = re.match(r"(10\.\d{4,}/\S+)", value)
    if match:
        return f"https://doi.org/{match.group(1)}"

    return None


def read_excel_papers(path: str) -> list[str]:
    """
    Read paper links from an Excel file.

    Accepts arXiv URLs/IDs and journal URLs (DOI links, publisher pages, etc.).
    Scans every cell; for each row takes the first recognisable paper link.
    Returns a list of canonical URLs.
    """
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active

    links = []
    for row in ws.iter_rows(values_only=True):
        for cell in row:
            if cell is None:
                continue
            url = normalize_paper_link(str(cell))
            if url:
                links.append(url)
                break  # one paper per row

    wb.close()
    log.info("Read %d paper links from %s", len(links), path)
    return links


# ---------------------------------------------------------------------------
# Input collection
# ---------------------------------------------------------------------------

def read_list(prompt: str) -> list[str]:
    """Prompt the user for items one per line; blank line ends input."""
    print(prompt)
    items = []
    while True:
        line = input("  > ").strip()
        if not line:
            break
        items.append(line)
    return items


def read_names(prompt: str) -> list[str]:
    """
    Read a list of names. Each line may contain one name or several
    separated by commas — both styles are accepted and can be mixed.

    Examples (all valid):
        John Smith
        Jane Doe, Bob Jones, Alice Wu
        Carol Lee
    """
    print(prompt)
    names = []
    while True:
        line = input("  > ").strip()
        if not line:
            break
        for part in line.split(","):
            name = part.strip()
            if name:
                names.append(name)
    return names


def read_paragraph(prompt: str) -> str:
    """Prompt for multi-line free text; blank line ends input."""
    print(prompt)
    lines = []
    while True:
        line = input("  > ")
        if not line.strip():
            if lines:
                break
        else:
            lines.append(line.strip())
    return " ".join(lines)


def collect_inputs() -> dict:
    """Run the four-part interview and return raw user inputs."""
    print()
    print("=" * 58)
    print("  arXiv Grader — Profile Setup")
    print("=" * 58)

    # --- Part 1: arXiv categories ---
    print()
    print("Part 1 of 4 — arXiv categories")
    print("Which arXiv listing pages are you interested in?")
    print("Enter one or more categories, comma-separated.")
    print("Examples: cond-mat  |  cond-mat.str-el  |  quant-ph  |  cs.AI")
    raw_cats = input("  > ").strip()
    categories = [c.strip() for c in raw_cats.split(",") if c.strip()]

    # --- Part 2: Free-text research interests ---
    print()
    print("Part 2 of 4 — Research interests")
    print("Describe your research interests in your own words.")
    print("Be as specific as you like. Mention what you focus on most,")
    print("and what you follow more loosely. Press Enter twice when done.")
    interests_text = read_paragraph("")

    # --- Part 3: Researchers to follow ---
    print()
    print("Part 3 of 4 — Researchers you follow")
    print("List researchers whose new papers you always want to see.")
    print("One name per line, or several names comma-separated. Blank line when done.")
    researchers = read_names("")

    # --- Part 4: Recent papers from Excel ---
    print()
    print("Part 4 of 4 — Recently read papers (Excel file)")
    print("Provide the path to an Excel file with one paper link per row.")
    print("Accepted formats: arXiv URLs, arXiv IDs, DOI links, or any journal page URL.")
    print("Press Enter to skip if you have no file.")
    excel_path = input("  > ").strip()

    paper_links = []
    if excel_path:
        if not Path(excel_path).exists():
            log.warning("File not found: %s — skipping paper import.", excel_path)
        else:
            paper_links = read_excel_papers(excel_path)
            if not paper_links:
                log.warning("No paper links found in %s.", excel_path)
            else:
                arxiv_count = sum(1 for l in paper_links if "arxiv.org" in l)
                journal_count = len(paper_links) - arxiv_count
                parts = []
                if arxiv_count:
                    parts.append(f"{arxiv_count} arXiv")
                if journal_count:
                    parts.append(f"{journal_count} journal")
                print(f"  Found {len(paper_links)} paper(s): {', '.join(parts)}.")

    return {
        "categories": categories,
        "interests_text": interests_text,
        "researchers": researchers,
        "paper_links": paper_links,
    }


# ---------------------------------------------------------------------------
# Paper metadata fetching (Python-side — keeps LLM context small and cheap)
# ---------------------------------------------------------------------------

HEADERS = {"User-Agent": "arxiv-grader-profile-builder/1.0"}
HTML_CAP = 50_000  # bytes — enough to find meta tags on any publisher page


def fetch_arxiv_batch(urls: list[str]) -> list[dict]:
    """Fetch metadata for a list of arXiv URLs using the batch API."""
    ids = []
    for url in urls:
        m = re.search(r"arxiv\.org/abs/([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)", url)
        if m:
            ids.append(m.group(1))
    if not ids:
        return []

    api_url = f"https://export.arxiv.org/api/query?id_list={','.join(ids)}&max_results={len(ids)}"
    log.info("Fetching %d arXiv paper(s)...", len(ids))
    try:
        resp = requests.get(api_url, timeout=20, headers=HEADERS)
        resp.raise_for_status()
    except Exception as exc:
        log.warning("arXiv API error: %s", exc)
        return []

    # Parse Atom XML.
    papers = []
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(resp.text)
    for entry in root.findall("atom:entry", ns):
        def text(tag):
            el = entry.find(tag, ns)
            return el.text.strip() if el is not None and el.text else ""

        arxiv_id = text("atom:id").split("/abs/")[-1]
        title = re.sub(r"\s+", " ", text("atom:title"))
        abstract = re.sub(r"\s+", " ", text("atom:summary"))
        authors = [
            a.find("atom:name", ns).text.strip()
            for a in entry.findall("atom:author", ns)
            if a.find("atom:name", ns) is not None
        ]
        papers.append({
            "source": "arxiv",
            "arxiv_id": arxiv_id,
            "title": title,
            "abstract": abstract,
            "authors": authors,
        })
        log.info("  [arXiv] %s — %s", arxiv_id, title[:60])

    return papers


def fetch_journal_paper(url: str) -> dict:
    """
    Fetch title, authors, and abstract from a journal page.
    Uses standard citation meta tags present on most publisher sites.
    Falls back to Open Graph / page title if meta tags are absent.
    """
    log.info("Fetching journal paper: %s", url)
    try:
        resp = requests.get(url, timeout=20, headers=HEADERS)
        resp.raise_for_status()
        html = resp.text[:HTML_CAP]
    except Exception as exc:
        log.warning("Could not fetch %s: %s", url, exc)
        return {"source": "journal", "url": url, "title": "", "abstract": "", "authors": []}

    # citation_* meta tags — supported by Google Scholar, most publishers.
    def meta(name):
        m = re.search(
            rf'<meta\s[^>]*name=["\']citation_{name}["\'][^>]*content=["\'](.*?)["\']',
            html, re.IGNORECASE | re.DOTALL,
        )
        return m.group(1).strip() if m else ""

    def all_meta(name):
        return re.findall(
            rf'<meta\s[^>]*name=["\']citation_{name}["\'][^>]*content=["\'](.*?)["\']',
            html, re.IGNORECASE | re.DOTALL,
        )

    title = meta("title")
    abstract = meta("abstract")
    authors = [a.strip() for a in all_meta("author") if a.strip()]

    # Fallbacks.
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title = re.sub(r"\s+", " ", m.group(1)).strip() if m else url
    if not abstract:
        m = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\'](.*?)["\']', html, re.IGNORECASE)
        abstract = m.group(1).strip() if m else ""

    log.info("  [journal] %s — %s", url[:50], title[:60])
    return {
        "source": "journal",
        "url": url,
        "title": title,
        "abstract": abstract,
        "authors": authors,
    }


def fetch_all_papers(paper_links: list[str]) -> list[dict]:
    """Fetch metadata for all paper links (arXiv batch + journal one-by-one)."""
    arxiv_urls = [l for l in paper_links if "arxiv.org" in l]
    journal_urls = [l for l in paper_links if "arxiv.org" not in l]

    papers = fetch_arxiv_batch(arxiv_urls)
    for url in journal_urls:
        papers.append(fetch_journal_paper(url))

    return papers


# ---------------------------------------------------------------------------
# LLM — single call, no tools, no extended thinking
# ---------------------------------------------------------------------------

def load_system_prompt() -> str:
    path = PROMPTS_DIR / "profile_creator.txt"
    if not path.exists():
        log.error("System prompt not found: %s", path)
        sys.exit(1)
    return path.read_text(encoding="utf-8")


def compute_author_frequencies(papers: list[dict]) -> list[tuple[str, int]]:
    """Count how many papers each author appears in, sorted by frequency."""
    counts: dict[str, int] = {}
    for paper in papers:
        for author in paper.get("authors", []):
            counts[author] = counts.get(author, 0) + 1
    return sorted(counts.items(), key=lambda x: x[1], reverse=True)



def build_user_message(inputs: dict, papers: list[dict]) -> str:
    categories_str = ", ".join(inputs["categories"]) if inputs["categories"] else "not specified"
    researchers_str = (
        "\n".join(f"- {r}" for r in inputs["researchers"])
        if inputs["researchers"] else "none provided"
    )

    # Pre-computed author frequencies — Claude only needs to deduplicate and rank.
    author_freqs = compute_author_frequencies(papers)
    author_freq_str = (
        "\n".join(f"  {name}: {count} paper(s)" for name, count in author_freqs[:40])
        if author_freqs else "  none"
    )

    paper_blocks = []
    for p in papers:
        block = f"Title: {p['title']}\n"
        block += f"Authors: {', '.join(p['authors']) if p['authors'] else 'unknown'}\n"
        if p.get("arxiv_id"):
            block += f"arXiv ID: {p['arxiv_id']}\n"
        else:
            block += f"URL: {p.get('url', '')}\n"
        block += f"Abstract: {p.get('abstract', '(not available)')}"
        paper_blocks.append(block)

    papers_str = "\n\n---\n\n".join(paper_blocks) if paper_blocks else "none provided"

    return (
        f"arXiv categories of interest: {categories_str}\n\n"
        f"Free-text description of research interests:\n{inputs['interests_text']}\n\n"
        f"Researchers explicitly followed by user:\n{researchers_str}\n\n"
        f"Author frequency in provided papers (pre-counted by Python):\n{author_freq_str}\n\n"
        f"Recently read papers:\n\n{papers_str}"
    )


def call_llm(system_prompt: str, user_message: str) -> dict:
    """
    Single Claude call — returns compact rankings JSON only.
    Python assembles the full profile afterwards.
    """
    client = Anthropic()

    log.info("Calling Claude to analyse interests and build rankings...")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    log.info("Done. (input tokens: %d, output tokens: %d)",
             response.usage.input_tokens, response.usage.output_tokens)

    text = response.content[0].text.strip()

    # Try 1: direct parse.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try 2: strip markdown fences then parse.
    stripped = "\n".join(
        line for line in text.splitlines()
        if not line.startswith("```")
    ).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # Try 3: extract the first {...} block (handles leading prose).
    m = re.search(r"\{[\s\S]*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    log.error("Failed to parse rankings JSON. Raw response:\n%s", text[:800])
    sys.exit(1)


def assemble_profile(rankings: dict, inputs: dict, papers: list[dict]) -> dict:
    """
    Build the full taste_profile.json from:
      - Claude's compact rankings (keywords, areas, authors, paper notes)
      - Pre-fetched paper metadata (Python already has this)
      - Raw user inputs
    """
    # Map paper assessments by id/url so we can merge with metadata.
    notes_by_id = {}
    for note in rankings.get("paper_assessments", []):
        key = note.get("arxiv_id") or note.get("url", "")
        if key:
            notes_by_id[key] = note

    liked_papers = []
    for paper in papers:
        key = paper.get("arxiv_id") or paper.get("url", "")
        note = notes_by_id.get(key, {})
        liked_papers.append({
            "arxiv_id": paper.get("arxiv_id"),
            "title": paper.get("title", ""),
            "rating": "good",
            "why_relevant": note.get("why_relevant", ""),
        })

    return {
        "arxiv_categories": inputs["categories"],
        "interests_description": inputs["interests_text"],
        "keywords": rankings.get("keywords", []),
        "research_areas": rankings.get("research_areas", []),
        "authors": rankings.get("authors", []),
        "liked_papers": liked_papers,
        "evolved_interests": "",
    }


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def display_profile(profile: dict, categories: list[str]) -> None:
    """Print a human-readable summary of the draft profile."""
    print()
    print("=" * 58)
    print("  YOUR PROFILE DRAFT")
    print("=" * 58)

    print(f"\narXiv categories: {', '.join(categories) if categories else '(none)'}")

    print("\nKeywords (grade 1 = most relevant, 5 = tentative):")
    for kw in sorted(profile["keywords"], key=lambda x: x["grade"]):
        print(f"  grade {kw['grade']}: {kw['keyword']}")

    print("\nResearch areas (grade 1 = most relevant, 5 = tentative):")
    for area in sorted(profile["research_areas"], key=lambda x: x["grade"]):
        print(f"  grade {area['grade']}: {area['area']}")

    print("\nAuthors (ranked):")
    if profile.get("authors"):
        for author in sorted(profile["authors"], key=lambda x: x["rank"]):
            print(f"  {author['rank']:2d}. {author['name']}")
    else:
        print("  (none)")

    if profile["liked_papers"]:
        print(f"\nSeed papers ({len(profile['liked_papers'])}):")
        for p in profile["liked_papers"]:
            print(f"  - [{p['arxiv_id']}] {p['title']}")
    else:
        print("\nSeed papers: (none)")


# ---------------------------------------------------------------------------
# Edit flow
# ---------------------------------------------------------------------------

def edit_grades(items: list[dict], key: str) -> list[dict]:
    """
    Show graded items and let the user reassign grades.
    Enter changes as "name: grade" pairs, one per line. Blank line to finish.
    Grade must be 1–5 (6–7 are reserved for the monthly refiner).
    """
    sorted_items = sorted(items, key=lambda x: x["grade"])

    print("\nCurrent grades:")
    for item in sorted_items:
        print(f"  grade {item['grade']}: {item[key]}")

    print()
    print("Enter grade changes as \"name: grade\" pairs (e.g. \"STM: 1\").")
    print("Grade must be 1–5. Press Enter on a blank line when done.")

    name_map = {item[key].lower(): item for item in items}

    while True:
        raw = input("  > ").strip()
        if not raw:
            break
        if ":" not in raw:
            print("  Format: name: grade  (e.g. \"STM: 2\")")
            continue
        name_part, grade_part = raw.rsplit(":", 1)
        name_part = name_part.strip()
        grade_part = grade_part.strip()
        if not grade_part.isdigit() or not (1 <= int(grade_part) <= 5):
            print("  Grade must be an integer 1–5.")
            continue
        match = name_map.get(name_part.lower())
        if match is None:
            print(f"  \"{name_part}\" not found — check spelling.")
            continue
        match["grade"] = int(grade_part)
        print(f"  Set grade {grade_part} for: {match[key]}")

    return items


def reorder_authors(items: list[dict]) -> list[dict]:
    """
    Show the current author ranking and let the user type a new order.
    Unlisted authors are appended at the end in their original relative order.
    """
    sorted_items = sorted(items, key=lambda x: x["rank"])

    print("\nCurrent order:")
    for item in sorted_items:
        print(f"  {item['rank']:2d}. {item['name']}")

    print()
    print("Enter new order as comma-separated names.")
    print("Unlisted authors keep their relative position at the end.")
    print("Press Enter to keep the current order.")
    raw = input("  > ").strip()

    if not raw:
        return items

    new_names = [n.strip() for n in raw.split(",") if n.strip()]
    name_map = {item["name"].lower(): item for item in items}

    reordered = []
    rank = 1
    mentioned = set()

    for name in new_names:
        match = name_map.get(name.lower())
        if match:
            reordered.append({"name": match["name"], "rank": rank})
            mentioned.add(match["name"].lower())
            rank += 1

    for item in sorted_items:
        if item["name"].lower() not in mentioned:
            reordered.append({"name": item["name"], "rank": rank})
            rank += 1

    return reordered


def edit_rankings(profile: dict) -> dict:
    """Interactive editor for keyword/area grades and author rankings."""
    print()
    print("--- Edit keyword grades ---")
    profile["keywords"] = edit_grades(profile["keywords"], "keyword")

    print()
    print("--- Edit research area grades ---")
    profile["research_areas"] = edit_grades(profile["research_areas"], "area")

    print()
    print("--- Edit author rankings ---")
    profile["authors"] = reorder_authors(profile.get("authors", []))

    return profile


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="One-time onboarding: create your arXiv grader taste profile."
    )
    parser.add_argument(
        "--user-dir", default=None,
        help="User directory to create (e.g. users/alice). Creates the directory and writes .env and taste_profile.json there.",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output path for the profile JSON (default: <user-dir>/taste_profile.json or ./taste_profile.json)",
    )
    args = parser.parse_args()

    # Resolve user directory and paths.
    if args.user_dir:
        user_dir = Path(args.user_dir)
        user_dir.mkdir(parents=True, exist_ok=True)
        (user_dir / "data").mkdir(exist_ok=True)
        env_path = user_dir / ".env"
        output_path = args.output or str(user_dir / "taste_profile.json")
        print(f"\n  User directory: {user_dir}")
    else:
        env_path = _DEFAULT_ENV_PATH
        output_path = args.output or DEFAULT_OUTPUT

    # 0. Ensure credentials are present and valid; prompt + save if not.
    setup_credentials(env_path)

    # 1. Collect user inputs.
    inputs = collect_inputs()

    # 2. Pre-fetch all paper metadata in Python.
    papers = fetch_all_papers(inputs["paper_links"])

    # 3. Single Claude call — returns compact rankings only.
    system_prompt = load_system_prompt()
    user_message = build_user_message(inputs, papers)
    rankings = call_llm(system_prompt, user_message)

    # 4. Python assembles the full profile from rankings + pre-fetched data.
    profile = assemble_profile(rankings, inputs, papers)

    # 4. Review / edit loop.
    while True:
        display_profile(profile, inputs["categories"])
        print()
        print("What would you like to do?")
        print("  [a]  Accept and save")
        print("  [e]  Edit rankings")
        print("  [q]  Quit without saving")
        choice = input("  > ").strip().lower()

        if choice == "a":
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(profile, f, indent=2, ensure_ascii=False)
            log.info("Profile saved to %s", output_path)
            break
        elif choice == "e":
            profile = edit_rankings(profile)
        elif choice == "q":
            print("Exiting without saving.")
            sys.exit(0)
        else:
            print("Please enter 'a', 'e', or 'q'.")


if __name__ == "__main__":
    main()
