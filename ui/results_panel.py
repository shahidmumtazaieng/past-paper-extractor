"""
ui/results_panel.py
====================
Right panel showing search results.

Features:
- Checkbox per question for selection
- "Select All" / "Deselect All"
- Lazy image loading (renders on demand, not all at once)
- Export to PDF button with output path chooser
- Question count summary
"""

import io
import json
import threading
import tkinter as tk
from tkinter import filedialog
from pathlib import Path
import customtkinter as ctk
from PIL import Image as PILImage, ImageTk
from typing import Callable, Optional

from core.question_extractor import render_question_crop

C_NAVY  = "#1a3a5c"
C_BLUE  = "#2563eb"
C_WHITE = "#ffffff"
C_BG    = "#f8fafc"

PREVIEW_HEIGHT_PX = 180   # max height for inline preview thumbnails


class ResultsPanel(ctk.CTkFrame):
    def __init__(self, parent, on_export: Callable, **kwargs):
        kwargs.setdefault("corner_radius", 12)
        super().__init__(parent, **kwargs)
        self.on_export = on_export
        self._question_rows: list[dict] = []
        self._checkboxes: list[ctk.CTkCheckBox] = []
        self._check_vars: list[ctk.BooleanVar] = []
        self._image_refs: list = []    # keep PIL refs alive

        self._build()

    def _build(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Header bar
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Results",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=C_NAVY,
        ).grid(row=0, column=0, sticky="w")

        self.count_label = ctk.CTkLabel(
            header,
            text="No search yet",
            font=ctk.CTkFont(size=11),
            text_color="#6b7280",
        )
        self.count_label.grid(row=0, column=1, sticky="e")

        # Select All / Deselect All
        sel_frame = ctk.CTkFrame(self, fg_color="transparent")
        sel_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 6))

        ctk.CTkButton(
            sel_frame,
            text="Select All",
            font=ctk.CTkFont(size=11),
            fg_color="transparent",
            text_color=C_BLUE,
            hover_color="#eff6ff",
            corner_radius=6,
            height=26,
            width=80,
            command=self._select_all,
        ).pack(side="left")

        ctk.CTkButton(
            sel_frame,
            text="Deselect All",
            font=ctk.CTkFont(size=11),
            fg_color="transparent",
            text_color="#6b7280",
            hover_color="#f1f5f9",
            corner_radius=6,
            height=26,
            width=90,
            command=self._deselect_all,
        ).pack(side="left", padx=4)

        self.selected_label = ctk.CTkLabel(
            sel_frame,
            text="0 selected",
            font=ctk.CTkFont(size=11),
            text_color="#6b7280",
        )
        self.selected_label.pack(side="right")

        # Scrollable results list
        self.scroll = ctk.CTkScrollableFrame(
            self,
            fg_color=C_BG,
            corner_radius=8,
        )
        self.scroll.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 8))
        self.grid_rowconfigure(2, weight=1)

        # Empty state label
        self.empty_label = ctk.CTkLabel(
            self.scroll,
            text="Use the filters on the left\nand click Search.",
            font=ctk.CTkFont(size=13),
            text_color="#94a3b8",
            justify="center",
        )
        self.empty_label.pack(expand=True, pady=80)

        # Export bar
        export_bar = ctk.CTkFrame(self, fg_color="#f1f5f9", corner_radius=8)
        export_bar.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 12))
        export_bar.grid_columnconfigure(0, weight=1)

        self.output_path_var = tk.StringVar(value=str(Path.home() / "Desktop" / "questions.pdf"))

        ctk.CTkEntry(
            export_bar,
            textvariable=self.output_path_var,
            height=34,
            corner_radius=6,
            font=ctk.CTkFont(size=11),
        ).grid(row=0, column=0, padx=(12, 6), pady=10, sticky="ew")

        ctk.CTkButton(
            export_bar,
            text="📁",
            width=36,
            height=34,
            corner_radius=6,
            fg_color="#e2e8f0",
            text_color="#374151",
            hover_color="#cbd5e1",
            command=self._browse_output,
        ).grid(row=0, column=1, padx=(0, 6), pady=10)

        ctk.CTkButton(
            export_bar,
            text="Export Selected → PDF",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=C_NAVY,
            hover_color="#0f2740",
            corner_radius=8,
            height=34,
            command=self._do_export,
        ).grid(row=0, column=2, padx=(0, 12), pady=10)

    # ─── Public API ───────────────────────────────────────────

    def clear(self):
        for w in self.scroll.winfo_children():
            w.destroy()
        self._question_rows.clear()
        self._checkboxes.clear()
        self._check_vars.clear()
        self._image_refs.clear()
        self.empty_label = ctk.CTkLabel(
            self.scroll,
            text="Searching...",
            font=ctk.CTkFont(size=13),
            text_color="#94a3b8",
        )
        self.empty_label.pack(expand=True, pady=80)

    def show_results(self, results: list[dict]):
        # Clear old
        for w in self.scroll.winfo_children():
            w.destroy()
        self._question_rows = results
        self._checkboxes.clear()
        self._check_vars.clear()
        self._image_refs.clear()

        self.count_label.configure(text=f"{len(results)} question(s) found")

        if not results:
            ctk.CTkLabel(
                self.scroll,
                text="No questions matched your filters.\nTry broadening the search.",
                font=ctk.CTkFont(size=13),
                text_color="#94a3b8",
                justify="center",
            ).pack(expand=True, pady=80)
            self.selected_label.configure(text="0 selected")
            return

        # For sub-sub mode (level-2 cards): inject a visual group header
        # each time the parent sub-question changes.
        # e.g.  ── 5(b) ──────────────  then (i) card, (ii) card, (iii) card
        #        ── 5(c) ──────────────  then (i) card, (ii) card
        last_parent = None
        for q in results:
            if q.get("question_level", 0) == 2:
                parent = q.get("_parent_sub") or q["question_number"].rsplit("(", 1)[0]
                if parent != last_parent:
                    self._add_parent_separator(parent)
                    last_parent = parent
            else:
                last_parent = None   # reset when non-subsub cards mixed in
            self._add_question_card(q)

        self._update_selected_count()

    def _add_parent_separator(self, parent_label: str):
        """Visual group header for sub-sub cards — shows the parent (a)/(b) label."""
        sep = ctk.CTkFrame(self.scroll, fg_color="transparent")
        sep.pack(fill="x", padx=8, pady=(10, 2))

        # Left line
        ctk.CTkFrame(sep, fg_color="#cbd5e1", height=1, width=40).pack(
            side="left", padx=(0, 8), pady=8
        )

        # Parent label badge
        badge = ctk.CTkFrame(sep, fg_color="#7c3aed", corner_radius=6)
        badge.pack(side="left")
        ctk.CTkLabel(
            badge,
            text=f"  {parent_label}  ",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#ffffff",
        ).pack(padx=2, pady=3)

        # Right label
        ctk.CTkLabel(
            sep,
            text="  sub-sub questions:",
            font=ctk.CTkFont(size=10),
            text_color="#6b7280",
        ).pack(side="left", padx=4)

        # Expand line
        ctk.CTkFrame(sep, fg_color="#cbd5e1", height=1).pack(
            side="left", fill="x", expand=True, pady=8
        )

    # ─── Private: Card building ───────────────────────────────

    def _add_question_card(self, q: dict):
        card = ctk.CTkFrame(
            self.scroll,
            fg_color=C_WHITE,
            corner_radius=10,
            border_width=1,
            border_color="#e2e8f0",
        )
        card.pack(fill="x", padx=4, pady=6)
        card.grid_columnconfigure(1, weight=1)

        # Checkbox
        var = ctk.BooleanVar(value=False)
        cb = ctk.CTkCheckBox(
            card,
            text="",
            variable=var,
            width=24,
            command=self._update_selected_count,
        )
        cb.grid(row=0, column=0, padx=(12, 4), pady=12, rowspan=3, sticky="nw")
        self._checkboxes.append(cb)
        self._check_vars.append(var)

        # ── Badge row ────────────────────────────────────────────────────
        q_num   = q["question_number"]
        q_level = q.get("question_level", 0)
        is_cont = q.get("_is_continuation", False)
        seg_cnt = q.get("_segment_count", 1)

        # Color by depth level
        badge_colors = {0: "#1a3a5c", 1: "#0d7a5f", 2: "#7c3aed"}
        badge_color  = badge_colors.get(q_level, C_NAVY)

        level_labels = {0: "Full Question", 1: "Sub-question", 2: "Sub-sub"}
        level_text   = level_labels.get(q_level, "")

        badge_row = ctk.CTkFrame(card, fg_color="transparent")
        badge_row.grid(row=0, column=1, padx=(4, 12), pady=(12, 4), sticky="w")

        # Main badge
        badge_frame = ctk.CTkFrame(badge_row, fg_color=badge_color, corner_radius=6)
        badge_frame.pack(side="left", padx=(0, 6))
        ctk.CTkLabel(
            badge_frame,
            text=f"Q {q_num}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=C_WHITE,
        ).pack(padx=8, pady=(3, 0))
        ctk.CTkLabel(
            badge_frame,
            text=level_text,
            font=ctk.CTkFont(size=9),
            text_color="#cbd5e1",
        ).pack(padx=8, pady=(0, 3))

        # Segment count badge (only for grouped questions)
        if seg_cnt > 1:
            seg_badge = ctk.CTkFrame(badge_row, fg_color="#f1f5f9", corner_radius=6)
            seg_badge.pack(side="left", padx=(0, 6))
            ctk.CTkLabel(
                seg_badge,
                text=f"{seg_cnt} parts",
                font=ctk.CTkFont(size=10),
                text_color="#475569",
            ).pack(padx=6, pady=4)

        # Continuation badge
        if is_cont:
            cont_badge = ctk.CTkFrame(badge_row, fg_color="#fef3c7", corner_radius=6)
            cont_badge.pack(side="left")
            ctk.CTkLabel(
                cont_badge,
                text="↪ continued",
                font=ctk.CTkFont(size=10),
                text_color="#92400e",
            ).pack(padx=6, pady=4)

        # Multi-page badge
        if q.get("_is_multipage"):
            pg_count = q.get("_page_count", 2)
            mp_badge = ctk.CTkFrame(badge_row, fg_color="#dbeafe", corner_radius=6)
            mp_badge.pack(side="left", padx=(6, 0))
            ctk.CTkLabel(
                mp_badge,
                text=f"📄×{pg_count} pages",
                font=ctk.CTkFont(size=10),
                text_color="#1e40af",
            ).pack(padx=6, pady=4)

        # ── Metadata row ────────────────────────────────────────────────
        marks_str = f"  ·  {q['marks']} marks" if q.get("marks") else ""
        is_ms = q.get("doc_type") == "marking_scheme"

        if is_ms:
            # Marking scheme card — show topic and source ref
            topic_str  = q.get("topic", "") or ""
            source_ref = q.get("source_ref", "") or ""
            meta_parts = []
            if q.get("level"):   meta_parts.append(q["level"])
            if q.get("subject"): meta_parts.append(q["subject"])
            if topic_str:        meta_parts.append(topic_str)
            meta = "  ·  ".join(meta_parts) + marks_str
        else:
            meta = (
                f"{q.get('level', '')}  ·  {q.get('subject', '')}  ·  "
                f"{q.get('year', '')} {q.get('season', '')}  ·  "
                f"Paper {q.get('paper', '')} Var {q.get('variant', '')}"
                f"{marks_str}"
            )
            source_ref = ""

        ctk.CTkLabel(
            card,
            text=meta.strip(" · "),
            font=ctk.CTkFont(size=10),
            text_color="#6b7280",
        ).grid(row=1, column=1, padx=(4, 12), pady=0, sticky="w")

        # Source ref (marking scheme only) e.g. "[Q10(d) Paper 11 M/J/18]"
        if source_ref:
            ctk.CTkLabel(
                card,
                text=f"📌 {source_ref}",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color="#7c3aed",
            ).grid(row=2, column=1, padx=(4, 12), pady=(0, 2), sticky="w")

        # ── Sub-question / sub-sub summary ─────────────────────────────────
        sub_summary = q.get("_sub_summary", "")
        if sub_summary:
            if q_level == 0:
                prefix = "Contains:"
                color  = "#2563eb"
            elif q_level == 1:
                prefix = "Includes:"
                color  = "#0d7a5f"
            else:
                # Level 2: show "Part of: 5(b)  →  (i) (ii) [iii]"
                prefix = "Part of:"
                color  = "#7c3aed"
            ctk.CTkLabel(
                card,
                text=f"{prefix} {sub_summary}",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=color,
            ).grid(row=2, column=1, padx=(4, 12), pady=(0, 2), sticky="w")

        # ── Text snippet ────────────────────────────────────────────────
        snippet = (q.get("text_content") or "")[:140].replace("\n", "  ")
        if len(q.get("text_content") or "") > 140:
            snippet += "..."
        ctk.CTkLabel(
            card,
            text=snippet,
            font=ctk.CTkFont(size=11),
            text_color="#374151",
            wraplength=500,
            justify="left",
        ).grid(row=3, column=1, padx=(4, 12), pady=(2, 0), sticky="w")

        # ── Preview image (lazy loaded) ─────────────────────────────────
        preview_frame = ctk.CTkFrame(card, fg_color="#f8fafc", corner_radius=6)
        preview_frame.grid(row=4, column=0, columnspan=3, padx=12, pady=(6, 12), sticky="ew")

        loading_label = ctk.CTkLabel(
            preview_frame,
            text="Loading preview...",
            font=ctk.CTkFont(size=10),
            text_color="#9ca3af",
        )
        loading_label.pack(pady=8)

        threading.Thread(
            target=self._load_preview,
            args=(q, preview_frame, loading_label),
            daemon=True,
        ).start()

    def _load_preview(self, q: dict, frame: ctk.CTkFrame, loading_label: ctk.CTkLabel):
        """Render question image in background, then update UI."""
        try:
            from core.question_extractor import render_question_crop_smart
            png_bytes = render_question_crop_smart(q, dpi=100)

            img_buf = io.BytesIO(png_bytes)
            pil_img = PILImage.open(img_buf)

            # Multi-page questions get taller preview (each extra page adds ~180px)
            page_count = q.get("_page_count", 1)
            max_h = PREVIEW_HEIGHT_PX * max(1, page_count)
            max_h = min(max_h, 600)   # cap at 600px so UI doesn't become unwieldy

            # Constrain height while preserving aspect ratio
            w, h = pil_img.size
            if h > max_h:
                scale = max_h / h
                pil_img = pil_img.resize((int(w * scale), max_h), PILImage.LANCZOS)

            ctk_img = ctk.CTkImage(light_image=pil_img, size=pil_img.size)
            self._image_refs.append(ctk_img)  # prevent GC

            self.after(0, lambda: self._set_preview_image(frame, loading_label, ctk_img))
        except Exception as e:
            self.after(0, lambda: loading_label.configure(
                text=f"Preview unavailable", text_color="#ef4444"
            ))

    def _set_preview_image(self, frame, loading_label, ctk_img):
        loading_label.destroy()
        lbl = ctk.CTkLabel(frame, image=ctk_img, text="")
        lbl.pack(pady=6, padx=8)

    # ─── Selection helpers ────────────────────────────────────

    def _select_all(self):
        for v in self._check_vars:
            v.set(True)
        self._update_selected_count()

    def _deselect_all(self):
        for v in self._check_vars:
            v.set(False)
        self._update_selected_count()

    def _update_selected_count(self):
        n = sum(1 for v in self._check_vars if v.get())
        self.selected_label.configure(text=f"{n} selected")

    # ─── Export ───────────────────────────────────────────────

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            title="Save PDF As",
            defaultextension=".pdf",
            filetypes=[("PDF Files", "*.pdf")],
            initialfile="questions.pdf",
        )
        if path:
            self.output_path_var.set(path)

    def _do_export(self):
        selected = [
            self._question_rows[i]
            for i, v in enumerate(self._check_vars)
            if v.get()
        ]
        self.on_export(selected, self.output_path_var.get())