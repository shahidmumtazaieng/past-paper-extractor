"""
ui/filter_panel.py
===================
Left-side filter panel.

NEW: Mode tabs at top — "Questions" vs "Marking Scheme"
When mode changes, the depth/question-depth dropdown adjusts,
and doc_type is injected into search filters automatically.
"""

import tkinter as tk
import customtkinter as ctk
from typing import Callable, Optional

C_NAVY   = "#1a3a5c"
C_BLUE   = "#2563eb"
C_WHITE  = "#ffffff"
C_BG     = "#f8fafc"
C_BORDER = "#e2e8f0"
C_PURPLE = "#7c3aed"
C_GREEN  = "#16a34a"


class FilterPanel(ctk.CTkFrame):
    def __init__(self, parent, on_search: Callable, **kwargs):
        kwargs.setdefault("corner_radius", 12)
        super().__init__(parent, **kwargs)
        self.on_search = on_search

        # State
        self._mode        = tk.StringVar(value="question_paper")  # or "marking_scheme"
        self._level       = tk.StringVar(value="")
        self._subject     = tk.StringVar(value="")
        self._year        = tk.StringVar(value="")
        self._season      = tk.StringVar(value="")
        self._paper       = tk.StringVar(value="")
        self._variant     = tk.StringVar(value="")
        self._topic       = tk.StringVar(value="")
        self._q_depth     = tk.StringVar(value="Main only (1,2,3…)")
        self._q_number    = tk.StringVar(value="")

        self._filter_options = {}
        self._build()

    # ─── Build ───────────────────────────────────────────────────────────────

    def _build(self):
        self.grid_columnconfigure(0, weight=1)

        # Title
        ctk.CTkLabel(
            self,
            text="Filters",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=C_NAVY,
        ).grid(row=0, column=0, padx=16, pady=(16, 8), sticky="w")

        # ── Mode tabs ─────────────────────────────────────────────────────────
        tab_frame = ctk.CTkFrame(self, fg_color="#f1f5f9", corner_radius=8)
        tab_frame.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="ew")
        tab_frame.grid_columnconfigure((0, 1), weight=1)

        self._qp_tab = ctk.CTkButton(
            tab_frame,
            text="📄 Questions",
            height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=C_NAVY,
            text_color=C_WHITE,
            hover_color="#0f2740",
            corner_radius=6,
            command=lambda: self._set_mode("question_paper"),
        )
        self._qp_tab.grid(row=0, column=0, padx=4, pady=4, sticky="ew")

        self._ms_tab = ctk.CTkButton(
            tab_frame,
            text="✅ Marking Scheme",
            height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="transparent",
            text_color="#6b7280",
            hover_color="#e2e8f0",
            corner_radius=6,
            command=lambda: self._set_mode("marking_scheme"),
        )
        self._ms_tab.grid(row=0, column=1, padx=4, pady=4, sticky="ew")

        # ── Scrollable filter area ────────────────────────────────────────────
        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent", corner_radius=0
        )
        self._scroll.grid(row=2, column=0, sticky="nsew", padx=4)
        self._scroll.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_filters()

        # ── Search button ─────────────────────────────────────────────────────
        ctk.CTkButton(
            self,
            text="🔍  Search",
            height=40,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=C_NAVY,
            hover_color="#0f2740",
            corner_radius=8,
            command=self._do_search,
        ).grid(row=3, column=0, padx=12, pady=(8, 6), sticky="ew")

        ctk.CTkButton(
            self,
            text="Clear",
            height=32,
            font=ctk.CTkFont(size=11),
            fg_color="transparent",
            border_width=1,
            border_color=C_BORDER,
            text_color="#6b7280",
            hover_color="#f1f5f9",
            corner_radius=8,
            command=self._clear_filters,
        ).grid(row=4, column=0, padx=12, pady=(0, 12), sticky="ew")

    def _set_mode(self, mode: str):
        self._mode.set(mode)
        # Update tab button styles
        if mode == "question_paper":
            self._qp_tab.configure(fg_color=C_NAVY,      text_color=C_WHITE)
            self._ms_tab.configure(fg_color="transparent", text_color="#6b7280")
        else:
            self._qp_tab.configure(fg_color="transparent", text_color="#6b7280")
            self._ms_tab.configure(fg_color=C_PURPLE,     text_color=C_WHITE)
        self._build_filters()

    def _build_filters(self):
        """Rebuild filter fields based on current mode."""
        for w in self._scroll.winfo_children():
            w.destroy()

        mode = self._mode.get()
        is_ms = mode == "marking_scheme"
        opts  = self._filter_options
        row   = 0

        def section(title, color=C_NAVY):
            nonlocal row
            ctk.CTkLabel(
                self._scroll,
                text=title,
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=color,
            ).grid(row=row, column=0, padx=8, pady=(12, 2), sticky="w")
            row += 1

        def field(label_text, var, values=None, placeholder=""):
            nonlocal row
            ctk.CTkLabel(
                self._scroll,
                text=label_text,
                font=ctk.CTkFont(size=10),
                text_color="#374151",
            ).grid(row=row, column=0, padx=8, pady=(4, 0), sticky="w")
            row += 1
            if values is not None:
                w = ctk.CTkComboBox(
                    self._scroll,
                    variable=var,
                    values=[""] + (values if isinstance(values, list) else list(values)),
                    height=30,
                    font=ctk.CTkFont(size=11),
                )
            else:
                w = ctk.CTkEntry(
                    self._scroll,
                    textvariable=var,
                    placeholder_text=placeholder,
                    height=30,
                    font=ctk.CTkFont(size=11),
                )
            w.grid(row=row, column=0, padx=8, pady=(0, 4), sticky="ew")
            row += 1

        # ── Common fields ─────────────────────────────────────────────────────
        section("DOCUMENT", color=C_PURPLE if is_ms else C_NAVY)
        field("Level",   self._level,   opts.get("levels", []))
        field("Subject", self._subject, opts.get("subjects", []))

        if is_ms:
            # Marking scheme specific
            field("Topic", self._topic, opts.get("topics", []),
                  placeholder="e.g. Topic 5")
            field("Year (optional)", self._year, opts.get("years", []))

            section("QUESTION NUMBER", color=C_PURPLE)
            field("Question #", self._q_number, placeholder="e.g. 1, 5, 12")

        else:
            # Question paper fields
            field("Year",    self._year,    opts.get("years", []))
            field("Season",  self._season,  opts.get("seasons", []))
            field("Paper",   self._paper,   opts.get("papers", []))
            field("Variant", self._variant, opts.get("variants", []))

            section("QUESTION DEPTH")
            depth_opts = [
                "Any",
                "Main only (1,2,3…)",
                "Sub-questions (a,b,c)",
                "Sub-sub (i,ii,iii)",
            ]
            ctk.CTkComboBox(
                self._scroll,
                variable=self._q_depth,
                values=depth_opts,
                height=30,
                font=ctk.CTkFont(size=11),
            ).grid(row=row, column=0, padx=8, pady=(0, 4), sticky="ew")
            row += 1

            section("QUESTION NUMBER")
            field("Question #", self._q_number, placeholder="e.g. 1, 2(a)")

    # ─── Public ───────────────────────────────────────────────────────────────

    def refresh_options(self, options: dict):
        """Called after import to update dropdown values."""
        self._filter_options = options
        self._build_filters()

    # ─── Search ───────────────────────────────────────────────────────────────

    def _do_search(self):
        mode  = self._mode.get()
        is_ms = mode == "marking_scheme"

        # Map depth label → integer
        depth_map = {
            "Any":                    None,
            "Main only (1,2,3…)":     0,
            "Sub-questions (a,b,c)":  1,
            "Sub-sub (i,ii,iii)":     2,
        }
        depth = depth_map.get(self._q_depth.get(), 0) if not is_ms else None

        filters = {
            "doc_type":       mode,
            "level":          self._level.get()   or None,
            "subject":        self._subject.get() or None,
            "year":           int(self._year.get()) if self._year.get().isdigit() else None,
            "question_level": depth,
        }

        if is_ms:
            filters["topic"]           = self._topic.get() or None
            filters["question_number"] = self._q_number.get().strip() or None
        else:
            filters["season"]          = self._season.get()  or None
            filters["paper"]           = int(self._paper.get())   if self._paper.get().isdigit()   else None
            filters["variant"]         = int(self._variant.get()) if self._variant.get().isdigit() else None
            filters["question_number"] = self._q_number.get().strip() or None

        self.on_search(filters)

    def _clear_filters(self):
        for var in [self._level, self._subject, self._year, self._season,
                    self._paper, self._variant, self._topic, self._q_number]:
            var.set("")
        self._q_depth.set("Main only (1,2,3…)")
        self._build_filters()