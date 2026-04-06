#!/usr/bin/env python3
"""
build_digest_pdf.py — Generate the daily arXiv cond-mat digest PDF.

Reads scored_papers.json (graded, sorted by score desc) and today_papers.json
(all arXiv papers), writes a styled PDF: scored papers on top, unscored below a divider.
Within each section, journal papers come first, then arXiv papers.
Rating buttons are styled hyperlinks pointing to the /rate endpoint.

Usage:
    python build_digest_pdf.py
    python build_digest_pdf.py --scored scored_papers.json --papers today_papers.json --output digest.pdf
"""

import json
import sys
import argparse
from datetime import date
from pathlib import Path
from urllib.parse import quote

import os
import matplotlib
from reportlab.lib.utils import ImageReader
from pylatexenc.latex2text import LatexNodes2Text
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.colors import HexColor, white
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether, PageBreak,
)

# ── Rating endpoint — overridden by --base-url and --user CLI flags ──────────
RATE_BASE_URL = "https://your-server.com/rate"
RATE_USER     = ""   # set from --user flag; embedded in every rating URL

# ── Logo ──────────────────────────────────────────────────────────────────────
_LOGO_PATH = Path(__file__).parent / "docs" / "logo_for_pdf_2.png"
_LOGO_W    = 18 * mm   # display width on page
_LOGO_H    = 24 * mm   # display height (preserveAspectRatio keeps it correct)

# ── Page geometry ─────────────────────────────────────────────────────────────
PAGE_W, PAGE_H = A4
MARGIN = 15 * mm
COL_W = PAGE_W - 2 * MARGIN
BADGE_W = 13 * mm

# ── Colour palette — warm gray / off-white / beige ────────────────────────────
C = {
    "page_bg":       HexColor("#F7F4EF"),   # warm off-white page background
    "title_bg":      HexColor("#DDD5C8"),   # beige title band
    "author_bg":     HexColor("#EAE4DB"),   # lighter beige author band
    "score_high":    HexColor("#6E9E7E"),   # muted sage green  — score 8–10
    "score_mid":     HexColor("#B5963E"),   # muted amber       — score 5–7
    "score_low":     HexColor("#B07060"),   # muted terracotta  — score 1–4
    "tag_bg":        HexColor("#E0D8CC"),   # tag pill / section divider
    "divider":       HexColor("#C0B8AD"),   # horizontal rule colour
    "text_dark":     HexColor("#2C2826"),   # primary text
    "text_mid":      HexColor("#5C5550"),   # secondary / muted text
    "btn_relevant":  HexColor("#8FAF8F"),   # green-ish
    "btn_interest":  HexColor("#A8A890"),   # neutral sage
    "btn_skip":      HexColor("#B8A8A8"),   # muted rose-gray
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def score_color(score: int):
    if score >= 8:
        return C["score_high"]
    if score >= 5:
        return C["score_mid"]
    return C["score_low"]


def paper_url(paper_id: str) -> str:
    """Return a link URL: pass through full URLs, doi.org for DOIs (10.*), arxiv.org otherwise."""
    if paper_id.startswith("http://") or paper_id.startswith("https://"):
        return paper_id
    if paper_id.startswith("10."):
        return f"https://doi.org/{paper_id}"
    base = paper_id.split("v")[0]
    return f"https://arxiv.org/abs/{base}"


def rate_url(paper_id: str, rating: str, date_str: str) -> str:
    encoded_id = quote(paper_id, safe="")
    url = f"{RATE_BASE_URL}?paper_id={encoded_id}&rating={rating}&date={date_str}"
    if RATE_USER:
        url += f"&user={RATE_USER}"
    return url


def register_fonts():
    """Register DejaVu Sans from matplotlib's bundled fonts — broad Unicode coverage."""
    font_dir = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
    pdfmetrics.registerFont(TTFont("DejaVuSans",        os.path.join(font_dir, "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold",   os.path.join(font_dir, "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Oblique",os.path.join(font_dir, "DejaVuSans-Oblique.ttf")))


import re as _re

_latex_converter = LatexNodes2Text()

# $...$ or \(...\) — the \(...\) pattern allows backslashes inside
_MATH_BLOCK = _re.compile(r'(\$[^$]+\$|\\\(.+?\\\))')
_SCRIPT_PAT = _re.compile(r'([_^])\{([^}]*)\}|([_^])([^\s{\\])')

# ^\circ and ^{\circ} → degree symbol (must be caught before general ^ processing)
_DEGREE_PAT = _re.compile(r'\^\{?\\circ\}?')

# Unicode superscripts for digits/signs — used inside _{} content where we
# can't nest <super> tags inside a <sub> tag
_SUP_UNICODE = str.maketrans("0123456789+-n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻ⁿ")


def safe(text: str) -> str:
    """Escape XML special characters for ReportLab markup."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _convert_symbols(text: str) -> str:
    """Run pylatexenc on a fragment (Greek letters, operators → Unicode)."""
    try:
        return _latex_converter.latex_to_text(text)
    except Exception:
        return text


def _inner_script(content: str) -> str:
    """
    Process the content inside _{} or ^{}.
    Converts LaTeX commands to Unicode, then converts any nested ^x patterns
    to Unicode superscripts (can't nest <super> inside <sub> in ReportLab).
    """
    text = _convert_symbols(content)
    # nested ^x or ^{...} → Unicode superscript characters
    text = _re.sub(
        r'\^\{([^}]*)\}|\^([^\s{\\])',
        lambda m: (m.group(1) or m.group(2)).translate(_SUP_UNICODE),
        text,
    )
    return safe(text)


def _process_math(math: str) -> str:
    r"""
    Convert a LaTeX string to ReportLab markup.
    - ^\circ / ^{\circ} → ° (degree) before anything else
    - _{} / ^{} → <sub>/<super> tags
    - Other LaTeX commands → Unicode via pylatexenc
    """
    # Degree sign must come first — \circ would otherwise become ∘ (ring operator)
    math = _DEGREE_PAT.sub("°", math)

    parts = []
    pos = 0
    for m in _SCRIPT_PAT.finditer(math):
        before = math[pos:m.start()]
        if before:
            parts.append(safe(_convert_symbols(before)))

        if m.group(1):                      # braced: _{…} or ^{…}
            marker, content = m.group(1), m.group(2)
        else:                               # single char: _x or ^x
            marker, content = m.group(3), m.group(4)

        tag = "sub" if marker == "_" else "super"
        parts.append(f"<{tag}>{_inner_script(content)}</{tag}>")
        pos = m.end()

    tail = math[pos:]
    if tail:
        parts.append(safe(_convert_symbols(tail)))
    return "".join(parts)


def delatex_markup(text: str) -> str:
    """
    Convert a LaTeX string to ReportLab paragraph markup.
    - $...$ and \\(...\\) blocks: full math processing
    - Plain text segments: same pipeline (handles bare ^{} outside $)
    Returns a markup-safe string. Do NOT wrap the result in safe().
    """
    parts = []
    for seg in _MATH_BLOCK.split(text):
        if seg.startswith("$") and seg.endswith("$") and len(seg) > 1:
            parts.append(_process_math(seg[1:-1]))
        elif seg.startswith("\\(") and seg.endswith("\\)"):
            parts.append(_process_math(seg[2:-2]))
        else:
            parts.append(_process_math(seg))
    return "".join(parts)


# ── Styles ────────────────────────────────────────────────────────────────────

def make_styles() -> dict:
    return {
        "page_title": ParagraphStyle(
            "page_title",
            fontName="DejaVuSans-Bold", fontSize=18, leading=24,
            textColor=C["text_dark"], alignment=TA_CENTER,
        ),
        "page_date": ParagraphStyle(
            "page_date",
            fontName="DejaVuSans", fontSize=12, leading=16,
            textColor=C["text_mid"], alignment=TA_CENTER, spaceAfter=6,
        ),
        "section_header": ParagraphStyle(
            "section_header",
            fontName="DejaVuSans-Bold", fontSize=14, leading=20,
            textColor=C["text_dark"], spaceBefore=4, spaceAfter=2,
        ),
        "subsection_header": ParagraphStyle(
            "subsection_header",
            fontName="DejaVuSans-Bold", fontSize=11, leading=16,
            textColor=C["text_mid"], spaceBefore=6, spaceAfter=2,
        ),
        "title": ParagraphStyle(
            "title",
            fontName="DejaVuSans-Bold", fontSize=13, leading=18,
            textColor=C["text_dark"],
        ),
        "authors": ParagraphStyle(
            "authors",
            fontName="DejaVuSans", fontSize=10, leading=14,
            textColor=C["text_mid"],
        ),
        "justification": ParagraphStyle(
            "justification",
            fontName="DejaVuSans-Oblique", fontSize=10, leading=15,
            textColor=C["text_mid"], spaceBefore=5,
        ),
        "abstract": ParagraphStyle(
            "abstract",
            fontName="DejaVuSans", fontSize=10, leading=15,
            textColor=C["text_dark"], spaceBefore=5, spaceAfter=4,
        ),
        "tags": ParagraphStyle(
            "tags",
            fontName="DejaVuSans", fontSize=9, leading=13,
            textColor=C["text_mid"], spaceBefore=4,
        ),
        "score_badge": ParagraphStyle(
            "score_badge",
            fontName="DejaVuSans-Bold", fontSize=17, leading=22,
            textColor=white, alignment=TA_CENTER,
        ),
        "btn": ParagraphStyle(
            "btn",
            fontName="DejaVuSans-Bold", fontSize=10, leading=14,
            textColor=C["text_dark"], alignment=TA_CENTER,
        ),
        "divider_label": ParagraphStyle(
            "divider_label",
            fontName="DejaVuSans", fontSize=11, leading=15,
            textColor=C["text_mid"], alignment=TA_CENTER,
        ),
    }


# ── Component builders ────────────────────────────────────────────────────────

def title_table(paper: dict, styles: dict, scored: bool) -> Table:
    """Coloured title band, optionally with a score badge on the left."""
    url = paper_url(paper["arxiv_id"])
    title_para = Paragraph(
        f'<a href="{url}" color="#2C2826">{delatex_markup(paper.get("title", "Untitled"))}</a>',
        styles["title"],
    )

    if scored:
        score = paper["score"]
        badge = Paragraph(str(score), styles["score_badge"])
        data = [[badge, title_para]]
        col_widths = [BADGE_W, COL_W - BADGE_W]
        style = TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), score_color(score)),
            ("BACKGROUND", (1, 0), (1, 0), C["title_bg"]),
            ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING",  (0, 0), (0, 0), 2),
            ("RIGHTPADDING", (0, 0), (0, 0), 2),
            ("LEFTPADDING",  (1, 0), (1, 0), 8),
            ("RIGHTPADDING", (1, 0), (1, 0), 8),
        ])
    else:
        data = [[title_para]]
        col_widths = [COL_W]
        style = TableStyle([
            ("BACKGROUND",    (0, 0), (0, 0), C["title_bg"]),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ])

    t = Table(data, colWidths=col_widths)
    t.setStyle(style)
    return t


def author_table(paper: dict, styles: dict) -> Table:
    """Lighter beige author band with source label (journal name or arXiv subcategory)."""
    authors_text = safe(", ".join(paper.get("authors", [])) or "Unknown authors")

    source = paper.get("source", "")
    subcats = paper.get("subcategories", [])
    if source:
        label = f'  <font size="8">[{safe(source)}]</font>'
    elif subcats:
        label = f'  <font size="8">[{safe(subcats[0])}]</font>'
    else:
        label = ""

    para = Paragraph(authors_text + label, styles["authors"])
    t = Table([[para]], colWidths=[COL_W])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (0, 0), C["author_bg"]),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def rating_table(paper_id: str, date_str: str, styles: dict) -> Table:
    """Three-button rating row as styled hyperlinks."""
    buttons = [
        ("excellent",  "★  Very Relevant", C["btn_relevant"]),
        ("good",       "◆  Interesting",   C["btn_interest"]),
        ("irrelevant", "✕  Not Relevant",  C["btn_skip"]),
    ]
    w = COL_W / 3
    cells = [
        Paragraph(
            f'<a href="{rate_url(paper_id, key, date_str)}" color="#2C2826">{label}</a>',
            styles["btn"],
        )
        for key, label, _ in buttons
    ]
    t = Table([cells], colWidths=[w, w, w])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), C["btn_relevant"]),
        ("BACKGROUND", (1, 0), (1, 0), C["btn_interest"]),
        ("BACKGROUND", (2, 0), (2, 0), C["btn_skip"]),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LINEAFTER",  (0, 0), (1, 0), 1, C["page_bg"]),   # subtle gap between buttons
    ]))
    return t


def separator():
    return HRFlowable(width=COL_W, thickness=0.5, color=C["divider"], spaceAfter=8)


def subsection_divider(label: str, count: int, styles: dict) -> list:
    """Subsection header (e.g. 'Journals (3)' or 'arXiv (17)')."""
    return [
        Paragraph(f"{label}  ({count})", styles["subsection_header"]),
        Spacer(1, 2 * mm),
    ]


# ── Paper blocks ──────────────────────────────────────────────────────────────

def scored_block(paper: dict, date_str: str, styles: dict) -> KeepTogether:
    els = [
        title_table(paper, styles, scored=True),
        author_table(paper, styles),
    ]

    tags = paper.get("tags", [])
    if tags:
        els.append(Paragraph("  ".join(f"[{t}]" for t in tags), styles["tags"]))

    if paper.get("justification"):
        els.append(Paragraph(safe(paper["justification"]), styles["justification"]))

    abstract = paper.get("abstract", "").strip()
    if abstract:
        els.append(Paragraph(delatex_markup(abstract), styles["abstract"]))

    els += [
        Spacer(1, 4),
        rating_table(paper["arxiv_id"], date_str, styles),
        Spacer(1, 6),
        separator(),
    ]
    return KeepTogether(els)


def unscored_block(paper: dict, date_str: str, styles: dict) -> KeepTogether:
    els = [
        title_table(paper, styles, scored=False),
        author_table(paper, styles),
        Spacer(1, 2),
        rating_table(paper["arxiv_id"], date_str, styles),
        Spacer(1, 3),
        separator(),
    ]
    return KeepTogether(els)


# ── Page background ───────────────────────────────────────────────────────────

def draw_background(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(C["page_bg"])
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    canvas.restoreState()


def draw_first_page(canvas, doc):
    """First page: warm background + logo at top-left."""
    draw_background(canvas, doc)
    if _LOGO_PATH.exists():
        canvas.saveState()
        canvas.drawImage(
            str(_LOGO_PATH),
            MARGIN,
            PAGE_H - MARGIN - _LOGO_H,
            width=_LOGO_W,
            height=_LOGO_H,
            preserveAspectRatio=True,
            mask="auto",
        )
        canvas.restoreState()


# ── Main builder ──────────────────────────────────────────────────────────────

def build_pdf(scored_path: str, papers_path: str, output_path: str, journals_path: str | None = None):
    register_fonts()
    scored = json.loads(Path(scored_path).read_text(encoding="utf-8"))
    all_arxiv = json.loads(Path(papers_path).read_text(encoding="utf-8"))
    all_journals = json.loads(Path(journals_path).read_text(encoding="utf-8")) if journals_path else []

    scored_ids = {p["arxiv_id"] for p in scored}

    # Split scored into journal and arXiv (already sorted by score desc)
    scored_journals = [p for p in scored if p.get("source")]
    scored_arxiv    = [p for p in scored if not p.get("source")]

    # Unscored: everything not in scored
    unscored_journals = [p for p in all_journals if p["arxiv_id"] not in scored_ids]
    unscored_arxiv    = [p for p in all_arxiv    if p["arxiv_id"] not in scored_ids]

    total_papers = len(all_arxiv) + len(all_journals)
    total_scored = len(scored)
    total_unscored = len(unscored_arxiv) + len(unscored_journals)

    styles = make_styles()
    d = date.today()
    date_str = d.strftime(f"%A, %B {d.day}, %Y")

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN,
    )

    story = [
        Spacer(1, 4 * mm),
        Paragraph("Incoming Science — daily digest", styles["page_title"]),
        Paragraph(date_str, styles["page_date"]),
        Paragraph(
            f"{total_papers} papers today  ·  {total_scored} scored  ·  {total_unscored} unscored",
            styles["page_date"],
        ),
        KeepTogether([
            HRFlowable(width=COL_W, thickness=1, color=C["divider"], spaceAfter=6),
            Spacer(1, 4 * mm),
            Paragraph(f"Top Papers  ({total_scored})", styles["section_header"]),
            Spacer(1, 3 * mm),
        ]),
    ]

    # ── Scored: journals first, then arXiv ────────────────────────────────────
    if scored_journals:
        first = scored_block(scored_journals[0], d.isoformat(), styles)
        story.append(KeepTogether(subsection_divider("Journals", len(scored_journals), styles) + [first]))
        for paper in scored_journals[1:]:
            story.append(scored_block(paper, d.isoformat(), styles))

    if scored_arxiv:
        first = scored_block(scored_arxiv[0], d.isoformat(), styles)
        story.append(KeepTogether(subsection_divider("arXiv", len(scored_arxiv), styles) + [first]))
        for paper in scored_arxiv[1:]:
            story.append(scored_block(paper, d.isoformat(), styles))

    # ── Section divider ───────────────────────────────────────────────────────
    story.append(PageBreak())
    div_row = Table(
        [[Paragraph("— Remaining papers —", styles["divider_label"])]],
        colWidths=[COL_W],
    )
    div_row.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (0, 0), C["tag_bg"]),
        ("TOPPADDING",    (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    _browse_header = [
        div_row,
        Spacer(1, 4 * mm),
        Paragraph(f"Browse  ({total_unscored} papers)", styles["section_header"]),
        Spacer(1, 3 * mm),
    ]

    # ── Unscored: journals first, then arXiv ──────────────────────────────────
    if unscored_journals:
        first = unscored_block(unscored_journals[0], d.isoformat(), styles)
        story.append(KeepTogether(
            _browse_header
            + subsection_divider("Journals", len(unscored_journals), styles)
            + [first]
        ))
        for paper in unscored_journals[1:]:
            story.append(unscored_block(paper, d.isoformat(), styles))

    if unscored_arxiv:
        first = unscored_block(unscored_arxiv[0], d.isoformat(), styles)
        header = _browse_header if not unscored_journals else []
        story.append(KeepTogether(header + subsection_divider("arXiv", len(unscored_arxiv), styles) + [first]))
        for paper in unscored_arxiv[1:]:
            story.append(unscored_block(paper, d.isoformat(), styles))

    doc.build(story, onFirstPage=draw_first_page, onLaterPages=draw_background)
    sys.stdout.buffer.write(
        f"Digest -> {output_path}  ({total_scored} scored, {total_unscored} unscored)\n"
        .encode("utf-8", errors="replace")
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Build daily arXiv digest PDF")
    p.add_argument("--scored",    default="scored_papers.json",          help="Scored papers JSON")
    p.add_argument("--papers",    default="today_papers.json",           help="All arXiv papers JSON")
    p.add_argument("--journals",  default=None,                          help="All journal papers JSON (optional)")
    p.add_argument("--output",    default=None,                          help="Output PDF path")
    p.add_argument("--base-url",  default=None,                          help="Override rating base URL (e.g. http://localhost:5000/rate)")
    p.add_argument("--user",      default=None,                          help="Username embedded in rating URLs (e.g. alice)")
    args = p.parse_args()

    if args.base_url:
        global RATE_BASE_URL
        RATE_BASE_URL = args.base_url

    if args.user:
        global RATE_USER
        RATE_USER = args.user

    if args.output is None:
        args.output = f"digest_{date.today().strftime('%Y-%m-%d')}.pdf"

    missing = [f for f in [args.scored, args.papers] if not Path(f).exists()]
    if missing:
        for f in missing:
            print(f"Error: {f} not found", file=sys.stderr)
        sys.exit(1)

    build_pdf(args.scored, args.papers, args.output, journals_path=args.journals)


if __name__ == "__main__":
    main()
