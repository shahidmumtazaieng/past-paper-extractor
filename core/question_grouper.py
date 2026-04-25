"""
core/question_grouper.py
=========================
Groups flat DB rows into display cards based on depth mode.

FIX APPLIED: FULL PAGE CONTENT CAPTURE
=======================================
When rendering a Main question across multiple pages, if a page contains 
multiple sub-parts like (d), (e), (f), (g), it now merges ALL their bounding 
boxes vertically. This guarantees the exported image shows every single 
part from top to bottom, fixing the "missing data at the end" bug.
"""

import json
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

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

def _parse_bbox(s: str) -> Optional[dict]:
    if not s: return None
    try:
        b = json.loads(s)
        return b if b and b.get("y1", 0) > 0 else None
    except Exception: return None

def _merge_bboxes(rows: list) -> dict:
    """Merges multiple rows into ONE giant bounding box covering all of them."""
    bboxes = [_parse_bbox(r.get("bbox", "")) for r in rows]
    bboxes = [b for b in bboxes if b]
    if not bboxes: return {"x0": 0, "y0": 0, "x1": 595, "y1": 842}
    return {
        "x0": 0, 
        "y0": min(b["y0"] for b in bboxes), 
        "x1": max(b["x1"] for b in bboxes), 
        "y1": max(b["y1"] for b in bboxes), # Stretches to the very last part!
    }

def _best_bbox(rep_row: dict, sibling_rows: list) -> dict:
    b = _parse_bbox(rep_row.get("bbox_full", ""))
    return b if b else _merge_bboxes(sibling_rows)

def group_questions_by_depth(rows: list, depth_mode: Optional[int]) -> list:
    if not rows: return []
    if depth_mode is None: return rows
    if depth_mode == 0: return _group_main(rows)
    if depth_mode == 1: return _group_sub(rows)
    if depth_mode == 2: return _group_sub(rows)
    return rows

def _build_lookup(rows):
    by_main = {}; by_sub = {}
    main_ordered_starts = {}; sub_pages = {}; doc_max_page = {}

    for r in rows:
        qn, doc, pg = r["question_number"], r["doc_id"], r["page_number"]
        mn, sn = get_main_number(qn), get_sub_number(qn)

        by_main.setdefault((doc, mn, pg), []).append(r)
        by_sub.setdefault((doc, sn, pg), []).append(r)
        
        if doc not in doc_max_page or pg > doc_max_page[doc]: doc_max_page[doc] = pg

        if r.get("question_level", 0) == 0:
            if doc not in main_ordered_starts: main_ordered_starts[doc] = []
            if not any(mn == num for num, _ in main_ordered_starts[doc]):
                main_ordered_starts[doc].append((mn, pg))

        if (doc, sn) not in sub_pages: sub_pages[(doc, sn)] = [pg, pg]
        else:
            sub_pages[(doc, sn)][0] = min(sub_pages[(doc, sn)][0], pg)
            sub_pages[(doc, sn)][1] = max(sub_pages[(doc, sn)][1], pg)

    main_pages = {}
    for doc, starts in main_ordered_starts.items():
        starts.sort(key=lambda x: x[1])
        for i, (mn, start_pg) in enumerate(starts):
            end_pg = starts[i + 1][1] - 1 if i + 1 < len(starts) else doc_max_page.get(doc, start_pg)
            main_pages[(doc, mn)] = [start_pg, end_pg]

    return by_main, by_sub, main_pages, sub_pages

def _group_main(rows: list) -> list:
    by_main, _, main_pages, _ = _build_lookup(rows)
    seen, result = set(), []

    for r in rows:
        if r.get("question_level", 0) != 0: continue
        doc, main = r["doc_id"], get_main_number(r["question_number"])
        key = (doc, main)
        if key in seen: continue
        seen.add(key)

        page_range = main_pages.get(key, [r["page_number"], r["page_number"]])
        pages = list(range(page_range[0], page_range[1] + 1))

        page_segments, all_rows = [], []
        for pg in pages:
            pg_rows = by_main.get((doc, main, pg), [])
            
            if not pg_rows:
                # GAP FILLER: Pure diagram/table page with no text markers
                page_segments.append({
                    "page_number": pg,
                    "bbox": {"x0": 0.0, "y0": 0.0, "x1": r.get("page_width", 595.0), "y1": r.get("page_height", 842.0)},
                    "filepath": r["filepath"],
                })
            else:
                # THE FIX: Merge ALL sub-parts on this page into one giant box!
                # Previously, it only used the first part (d), cutting off (e),(f),(g).
                # Now it stretches from the top of (d) all the way to the bottom of (g).
                pg_rep = pg_rows[0]
                pg_bbox = _merge_bboxes(pg_rows)
                
                page_segments.append({
                    "page_number": pg,
                    "bbox":        pg_bbox,
                    "filepath":    pg_rep["filepath"],
                })
                all_rows.extend(pg_rows)

        if not page_segments: continue

        sub_labels = _ordered_unique([get_label_only(x["question_number"]) for x in all_rows if x.get("question_level", 0) == 1])
        rep = next((x for x in all_rows if x.get("question_level", 0) == 0), r)
        
        result.append({
            **rep, "question_number": str(main), "question_level": 0,
            "bbox": json.dumps(page_segments[0]["bbox"]),
            "text_content": _join_text(all_rows),
            "_sub_summary": " ".join(sub_labels), "_is_continuation": False,
            "_segment_count": len(all_rows) if all_rows else len(page_segments),
            "_page_segments": page_segments, "_is_multipage": len(pages) > 1, "_page_count": len(pages),
        })
    return result

def _group_sub(rows: list) -> list:
    _, by_sub, _, sub_pages = _build_lookup(rows)
    level1_rows = [r for r in rows if r.get("question_level", 0) == 1]
    if not level1_rows: return _group_main(rows)

    seen, result = set(), []
    for r in level1_rows:
        doc, sub = r["doc_id"], get_sub_number(r["question_number"])
        key = (doc, sub)
        if key in seen: continue
        seen.add(key)

        page_range = sub_pages.get(key, [r["page_number"], r["page_number"]])
        pages = list(range(page_range[0], page_range[1] + 1))
        
        page_segments, all_rows = [], []
        for pg in pages:
            pg_rows = by_sub.get((doc, sub, pg), [])
            if not pg_rows:
                page_segments.append({
                    "page_number": pg,
                    "bbox": {"x0": 0.0, "y0": 0.0, "x1": r.get("page_width", 595.0), "y1": r.get("page_height", 842.0)},
                    "filepath": r["filepath"],
                })
            else:
                # For sub-questions, also merge to capture everything inside it
                pg_rep = pg_rows[0]
                pg_bbox = _merge_bboxes(pg_rows)
                
                page_segments.append({
                    "page_number": pg,
                    "bbox":        pg_bbox,
                    "filepath":    pg_rep["filepath"],
                })
                all_rows.extend(pg_rows)

        if not page_segments: continue
        result.append({
            **r, "question_number": sub, "question_level": 1,
            "bbox": json.dumps(page_segments[0]["bbox"]),
            "text_content": _join_text(all_rows), "marks": r.get("marks"),
            "_sub_summary": "", "_is_continuation": False,
            "_segment_count": len(all_rows) if all_rows else len(page_segments),
            "_page_segments": page_segments, "_is_multipage": len(pages) > 1, "_page_count": len(pages),
        })
    return result

def _ordered_unique(items: list) -> list:
    seen, out = set(), []
    for x in items:
        if x not in seen: seen.add(x); out.append(x)
    return out

def _join_text(rows: list) -> str:
    return "\n".join(r["text_content"] for r in rows if r.get("text_content"))