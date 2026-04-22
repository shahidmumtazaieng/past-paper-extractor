"""
core/import_worker.py
======================
Background thread worker for importing PDFs.
Runs in a separate thread so the UI never freezes.

Flow:
  1. Compute file hash → check for duplicates
  2. Insert document metadata into DB
  3. Parse PDF — routes to correct parser by doc_type
  4. Insert questions batch
  5. Update document status to 'indexed'
  6. Trigger pre-caching of page 1 (warm-up)
  7. Callback UI with result
"""

import threading
import logging
from typing import Callable

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
        metadata: dict,          # {level, subject, year, season, variant, paper, doc_type, topic}
        on_progress: Callable,   # (message: str, percent: int) → None
        on_complete: Callable,   # (success: bool, message: str) → None
    ):
        super().__init__(daemon=True)
        self.filepath    = filepath
        self.metadata    = metadata
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
        meta     = self.metadata
        doc_type = meta.get("doc_type", "question_paper")

        # Step 1: Duplicate check
        self.on_progress("Checking for duplicates...", 5)
        existing = document_exists(filepath)
        if existing:
            log_import(filepath, "duplicate", f"Already imported as doc_id={existing['id']}")
            self.on_complete(False, f"Already imported on {existing['imported_at'][:10]}.")
            return

        # Step 2: Count pages
        self.on_progress("Reading PDF...", 10)
        from core.pdf_parser import get_page_count
        page_count = get_page_count(filepath)

        # Step 3: Insert document record (status=pending)
        self.on_progress("Creating database record...", 15)
        doc_id = insert_document(
            filepath   = filepath,
            level      = meta.get("level", ""),
            subject    = meta.get("subject", ""),
            year       = int(meta["year"])     if meta.get("year")    and str(meta.get("year","")).isdigit()    else None,
            season     = meta.get("season", ""),
            variant    = int(meta["variant"])  if meta.get("variant") and str(meta.get("variant","")).isdigit() else None,
            paper      = int(meta["paper"])    if meta.get("paper")   and str(meta.get("paper","")).isdigit()   else None,
            page_count = page_count,
            doc_type   = doc_type,
            topic      = meta.get("topic", ""),
        )

        # Step 4: Parse with correct parser
        entry_word = "entries" if doc_type == "marking_scheme" else "questions"

        if doc_type == "marking_scheme":
            self.on_progress("Parsing marking scheme...", 20)
            try:
                from core.marking_parser import parse_marking_scheme
                questions = parse_marking_scheme(filepath)
            except Exception as e:
                update_document_status(doc_id, "error")
                log_import(filepath, "error", str(e))
                raise RuntimeError(f"Marking scheme parsing failed: {e}") from e
        else:
            self.on_progress("Detecting questions...", 20)
            try:
                from core.pdf_parser import parse_questions_from_pdf
                questions = parse_questions_from_pdf(filepath)
            except Exception as e:
                update_document_status(doc_id, "error")
                log_import(filepath, "error", str(e))
                raise RuntimeError(f"PDF parsing failed: {e}") from e

        # Step 5: Validate result
        if not questions:
            update_document_status(doc_id, "error")
            hint = (
                "No marking scheme entries detected.\n\n"
                "Make sure this is a text-based CIE marking scheme PDF.\n"
                "The parser looks for question numbers like '1(a)', '1(b)', '2(a)'\n"
                "in the left 'Question' column of the standard CIE MS table."
            ) if doc_type == "marking_scheme" else (
                "No questions detected.\n\n"
                "Make sure the PDF is text-based (not a scanned image).\n"
                "Question numbers must appear at the left margin."
            )
            log_import(filepath, "error", f"No {entry_word} detected")
            self.on_complete(False, hint)
            return

        # Step 6: Insert
        self.on_progress(f"Indexing {len(questions)} {entry_word}...", 60)
        for q in questions:
            q["document_id"] = doc_id

        insert_questions_batch(questions)
        update_document_status(doc_id, "indexed")
        log_import(filepath, "success", f"Indexed {len(questions)} {entry_word}")

        # Step 7: Warm cache
        self.on_progress("Warming image cache...", 85)
        try:
            render_full_page(filepath, 0)
        except Exception:
            pass

        self.on_progress("Done!", 100)
        self.on_complete(
            True,
            f"Successfully imported!\n{len(questions)} {entry_word} from {page_count} pages."
        )