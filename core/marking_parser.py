"""
core/marking_parser.py
=======================
Parses REAL CIE MARKING SCHEME PDFs.

REAL CIE FORMAT (learned from screenshots 0985_s25_ms_22):
===========================================================

Page layout:
  Header:  "0985/22  Cambridge IGCSE (9-1) – Mark Scheme  May/June 2025  PUBLISHED"

  Table:   ┌──────────┬──────────────────────────────────┬───────┐
           │ Question │ Answer                            │ Marks │
           ├──────────┼──────────────────────────────────┼───────┤
           │  1(a)    │ Kadima Cash Book ...              │  12   │
           │  1(b)    │ Cash book balance 579 ...         │   3   │
           │  1(c)    │ For requiring bank transfers...   │   5   │
           │  2(a)    │ Farah and Salma...                │   6   │
           │  2(b)    │ Current account...                │   7   │
           └──────────┴──────────────────────────────────┴───────┘

QUESTION NUMBER PATTERNS:
  "1(a)"   → main=1, sub=(a)  → question_level=1
  "1(b)"   → main=1, sub=(b)  → question_level=1
  "2(a)"   → main=2, sub=(a)  → question_level=1
  "1(a)(i)"→ main=1, sub=(a), subsub=(i) → question_level=2
  "1"      → main only        → question_level=0

SAME HIERARCHY AS QUESTION PAPERS:
  Level 0: "1", "2", "3"
  Level 1: "1(a)", "1(b)", "2(a)"
  Level 2: "1(a)(i)", "1(a)(ii)"

ALGORITHM:
  Pass 1: Extract all words, identify "Question" column x-range
  Pass 2: Find all rows where the left-column cell matches a question number pattern
  Pass 3: For each question cell, compute bbox = that row's region
  Pass 4: Extract text from the Answer column for that row
  Pass 5: Extract marks from Marks column

Returns SAME dict structure as pdf_parser.py — fully compatible with
grouper, exporter, results panel, everything.
"""

import re
import json
import logging
from typing import Optional

import pdfplumber

logger = logging.getLogger(__name__)

# ── Question number patterns (same as pdf_parser) ───────────────────────────
RE_MAIN       = re.compile(r'^(\d{1,2})\.?$')
RE_SUB        = re.compile(r'^(\d{1,2})\(([a-z])\)$', re.IGNORECASE)
RE_SUBSUB     = re.compile(r'^(\d{1,2})\(([a-z])\)\((i{1,3}|iv|vi{0,3}|ix|x{1,3})\)$', re.IGNORECASE)

# Also handle formats like "(a)" alone in column (if question # is on prev row)
RE_SUB_ALONE  = re.compile(r'^\(([a-z])\)$', re.IGNORECASE)
RE_SUBSUB_ALONE = re.compile(r'^\((i{1,3}|iv|vi{0,3}|ix|x{1,3})\)$', re.IGNORECASE)

RE_MARKS_COL  = re.compile(r'^\d{1,3}$')   # just a number in Marks column


def parse_marking_scheme(filepath: str) -> list:
    """
    Parse a real CIE marking scheme PDF.
    Returns list of question dicts (same schema as pdf_parser).
    """
    logger.info("Parsing CIE marking scheme: %s", filepath)

    try:
        with pdfplumber.open(filepath) as pdf:
            all_markers = []
            ctx = {"main": None, "sub": None}

            for pg_idx, page in enumerate(pdf.pages):
                markers = _parse_page(page, pg_idx, ctx)
                all_markers.extend(markers)

            if not all_markers:
                logger.warning("No question markers found in marking scheme: %s", filepath)
                return []

            logger.info("Marking scheme: found %d entries", len(all_markers))
            return all_markers

    except Exception as e:
        logger.error("Failed to parse marking scheme %s: %s", filepath, e)
        raise


def _parse_page(page, pg_idx: int, ctx: dict) -> list:
    """Parse one page of a CIE marking scheme."""
    words = page.extract_words(x_tolerance=4, y_tolerance=4,
                                keep_blank_chars=False, use_text_flow=False)
    if not words:
        return []

    # ── Step 1: Find the "Question" column x-boundary ────────────────────────
    # The Question column header word "Question" tells us the left x range.
    # Typically x0 ≈ 30-80 pts, x1 ≈ 90-130 pts for the question number column.
    q_col_x0, q_col_x1 = _find_question_column(words, page.width)

    # ── Step 2: Group words into lines by y-position ─────────────────────────
    lines = _group_lines(words)

    # ── Step 3: Scan lines for question number tokens in Question column ──────
    raw_markers = []
    for line in lines:
        q_token = _find_q_token_in_line(line, q_col_x0, q_col_x1)
        if not q_token:
            continue

        text   = q_token["text"]
        y_top  = q_token["y_top"]
        y_bot  = q_token["y_bot"]

        qnum, level, parent = _classify_token(text, ctx)
        if qnum is None:
            continue

        # Collect all text on this line (the answer row text)
        line_text = " ".join(w["text"] for w in line)
        marks     = _extract_marks_from_line(line)

        raw_markers.append({
            "question_number": qnum,
            "question_level":  level,
            "parent_number":   parent,
            "page_number":     pg_idx,
            "page_width":      page.width,
            "page_height":     page.height,
            "y_top":           y_top,
            "y_bottom":        y_bot,
            "line_text":       line_text,
            "marks":           marks,
        })

    if not raw_markers:
        return []

    # ── Step 4: Assign bboxes — from y_top of this row to y_top of next ──────
    result = []
    n = len(raw_markers)
    for i, m in enumerate(raw_markers):
        y0 = max(0.0, m["y_top"] - 2)
        y1 = raw_markers[i + 1]["y_top"] - 2 if i + 1 < n else page.height

        bbox = {
            "x0": 0.0,
            "y0": y0,
            "x1": page.width,
            "y1": min(page.height, y1),
        }

        # Extract full text from the region
        try:
            region = page.within_bbox((bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"]))
            text   = region.extract_text() or ""
        except Exception:
            text = m["line_text"]

        result.append({
            "question_number": m["question_number"],
            "question_level":  m["question_level"],
            "parent_number":   m["parent_number"],
            "page_number":     m["page_number"],
            "page_width":      m["page_width"],
            "page_height":     m["page_height"],
            "y_top":           m["y_top"],
            "bbox":            json.dumps(bbox),
            "bbox_full":       json.dumps(bbox),
            "text_content":    text.strip(),
            "marks":           m["marks"] or _extract_marks_from_text(text),
            "source_ref":      "",
            "doc_type":        "marking_scheme",
        })

    return result


def _find_question_column(words: list, page_width: float):
    """
    Identify the x-range of the "Question" column.

    Strategy:
    1. Look for word "Question" near left side → use its x0/x1 as column boundary
    2. Fall back to left 15% of page width
    """
    for w in words:
        if w["text"].strip().lower() == "question" and w["x0"] < page_width * 0.25:
            # Column header found — question cells are in this x-range
            col_x0 = max(0, w["x0"] - 10)
            col_x1 = w["x1"] + 60   # allow some extra width for the numbers
            return col_x0, col_x1

    # Fallback: left 18% of page
    return 0.0, page_width * 0.18


def _group_lines(words: list, y_tol: float = 5.0) -> list:
    """Group words into lines by y proximity."""
    if not words:
        return []
    sorted_w = sorted(words, key=lambda w: (round(w["top"] / y_tol) * y_tol, w["x0"]))
    lines, cur = [], [sorted_w[0]]
    for w in sorted_w[1:]:
        if abs(w["top"] - cur[-1]["top"]) <= y_tol:
            cur.append(w)
        else:
            lines.append(cur)
            cur = [w]
    lines.append(cur)
    return lines


def _find_q_token_in_line(line: list, col_x0: float, col_x1: float) -> Optional[dict]:
    """
    Find the question-number token within the Question column x-range.
    Returns a dict with text, y_top, y_bot or None.
    """
    col_words = [w for w in line if col_x0 <= w["x0"] <= col_x1]
    if not col_words:
        return None

    # Combine col words into one token
    token_text = "".join(w["text"] for w in col_words).strip()
    y_top = min(w["top"] for w in col_words)
    y_bot = max(w["bottom"] for w in col_words)

    # Must look like a question number
    if _is_question_number(token_text):
        return {"text": token_text, "y_top": y_top, "y_bot": y_bot}

    # Try individual words in case they're spaced apart (e.g. "1 (a)")
    combined = "".join(w["text"] for w in sorted(col_words, key=lambda w: w["x0"]))
    if _is_question_number(combined):
        return {"text": combined, "y_top": y_top, "y_bot": y_bot}

    return None


def _is_question_number(text: str) -> bool:
    """Check if text matches any question number pattern."""
    t = text.strip()
    return bool(
        RE_MAIN.match(t) or
        RE_SUB.match(t) or
        RE_SUBSUB.match(t) or
        RE_SUB_ALONE.match(t) or
        RE_SUBSUB_ALONE.match(t)
    )


def _classify_token(text: str, ctx: dict) -> tuple:
    """
    Classify question number token.
    Returns (question_number, level, parent_number).
    Updates ctx in place.
    """
    t = text.strip()

    # Full format: "1(a)(i)"
    m = RE_SUBSUB.match(t)
    if m:
        main, sub_l, subsub_l = m.group(1), f"({m.group(2).lower()})", f"({m.group(3).lower()})"
        ctx["main"] = main
        ctx["sub"]  = sub_l
        return f"{main}{sub_l}{subsub_l}", 2, f"{main}{sub_l}"

    # Format: "1(a)"
    m = RE_SUB.match(t)
    if m:
        main, sub_l = m.group(1), f"({m.group(2).lower()})"
        ctx["main"] = main
        ctx["sub"]  = sub_l
        return f"{main}{sub_l}", 1, main

    # Format: "1"
    m = RE_MAIN.match(t)
    if m:
        main = m.group(1)
        ctx["main"] = main
        ctx["sub"]  = None
        return main, 0, ""

    # Alone format: "(a)" — combine with last known main
    m = RE_SUB_ALONE.match(t)
    if m and ctx.get("main"):
        sub_l = f"({m.group(1).lower()})"
        ctx["sub"] = sub_l
        return f"{ctx['main']}{sub_l}", 1, ctx["main"]

    # Alone format: "(i)" — combine with last known main + sub
    m = RE_SUBSUB_ALONE.match(t)
    if m and ctx.get("main") and ctx.get("sub"):
        subsub_l = f"({m.group(1).lower()})"
        return f"{ctx['main']}{ctx['sub']}{subsub_l}", 2, f"{ctx['main']}{ctx['sub']}"

    return None, None, None


def _extract_marks_from_line(line: list) -> Optional[int]:
    """Find the marks number — typically rightmost numeric token on the line."""
    # Look for isolated numbers near right edge of page
    right_nums = [w for w in line if RE_MARKS_COL.match(w["text"].strip())]
    if right_nums:
        rightmost = max(right_nums, key=lambda w: w["x0"])
        try:
            val = int(rightmost["text"].strip())
            if 1 <= val <= 50:   # reasonable marks range
                return val
        except ValueError:
            pass
    return None


def _extract_marks_from_text(text: str) -> Optional[int]:
    """Fallback: extract marks from text content."""
    patterns = [
        re.compile(r'\[Total:\s*(\d+)\]', re.IGNORECASE),
        re.compile(r'\[(\d+)\s*marks?\]', re.IGNORECASE),
        re.compile(r'\[(\d+)\]'),
    ]
    for pat in patterns:
        m = pat.search(text)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
    return None