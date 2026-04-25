"""
core/marking_parser.py
=======================
Parses CIE marking scheme PDFs using table extraction with row merging.

FIX: Context and accumulation state now persist across pages.
If an answer table splits across pages without reprinting the question number,
the parser correctly appends the continuation text instead of dropping it.
"""

import re
import json
import logging
from typing import Optional, List, Dict, Any, Tuple

import pdfplumber

logger = logging.getLogger(__name__)

# ── Question number patterns ───────────────────────────────────────────────
RE_MAIN       = re.compile(r'^(\d{1,2})\.?$')
RE_SUB        = re.compile(r'^(\d{1,2})\(([a-z])\)$', re.IGNORECASE)
RE_SUBSUB     = re.compile(r'^(\d{1,2})\(([a-z])\)\((i{1,3}|iv|vi{0,3}|ix|x{1,3})\)$', re.IGNORECASE)

RE_SUB_ALONE  = re.compile(r'^\(([a-z])\)$', re.IGNORECASE)
RE_SUBSUB_ALONE = re.compile(r'^\((i{1,3}|iv|vi{0,3}|ix|x{1,3})\)$', re.IGNORECASE)

RE_MARKS_COL  = re.compile(r'^\d{1,3}$')


def parse_marking_scheme(filepath: str) -> List[Dict[str, Any]]:
    logger.info("Parsing marking scheme: %s", filepath)

    all_entries = []
    try:
        with pdfplumber.open(filepath) as pdf:
            ctx = {"main": None, "sub": None}
            
            # Persistent state across pages to handle table continuations
            current_q_num = None
            current_level = None
            current_parent = None
            answer_lines = []
            marks = None
            last_page_idx = len(pdf.pages) - 1

            for page_idx, page in enumerate(pdf.pages):
                entries, current_q_num, current_level, current_parent, answer_lines, marks = \
                    _parse_page_tables(
                        page, page_idx, ctx, 
                        current_q_num, current_level, current_parent, 
                        answer_lines, marks
                    )
                
                if not entries:
                    entries = _parse_page_lines(page, page_idx, ctx)
                all_entries.extend(entries)

            # Flush the very last accumulated question at the end of the document
            if current_q_num is not None:
                answer_text = "\n".join(answer_lines).strip()
                if answer_text:
                    if marks is None:
                        marks = _extract_marks_from_text(answer_text)
                    # Use last page dimensions as fallback
                    last_page = pdf.pages[last_page_idx]
                    all_entries.append({
                        "question_number": current_q_num,
                        "question_level":  current_level,
                        "parent_number":   current_parent,
                        "page_number":     last_page_idx,
                        "page_width":      last_page.width,
                        "page_height":     last_page.height,
                        "y_top":           0.0,
                        "bbox":            json.dumps({"x0": 0.0, "y0": 0.0, "x1": last_page.width, "y1": last_page.height}),
                        "bbox_full":       json.dumps({"x0": 0.0, "y0": 0.0, "x1": last_page.width, "y1": last_page.height}),
                        "text_content":    answer_text,
                        "marks":           marks,
                        "source_ref":      "",
                        "doc_type":        "marking_scheme",
                    })

        if not all_entries:
            logger.warning("No question entries found in marking scheme: %s", filepath)
            return []

        logger.info("Marking scheme parsed: %d entries", len(all_entries))
        return all_entries

    except Exception as e:
        logger.error("Failed to parse marking scheme %s: %s", filepath, e)
        raise


def _parse_page_tables(page, page_idx: int, ctx: dict,
                       current_q_num: Optional[str], current_level: Optional[int], 
                       current_parent: Optional[str], answer_lines: List[str], 
                       marks: Optional[int]) -> Tuple[List[Dict], Optional[str], Optional[int], Optional[str], List[str], Optional[int]]:
    """Parse tables on a single page, maintaining state from previous pages."""
    entries = []

    def _flush_current():
        nonlocal current_q_num, current_level, current_parent, answer_lines, marks
        if current_q_num is None:
            return None
        answer_text = "\n".join(answer_lines).strip()
        if not answer_text:
            # Reset state even if empty to prevent corrupt merging
            current_q_num = None
            current_level = None
            current_parent = None
            answer_lines = []
            marks = None
            return None
            
        if marks is None:
            marks = _extract_marks_from_text(answer_text)
        bbox = _estimate_row_bbox(page, current_q_num, answer_text)
        
        entry = {
            "question_number": current_q_num,
            "question_level":  current_level,
            "parent_number":   current_parent,
            "page_number":     page_idx,
            "page_width":      page.width,
            "page_height":     page.height,
            "y_top":           bbox["y0"],
            "bbox":            json.dumps(bbox),
            "bbox_full":       json.dumps(bbox),
            "text_content":    answer_text,
            "marks":           marks,
            "source_ref":      "",
            "doc_type":        "marking_scheme",
        }
        
        # Reset accumulation state
        current_q_num = None
        current_level = None
        current_parent = None
        answer_lines = []
        marks = None
        return entry

    q_col = None
    ans_col = None
    marks_col = None

    for strategy in ["lines", "text"]:
        try:
            tables = page.extract_tables({
                "vertical_strategy": strategy,
                "horizontal_strategy": strategy,
                "snap_tolerance": 3,
            })
        except Exception:
            continue

        for table in tables:
            if not table or len(table) < 1:
                continue

            header_idx = _find_header_row(table)
            
            # Determine columns
            if header_idx is not None:
                q_col = _find_column_index(table[header_idx], ["question", "q", "quest"])
                ans_col = _find_column_index(table[header_idx], ["answer", "response", "guidance"])
                marks_col = _find_column_index(table[header_idx], ["marks", "mark", "total"])
                if q_col is None:
                    continue
            else:
                # No header found. It might be a continuation table.
                if len(table[0]) >= 2:
                    q_col, ans_col, marks_col = 0, 1, (2 if len(table[0]) > 2 else None)
                else:
                    q_col, ans_col, marks_col = None, None, None

            for row_idx, row in enumerate(table):
                if header_idx is not None and row_idx <= header_idx:
                    continue

                if not row or all(cell is None or str(cell).strip() == "" for cell in row):
                    continue

                q_cell = row[q_col] if q_col is not None and q_col < len(row) else None
                q_text = str(q_cell).strip() if q_cell else ""

                if q_text and _is_question_number(q_text):
                    # Flush the PREVIOUS question before starting this one
                    entry = _flush_current()
                    if entry:
                        entries.append(entry)
                        
                    # Start accumulating new question
                    q_num, level, parent = _classify_question_number(q_text, ctx)
                    current_q_num = q_num
                    current_level = level
                    current_parent = parent
                    answer_lines = []
                    marks = None
                    
                    if marks_col is not None and marks_col < len(row):
                        marks_str = str(row[marks_col] or "").strip()
                        if RE_MARKS_COL.match(marks_str):
                            try:
                                marks = int(marks_str)
                            except ValueError:
                                pass

                # Accumulate answer text
                if ans_col is not None and ans_col < len(row):
                    ans_text = str(row[ans_col] or "").strip()
                    if ans_text:
                        answer_lines.append(ans_text)
                elif current_q_num is not None:
                    row_text = " ".join(str(cell) for cell in row if cell).strip()
                    if row_text:
                        answer_lines.append(row_text)

        if entries:
            break

    # NOTE: We DO NOT flush current_q_num here. If a table splits across pages,
    # the next page will continue appending to answer_lines.
    return entries, current_q_num, current_level, current_parent, answer_lines, marks


def _parse_page_lines(page, page_idx: int, ctx: dict) -> List[Dict[str, Any]]:
    """Fallback: scan plain text lines for question markers."""
    text = page.extract_text()
    if not text:
        return []

    lines = text.split('\n')
    entries = []
    for line in lines:
        line = line.strip()
        if not line:
            continue

        match = None
        for pattern in [RE_SUBSUB, RE_SUB, RE_MAIN, RE_SUB_ALONE, RE_SUBSUB_ALONE]:
            match = pattern.search(line)
            if match:
                break
        if not match:
            continue

        token = match.group(0)
        q_num, level, parent = _classify_question_number(token, ctx)
        if q_num is None:
            continue

        remaining = line[match.end():].strip()
        marks = _extract_marks_from_text(remaining)
        bbox = _estimate_row_bbox(page, token, remaining)

        entries.append({
            "question_number": q_num,
            "question_level":  level,
            "parent_number":   parent,
            "page_number":     page_idx,
            "page_width":      page.width,
            "page_height":     page.height,
            "y_top":           bbox["y0"],
            "bbox":            json.dumps(bbox),
            "bbox_full":       json.dumps(bbox),
            "text_content":    remaining,
            "marks":           marks,
            "source_ref":      "",
            "doc_type":        "marking_scheme",
        })

    return entries


def _find_header_row(table: List[List]) -> Optional[int]:
    for i, row in enumerate(table):
        if not row:
            continue
        row_lower = [str(cell).lower() for cell in row if cell]
        if any("question" in cell for cell in row_lower) and any("answer" in cell for cell in row_lower):
            return i
    return None


def _find_column_index(header_row: List, keywords: List[str]) -> Optional[int]:
    for i, cell in enumerate(header_row):
        if cell is None:
            continue
        cell_lower = str(cell).lower()
        if any(kw in cell_lower for kw in keywords):
            return i
    return None


def _is_question_number(text: str) -> bool:
    t = text.strip()
    return bool(
        RE_MAIN.match(t) or
        RE_SUB.match(t) or
        RE_SUBSUB.match(t) or
        RE_SUB_ALONE.match(t) or
        RE_SUBSUB_ALONE.match(t)
    )


def _classify_question_number(text: str, ctx: dict):
    t = text.strip()

    m = RE_SUBSUB.match(t)
    if m:
        main, sub_l, subsub_l = m.group(1), f"({m.group(2).lower()})", f"({m.group(3).lower()})"
        ctx["main"] = main
        ctx["sub"]  = sub_l
        return f"{main}{sub_l}{subsub_l}", 2, f"{main}{sub_l}"

    m = RE_SUB.match(t)
    if m:
        main, sub_l = m.group(1), f"({m.group(2).lower()})"
        ctx["main"] = main
        ctx["sub"]  = sub_l
        return f"{main}{sub_l}", 1, main

    m = RE_MAIN.match(t)
    if m:
        main = m.group(1)
        ctx["main"] = main
        ctx["sub"]  = None
        return main, 0, ""

    m = re.match(r'^\(([a-z])\)$', t, re.IGNORECASE)
    if m and ctx.get("main"):
        sub_l = f"({m.group(1).lower()})"
        ctx["sub"] = sub_l
        return f"{ctx['main']}{sub_l}", 1, ctx["main"]

    m = re.match(r'^\((i{1,3}|iv|vi{0,3}|ix|x{1,3})\)$', t, re.IGNORECASE)
    if m and ctx.get("main") and ctx.get("sub"):
        subsub_l = f"({m.group(1).lower()})"
        return f"{ctx['main']}{ctx['sub']}{subsub_l}", 2, f"{ctx['main']}{ctx['sub']}"

    return None, None, None


def _estimate_row_bbox(page, question_text: str, answer_text: str) -> Dict[str, float]:
    words = page.extract_words()
    for w in words:
        if question_text in w["text"]:
            return {
                "x0": 0.0,
                "y0": w["top"] - 2,
                "x1": page.width,
                "y1": w["bottom"] + 50,
            }
    return {
        "x0": 0.0,
        "y0": 0.0,
        "x1": page.width,
        "y1": 100.0,
    }


def _extract_marks_from_text(text: str) -> Optional[int]:
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