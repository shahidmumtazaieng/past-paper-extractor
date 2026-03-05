"""
core/pdf_exporter.py
=====================
Generates a clean output PDF from selected question images.

MULTI-PAGE EXPORT STRATEGY:
============================
If a question spans multiple source pages (e.g. Q1 on pages 2 and 3),
it is exported across MULTIPLE pages in the output PDF — one output page
per source page segment. This preserves full resolution and readability.

Layout per output page:
  ┌─────────────────────────────────────┐
  │  Question 1   [10 marks]            │  ← header (only on first page of Q)
  │  O-Level | Physics | 2020 | Paper 4 │  ← source (only on first page)
  ├─────────────────────────────────────┤
  │                                     │
  │   [FULL WIDTH QUESTION IMAGE]       │  ← scales to fill available height
  │   (from source page 2)              │
  │                                     │
  └─────────────────────────────────────┘
  ┌─────────────────────────────────────┐
  │  Question 1 (cont.)                 │  ← continuation header
  ├─────────────────────────────────────┤
  │                                     │
  │   [FULL WIDTH QUESTION IMAGE]       │  ← from source page 3
  │                                     │
  └─────────────────────────────────────┘

Single-page questions get ONE output page.
Multi-page questions get N output pages (one per source page segment).
"""

import io
import json
import logging
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Image, Spacer, Paragraph,
    HRFlowable, PageBreak, KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER

from core.question_extractor import render_question_crop, EXPORT_DPI

logger = logging.getLogger(__name__)

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN      = 18 * mm
CONTENT_W   = PAGE_WIDTH  - 2 * MARGIN
HEADER_H    = 36          # pts reserved for question header line
CONT_H      = 20          # pts reserved for "(cont.)" header
CONTENT_H   = PAGE_HEIGHT - 2 * MARGIN   # full usable height per page


def export_questions_to_pdf(
    question_rows: list,
    output_path: str,
    title: str = "Extracted Questions",
    progress_callback=None,
) -> str:
    """
    Build a PDF from a list of question dicts.
    Multi-page questions automatically span multiple output pages.
    Returns output_path on success.
    """
    logger.info("Exporting %d questions to %s", len(question_rows), output_path)

    styles    = getSampleStyleSheet()
    st_title  = _make_style("PPTitle",  styles, "Helvetica-Bold",    16, "#1a3a5c", TA_CENTER, spaceAfter=6)
    st_meta   = _make_style("PPMeta",   styles, "Helvetica",          9, "#555555", TA_CENTER, spaceAfter=10)
    st_qhead  = _make_style("QPHead",   styles, "Helvetica-Bold",    11, "#1a3a5c", TA_LEFT,   spaceBefore=4, spaceAfter=3)
    st_cont   = _make_style("QPCont",   styles, "Helvetica-Oblique", 10, "#3b82f6", TA_LEFT,   spaceBefore=2, spaceAfter=3)
    st_source = _make_style("QPSrc",    styles, "Helvetica-Oblique",  8, "#888888", TA_LEFT,   spaceAfter=4)

    story = []

    # ── Cover header ─────────────────────────────────────────────────────────
    story.append(Paragraph(title, st_title))
    story.append(Paragraph(
        f"Generated: {datetime.now().strftime('%d %B %Y, %H:%M')}  |  "
        f"{len(question_rows)} question(s)",
        st_meta,
    ))
    story.append(HRFlowable(width="100%", thickness=1.5,
                             color=colors.HexColor("#1a3a5c"), spaceAfter=10))

    total = len(question_rows)

    for idx, q in enumerate(question_rows):
        if progress_callback:
            progress_callback(idx + 1, total)

        qnum    = q.get("question_number", "?")
        marks   = q.get("marks")
        source  = _build_source_label(q)

        marks_str   = f"  [{marks} marks]" if marks else ""
        q_head_text = f"Question {qnum}{marks_str}"

        # ── Get page segments ────────────────────────────────────────────────
        # _page_segments is set by the grouper for multi-page questions.
        # Fall back to single-segment using the question's own bbox.
        segments = q.get("_page_segments")
        if not segments:
            # Build a single segment from the question row itself
            bbox_str = q.get("bbox_full") or q.get("bbox") or "{}"
            try:
                bbox = json.loads(bbox_str)
            except Exception:
                bbox = {"x0": 0, "y0": 0, "x1": 595, "y1": 842}
            segments = [{
                "page_number": q.get("page_number", 0),
                "bbox":        bbox,
                "filepath":    q.get("filepath", ""),
            }]

        n_segs = len(segments)

        for seg_idx, seg in enumerate(segments):
            is_first = seg_idx == 0
            is_last  = seg_idx == n_segs - 1

            # ── Header for this output page ──────────────────────────────────
            if is_first:
                story.append(Paragraph(q_head_text, st_qhead))
                story.append(Paragraph(source, st_source))
                avail_h = CONTENT_H - HEADER_H
            else:
                story.append(Paragraph(f"Question {qnum}  (cont.)", st_cont))
                avail_h = CONTENT_H - CONT_H

            # ── Render this page segment ─────────────────────────────────────
            try:
                png_bytes = render_question_crop(
                    seg["filepath"],
                    seg["page_number"],
                    seg["bbox"],
                    dpi=EXPORT_DPI,
                )

                from PIL import Image as PILImage
                with PILImage.open(io.BytesIO(png_bytes)) as pil:
                    img_w_px, img_h_px = pil.size

                # Scale to fill full content width
                scale     = CONTENT_W / img_w_px
                img_w_pts = CONTENT_W
                img_h_pts = img_h_px * scale

                # If taller than available height on this page, scale down
                # (only happens for unusually long single segments)
                if img_h_pts > avail_h:
                    scale     = avail_h / img_h_pts
                    img_w_pts = CONTENT_W * scale
                    img_h_pts = avail_h

                img_buf   = io.BytesIO(png_bytes)
                rl_image  = Image(img_buf, width=img_w_pts, height=img_h_pts)
                rl_image.hAlign = "LEFT"
                story.append(rl_image)

            except Exception as render_err:
                logger.error("Segment render failed Q%s seg%d: %s",
                             qnum, seg_idx, render_err)
                story.append(Paragraph(
                    f"[Render error: {render_err}]", styles["Normal"]
                ))

            # ── Separator / page break ───────────────────────────────────────
            if not is_last:
                # More segments follow → force a new page
                story.append(PageBreak())
            else:
                # Last segment of this question → thin rule
                story.append(HRFlowable(
                    width="100%", thickness=0.5,
                    color=colors.HexColor("#d1d5db"),
                    spaceBefore=8, spaceAfter=8,
                ))

        # After the last question, no extra page break needed
        # (the HRFlowable above separates questions naturally)

    # ── Build PDF ─────────────────────────────────────────────────────────────
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=title,
        author="Past Paper Extractor",
    )
    doc.build(story)
    logger.info("PDF exported: %s", output_path)
    return output_path


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_style(name, styles, font, size, hex_color, align,
                spaceBefore=0, spaceAfter=0):
    return ParagraphStyle(
        name,
        parent=styles["Normal"],
        fontName=font,
        fontSize=size,
        textColor=colors.HexColor(hex_color),
        alignment=align,
        spaceBefore=spaceBefore,
        spaceAfter=spaceAfter,
    )


def _build_source_label(q: dict) -> str:
    parts = []
    for field, prefix in [
        ("level",   ""),
        ("subject", ""),
        ("year",    ""),
        ("season",  ""),
        ("paper",   "Paper "),
        ("variant", "Variant "),
    ]:
        val = q.get(field)
        if val:
            parts.append(f"{prefix}{val}")
    return "  |  ".join(parts) if parts else "Source: Unknown"