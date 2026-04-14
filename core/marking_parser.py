"""
core/marking_parser.py
======================
Parses MARKING SCHEME / TOPICAL BOOK PDFs.

PATTERNS OBSERVED (from sample images):
=========================================
These are compiled topical books, NOT original CIE papers.

Question markers:
  "Question #1:"  at left margin  → level 0, question_number = "1"
  "Question #2:"  at left margin  → level 0, question_number = "2"

Sub-answer markers (inside a question block):
  "(a)(i)"  "(a)(ii)"  "(a)"  "(b)"   → level 1 or 2

Source reference (on same line as "Question #N:"):
  "[Q10(d)  Paper 11 M/J/18]"
  "Specimen paper set B Q8"

Algorithm:
  Pass 1: scan all text lines for "Question #N:" pattern → collect main markers
  Pass 2: for each main question, compute bbox_full to next "Question #N:"
  Pass 3: scan inside each question block for sub-markers
  Pass 4: extract text and marks

Returns same dict structure as pdf_parser.py so everything downstream
(db_manager, grouper, exporter) works identically.
"""

import re
import json
import logging
from typing import Optional

import pdfplumber

logger = logging.getLogger(__name__)

# ── Regexes ───────────────────────────────────────────────────────────────────

# "Question #1:"  "Question #12:"  "Question#1:"  "Q#1:"
RE_Q_HASH  = re.compile(r'^[Qq]uestion\s*#\s*(\d+)\s*:?\s*$', re.IGNORECASE)
RE_Q_HASH2 = re.compile(r'[Qq]uestion\s*#\s*(\d+)', re.IGNORECASE)  # anywhere in line

# Sub-answer markers — same as question paper format
RE_SUB_PAREN  = re.compile(r'^\(([a-z])\)$',                                re.IGNORECASE)
RE_SUBSUB_ROM = re.compile(r'^\((i{1,3}|iv|vi{0,3}|ix|xi{0,3}|x)\)$',     re.IGNORECASE)

# Source reference: "[Q10(d) Paper 11 M/J/18]" or "Specimen paper set B Q8"
RE_SOURCE = re.compile(
    r'\[Q[\d\w()\s]+Paper\s+\d+[^\]]*\]'
    r'|Specimen\s+paper[^\n]*Q\d+'
    r'|\[Q[\w\d()\s]+\]',
    re.IGNORECASE
)

# Marks: [1]  [2]  [Total: 10]
RE_MARKS = re.compile(r'\[(\d+)\s*(?:marks?)?\]|\[Total:\s*(\d+)\]', re.IGNORECASE)

# Position thresholds (pts from left) — marking schemes tend to have wider margins
MAIN_MAX_X  = 120   # "Question #N:" starts within 120pt
SUB_MAX_X   = 180   # (a)(b)(c) within 180pt
SUBSUB_MAX_X = 260  # (i)(ii)(iii) within 260pt


def parse_marking_scheme(filepath: str) -> list:
    """
    Parse a marking scheme / topical book PDF.
    Returns list of question dicts (same schema as pdf_parser).
    """
    logger.info("Parsing marking scheme: %s", filepath)
    results = []

    try:
        with pdfplumber.open(filepath) as pdf:
            # ── Pass 1: collect all "Question #N:" markers across pages ──────
            all_markers = []
            for pg_idx, page in enumerate(pdf.pages):
                markers = _find_question_markers(page, pg_idx)
                all_markers.extend(markers)

            if not all_markers:
                logger.warning("No 'Question #N:' markers found in %s", filepath)
                # Fallback: treat as single-question document
                return []

            logger.info("Found %d question markers", len(all_markers))

            # ── Pass 2: assign bboxes ─────────────────────────────────────────
            _assign_bboxes(all_markers, pdf)

            # ── Pass 3: extract text + sub-markers + marks ────────────────────
            for m in all_markers:
                pg   = pdf.pages[m["page_number"]]
                bbox = json.loads(m["bbox"])
                try:
                    region = pg.within_bbox(
                        (bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])
                    )
                    text = region.extract_text() or ""
                except Exception:
                    text = ""
                m["text_content"] = text.strip()
                m["marks"]        = _extract_marks(text)
                m["source_ref"]   = _extract_source(text)

            results = all_markers

    except Exception as e:
        logger.error("Failed to parse marking scheme %s: %s", filepath, e)
        raise

    logger.info("Marking scheme: found %d entries in %s", len(results), filepath)
    return results


def _find_question_markers(page, pg_idx: int) -> list:
    """Scan page words/lines for 'Question #N:' markers."""
    markers = []

    # Use line-level extraction for better accuracy
    words = page.extract_words(x_tolerance=5, y_tolerance=5)
    if not words:
        return []

    # Group words into lines by y-position
    lines = _group_into_lines(words)

    for line in lines:
        line_text = " ".join(w["text"] for w in line).strip()
        m = RE_Q_HASH2.search(line_text)
        if not m:
            continue

        # Check it's near left margin (main question marker)
        x0    = min(w["x0"] for w in line)
        y_top = min(w["top"] for w in line)
        y_bot = max(w["bottom"] for w in line)

        if x0 > MAIN_MAX_X:
            continue   # too indented — not a main marker

        q_num = m.group(1)

        markers.append({
            "question_number": q_num,
            "question_level":  0,
            "parent_number":   "",
            "page_number":     pg_idx,
            "page_width":      page.width,
            "page_height":     page.height,
            "y_top":           y_top,
            "y_bottom":        y_bot,
            "bbox":            "",
            "bbox_full":       "",
            "text_content":    "",
            "marks":           None,
            "source_ref":      "",
            "doc_type":        "marking_scheme",
        })

    return markers


def _group_into_lines(words: list, y_tol: float = 4.0) -> list:
    """Group word dicts into lines by proximity of y-coordinates."""
    if not words:
        return []
    sorted_words = sorted(words, key=lambda w: (round(w["top"] / y_tol), w["x0"]))
    lines = []
    current_line = [sorted_words[0]]
    for w in sorted_words[1:]:
        if abs(w["top"] - current_line[-1]["top"]) <= y_tol:
            current_line.append(w)
        else:
            lines.append(current_line)
            current_line = [w]
    lines.append(current_line)
    return lines


def _assign_bboxes(markers: list, pdf):
    """Compute tight bbox for each question: from y_top to next marker's y_top."""
    n = len(markers)
    for i, m in enumerate(markers):
        pg     = m["page_number"]
        y0     = max(0.0, m["y_top"] - 2)
        page_h = m["page_height"]
        page_w = m["page_width"]

        # Find next marker on same page → use as y1
        y1 = page_h
        for j in range(i + 1, n):
            nxt = markers[j]
            if nxt["page_number"] == pg:
                y1 = nxt["y_top"] - 2
                break
            else:
                # Next marker is on next page → use full page height
                break

        bbox = {"x0": 0.0, "y0": y0, "x1": page_w, "y1": min(page_h, y1)}
        m["bbox"]      = json.dumps(bbox)
        m["bbox_full"] = json.dumps(bbox)


def _extract_marks(text: str) -> Optional[int]:
    """Extract total marks from text."""
    # Try [Total: N] first
    for pat in [
        re.compile(r'\[Total:\s*(\d+)\]', re.IGNORECASE),
        re.compile(r'\[(\d+)\s*marks?\]', re.IGNORECASE),
        re.compile(r'\[(\d+)\]'),
    ]:
        m = pat.search(text)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
    return None


def _extract_source(text: str) -> str:
    """Extract source reference like '[Q10(d) Paper 11 M/J/18]'."""
    m = RE_SOURCE.search(text)
    return m.group(0).strip() if m else ""