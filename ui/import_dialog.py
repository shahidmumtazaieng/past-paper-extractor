"""
ui/import_dialog.py
====================
Import dialog with two modes:
  - Question Paper  (standard CIE QP format)
  - Marking Scheme  (topical book / compiled marking scheme)

The doc_type radio button switches the form fields accordingly.
"""

import tkinter as tk
from tkinter import filedialog
from pathlib import Path
import customtkinter as ctk

C_NAVY   = "#1a3a5c"
C_WHITE  = "#ffffff"
C_BG     = "#f8fafc"
C_BLUE   = "#2563eb"
C_GREEN  = "#16a34a"
C_PURPLE = "#7c3aed"

YEARS   = [str(y) for y in range(2000, 2041)][::-1]
SEASONS = ["May/June", "Oct/Nov", "Feb/Mar"]
PAPERS  = ["1", "2", "3", "4", "5", "6"]
VARIANTS= ["1", "2", "3", "4"]
LEVELS  = ["O-Level", "A-Level", "IGCSE", "AS-Level"]


class ImportDialog(ctk.CTkToplevel):
    def __init__(self, parent, on_import_complete):
        super().__init__(parent)
        self.on_import_complete = on_import_complete
        self.title("Import PDF")
        self.geometry("580x680")
        self.resizable(False, False)
        self.grab_set()

        self._filepath    = tk.StringVar()
        self._doc_type    = tk.StringVar(value="question_paper")
        self._level       = tk.StringVar(value="O-Level")
        self._subject     = tk.StringVar(value="Physics")
        self._year        = tk.StringVar(value="2023")
        self._season      = tk.StringVar(value="May/June")
        self._paper       = tk.StringVar(value="4")
        self._variant     = tk.StringVar(value="1")
        self._topic       = tk.StringVar(value="")

        self._build()

    # ─── UI ──────────────────────────────────────────────────────────────────

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # Title
        ctk.CTkLabel(
            self, text="Import PDF",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=C_NAVY,
        ).grid(row=0, column=0, padx=20, pady=(20, 4), sticky="w")

        # ── Doc type selector ─────────────────────────────────────────────────
        type_frame = ctk.CTkFrame(self, fg_color="#f1f5f9", corner_radius=10)
        type_frame.grid(row=1, column=0, padx=20, pady=(0, 12), sticky="ew")
        type_frame.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(
            type_frame, text="Document Type:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#374151",
        ).grid(row=0, column=0, columnspan=2, padx=12, pady=(10, 4), sticky="w")

        self._qp_btn = ctk.CTkRadioButton(
            type_frame,
            text="📄  Question Paper",
            variable=self._doc_type,
            value="question_paper",
            font=ctk.CTkFont(size=12),
            fg_color=C_NAVY,
            command=self._on_type_change,
        )
        self._qp_btn.grid(row=1, column=0, padx=16, pady=(0, 10), sticky="w")

        self._ms_btn = ctk.CTkRadioButton(
            type_frame,
            text="✅  Marking Scheme",
            variable=self._doc_type,
            value="marking_scheme",
            font=ctk.CTkFont(size=12),
            fg_color=C_PURPLE,
            command=self._on_type_change,
        )
        self._ms_btn.grid(row=1, column=1, padx=16, pady=(0, 10), sticky="w")

        # ── Form fields (scrollable area) ─────────────────────────────────────
        self._form = ctk.CTkFrame(self, fg_color="transparent")
        self._form.grid(row=2, column=0, padx=20, pady=0, sticky="nsew")
        self._form.grid_columnconfigure(1, weight=1)

        self._build_form()

        # ── File picker ───────────────────────────────────────────────────────
        file_frame = ctk.CTkFrame(self, fg_color="#f1f5f9", corner_radius=8)
        file_frame.grid(row=3, column=0, padx=20, pady=12, sticky="ew")
        file_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            file_frame, text="PDF File:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#374151",
        ).grid(row=0, column=0, columnspan=2, padx=12, pady=(10, 4), sticky="w")

        ctk.CTkEntry(
            file_frame,
            textvariable=self._filepath,
            placeholder_text="Select a PDF file...",
            height=34,
            font=ctk.CTkFont(size=11),
        ).grid(row=1, column=0, padx=(12, 6), pady=(0, 10), sticky="ew")

        ctk.CTkButton(
            file_frame,
            text="Browse",
            width=80, height=34,
            fg_color=C_NAVY,
            command=self._browse,
        ).grid(row=1, column=1, padx=(0, 12), pady=(0, 10))

        # ── Progress + Import ─────────────────────────────────────────────────
        self._progress_label = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=10), text_color="#6b7280"
        )
        self._progress_label.grid(row=4, column=0, padx=20, pady=(0, 4), sticky="w")

        self._progress_bar = ctk.CTkProgressBar(self, height=6)
        self._progress_bar.grid(row=5, column=0, padx=20, pady=(0, 8), sticky="ew")
        self._progress_bar.set(0)

        self._import_btn = ctk.CTkButton(
            self,
            text="Import PDF",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=42,
            fg_color=C_NAVY,
            hover_color="#0f2740",
            corner_radius=8,
            command=self._do_import,
        )
        self._import_btn.grid(row=6, column=0, padx=20, pady=(0, 20), sticky="ew")

    def _build_form(self):
        """Build the metadata form. Rebuilt when doc_type changes."""
        for w in self._form.winfo_children():
            w.destroy()

        is_ms = self._doc_type.get() == "marking_scheme"
        row   = 0

        def label(text):
            ctk.CTkLabel(
                self._form, text=text,
                font=ctk.CTkFont(size=11),
                text_color="#374151",
                width=90, anchor="w",
            ).grid(row=row, column=0, padx=(0, 8), pady=4, sticky="w")

        def combo(var, values, **kw):
            ctk.CTkComboBox(
                self._form, variable=var, values=values,
                height=32, font=ctk.CTkFont(size=11), **kw
            ).grid(row=row, column=1, pady=4, sticky="ew")

        def entry(var, placeholder=""):
            ctk.CTkEntry(
                self._form, textvariable=var,
                placeholder_text=placeholder,
                height=32, font=ctk.CTkFont(size=11),
            ).grid(row=row, column=1, pady=4, sticky="ew")

        # Level
        label("Level:")
        combo(self._level, LEVELS)
        row += 1

        # Subject
        label("Subject:")
        entry(self._subject, "e.g. Physics, Chemistry")
        row += 1

        if is_ms:
            # Topic (marking scheme book topic)
            label("Topic:")
            entry(self._topic, "e.g. Topic 5: The Internet")
            row += 1

            # Marking scheme document metadata
            label("Year (optional):")
            combo(self._year, [""] + YEARS)
            row += 1

            label("Season (optional):")
            combo(self._season, [""] + SEASONS)
            row += 1

            label("Paper (optional):")
            combo(self._paper, [""] + PAPERS)
            row += 1

            label("Variant (optional):")
            combo(self._variant, [""] + VARIANTS)
            row += 1
        else:
            # Full question paper fields
            label("Year:")
            combo(self._year, YEARS)
            row += 1

            label("Season:")
            combo(self._season, SEASONS)
            row += 1

            label("Paper:")
            combo(self._paper, PAPERS)
            row += 1

            label("Variant:")
            combo(self._variant, VARIANTS)
            row += 1

        # Colour hint for marking scheme mode
        if is_ms:
            ctk.CTkLabel(
                self._form,
                text="✅ Marking scheme mode: detects 'Question #N:' patterns",
                font=ctk.CTkFont(size=10),
                text_color=C_PURPLE,
            ).grid(row=row, column=0, columnspan=2, pady=(8, 0), sticky="w")

    def _on_type_change(self):
        self._build_form()

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Select PDF",
            filetypes=[("PDF files", "*.pdf")],
        )
        if path:
            self._filepath.set(path)

    def _do_import(self):
        fp = self._filepath.get().strip()
        if not fp:
            self._progress_label.configure(text="Please select a PDF file.", text_color="#dc2626")
            return

        doc_type = self._doc_type.get()
        year_val = self._year.get()

        metadata = {
            "doc_type": doc_type,
            "level":    self._level.get(),
            "subject":  self._subject.get(),
            "year":     int(year_val) if year_val and year_val.isdigit() else None,
            "season":   self._season.get() or "",
            "paper":    int(self._paper.get()) if self._paper.get().isdigit() else None,
            "variant":  int(self._variant.get()) if self._variant.get().isdigit() else None,
            "topic":    self._topic.get() if doc_type == "marking_scheme" else "",
        }

        self._import_btn.configure(state="disabled", text="Importing...")
        self._progress_bar.set(0)

        from core.import_worker import ImportWorker
        worker = ImportWorker(
            filepath    = fp,
            metadata    = metadata,
            on_progress = self._on_progress,
            on_complete = self._on_complete,
        )
        worker.start()

    def _on_progress(self, arg1, arg2=None):
        """Handle progress callback from background worker.

        ImportWorker currently calls on_progress(message, percent), while
        other callers may use (percent, message). Normalize both.
        """
        if arg2 is None:
            # If only one argument is provided, we cannot update a progress bar.
            msg = str(arg1)
            pct = 0
        else:
            if isinstance(arg1, str) and isinstance(arg2, (int, float)):
                msg = arg1
                pct = arg2
            else:
                msg = str(arg2)
                pct = arg1

        self.after(0, lambda: self.__update_progress(pct, msg))

    def __update_progress(self, pct, msg: str):
        try:
            pct_value = float(pct)
        except (TypeError, ValueError):
            pct_value = 0.0

        self._progress_bar.set(min(max(pct_value / 100, 0.0), 1.0))
        self._progress_label.configure(text=msg, text_color="#374151")

    def _on_complete(self, success: bool, message: str):
        self.after(0, lambda: self.__finish(success, message))

    def __finish(self, success: bool, message: str):
        self._import_btn.configure(state="normal", text="Import PDF")
        if success:
            self._progress_label.configure(text=f"✓ {message}", text_color="#16a34a")
            self._progress_bar.set(1)
            self.on_import_complete(True, message)
            self.after(1500, self.destroy)
        else:
            self._progress_label.configure(text=f"✗ {message}", text_color="#dc2626")
            self._progress_bar.set(0)
            self.on_import_complete(False, message)