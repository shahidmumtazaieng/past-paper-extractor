"""
ui/documents_panel.py
======================
Modal dialog to view and manage all imported PDFs.
Allows deletion of documents from the library.
"""

from tkinter import messagebox
import customtkinter as ctk
from typing import Callable
from database.db_manager import get_all_documents, delete_document

C_NAVY = "#1a3a5c"
C_RED  = "#dc2626"


class DocumentsPanel(ctk.CTkToplevel):
    def __init__(self, parent, on_change: Callable):
        super().__init__(parent)
        self.on_change = on_change
        self.title("Manage Imported PDFs")
        self.geometry("700x500")
        self.resizable(True, True)
        self.configure(fg_color="#f8fafc")
        self._center()
        self._build()
        self._load()

    def _center(self):
        self.update_idletasks()
        pw = self.master.winfo_x() + self.master.winfo_width() // 2
        ph = self.master.winfo_y() + self.master.winfo_height() // 2
        self.geometry(f"+{pw - 350}+{ph - 250}")

    def _build(self):
        ctk.CTkLabel(
            self,
            text="Imported PDF Library",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=C_NAVY,
        ).pack(pady=(20, 4), padx=20, anchor="w")

        ctk.CTkLabel(
            self,
            text="All PDFs you have imported. Delete removes the index but NOT the original file.",
            font=ctk.CTkFont(size=11),
            text_color="#6b7280",
        ).pack(pady=(0, 12), padx=20, anchor="w")

        self.scroll = ctk.CTkScrollableFrame(
            self, fg_color="#ffffff", corner_radius=10
        )
        self.scroll.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def _load(self):
        for w in self.scroll.winfo_children():
            w.destroy()

        docs = get_all_documents()
        if not docs:
            ctk.CTkLabel(
                self.scroll,
                text="No PDFs imported yet.",
                font=ctk.CTkFont(size=13),
                text_color="#94a3b8",
            ).pack(pady=40)
            return

        for doc in docs:
            self._add_doc_row(doc)

    def _add_doc_row(self, doc: dict):
        row = ctk.CTkFrame(
            self.scroll, fg_color="#f8fafc",
            corner_radius=8, border_width=1, border_color="#e2e8f0"
        )
        row.pack(fill="x", padx=8, pady=4)
        row.grid_columnconfigure(1, weight=1)

        # Status indicator
        status_color = {"indexed": "#16a34a", "pending": "#f59e0b", "error": "#dc2626"}.get(
            doc.get("status", ""), "#9ca3af"
        )
        indicator = ctk.CTkFrame(row, fg_color=status_color, width=6, corner_radius=3)
        indicator.grid(row=0, column=0, padx=(10, 8), pady=10, rowspan=2, sticky="ns")

        # File info
        ctk.CTkLabel(
            row,
            text=doc.get("filename", "Unknown"),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#1e293b",
        ).grid(row=0, column=1, padx=4, pady=(10, 2), sticky="w")

        meta = (
            f"{doc.get('level', '—')}  ·  {doc.get('subject', '—')}  ·  "
            f"{doc.get('year', '—')} {doc.get('season', '')}  ·  "
            f"Paper {doc.get('paper', '—')} Var {doc.get('variant', '—')}  ·  "
            f"Status: {doc.get('status', '—')}  ·  "
            f"Imported: {(doc.get('imported_at') or '')[:10]}"
        )
        ctk.CTkLabel(
            row,
            text=meta,
            font=ctk.CTkFont(size=10),
            text_color="#6b7280",
        ).grid(row=1, column=1, padx=4, pady=(0, 10), sticky="w")

        # Delete button
        ctk.CTkButton(
            row,
            text="Delete",
            font=ctk.CTkFont(size=11),
            fg_color="transparent",
            border_color="#fca5a5",
            border_width=1,
            text_color=C_RED,
            hover_color="#fef2f2",
            corner_radius=6,
            height=30,
            width=70,
            command=lambda d=doc: self._confirm_delete(d),
        ).grid(row=0, column=2, padx=12, pady=10, rowspan=2)

    def _confirm_delete(self, doc: dict):
        if messagebox.askyesno(
            "Confirm Delete",
            f"Remove '{doc['filename']}' from the library?\n\n"
            f"This deletes the index only — your original PDF is NOT deleted.",
        ):
            delete_document(doc["id"])
            self.on_change()
            self._load()
