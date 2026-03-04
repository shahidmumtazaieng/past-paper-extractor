"""
core/pdf_parser.py
===================
Parses CIE / Cambridge past paper PDFs to detect ALL question levels.

KEY DESIGN — LEARNED FROM REAL CIE CHEMISTRY/PHYSICS PAPERS:
=============================================================

Example from 0620_s23_qp_41 (Chemistry):

  Page 2:
    1   [main]  "Some symbol equations..."
      (a)  "a neutralisation reaction"          [1]
      (b)  "a precipitation reaction"           [1]
      (c)  "the formation of an ester"          [1]
      (d)  "photosynthesis"                     [1]
      (e)  "fermentation"                       [1]
      (f)  "cracking"                           [1]
                                          [Total: 6]

  Page 3:
    2   [main]  "The symbols of the elements..."
      (a) [sub]
        (i)   "makes up approximately 78%..."   [1]
        (ii)  "contains atoms with only..."     [1]
        (iii) "contains atoms with only..."     [1]
        (iv)  "exists as graphite"              [1]
        (v)   "is an alkali metal"              [1]
        (vi)  "only has an oxidation..."        [1]
      (b) [sub]  "Boron, B, has two isotopes"
        (i)   "State the meaning..."            [2]
        (ii)  "Table 2.1 shows..."              [2]

WHAT THE USER WANTS:
====================

  "Main only (1,2,3...)"
  → Give FULL question 1 as ONE image block
    = from "1 Some symbol equations..." all the way through "(f) cracking [1]"
    = the COMPLETE question including ALL sub-parts

  "Sub-questions (a,b,c)"
  → Give each (a)(b)(c) as its own image block
    = 2(a) = from "(a) Give the symbol..." through "(vi) only has..."
    = 2(b) = from "(b) Boron..." through "(ii) Table 2.1..."
    (each sub includes its own sub-sub parts)

  "Sub-sub (i,ii,iii)"
  → Give each (i)(ii)(iii) as its own tiny image block

STORAGE STRATEGY:
=================
We store EVERY marker (all 3 levels) in the DB with individual bboxes.
At QUERY TIME, when user selects "Main only", we MERGE the bboxes of all
children back into the parent's bbox, so the exported image captures
the complete question.

This is better than storing merged bboxes at parse time because:
- We can always go from merged → split (just query sub-level)
- We cannot go from split → merged without the parent info
- Storage is cheap; computation at query time is fast

The DB stores question_level so the query layer knows how to merge.
"""

import re
import json
import logging
from typing import Optional
import pdfplumber

logger = logging.getLogger(__name__)

# ─── Indent thresholds (PDF points from left edge) ───────────────────────────
# Calibrated from real CIE A4 papers (page width ~595 pts).
# These represent the LEFT EDGE (x0) of the marker token.
#
# CIE standard layout (measured from screenshots):
#   Main "1"     → x0 ≈ 36–55 pts
#   Sub  "(a)"   → x0 ≈ 56–100 pts
#   Sub  "(b)"   → same range
#   Subsub "(i)" → x0 ≈ 101–165 pts
#
MAIN_Q_MAX_X   = 65     # anything left of this = main question
SUB_Q_MAX_X    = 115    # between MAIN_Q_MAX_X and this = sub (a)(b)(c)
SUBSUB_Q_MAX_X = 180    # between SUB_Q_MAX_X and this = subsub (i)(ii)(iii)

# ─── Regex patterns ───────────────────────────────────────────────────────────

RE_MAIN          = re.compile(r"^(\d{1,2})\.?$")
RE_MAIN_Q        = re.compile(r"^[Qq](\d{1,2})\.?$")
RE_SUB_PAREN     = re.compile(r"^\(([a-z])\)$",                         re.IGNORECASE)
RE_SUB_BARE      = re.compile(r"^([a-hj-z])$")          # bare letter, NOT i (avoids roman numeral clash)
RE_SUBSUB_ROMAN  = re.compile(r"^\((i{1,3}|iv|vi{0,3}|ix|xi{0,3}|x)\)$", re.IGNORECASE)
RE_SUBSUB_BARE   = re.compile(r"^(i{1,3}|iv|vi{0,3}|ix|xi{0,3}|x)$",    re.IGNORECASE)
RE_MARKS         = re.compile(r"\[(\d{1,2})\s*(?:marks?)?\]",            re.IGNORECASE)


# ─── Single-word classifier ───────────────────────────────────────────────────

def _classify_word(word: dict) -> Optional[dict]:
    """
    Returns classification dict if this word is a question marker, else None.
    """
    text = word["text"].strip()
    x0   = word["x0"]
    ytop = word["top"]
    ybot = word["bottom"]

    # Level 0 — main question
    if x0 <= MAIN_Q_MAX_X:
        if RE_MAIN.match(text):
            return {"level": 0, "label": RE_MAIN.match(text).group(1),
                    "x0": x0, "y_top": ytop, "y_bottom": ybot}
        if RE_MAIN_Q.match(text):
            return {"level": 0, "label": RE_MAIN_Q.match(text).group(1),
                    "x0": x0, "y_top": ytop, "y_bottom": ybot}

    # Level 1 — sub-question (a)(b)(c)
    if MAIN_Q_MAX_X < x0 <= SUB_Q_MAX_X:
        if RE_SUB_PAREN.match(text):
            return {"level": 1, "label": text,
                    "x0": x0, "y_top": ytop, "y_bottom": ybot}
        if RE_SUB_BARE.match(text):
            return {"level": 1, "label": f"({text.lower()})",
                    "x0": x0, "y_top": ytop, "y_bottom": ybot}

    # Level 2 — sub-sub-question (i)(ii)(iii)
    if SUB_Q_MAX_X < x0 <= SUBSUB_Q_MAX_X:
        if RE_SUBSUB_ROMAN.match(text):
            return {"level": 2, "label": text,
                    "x0": x0, "y_top": ytop, "y_bottom": ybot}
        if RE_SUBSUB_BARE.match(text):
            return {"level": 2, "label": f"({text.lower()})",
                    "x0": x0, "y_top": ytop, "y_bottom": ybot}

    return None


# ─── Context tracker ─────────────────────────────────────────────────────────

def _build_full_number(marker: dict, ctx: dict) -> str:
    """Build canonical question number and update context."""
    if marker["level"] == 0:
        ctx.update({"main": marker["label"], "sub": None, "subsub": None})
        return marker["label"]
    elif marker["level"] == 1:
        ctx.update({"sub": marker["label"], "subsub": None})
        return f"{ctx.get('main','?')}{marker['label']}"
    else:
        ctx["subsub"] = marker["label"]
        return f"{ctx.get('main','?')}{ctx.get('sub','(?)')}{marker['label']}"


# ─── Main parse entry point ───────────────────────────────────────────────────

def parse_questions_from_pdf(filepath: str) -> list[dict]:
    """
    Parse ALL question markers from a PDF.

    Returns list of dicts — one per detected marker at any level:
    {
        question_number : str   — "1", "1(a)", "1(a)(i)"
        question_level  : int   — 0=main, 1=sub, 2=subsub
        parent_number   : str   — parent q number (for merge logic), or ""
        page_number     : int   — 0-indexed
        bbox            : str   — JSON {"x0","y0","x1","y1"}  ← INDIVIDUAL bbox only
        bbox_full       : str   — JSON bbox spanning this + ALL children on same page
                                  (pre-computed for "Main only" query mode)
        text_content    : str
        marks           : int|None
    }

    bbox_full is what gets used when user selects "Main only".
    bbox      is what gets used when user selects sub or subsub level.
    """
    questions = []
    ctx = {"main": None, "sub": None, "subsub": None}

    logger.info("Parsing: %s", filepath)
    try:
        with pdfplumber.open(filepath) as pdf:
            all_pages_markers = []

            # ── Pass 1: collect every marker across all pages ──────────────
            for page_idx, page in enumerate(pdf.pages):
                page_markers = _collect_page_markers(page, page_idx, ctx)
                all_pages_markers.extend(page_markers)

            # ── Pass 2: compute individual bboxes ─────────────────────────
            _assign_individual_bboxes(all_pages_markers)

            # ── Pass 3: compute full (collapsed) bboxes ───────────────────
            # For each main question, extend its bbox_full to cover ALL
            # its children across potentially multiple pages.
            _assign_full_bboxes(all_pages_markers)

            # ── Pass 4: extract text and marks for each segment ───────────
            for m in all_pages_markers:
                page  = pdf.pages[m["page_number"]]
                bbox  = json.loads(m["bbox"])
                try:
                    region = page.within_bbox(
                        (bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])
                    )
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
    """Collect and classify all markers on one page. Mutates ctx."""
    words = page.extract_words(
        x_tolerance=3, y_tolerance=3,
        keep_blank_chars=False, use_text_flow=False,
    )
    if not words:
        return []

    raw = []
    for word in words:
        c = _classify_word(word)
        if c:
            raw.append(c)

    # Deduplicate by (level, label, rounded_y)
    seen, deduped = set(), []
    for m in raw:
        key = (m["level"], m["label"], round(m["y_top"]))
        if key not in seen:
            seen.add(key)
            deduped.append(m)

    deduped.sort(key=lambda m: m["y_top"])

    # Annotate with full question number and parent
    result = []
    for m in deduped:
        full_num = _build_full_number(m, ctx)
        # Determine parent number
        if m["level"] == 0:
            parent = ""
        elif m["level"] == 1:
            parent = ctx.get("main", "")
        else:
            parent = f"{ctx.get('main','')}{ctx.get('sub','')}"

        result.append({
            "question_number": full_num,
            "question_level":  m["level"],
            "parent_number":   parent,
            "page_number":     page_idx,
            "page_width":      page.width,
            "page_height":     page.height,
            "y_top":           m["y_top"],
            # placeholders — filled in later passes
            "bbox":            "",
            "bbox_full":       "",
            "text_content":    "",
            "marks":           None,
        })
    return result


def _assign_individual_bboxes(markers: list[dict]):
    """
    For each marker, bbox = from its y_top to the y_top of the NEXT marker
    on the SAME page, or page bottom.
    This gives the tight individual segment.
    """
    for i, m in enumerate(markers):
        y_start = max(0.0, m["y_top"] - 4)

        # Find next marker on same page
        y_end = m["page_height"]
        for j in range(i + 1, len(markers)):
            if markers[j]["page_number"] == m["page_number"]:
                y_end = markers[j]["y_top"] - 4
                break

        m["bbox"] = json.dumps({
            "x0": 0.0,
            "y0": y_start,
            "x1": m["page_width"],
            "y1": min(m["page_height"], y_end),
        })


def _assign_full_bboxes(markers: list[dict]):
    """
    For each marker, bbox_full = from its y_top to the y_top of the next
    marker at THE SAME OR HIGHER level (i.e., same level or parent level).

    This means:
      - For main Q "1": bbox_full covers everything until Q "2" starts
        (swallows all (a)(b)(c)(i)(ii)(iii) inside)
      - For sub "(a)": bbox_full covers until next "(b)" or next main Q
        (swallows all (i)(ii)(iii) inside)
      - For subsub "(i)": bbox_full == bbox (no children possible)

    Cross-page: if question 1 starts on page 2 and ends on page 3,
    bbox_full will point to the LAST page's boundary. We store this
    as a multi-page span using bbox_full_end_page + bbox_full_y1.
    For rendering simplicity, bbox_full captures the FULL vertical span
    on the START page only (most questions fit on one page).
    For questions spanning pages, we store them as separate page segments.
    """
    n = len(markers)
    for i, m in enumerate(markers):
        current_level = m["question_level"]

        # Find next marker at same level or higher (lower level number)
        y_end        = m["page_height"]
        end_page     = m["page_number"]

        for j in range(i + 1, n):
            nxt = markers[j]
            if nxt["question_level"] <= current_level:
                # This is a sibling or parent — current question ends here
                if nxt["page_number"] == m["page_number"]:
                    y_end = nxt["y_top"] - 4
                else:
                    # Sibling is on next page → our question goes to bottom of current page
                    y_end = m["page_height"]
                end_page = nxt["page_number"]
                break

        y_start = max(0.0, m["y_top"] - 4)

        m["bbox_full"] = json.dumps({
            "x0": 0.0,
            "y0": y_start,
            "x1": m["page_width"],
            "y1": min(m["page_height"], y_end),
        })


def _extract_marks(text: str) -> Optional[int]:
    """Detect total marks from text. e.g. '[Total: 6]' → 6, '[2]' → 2"""
    # Prefer [Total: N] first
    total = re.search(r"\[Total:\s*(\d+)\]", text, re.IGNORECASE)
    if total:
        return int(total.group(1))
    m = RE_MARKS.search(text)
    if m:
        return int(m.group(1))
    return None


def get_page_count(filepath: str) -> int:
    with pdfplumber.open(filepath) as pdf:
        return len(pdf.pages)