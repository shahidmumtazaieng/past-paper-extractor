"""
core/pdf_parser.py
===================
Parses CIE / Cambridge past paper PDFs.

STRICT FOCUS (AS REQUESTED):
============================
- Level 0: Main questions ("1", "2", "3")
- Level 1: Sub-questions ("(a)", "(b)", "(c)")
- Level 2 (i, ii, iii) is 100% REMOVED to prevent context corruption.

ANTI-FALSE-POSITIVE PROTECTION:
================================
Main question numbers MUST have letters on the same line. 
This prevents stop-clock numbers ("0", "10", "30") and table data 
from being mistaken for Question 0 or Question 30, which was causing 
the page-boundary math to cut your questions short.
"""

import re
import json
import logging
from typing import Optional
import pdfplumber

logger = logging.getLogger(__name__)

# ─── Indent thresholds ────────────────────────────────────────────────────────
MAIN_Q_MAX_X = 65

# ─── Regex patterns ───────────────────────────────────────────────────────────
RE_MAIN      = re.compile(r"^(\d{1,2})\.?$")
RE_SUB_PAREN = re.compile(r"^\(([a-z])\)$", re.IGNORECASE)
RE_MARKS     = re.compile(r"\[(\d{1,2})\s*(?:marks?)?\]", re.IGNORECASE)


# ─── Single-word classifier ───────────────────────────────────────────────────

def _classify_word(word: dict, all_words: list) -> Optional[dict]:
    """
    Returns classification dict if this word is a question marker, else None.
    """
    text = word["text"].strip()
    x0   = word["x0"]
    ytop = word["top"]
    ybot = word["bottom"]

    # Level 1 — sub-question (a)(b)(c)... Pattern matches first, ignores X0.
    if RE_SUB_PAREN.match(text):
        return {"level": 1, "label": f"({text.lower()})",
                "x0": x0, "y_top": ytop, "y_bottom": ybot}

    # Level 0 — main question "1", "2"
    if x0 <= MAIN_Q_MAX_X and RE_MAIN.match(text):
        # CRITICAL SAFETY CHECK: Stop clocks and tables have isolated numbers.
        # Real question headers have letters on the same line (e.g., "2 A student...")
        has_letters_on_line = False
        for w in all_words:
            if w is word: continue
            if abs(w["top"] - ytop) <= 5:  # Same line (within 5 pts)
                if re.search(r'[a-zA-Z]', w["text"]):
                    has_letters_on_line = True
                    break
        
        if has_letters_on_line:
            return {"level": 0, "label": RE_MAIN.match(text).group(1),
                    "x0": x0, "y_top": ytop, "y_bottom": ybot}

    return None


# ─── Context tracker ─────────────────────────────────────────────────────────

def _build_full_number(marker: dict, ctx: dict) -> str:
    if marker["level"] == 0:
        ctx.update({"main": marker["label"], "sub": None})
        return marker["label"]
    else:
        ctx["sub"] = marker["label"]
        return f"{ctx.get('main','?')}{marker['label']}"


# ─── Main parse entry point ───────────────────────────────────────────────────

def parse_questions_from_pdf(filepath: str) -> list[dict]:
    questions = []
    ctx = {"main": None, "sub": None}

    logger.info("Parsing: %s", filepath)
    try:
        with pdfplumber.open(filepath) as pdf:
            all_pages_markers = []

            for page_idx, page in enumerate(pdf.pages):
                page_markers = _collect_page_markers(page, page_idx, ctx)
                all_pages_markers.extend(page_markers)

            _assign_individual_bboxes(all_pages_markers)
            _assign_full_bboxes(all_pages_markers)

            for m in all_pages_markers:
                page = pdf.pages[m["page_number"]]
                bbox = json.loads(m["bbox"])
                try:
                    region = page.within_bbox((bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"]))
                    text = region.extract_text() or ""
                except Exception:
                    text = ""
                m["text_content"] = text.strip()
                m["marks"]        = _extract_marks(text)

            questions = all_pages_markers

    except Exception as e:
        logger.error("Failed to parse %s: %s", filepath, e)
        raise

    logger.info("Found %d segments in %s", len(questions), filepath)
    return questions


def _collect_page_markers(page, page_idx: int, ctx: dict) -> list[dict]:
    words = page.extract_words(
        x_tolerance=3, y_tolerance=3,
        keep_blank_chars=False, use_text_flow=False,
    )
    if not words:
        return []

    # Pass all_words to classifier so it can check for letters on the same line
    raw = []
    for word in words:
        c = _classify_word(word, words)
        if c:
            raw.append(c)

    seen, deduped = set(), []
    for m in raw:
        key = (m["level"], m["label"], round(m["y_top"]))
        if key not in seen:
            seen.add(key)
            deduped.append(m)

    deduped.sort(key=lambda m: m["y_top"])

    result = []
    for m in deduped:
        full_num = _build_full_number(m, ctx)
        parent = ctx.get("main", "") if m["level"] == 1 else ""

        result.append({
            "question_number": full_num,
            "question_level":  m["level"],
            "parent_number":   parent,
            "page_number":     page_idx,
            "page_width":      page.width,
            "page_height":     page.height,
            "y_top":           m["y_top"],
            "bbox": "", "bbox_full": "", "text_content": "", "marks": None,
        })
    return result


def _assign_individual_bboxes(markers: list[dict]):
    for i, m in enumerate(markers):
        y_start = max(0.0, m["y_top"] - 4)
        y_end = m["page_height"]
        for j in range(i + 1, len(markers)):
            if markers[j]["page_number"] == m["page_number"]:
                y_end = markers[j]["y_top"] - 4
                break
        m["bbox"] = json.dumps({
            "x0": 0.0, "y0": y_start,
            "x1": m["page_width"], "y1": min(m["page_height"], y_end),
        })


def _assign_full_bboxes(markers: list[dict]):
    n = len(markers)
    for i, m in enumerate(markers):
        current_level = m["question_level"]
        y_end = m["page_height"]

        for j in range(i + 1, n):
            nxt = markers[j]
            if nxt["question_level"] <= current_level:
                y_end = nxt["y_top"] - 4 if nxt["page_number"] == m["page_number"] else m["page_height"]
                break

        y_start = max(0.0, m["y_top"] - 4)
        m["bbox_full"] = json.dumps({
            "x0": 0.0, "y0": y_start,
            "x1": m["page_width"], "y1": min(m["page_height"], y_end),
        })


def _extract_marks(text: str) -> Optional[int]:
    total = re.search(r"\[Total:\s*(\d+)\]", text, re.IGNORECASE)
    if total: return int(total.group(1))
    m = RE_MARKS.search(text)
    return int(m.group(1)) if m else None


def get_page_count(filepath: str) -> int:
    with pdfplumber.open(filepath) as pdf:
        return len(pdf.pages)