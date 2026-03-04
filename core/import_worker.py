"""
core/import_worker.py
======================
Background thread worker for importing PDFs.
Runs in a separate thread so the UI never freezes.

Flow:
  1. Compute file hash → check for duplicates
  2. Insert document metadata into DB
  3. Parse PDF questions (page by page)
  4. Insert questions batch
  5. Update document status to 'indexed'
  6. Trigger pre-caching of page 1 (warm-up)
  7. Callback UI with result
"""

import threading
import logging
from typing import Callable

from core.pdf_parser import parse_questions_from_pdf, get_page_count
from core.question_extractor import render_full_page
from database.db_manager import (
    document_exists, insert_document, insert_questions_batch,
    update_document_status, log_import,
)

logger = logging.getLogger(__name__)


class ImportWorker(threading.Thread):
    def __init__(
        self,
        filepath: str,
        metadata: dict,          # {level, subject, year, season, variant, paper}
        on_progress: Callable,   # (message: str, percent: int) → None
        on_complete: Callable,   # (success: bool, message: str) → None
    ):
        super().__init__(daemon=True)
        self.filepath = filepath
        self.metadata = metadata
        self.on_progress = on_progress
        self.on_complete = on_complete

    def run(self):
        try:
            self._run()
        except Exception as e:
            logger.exception("ImportWorker failed")
            log_import(self.filepath, "error", str(e))
            self.on_complete(False, f"Import failed: {e}")

    def _run(self):
        filepath = self.filepath
        meta = self.metadata

        # Step 1: Duplicate check
        self.on_progress("Checking for duplicates...", 5)
        existing = document_exists(filepath)
        if existing:
            log_import(filepath, "duplicate", f"Already imported as doc_id={existing['id']}")
            self.on_complete(False, f"This PDF was already imported on {existing['imported_at'][:10]}.")
            return

        # Step 2: Count pages
        self.on_progress("Reading PDF...", 10)
        page_count = get_page_count(filepath)

        # Step 3: Insert document record (status=pending)
        self.on_progress("Creating database record...", 15)
        doc_id = insert_document(
            filepath=filepath,
            level=meta.get("level", ""),
            subject=meta.get("subject", ""),
            year=int(meta.get("year", 0)) if meta.get("year") else None,
            season=meta.get("season", ""),
            variant=int(meta.get("variant", 0)) if meta.get("variant") else None,
            paper=int(meta.get("paper", 0)) if meta.get("paper") else None,
            page_count=page_count,
        )

        # Step 4: Parse questions (the heavy step)
        self.on_progress("Detecting questions... (this may take a moment)", 20)
        try:
            questions = parse_questions_from_pdf(filepath)
        except Exception as e:
            update_document_status(doc_id, "error")
            raise RuntimeError(f"PDF parsing failed: {e}") from e

        if not questions:
            update_document_status(doc_id, "error")
            log_import(filepath, "error", "No questions detected")
            self.on_complete(
                False,
                "No questions were detected in this PDF.\n\n"
                "Make sure the PDF is text-based (not scanned image).\n"
                "Check that question numbers appear at the left margin."
            )
            return

        # Step 5: Tag questions with document ID
        self.on_progress(f"Indexing {len(questions)} questions...", 60)
        for q in questions:
            q["document_id"] = doc_id

        insert_questions_batch(questions)
        update_document_status(doc_id, "indexed")
        log_import(filepath, "success", f"Indexed {len(questions)} questions")

        # Step 6: Warm the cache for page 1 (so first view is instant)
        self.on_progress("Warming image cache...", 85)
        try:
            render_full_page(filepath, 0)   # pre-render page 1
        except Exception:
            pass  # cache warm-up failure is non-fatal

        self.on_progress("Done!", 100)
        self.on_complete(
            True,
            f"Successfully imported!\n"
            f"{len(questions)} questions indexed from {page_count} pages."
        )
