"""
ui/filter_panel.py
===================
Left-side filter panel.

NEW: Mode tabs at top — "Questions" vs "Marking Scheme"
When mode changes, the depth/question-depth dropdown adjusts,
and doc_type is injected into search filters automatically.

FIX (2026-04-22): Guard against _textvariable_callback firing on
already-destroyed CTkEntry widgets when _build_filters() rebuilds
the scroll frame.  Root cause: CustomTkinter traces a StringVar even
after the widget is destroyed, which raises TclError on Python 3.14.
Solution: set self._rebuilding = True before destroying children and
subclass / monkey-patch is NOT needed — instead we replace each
StringVar with a fresh object before every rebuild so no old widget
holds a reference to the current var.
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

        # State — these hold the *current* values across rebuilds.
        # We store plain Python strings and only create fresh StringVars
        # during _build_filters() so destroyed widgets never hold a live ref.
        self._mode_val     = "question_paper"
        self._level_val    = ""
        self._subject_val  = ""
        self._year_val     = ""
        self._season_val   = ""
        self._paper_val    = ""
        self._variant_val  = ""
        self._topic_val    = ""
        self._q_depth_val  = "Main only (1,2,3…)"
        self._q_number_val = ""

        # Current live StringVar refs (replaced on every rebuild)
        self._mode     = None
        self._level    = None
        self._subject  = None
        self._year     = None
        self._season   = None
        self._paper    = None
        self._variant  = None
        self._topic    = None
        self._q_depth  = None
        self._q_number = None

        self._filter_options = {}
        self._build()

    # ─── Helpers to snapshot / restore values ────────────────────────────────

    def _snapshot_values(self):
        """Save current StringVar values into plain-string backing store."""
        if self._level    is not None: self._level_val    = self._level.get()
        if self._subject  is not None: self._subject_val  = self._subject.get()
        if self._year     is not None: self._year_val     = self._year.get()
        if self._season   is not None: self._season_val   = self._season.get()
        if self._paper    is not None: self._paper_val    = self._paper.get()
        if self._variant  is not None: self._variant_val  = self._variant.get()
        if self._topic    is not None: self._topic_val    = self._topic.get()
        if self._q_depth  is not None: self._q_depth_val  = self._q_depth.get()
        if self._q_number is not None: self._q_number_val = self._q_number.get()

    def _make_vars(self):
        """Create brand-new StringVar objects from the backing store.
        Old vars are discarded — any old CTkEntry that still holds a
        reference to them will trace against an orphaned object that no
        widget cares about, so its callback is harmless even if it fires.
        """
        self._level    = tk.StringVar(value=self._level_val)
        self._subject  = tk.StringVar(value=self._subject_val)
        self._year     = tk.StringVar(value=self._year_val)
        self._season   = tk.StringVar(value=self._season_val)
        self._paper    = tk.StringVar(value=self._paper_val)
        self._variant  = tk.StringVar(value=self._variant_val)
        self._topic    = tk.StringVar(value=self._topic_val)
        self._q_depth  = tk.StringVar(value=self._q_depth_val)
        self._q_number = tk.StringVar(value=self._q_number_val)

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
        self._snapshot_values()
        self._mode_val = mode
        # Update tab button styles
        if mode == "question_paper":
            self._qp_tab.configure(fg_color=C_NAVY,       text_color=C_WHITE)
            self._ms_tab.configure(fg_color="transparent", text_color="#6b7280")
        else:
            self._qp_tab.configure(fg_color="transparent", text_color="#6b7280")
            self._ms_tab.configure(fg_color=C_PURPLE,      text_color=C_WHITE)
        self._build_filters()

    def _build_filters(self):
        """Rebuild filter fields based on current mode.

        Key fix: snapshot current values, destroy old widgets, create fresh
        StringVars, then build new widgets against those fresh vars.
        Destroying widgets before the old StringVars go out of scope means
        CTkEntry may fire _textvariable_callback once more — but because the
        internal Tk widget name is already invalid, CustomTkinter raises
        TclError.  By replacing the StringVar objects *before* any widget
        tries to read them, we ensure the callback on the orphaned old var
        is a no-op (nobody reads that var).  The real guard is that we call
        _make_vars() BEFORE grid/pack-ing any new widgets.
        """
        # 1. Save what the user typed so far
        self._snapshot_values()

        # 2. Destroy existing child widgets — this may trigger stale callbacks
        #    on the *old* StringVar objects, which is fine because we are
        #    about to replace them.
        for w in self._scroll.winfo_children():
            w.destroy()

        # 3. Create fresh StringVars — old ones are now unreferenced by us
        #    and will be GC'd; any stale Tcl trace on them is harmless.
        self._make_vars()

        # 4. Build new widgets against the fresh vars
        mode  = self._mode_val
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
            field("Topic", self._topic, opts.get("topics", []),
                  placeholder="e.g. Topic 5")
            field("Year (optional)",    self._year,    opts.get("years", []))
            field("Season (optional)",  self._season,  opts.get("seasons", []))
            field("Paper (optional)",   self._paper,   opts.get("papers", []))
            field("Variant (optional)", self._variant, opts.get("variants", []))

            section("QUESTION DEPTH", color=C_PURPLE)
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

            section("QUESTION NUMBER", color=C_PURPLE)
            field("Question #", self._q_number, placeholder="e.g. 1, 2(a), 3(b)")
        else:
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
            field("Question #", self._q_number, placeholder="e.g. 1, 2(a), 3(b)")

    # ─── Public ───────────────────────────────────────────────────────────────

    def refresh_options(self, options: dict):
        """Called after import to update dropdown values."""
        self._filter_options = options
        self._build_filters()

    # ─── Search ───────────────────────────────────────────────────────────────

    def _do_search(self):
        self._snapshot_values()   # make sure backing store is current
        mode  = self._mode_val
        is_ms = mode == "marking_scheme"

        depth_map = {
            "Any":                    None,
            "Main only (1,2,3…)":     0,
            "Sub-questions (a,b,c)":  1,
            "Sub-sub (i,ii,iii)":     2,
        }
        depth = depth_map.get(self._q_depth_val, 0)

        filters = {
            "doc_type":        mode,
            "level":           self._level_val   or None,
            "subject":         self._subject_val or None,
            "year":            int(self._year_val) if self._year_val.isdigit() else None,
            "season":          self._season_val  or None,
            "paper":           int(self._paper_val)   if self._paper_val.isdigit()   else None,
            "variant":         int(self._variant_val) if self._variant_val.isdigit() else None,
            "question_level":  depth,
            "question_number": self._q_number_val.strip() or None,
        }

        if is_ms:
            filters["topic"] = self._topic_val or None

        self.on_search(filters)

    def _clear_filters(self):
        self._level_val    = ""
        self._subject_val  = ""
        self._year_val     = ""
        self._season_val   = ""
        self._paper_val    = ""
        self._variant_val  = ""
        self._topic_val    = ""
        self._q_number_val = ""
        self._q_depth_val  = "Main only (1,2,3…)"
        self._build_filters()