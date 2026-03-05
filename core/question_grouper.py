"""
core/question_grouper.py
=========================
Groups flat DB rows into display cards based on depth mode.

MULTI-PAGE GROUPING (key feature added):
=========================================
CIE questions regularly span 2+ pages:
  Q1 (a)(b) on page 2,  Q1 (c) on page 3  → ONE card for Q1 (not two)
  Q4 (a)(b)(c) on page 6, Q4 (d)(e)(f) on page 7 → ONE card for Q4

When a question spans pages, we:
  1. Collect bboxes for each page segment
  2. Render each page segment separately
  3. Stitch them vertically into one tall image at display time

Each grouped card carries:
  _page_segments: [
    {"page_number": 2, "bbox": {...}, "filepath": "..."},
    {"page_number": 3, "bbox": {...}, "filepath": "..."},
  ]

The renderer (question_extractor.py) handles multi-page stitching.

DEPTH MODE RULES:
=================
  None  → flat, every DB row its own card
  0     → one card per MAIN question (merges ALL pages) ← NEW
  1     → one card per SUB-QUESTION (a,b,c) per page, (i)(ii)(iii) merged inside
  2     → one card per SUB-SUB (i)(ii)(iii), individual tight bbox + sibling context
"""

import json
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Number parsing ───────────────────────────────────────────────────────────

def _parts(qnum: str) -> list:
    return re.findall(r'\d+|\([a-zA-Z]+\)', qnum)

def get_main_number(qnum: str) -> str:
    p = _parts(qnum)
    return p[0] if p else qnum

def get_sub_number(qnum: str) -> str:
    p = _parts(qnum)
    return "".join(p[:2]) if len(p) >= 2 else qnum

def get_label_only(qnum: str) -> str:
    p = _parts(qnum)
    return p[-1] if p else qnum


# ─── BBox helpers ─────────────────────────────────────────────────────────────

def _parse_bbox(s: str) -> Optional[dict]:
    if not s:
        return None
    try:
        b = json.loads(s)
        if not b or b.get("y1", 0) == 0:
            return None
        return b
    except Exception:
        return None

def _merge_bboxes(rows: list) -> dict:
    bboxes = [_parse_bbox(r.get("bbox", "")) for r in rows]
    bboxes = [b for b in bboxes if b]
    if not bboxes:
        return {"x0": 0, "y0": 0, "x1": 595, "y1": 842}
    return {
        "x0": 0,
        "y0": min(b["y0"] for b in bboxes),
        "x1": max(b["x1"] for b in bboxes),
        "y1": max(b["y1"] for b in bboxes),
    }

def _best_bbox(rep_row: dict, sibling_rows: list) -> dict:
    b = _parse_bbox(rep_row.get("bbox_full", ""))
    if b:
        return b
    return _merge_bboxes(sibling_rows)


# ─── Main entry point ─────────────────────────────────────────────────────────

def group_questions_by_depth(rows: list, depth_mode: Optional[int]) -> list:
    if not rows:
        return []
    if depth_mode is None:
        return rows
    if depth_mode == 0:
        return _group_main(rows)
    if depth_mode == 1:
        return _group_sub(rows)
    if depth_mode == 2:
        return _group_subsub(rows)
    return rows


# ─── Lookup builder ───────────────────────────────────────────────────────────

def _build_lookup(rows):
    by_main    = {}   # (doc_id, main_num, page) -> [rows]
    by_sub     = {}   # (doc_id, sub_num,  page) -> [rows]
    main_pages = {}   # (doc_id, main_num)       -> sorted list of pages
    sub_pages  = {}   # (doc_id, sub_num)        -> sorted list of pages

    for r in rows:
        qn  = r["question_number"]
        doc = r["doc_id"]
        pg  = r["page_number"]
        mn  = get_main_number(qn)
        sn  = get_sub_number(qn)

        by_main.setdefault((doc, mn, pg), []).append(r)
        by_sub.setdefault((doc, sn, pg), []).append(r)
        main_pages.setdefault((doc, mn), set()).add(pg)
        sub_pages.setdefault((doc, sn), set()).add(pg)

    # Convert sets to sorted lists
    main_pages = {k: sorted(v) for k, v in main_pages.items()}
    sub_pages  = {k: sorted(v) for k, v in sub_pages.items()}

    return by_main, by_sub, main_pages, sub_pages


# ─── depth_mode=0: Main questions (MULTI-PAGE AWARE) ─────────────────────────

def _group_main(rows: list) -> list:
    """
    ONE card per main question, merging ALL pages it spans.

    Example — Q1 on pages 2 and 3:
      - Collects all Q1 rows from page 2 AND page 3
      - Computes bbox_for_each_page:
          page 2: covers (a)(b) region
          page 3: covers (c) region
      - Stores as _page_segments = [
            {"page_number":2, "bbox":{...}, "filepath":"..."},
            {"page_number":3, "bbox":{...}, "filepath":"..."},
        ]
      - Renderer stitches both page images vertically → ONE tall preview image

    The _page_segments list is what the renderer uses.
    The card's "bbox" field holds the FIRST page's bbox (for backward compat).
    """
    by_main, _, main_pages, _ = _build_lookup(rows)

    seen   = set()
    result = []

    for r in rows:
        if r.get("question_level", 0) != 0:
            continue
        doc  = r["doc_id"]
        main = get_main_number(r["question_number"])
        key  = (doc, main)

        if key in seen:
            continue
        seen.add(key)

        # All pages this question appears on, in order
        pages = main_pages.get(key, [r["page_number"]])

        # Build per-page segments: each has a bbox covering all Q content on that page
        page_segments = []
        for pg in pages:
            pg_key     = (doc, main, pg)
            pg_rows    = by_main.get(pg_key, [])
            if not pg_rows:
                continue

            # Rep row for this page = the level-0 row if available, else first row
            pg_rep = next(
                (x for x in pg_rows if x.get("question_level", 0) == 0),
                pg_rows[0]
            )
            pg_bbox = _best_bbox(pg_rep, pg_rows)

            page_segments.append({
                "page_number": pg,
                "bbox":        pg_bbox,
                "filepath":    pg_rep["filepath"],
            })

        if not page_segments:
            continue

        # All rows across all pages for this question
        all_rows = []
        for pg in pages:
            all_rows.extend(by_main.get((doc, main, pg), []))

        # Sub-question labels in document order
        sub_labels = _ordered_unique([
            get_label_only(x["question_number"])
            for x in all_rows
            if x.get("question_level", 0) == 1
        ])
        sub_summary = " ".join(sub_labels)

        all_text = _join_text(all_rows)

        # Use first page's rep row as the base record
        first_pg     = pages[0]
        first_pg_key = (doc, main, first_pg)
        first_rows   = by_main.get(first_pg_key, [r])
        rep          = next(
            (x for x in first_rows if x.get("question_level", 0) == 0),
            first_rows[0]
        )

        is_multipage = len(pages) > 1
        display      = str(main)

        result.append({
            **rep,
            "question_number":  display,
            "question_level":   0,
            # bbox = first page bbox (for single-page fallback)
            "bbox":             json.dumps(page_segments[0]["bbox"]),
            "text_content":     all_text,
            "_sub_summary":     sub_summary,
            "_is_continuation": False,
            "_segment_count":   len(all_rows),
            # KEY: multi-page rendering data
            "_page_segments":   page_segments,
            "_is_multipage":    is_multipage,
            "_page_count":      len(pages),
        })

    return result


# ─── depth_mode=1: Sub-questions ─────────────────────────────────────────────

def _group_sub(rows: list) -> list:
    """
    One card per sub-question (a,b,c) per page.
    bbox_full covers the (a)/(b)/(c) block including all its (i)(ii)(iii).
    """
    _, by_sub, _, sub_pages = _build_lookup(rows)

    level1_rows = [r for r in rows if r.get("question_level", 0) == 1]
    if not level1_rows:
        logger.warning("No level-1 rows, falling back to main grouping")
        return _group_main(rows)

    seen   = set()
    result = []

    for r in rows:
        if r.get("question_level", 0) != 1:
            continue
        doc = r["doc_id"]
        pg  = r["page_number"]
        sub = get_sub_number(r["question_number"])
        key = (doc, sub, pg)
        if key in seen:
            continue
        seen.add(key)

        siblings = by_sub.get(key, [r])
        bbox     = _best_bbox(r, siblings)

        subsub_labels = _ordered_unique([
            get_label_only(s["question_number"])
            for s in siblings
            if s.get("question_level", 0) == 2
        ])
        subsub_summary = " ".join(subsub_labels)

        all_text = _join_text(siblings)

        marks_list = [s["marks"] for s in siblings
                      if s.get("question_level", 0) == 2 and s.get("marks")]
        total_marks = sum(marks_list) if marks_list else r.get("marks")

        all_pgs = sub_pages.get((doc, sub), [pg])
        is_cont = len(all_pgs) > 1 and pg != min(all_pgs)
        display = f"{sub} (cont.)" if is_cont else sub

        result.append({
            **r,
            "question_number":  display,
            "question_level":   1,
            "bbox":             json.dumps(bbox),
            "text_content":     all_text,
            "marks":            total_marks,
            "_sub_summary":     subsub_summary,
            "_is_continuation": is_cont,
            "_segment_count":   len(siblings),
            "_page_segments":   [{"page_number": pg, "bbox": bbox, "filepath": r["filepath"]}],
            "_is_multipage":    False,
        })

    return result


# ─── depth_mode=2: Sub-sub questions ─────────────────────────────────────────

def _group_subsub(rows: list) -> list:
    """
    One card per (i)(ii)(iii), tight bbox, with sibling context shown.
    """
    sibling_map = {}
    sub_pages   = {}

    for r in rows:
        if r.get("question_level", 0) != 2:
            continue
        doc = r["doc_id"]
        sub = get_sub_number(r["question_number"])
        key = (doc, sub)
        sibling_map.setdefault(key, []).append(r)
        sub_pages.setdefault(key, set()).add(r["page_number"])

    level2_rows = [r for r in rows if r.get("question_level", 0) == 2]
    if not level2_rows:
        logger.warning("No level-2 rows for sub-sub mode")
        return rows

    result = []
    for r in level2_rows:
        doc   = r["doc_id"]
        qnum  = r["question_number"]
        sub   = get_sub_number(qnum)
        label = get_label_only(qnum)
        main  = get_main_number(qnum)

        all_siblings   = sibling_map.get((doc, sub), [r])
        sibling_labels = _ordered_unique([get_label_only(s["question_number"])
                                          for s in all_siblings])
        highlighted    = [f"[{lbl}]" if lbl == label else lbl
                          for lbl in sibling_labels]
        sibling_str    = " ".join(highlighted)

        sub_summary = f"{sub}  →  {sibling_str}"

        all_pgs = sub_pages.get((doc, sub), {r["page_number"]})
        is_cont = len(all_pgs) > 1 and r["page_number"] != min(all_pgs)
        display = f"{qnum} (cont.)" if is_cont else qnum

        bbox = _parse_bbox(r.get("bbox", "")) or {"x0": 0, "y0": 0, "x1": 595, "y1": 842}

        result.append({
            **r,
            "question_number":  display,
            "question_level":   2,
            "bbox":             r["bbox"],
            "_sub_summary":     sub_summary,
            "_is_continuation": is_cont,
            "_segment_count":   1,
            "_parent_sub":      sub,
            "_parent_main":     main,
            "_page_segments":   [{"page_number": r["page_number"],
                                  "bbox":        bbox,
                                  "filepath":    r["filepath"]}],
            "_is_multipage":    False,
        })

    return result


# ─── Utilities ────────────────────────────────────────────────────────────────

def _ordered_unique(items: list) -> list:
    seen = set()
    out  = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def _join_text(rows: list) -> str:
    return "\n".join(r["text_content"] for r in rows if r.get("text_content"))