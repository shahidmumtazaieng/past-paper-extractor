"""
core/question_extractor.py
===========================
Renders question regions from PDFs as images using PyMuPDF.

Design decisions:
- Render at 150 DPI by default (clear enough for reading, fast to render)
- Use 200 DPI for export PDFs (higher quality print output)
- All renders are cached to disk — same page is NEVER rendered twice
- Supports rendering full pages (for preview) and cropped regions (for export)
"""

import json
import io
import logging
from typing import Optional
import fitz   # PyMuPDF

from cache.cache_manager import (
    get_cached_page, set_cached_page,
    get_cached_crop, set_cached_crop,
)

logger = logging.getLogger(__name__)

PREVIEW_DPI = 150
EXPORT_DPI = 200


def _dpi_to_matrix(dpi: int) -> fitz.Matrix:
    scale = dpi / 72   # PDF base unit is 72 pts/inch
    return fitz.Matrix(scale, scale)


def render_full_page(filepath: str, page_number: int, dpi: int = PREVIEW_DPI) -> bytes:
    """
    Render a full PDF page as PNG bytes.
    Returns cached version if available.
    """
    cached = get_cached_page(filepath, page_number, dpi)
    if cached:
        logger.debug("Cache HIT: page %d of %s", page_number, filepath)
        return cached

    logger.debug("Cache MISS: rendering page %d of %s", page_number, filepath)
    doc = fitz.open(filepath)
    try:
        page = doc[page_number]
        mat = _dpi_to_matrix(dpi)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        png_bytes = pix.tobytes("png")
        set_cached_page(filepath, page_number, png_bytes, dpi)
        return png_bytes
    finally:
        doc.close()


def render_question_crop(
    filepath: str,
    page_number: int,
    bbox: dict,
    dpi: int = PREVIEW_DPI,
) -> bytes:
    """
    Render a specific bounding-box region from a page as PNG bytes.
    bbox = {"x0": float, "y0": float, "x1": float, "y1": float}
    Returns cached version if available.
    """
    bbox_str = json.dumps(bbox, sort_keys=True)
    cached = get_cached_crop(filepath, page_number, bbox_str, dpi)
    if cached:
        logger.debug("Cache HIT: crop page %d bbox %s", page_number, bbox_str)
        return cached

    logger.debug("Cache MISS: cropping page %d bbox %s", page_number, bbox_str)
    doc = fitz.open(filepath)
    try:
        page = doc[page_number]
        clip = fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])
        mat = _dpi_to_matrix(dpi)
        pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
        png_bytes = pix.tobytes("png")
        set_cached_crop(filepath, page_number, bbox_str, png_bytes, dpi)
        return png_bytes
    finally:
        doc.close()


def render_question_crop_smart(q: dict, dpi: int = PREVIEW_DPI) -> bytes:
    """
    Smart render that chooses the right bbox based on question level:
    - Level 0 (main):   uses bbox_full → captures entire question including all sub-parts
    - Level 1 (sub):    uses bbox_full → captures sub including its sub-sub parts
    - Level 2 (subsub): uses bbox      → individual tight crop

    This is the KEY function that makes "Main only" show the complete question.
    """
    level = q.get("question_level", 0)

    if level in (0, 1):
        # Use the full collapsed bbox so all children are included
        full_bbox_str = q.get("bbox_full") or q.get("bbox") or "{}"
        if full_bbox_str and full_bbox_str != "{}":
            try:
                bbox = json.loads(full_bbox_str)
                if bbox.get("y1", 0) > bbox.get("y0", 0):  # valid bbox
                    return render_question_crop(q["filepath"], q["page_number"], bbox, dpi)
            except (json.JSONDecodeError, KeyError):
                pass

    # Level 2 or fallback: use individual tight bbox
    bbox_str = q.get("bbox") or "{}"
    try:
        bbox = json.loads(bbox_str)
    except (json.JSONDecodeError, KeyError):
        bbox = {"x0": 0, "y0": 0, "x1": 595, "y1": 842}

    return render_question_crop(q["filepath"], q["page_number"], bbox, dpi)


def render_questions_for_export(question_rows: list[dict]) -> list[dict]:
    """
    Render all selected questions at export DPI.
    Returns list of {question_number, png_bytes, width_pts, height_pts, ...metadata}
    Used by pdf_exporter to build the output PDF.
    """
    results = []
    for q in question_rows:
        bbox = json.loads(q["bbox"])
        png_bytes = render_question_crop(
            q["filepath"], q["page_number"], bbox, dpi=EXPORT_DPI
        )

        # Compute actual pixel dimensions for layout in export
        import fitz as _fitz
        pix = _fitz.Pixmap(png_bytes)
        results.append({
            **q,
            "png_bytes": png_bytes,
            "img_width_px": pix.width,
            "img_height_px": pix.height,
        })
    return results


def get_image_dimensions_from_bytes(png_bytes: bytes) -> tuple[int, int]:
    """Return (width, height) in pixels from PNG bytes."""
    import fitz as _fitz
    pix = _fitz.Pixmap(png_bytes)
    return pix.width, pix.height
