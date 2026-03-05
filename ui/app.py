"""
ui/app.py
==========
Main application window.
Uses CustomTkinter for a modern, professional look.

Layout:
┌─────────────────────────────────────────────┐
│  HEADER (logo + title + stats)              │
├──────────────┬──────────────────────────────┤
│  LEFT PANEL  │  RIGHT PANEL                 │
│  - Filters   │  - Question results          │
│  - Docs list │  - Preview images            │
│              │  - Export controls           │
└──────────────┴──────────────────────────────┘
"""

import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
import logging
import threading
from pathlib import Path

from database.db_manager import init_db, get_filter_options, get_all_documents, delete_document
from ui.import_dialog import ImportDialog
from ui.filter_panel import FilterPanel
from ui.results_panel import ResultsPanel
from ui.documents_panel import DocumentsPanel
from cache.cache_manager import cache_stats, clear_cache

logger = logging.getLogger(__name__)

# App theme
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

APP_TITLE  = "Past Paper Question Extractor"
APP_VERSION = "1.0.0"
WIN_WIDTH  = 1280
WIN_HEIGHT = 800

# Color palette
C_NAVY     = "#1a3a5c"
C_BLUE     = "#2563eb"
C_ACCENT   = "#0ea5e9"
C_BG       = "#f0f4f8"
C_WHITE    = "#ffffff"
C_BORDER   = "#cbd5e1"
C_SUCCESS  = "#16a34a"
C_ERROR    = "#dc2626"


class PastPaperApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Initialize database on first run
        init_db()

        self._setup_window()
        self._build_ui()
        self._refresh_filter_options()

        logger.info("Application started")

    # ─────────────────────── Window setup ───────────────────────

    def _setup_window(self):
        self.title(APP_TITLE)
        self.geometry(f"{WIN_WIDTH}x{WIN_HEIGHT}")
        self.minsize(1000, 650)
        self.configure(fg_color=C_BG)

        # Center on screen
        self.update_idletasks()
        x = (self.winfo_screenwidth() - WIN_WIDTH) // 2
        y = (self.winfo_screenheight() - WIN_HEIGHT) // 2
        self.geometry(f"+{x}+{y}")

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ─────────────────────── UI Build ───────────────────────────

    def _build_ui(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_header()
        self._build_body()
        self._build_statusbar()

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color=C_NAVY, corner_radius=0, height=64)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(1, weight=1)

        # Logo / Title
        ctk.CTkLabel(
            header,
            text="📄 " + APP_TITLE,
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color=C_WHITE,
        ).grid(row=0, column=0, padx=20, pady=16, sticky="w")

        # Version
        ctk.CTkLabel(
            header,
            text=f"v{APP_VERSION}",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
        ).grid(row=0, column=1, padx=8, pady=16, sticky="w")

        # Action buttons
        btn_frame = ctk.CTkFrame(header, fg_color="transparent")
        btn_frame.grid(row=0, column=2, padx=12, pady=10, sticky="e")

        ctk.CTkButton(
            btn_frame,
            text="+ Import PDF",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=C_BLUE,
            hover_color="#1d4ed8",
            corner_radius=8,
            height=36,
            command=self._open_import_dialog,
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            btn_frame,
            text="Manage PDFs",
            font=ctk.CTkFont(size=13),
            fg_color="transparent",
            border_color="#4a7fa5",
            border_width=1,
            text_color=C_WHITE,
            hover_color="#2a4a6c",
            corner_radius=8,
            height=36,
            command=self._open_documents_panel,
        ).pack(side="left", padx=4)

    def _build_body(self):
        body = ctk.CTkFrame(self, fg_color=C_BG, corner_radius=0)
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        # Left: Filter panel
        self.filter_panel = FilterPanel(
            body,
            on_search=self._on_search,
            fg_color=C_WHITE,
            width=300,
        )
        self.filter_panel.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)

        # Right: Results panel
        self.results_panel = ResultsPanel(
            body,
            on_export=self._on_export,
            fg_color=C_WHITE,
        )
        self.results_panel.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=12)

    def _build_statusbar(self):
        bar = ctk.CTkFrame(self, fg_color=C_BORDER, corner_radius=0, height=28)
        bar.grid(row=2, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(1, weight=1)

        self.status_label = ctk.CTkLabel(
            bar,
            text="Ready",
            font=ctk.CTkFont(size=11),
            text_color="#374151",
        )
        self.status_label.grid(row=0, column=0, padx=12, pady=4, sticky="w")

        # Cache stats button
        ctk.CTkButton(
            bar,
            text="Cache Info",
            font=ctk.CTkFont(size=10),
            fg_color="transparent",
            text_color="#6b7280",
            hover_color="#e5e7eb",
            height=22,
            width=80,
            corner_radius=4,
            command=self._show_cache_info,
        ).grid(row=0, column=2, padx=8, pady=3, sticky="e")

    # ─────────────────────── Actions ────────────────────────────

    def _open_import_dialog(self):
        dialog = ImportDialog(self, on_import_complete=self._on_import_complete)
        dialog.grab_set()

    def _open_documents_panel(self):
        dialog = DocumentsPanel(self, on_change=self._refresh_filter_options)
        dialog.grab_set()

    def _on_import_complete(self, success: bool, message: str):
        if success:
            self._set_status("Import complete — refreshing filters...")
            self._refresh_filter_options()
        self._set_status("Ready")

    def _on_search(self, filters: dict):
        """Called by FilterPanel when user clicks Search."""
        self._set_status("Searching...")
        self.results_panel.clear()

        # Extract depth mode BEFORE removing from filters
        # depth_mode drives grouping AFTER the DB query
        depth_mode = filters.pop("question_level", None)

        def _search_thread():
            from database.db_manager import query_questions
            from core.question_grouper import group_questions_by_depth

            if depth_mode is None:
                # "Any" — fetch all levels, show flat
                results = query_questions(**filters)
                display = group_questions_by_depth(results, None)

            elif depth_mode == 0:
                # "Main only" — fetch ALL levels, then GROUP by main question
                # This gives full question including all (a)(b)(i)(ii) in one card
                results = query_questions(**filters)   # no level filter
                display = group_questions_by_depth(results, 0)

            elif depth_mode == 1:
                # "Sub-questions (a,b,c)" — fetch level 1+2, group by sub
                # Each (a)(b)(c) card includes its (i)(ii)(iii) merged in
                results = query_questions(**filters)   # no level filter
                display = group_questions_by_depth(results, 1)

            elif depth_mode == 2:
                # "Sub-sub (i,ii,iii)" — fetch level 2 only, tight bbox
                results = query_questions(**filters, question_level=2)
                display = group_questions_by_depth(results, 2)

            else:
                results = query_questions(**filters)
                display = results

            self.after(0, lambda: self._on_search_results(display, depth_mode))

        threading.Thread(target=_search_thread, daemon=True).start()

    def _on_search_results(self, results: list, depth_mode=None):
        count = len(results)
        mode_labels = {
            None: "all segments",
            0: "full questions",
            1: "sub-questions",
            2: "sub-sub segments",
        }
        label = mode_labels.get(depth_mode, "results")
        self.results_panel.show_results(results)
        self._set_status(f"Found {count} {label}")

    def _on_export(self, selected_questions: list, output_path: str):
        """Called by ResultsPanel when user triggers export."""
        if not selected_questions:
            messagebox.showwarning("No Selection", "Please select at least one question to export.")
            return

        self._set_status(f"Exporting {len(selected_questions)} questions...")

        def _export_thread():
            from core.pdf_exporter import export_questions_to_pdf
            try:
                export_questions_to_pdf(
                    selected_questions,
                    output_path,
                    title="Extracted Questions",
                    progress_callback=lambda cur, tot: self.after(
                        0,
                        lambda: self._set_status(f"Exporting {cur}/{tot}..."),
                    ),
                )
                self.after(0, lambda: self._on_export_complete(True, output_path))
            except Exception as e:
                logger.exception("Export failed")
                err_msg = str(e)   # capture by value NOW, not in lambda
                self.after(0, lambda m=err_msg: self._on_export_complete(False, m))

        threading.Thread(target=_export_thread, daemon=True).start()

    def _on_export_complete(self, success: bool, path_or_error: str):
        if success:
            self._set_status(f"Exported → {path_or_error}")
            messagebox.showinfo(
                "Export Complete",
                f"PDF saved successfully:\n\n{path_or_error}"
            )
        else:
            self._set_status("Export failed")
            messagebox.showerror("Export Failed", path_or_error)

    def _refresh_filter_options(self):
        """Reload filter dropdowns from DB (call after import or delete)."""
        opts = get_filter_options()
        self.filter_panel.update_options(opts)
        docs = get_all_documents()
        indexed = [d for d in docs if d["status"] == "indexed"]
        self._set_status(f"Ready — {len(indexed)} document(s) in library")

    def _show_cache_info(self):
        stats = cache_stats()
        msg = (
            f"Cache entries: {stats['entries']}\n"
            f"Cache size: {stats['size_mb']} MB / {stats['limit_mb']} MB\n\n"
            f"Cache stores rendered page images so searches\n"
            f"are fast after the first view.\n\n"
            f"Clear cache to free disk space?"
        )
        if messagebox.askyesno("Cache Information", msg):
            clear_cache()
            messagebox.showinfo("Cache Cleared", "Cache has been cleared.")

    def _set_status(self, text: str):
        self.status_label.configure(text=text)
        self.update_idletasks()

    def _on_close(self):
        self.destroy()