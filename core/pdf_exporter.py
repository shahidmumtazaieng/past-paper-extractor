"""
core/pdf_exporter.py
=====================
Generates a clean output PDF from selected question images.

Strategy:
- Crop each question as a high-DPI image (via question_extractor)
- Embed images into a new PDF using ReportLab
- Add a header per question (number, source paper, year, marks)
- Auto-size each page to fit the question image
"""

import io
import json
import logging
from datetime import datetime
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Image, Spacer, Paragraph, HRFlowable, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER

from core.question_extractor import render_question_crop, EXPORT_DPI

logger = logging.getLogger(__name__)

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 20 * mm
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN


def export_questions_to_pdf(
    question_rows: list[dict],
    output_path: str,
    title: str = "Extracted Questions",
    progress_callback=None,  # callable(current, total)
) -> str:
    """
    Build a PDF from a list of question dicts (from db_manager.query_questions).
    Returns output_path on success.
    """
    logger.info("Exporting %d questions to %s", len(question_rows), output_path)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "PPTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=16,
        textColor=colors.HexColor("#1a3a5c"),
        alignment=TA_CENTER,
        spaceAfter=6,
    )
    meta_style = ParagraphStyle(
        "PPMeta",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        textColor=colors.HexColor("#555555"),
        alignment=TA_CENTER,
        spaceAfter=12,
    )
    q_header_style = ParagraphStyle(
        "QPHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=colors.HexColor("#1a3a5c"),
        spaceBefore=6,
        spaceAfter=4,
    )
    source_style = ParagraphStyle(
        "QSource",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=8,
        textColor=colors.HexColor("#888888"),
        spaceAfter=4,
    )

    story = []

    # Cover header
    story.append(Paragraph(title, title_style))
    story.append(Paragraph(
        f"Generated: {datetime.now().strftime('%d %B %Y, %H:%M')} | "
        f"{len(question_rows)} Question(s)",
        meta_style,
    ))
    story.append(HRFlowable(width="100%", thickness=1.5,
                             color=colors.HexColor("#1a3a5c"), spaceAfter=12))

    total = len(question_rows)
    for idx, q in enumerate(question_rows):
        if progress_callback:
            progress_callback(idx + 1, total)

        # Question header
        marks_str = f"  [{q['marks']} marks]" if q.get("marks") else ""
        story.append(Paragraph(
            f"Question {q['question_number']}{marks_str}",
            q_header_style,
        ))

        # Source info
        source = _build_source_label(q)
        story.append(Paragraph(source, source_style))

        # Render the question image using smart bbox selection
        try:
            from core.question_extractor import render_question_crop_smart
            png_bytes = render_question_crop_smart(q, dpi=EXPORT_DPI)

            # Scale image to fit content width while preserving aspect ratio
            img_buf = io.BytesIO(png_bytes)
            from PIL import Image as PILImage
            with PILImage.open(img_buf) as pil_img:
                img_w_px, img_h_px = pil_img.size

            scale = CONTENT_WIDTH / img_w_px
            img_w_pts = CONTENT_WIDTH
            img_h_pts = img_h_px * scale

            img_buf.seek(0)
            rl_image = Image(img_buf, width=img_w_pts, height=img_h_pts)
            rl_image.hAlign = "LEFT"
            story.append(rl_image)

        except Exception as e:
            logger.error("Failed to render question %s: %s", q["question_number"], e)
            story.append(Paragraph(
                f"[Error rendering question: {e}]",
                styles["Normal"],
            ))

        story.append(HRFlowable(
            width="100%", thickness=0.5,
            color=colors.HexColor("#dddddd"),
            spaceBefore=10, spaceAfter=10,
        ))

    # Build PDF
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
    logger.info("PDF exported to %s", output_path)
    return output_path


def _build_source_label(q: dict) -> str:
    parts = []
    if q.get("level"):
        parts.append(q["level"])
    if q.get("subject"):
        parts.append(q["subject"])
    if q.get("year"):
        parts.append(str(q["year"]))
    if q.get("season"):
        parts.append(q["season"])
    if q.get("paper"):
        parts.append(f"Paper {q['paper']}")
    if q.get("variant"):
        parts.append(f"Variant {q['variant']}")
    return "  |  ".join(parts) if parts else "Source: Unknown"
