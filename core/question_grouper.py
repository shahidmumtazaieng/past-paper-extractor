"""
core/question_grouper.py
=========================
Groups flat DB rows into display cards based on depth mode.

PATTERNS FROM REAL CIE PAPERS (Chemistry 0620, Physics 5054):
==============================================================

Sub-question mode output for Q2:
  Card 1: "2(a)"  → image shows 2(a) + (i)(ii)(iii)(iv)(v)(vi) merged
                    badge shows: "Includes: (i) (ii) (iii) (iv) (v) (vi)"
  Card 2: "2(b)"  → image shows 2(b) + (i)(ii) merged
                    badge shows: "Includes: (i) (ii)"

Main question mode output:
  Card 1: "2"     → image shows entire Q2 from start to Q3 start
                    badge shows: "Contains: (a) (b)"

ORDERING GUARANTEE:
===================
DB rows fetched by q.id (insertion order = document top-to-bottom order).
Grouper walks rows in that order → cards always appear in document order.
"""

import json
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Number parsing ───────────────────────────────────────────────────────────

def _parts(qnum: str) -> list:
    """'1(a)(i)' -> ['1','(a)','(i)'],  '2(b)' -> ['2','(b)'],  '3' -> ['3']"""
    return re.findall(r'\d+|\([a-zA-Z]+\)', qnum)


def get_main_number(qnum: str) -> str:
    p = _parts(qnum)
    return p[0] if p else qnum


def get_sub_number(qnum: str) -> str:
    p = _parts(qnum)
    return "".join(p[:2]) if len(p) >= 2 else qnum


def get_label_only(qnum: str) -> str:
    """Return just the last component: '1(a)(i)' -> '(i)',  '1(a)' -> '(a)',  '1' -> '1'"""
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
    """Union of all tight bboxes from rows."""
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
    """
    Best bbox strategy:
    1. bbox_full from rep_row  (pre-computed, covers all children perfectly)
    2. Merge all sibling tight bboxes  (fallback for old imports)
    """
    b = _parse_bbox(rep_row.get("bbox_full", ""))
    if b:
        return b
    return _merge_bboxes(sibling_rows)


# ─── Main entry point ─────────────────────────────────────────────────────────

def group_questions_by_depth(rows: list, depth_mode: Optional[int]) -> list:
    """
    depth_mode:
        None  -> every segment flat, tight bbox
        0     -> one card per MAIN question per page (full Q with all subs inside)
        1     -> one card per SUB-QUESTION (a,b,c) per page
                 each card image includes ALL its (i)(ii)(iii) merged in
                 shown in order: 1(a) card, 1(b) card, 1(c) card ...
        2     -> one card per SUB-SUB question (i)(ii)(iii) in document order
                 each card shows ONLY that (i)/(ii)/(iii) with tight bbox
                 card header shows parent context: "5(b)(iii)"
                 sibling labels shown: "Part of: 5(b) → (i) (ii) (iii)"
    """
    if not rows:
        return []
    if depth_mode is None:
        return rows
    if depth_mode == 2:
        return _group_subsub(rows)
    if depth_mode == 0:
        return _group_main(rows)
    if depth_mode == 1:
        return _group_sub(rows)
    return rows


# ─── Lookup builder ───────────────────────────────────────────────────────────

def _build_lookup(rows):
    """
    Pre-build lookup dicts so O(n) grouping instead of O(n^2).
    Returns:
        by_main:  (doc_id, main_num, page) -> [all rows with that main Q on that page]
        by_sub:   (doc_id, sub_num,  page) -> [all rows with that sub Q on that page]
        main_pages: (doc_id, main_num) -> set of pages
        sub_pages:  (doc_id, sub_num)  -> set of pages
    """
    by_main    = {}
    by_sub     = {}
    main_pages = {}
    sub_pages  = {}

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

    return by_main, by_sub, main_pages, sub_pages


# ─── depth_mode=0: Main questions ────────────────────────────────────────────

def _group_main(rows: list) -> list:
    """
    One card per main question per page.
    Order: follows document order (DB insertion order via q.id).
    """
    by_main, _, main_pages, _ = _build_lookup(rows)

    seen   = set()
    result = []

    for r in rows:
        if r.get("question_level", 0) != 0:
            continue
        doc  = r["doc_id"]
        pg   = r["page_number"]
        main = get_main_number(r["question_number"])
        key  = (doc, main, pg)
        if key in seen:
            continue
        seen.add(key)

        siblings = by_main.get(key, [r])
        bbox     = _best_bbox(r, siblings)

        # Sub labels in document order, just the letter part: "(a)" "(b)" ...
        sub_labels = _ordered_unique([
            get_label_only(s["question_number"])
            for s in siblings
            if s.get("question_level", 0) == 1
        ])
        sub_summary = " ".join(sub_labels)

        all_text = _join_text(siblings)

        all_pgs = main_pages.get((doc, main), {pg})
        is_cont = len(all_pgs) > 1 and pg != min(all_pgs)
        display = f"{main} (cont.)" if is_cont else main

        result.append({
            **r,
            "question_number":  display,
            "question_level":   0,
            "bbox":             json.dumps(bbox),
            "text_content":     all_text,
            "_sub_summary":     sub_summary,
            "_is_continuation": is_cont,
            "_segment_count":   len(siblings),
        })

    return result


# ─── depth_mode=1: Sub-questions ─────────────────────────────────────────────

def _group_sub(rows: list) -> list:
    """
    One card per sub-question (a,b,c) per page, IN DOCUMENT ORDER.

    For each (a) card:
      - bbox covers (a) + ALL its (i)(ii)(iii) merged as one image
      - badge shows "Includes: (i) (ii) (iii)"

    For each (b) card:
      - bbox covers (b) + ALL its (i)(ii) merged as one image
      - badge shows "Includes: (i) (ii)"

    So the result for Q2 is:
      [ 2(a) card, 2(b) card ]   in that order
    """
    _, by_sub, _, sub_pages = _build_lookup(rows)

    level1_rows = [r for r in rows if r.get("question_level", 0) == 1]
    if not level1_rows:
        logger.warning("No level-1 rows found, falling back to main grouping")
        return _group_main(rows)

    seen   = set()
    result = []

    # Walk rows in DB order — emit a card each time we see a new level-1 row
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

        # siblings = this (a)/(b)/(c) row + all its (i)(ii)(iii) children on this page
        siblings = by_sub.get(key, [r])
        bbox     = _best_bbox(r, siblings)

        # Sub-sub labels in document order — just "(i)" "(ii)" "(iii)" not full numbers
        subsub_labels = _ordered_unique([
            get_label_only(s["question_number"])
            for s in siblings
            if s.get("question_level", 0) == 2
        ])
        subsub_summary = " ".join(subsub_labels)   # e.g. "(i) (ii) (iii)"

        all_text = _join_text(siblings)

        marks_list = [s["marks"] for s in siblings
                      if s.get("question_level", 0) == 2 and s.get("marks")]
        total_marks = sum(marks_list) if marks_list else r.get("marks")

        all_pgs = sub_pages.get((doc, sub), {pg})
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
        })

    return result


# ─── Utilities ────────────────────────────────────────────────────────────────

def _ordered_unique(items: list) -> list:
    """Remove duplicates while preserving order."""
    seen = set()
    out  = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _join_text(rows: list) -> str:
    return "\n".join(r["text_content"] for r in rows if r.get("text_content"))


# ─── depth_mode=2: Sub-sub questions (i)(ii)(iii) ────────────────────────────

def _group_subsub(rows: list) -> list:
    """
    One card per sub-sub question (i)(ii)(iii), in document order.

    Each card:
      - Shows ONLY that single (i)/(ii)/(iii) with its tight bbox
      - Badge label: full path e.g. "5(b)(iii)"
      - Info line: "Part of: 5(b)  ←  (i) (ii) [iii] (iv)"
        where the current one is shown in brackets to indicate position

    Cross-page: if 5(b)(iii) is on page 9 while 5(b)(i)(ii) are on page 8,
    the card for (iii) still shows "Part of: 5(b)" context correctly.

    Order: exact document order (by q.id from DB).
    """
    # Build sibling map: (doc_id, sub_num) -> all level-2 rows (any page)
    # so we can show the full "(i) (ii) (iii)" sibling list on each card
    sibling_map = {}   # (doc_id, sub_num) -> [level-2 rows in order]
    sub_pages   = {}   # (doc_id, sub_num) -> set of pages

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
        logger.warning("No level-2 rows found for sub-sub mode")
        return rows

    result = []
    for r in level2_rows:
        doc      = r["doc_id"]
        qnum     = r["question_number"]           # e.g. "5(b)(iii)"
        sub      = get_sub_number(qnum)            # e.g. "5(b)"
        label    = get_label_only(qnum)            # e.g. "(iii)"
        main     = get_main_number(qnum)           # e.g. "5"

        # All sibling sub-sub rows under same parent sub-question
        all_siblings = sibling_map.get((doc, sub), [r])

        # Build sibling position string: "(i) (ii) [(iii)] (iv)"
        # Current item shown in [] to mark its position
        sibling_labels = _ordered_unique([
            get_label_only(s["question_number"])
            for s in all_siblings
        ])
        highlighted = []
        for lbl in sibling_labels:
            if lbl == label:
                highlighted.append(f"[{lbl}]")   # mark current
            else:
                highlighted.append(lbl)
        sibling_str = " ".join(highlighted)

        # Sub-summary: "Part of: 5(b)  →  (i) (ii) [iii]"
        sub_summary = f"{sub}  →  {sibling_str}"

        # Cross-page context: is this the first page this sub appears?
        all_pgs = sub_pages.get((doc, sub), {r["page_number"]})
        is_cont = len(all_pgs) > 1 and r["page_number"] != min(all_pgs)
        display = f"{qnum} (cont.)" if is_cont else qnum

        result.append({
            **r,
            "question_number":  display,
            "question_level":   2,
            # Keep tight bbox — this is the individual (i)/(ii)/(iii) region only
            "bbox":             r["bbox"],
            "_sub_summary":     sub_summary,
            "_is_continuation": is_cont,
            "_segment_count":   1,
            "_parent_sub":      sub,    # used for grouping visual separator
            "_parent_main":     main,
        })

    return result