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
    HRFlowable, PageBreak,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from core.question_extractor import render_question_crop, EXPORT_DPI

logger = logging.getLogger(__name__)

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN      = 18 * mm
CONTENT_W   = PAGE_WIDTH  - 2 * MARGIN
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

    styles  = getSampleStyleSheet()
    story = []
    total = len(question_rows)

    for idx, q in enumerate(question_rows):
        if progress_callback:
            progress_callback(idx + 1, total)

        qnum    = q.get("question_number", "?")
        marks   = q.get("marks")

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

        # ── Add header only on first segment ──────────────────────────────────
        if n_segs > 0:
            # Question number header
            question_header = f"Question {qnum}"
            story.append(Paragraph(question_header, styles["Heading2"]))
            
            # Build source/filter info line
            source_line = _build_source_label(q)
            story.append(Paragraph(source_line, styles["Normal"]))
            
            # Small spacer before image
            story.append(Spacer(1, 6 * mm))

        for seg_idx, seg in enumerate(segments):
            is_last = seg_idx == n_segs - 1
            avail_h = CONTENT_H - (36 * mm) if seg_idx == 0 else CONTENT_H

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
                story.append(PageBreak())

        # After the last question, leave the final page as-is

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
    """Build filter info line like: IGCSE | CS | 2020 | Oct/Nov | Paper 2 | Variant 1"""
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
    return " | ".join(parts) if parts else ""