"""
ui/import_dialog.py
====================
Modal dialog for importing a new PDF.
Collects metadata (level/subject/year/season/variant/paper),
then runs ImportWorker in background thread.
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from typing import Callable

from core.import_worker import ImportWorker

C_NAVY   = "#1a3a5c"
C_BLUE   = "#2563eb"
C_WHITE  = "#ffffff"
C_BG     = "#f8fafc"

LEVELS   = ["O-Level", "A-Level", "AS-Level", "IGCSE"]
SEASONS  = ["May/June", "Oct/Nov", "Feb/Mar"]
VARIANTS = ["1", "2", "3", "4"]
PAPERS   = ["1", "2", "3", "4", "5", "6"]
YEARS    = [str(y) for y in range(2000, 2041)][::-1]


class ImportDialog(ctk.CTkToplevel):
    def __init__(self, parent, on_import_complete: Callable):
        super().__init__(parent)
        self.on_import_complete = on_import_complete
        self.selected_file = tk.StringVar()
        self._importing = False

        self.title("Import PDF")
        self.geometry("540x620")
        self.resizable(False, False)
        self.configure(fg_color=C_BG)
        self._center()
        self._build()

    def _center(self):
        self.update_idletasks()
        pw = self.master.winfo_x() + self.master.winfo_width() // 2
        ph = self.master.winfo_y() + self.master.winfo_height() // 2
        self.geometry(f"+{pw - 270}+{ph - 310}")

    def _build(self):
        # Title
        ctk.CTkLabel(
            self,
            text="Import Past Paper PDF",
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color=C_NAVY,
        ).pack(pady=(20, 4), padx=24, anchor="w")

        ctk.CTkLabel(
            self,
            text="Select a PDF and fill in its metadata.",
            font=ctk.CTkFont(size=12),
            text_color="#6b7280",
        ).pack(pady=(0, 16), padx=24, anchor="w")

        # File picker
        file_frame = ctk.CTkFrame(self, fg_color="#e8f0fe", corner_radius=10)
        file_frame.pack(fill="x", padx=24, pady=(0, 16))

        ctk.CTkButton(
            file_frame,
            text="📂  Choose PDF File",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=C_BLUE,
            hover_color="#1d4ed8",
            corner_radius=8,
            height=40,
            command=self._browse_file,
        ).pack(pady=(14, 8), padx=16)

        self.file_label = ctk.CTkLabel(
            file_frame,
            textvariable=self.selected_file,
            font=ctk.CTkFont(size=11),
            text_color="#374151",
            wraplength=440,
        )
        self.file_label.pack(pady=(0, 14), padx=16)

        # Metadata form
        form = ctk.CTkFrame(self, fg_color=C_WHITE, corner_radius=10)
        form.pack(fill="x", padx=24, pady=(0, 16))

        ctk.CTkLabel(
            form,
            text="Paper Metadata",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=C_NAVY,
        ).grid(row=0, column=0, columnspan=4, padx=16, pady=(14, 8), sticky="w")

        self._fields = {}

        def add_dropdown(label, key, values, row, col):
            ctk.CTkLabel(
                form, text=label, font=ctk.CTkFont(size=11), text_color="#374151"
            ).grid(row=row, column=col * 2, padx=(16, 4), pady=6, sticky="w")
            var = ctk.StringVar(value=values[0] if values else "")
            dd = ctk.CTkOptionMenu(
                form, values=values, variable=var,
                width=120, height=32, corner_radius=6,
                fg_color="#f1f5f9", button_color="#cbd5e1",
                text_color="#1e293b",
            )
            dd.grid(row=row, column=col * 2 + 1, padx=(0, 16), pady=6, sticky="w")
            self._fields[key] = var

        def add_entry(label, key, row, col, placeholder=""):
            ctk.CTkLabel(
                form, text=label, font=ctk.CTkFont(size=11), text_color="#374151"
            ).grid(row=row, column=col * 2, padx=(16, 4), pady=6, sticky="w")
            var = ctk.StringVar()
            entry = ctk.CTkEntry(
                form, textvariable=var, width=120, height=32,
                placeholder_text=placeholder, corner_radius=6,
            )
            entry.grid(row=row, column=col * 2 + 1, padx=(0, 16), pady=6, sticky="w")
            self._fields[key] = var

        add_dropdown("Level",   "level",   LEVELS,   1, 0)
        add_dropdown("Year",    "year",    YEARS,    1, 1)
        add_dropdown("Season",  "season",  SEASONS,  2, 0)
        add_dropdown("Variant", "variant", VARIANTS, 2, 1)
        add_dropdown("Paper",   "paper",   PAPERS,   3, 0)
        add_entry("Subject", "subject", 3, 1, "e.g. Physics")

        form.grid_columnconfigure((1, 3), weight=1)

        # Progress area
        self.progress_label = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=12), text_color="#374151"
        )
        self.progress_label.pack(pady=(0, 4))

        self.progress_bar = ctk.CTkProgressBar(self, width=480, height=10)
        self.progress_bar.pack(pady=(0, 12), padx=24)
        self.progress_bar.set(0)

        # Import button
        self.import_btn = ctk.CTkButton(
            self,
            text="Import PDF",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=C_NAVY,
            hover_color="#0f2740",
            corner_radius=10,
            height=44,
            command=self._start_import,
        )
        self.import_btn.pack(pady=(0, 20), padx=24, fill="x")

    def _browse_file(self):
        path = filedialog.askopenfilename(
            title="Select Past Paper PDF",
            filetypes=[("PDF Files", "*.pdf"), ("All Files", "*.*")],
        )
        if path:
            self.selected_file.set(path)

    def _start_import(self):
        filepath = self.selected_file.get().strip()
        if not filepath:
            messagebox.showwarning("No File", "Please select a PDF file first.")
            return
        if not os.path.exists(filepath):
            messagebox.showerror("File Not Found", f"File not found:\n{filepath}")
            return

        metadata = {k: v.get().strip() for k, v in self._fields.items()}

        self._set_importing(True)
        self.progress_bar.set(0)

        worker = ImportWorker(
            filepath=filepath,
            metadata=metadata,
            on_progress=self._on_progress,
            on_complete=self._on_complete,
        )
        worker.start()

    def _on_progress(self, message: str, percent: int):
        self.after(0, lambda: self._update_progress(message, percent))

    def _update_progress(self, message: str, percent: int):
        self.progress_label.configure(text=message)
        self.progress_bar.set(percent / 100)

    def _on_complete(self, success: bool, message: str):
        self.after(0, lambda: self._finish(success, message))

    def _finish(self, success: bool, message: str):
        self._set_importing(False)
        if success:
            messagebox.showinfo("Import Complete", message)
            self.on_import_complete(True, message)
            self.destroy()
        else:
            messagebox.showerror("Import Failed", message)
            self.on_import_complete(False, message)
            self.progress_bar.set(0)
            self.progress_label.configure(text="")

    def _set_importing(self, state: bool):
        self._importing = state
        self.import_btn.configure(
            state="disabled" if state else "normal",
            text="Importing..." if state else "Import PDF",
        )
