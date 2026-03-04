"""
ui/filter_panel.py
===================
Left sidebar panel with filter dropdowns for:
Level, Subject, Year, Season, Variant, Paper, Question Number

Dynamically populated from DB on startup and after imports.
"""

import customtkinter as ctk
from typing import Callable

C_NAVY  = "#1a3a5c"
C_BLUE  = "#2563eb"
C_WHITE = "#ffffff"


class FilterPanel(ctk.CTkFrame):
    def __init__(self, parent, on_search: Callable, **kwargs):
        kwargs.setdefault("corner_radius", 12)
        super().__init__(parent, **kwargs)
        self.on_search = on_search
        self._vars = {}

        self._build()

    def _build(self):
        self.grid_propagate(True)

        # Title
        ctk.CTkLabel(
            self,
            text="🔍  Search Filters",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=C_NAVY,
        ).pack(pady=(18, 12), padx=16, anchor="w")

        # Scrollable content frame
        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent", corner_radius=0
        )
        self._scroll.pack(fill="both", expand=True, padx=8)

        self._add_dropdown("Level",       "level",           ["Any"])
        self._add_dropdown("Subject",     "subject",         ["Any"])
        self._add_dropdown("Year",        "year",            ["Any"])
        self._add_dropdown("Season",      "season",          ["Any"])
        self._add_dropdown("Variant",     "variant",         ["Any"])
        self._add_dropdown("Paper",       "paper",           ["Any"])
        self._add_entry("Question No.",   "question_number", "e.g. 1 or 1(a)")

        # Question depth filter — very useful for CIE papers
        self._add_dropdown(
            "Question Depth",
            "question_level",
            ["Any", "Main only (1,2,3…)", "Sub-questions (a,b,c)", "Sub-sub (i,ii,iii)"],
        )

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=12)

        ctk.CTkButton(
            btn_frame,
            text="Search",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=C_BLUE,
            hover_color="#1d4ed8",
            corner_radius=8,
            height=40,
            command=self._do_search,
        ).pack(fill="x", pady=(0, 6))

        ctk.CTkButton(
            btn_frame,
            text="Clear Filters",
            font=ctk.CTkFont(size=12),
            fg_color="transparent",
            border_color="#cbd5e1",
            border_width=1,
            text_color="#374151",
            hover_color="#f1f5f9",
            corner_radius=8,
            height=34,
            command=self._clear_filters,
        ).pack(fill="x")

    def _add_dropdown(self, label: str, key: str, values: list):
        ctk.CTkLabel(
            self._scroll,
            text=label,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#475569",
        ).pack(anchor="w", padx=8, pady=(10, 2))

        var = ctk.StringVar(value="Any")
        self._vars[key] = var

        dd = ctk.CTkOptionMenu(
            self._scroll,
            values=values,
            variable=var,
            height=34,
            corner_radius=6,
            fg_color="#f1f5f9",
            button_color="#cbd5e1",
            text_color="#1e293b",
        )
        dd.pack(fill="x", padx=8, pady=(0, 2))

    def _add_entry(self, label: str, key: str, placeholder: str = ""):
        ctk.CTkLabel(
            self._scroll,
            text=label,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#475569",
        ).pack(anchor="w", padx=8, pady=(10, 2))

        var = ctk.StringVar()
        self._vars[key] = var

        ctk.CTkEntry(
            self._scroll,
            textvariable=var,
            placeholder_text=placeholder,
            height=34,
            corner_radius=6,
        ).pack(fill="x", padx=8, pady=(0, 2))

    def update_options(self, opts: dict):
        """Refresh dropdowns with fresh values from DB."""
        mapping = {
            "level":   ("level",   opts.get("levels", [])),
            "subject": ("subject", opts.get("subjects", [])),
            "year":    ("year",    opts.get("years", [])),
            "season":  ("season",  opts.get("seasons", [])),
            "variant": ("variant", opts.get("variants", [])),
            "paper":   ("paper",   opts.get("papers", [])),
        }
        for key, (_, values) in mapping.items():
            if key in self._vars:
                full_list = ["Any"] + values
                # Find the CTkOptionMenu for this key and update
                for widget in self._scroll.winfo_children():
                    if (
                        isinstance(widget, ctk.CTkOptionMenu)
                        and widget.cget("variable") == self._vars[key]
                    ):
                        widget.configure(values=full_list)
                        break

    def _do_search(self):
        filters = {}

        # Mapping for question_level dropdown to integer
        level_map = {
            "Main only (1,2,3…)":       0,
            "Sub-questions (a,b,c)":     1,
            "Sub-sub (i,ii,iii)":        2,
        }

        for key, var in self._vars.items():
            val = var.get().strip()
            if not val or val == "Any":
                continue

            if key == "question_level":
                if val in level_map:
                    filters["question_level"] = level_map[val]
            elif key in ("year", "variant", "paper"):
                try:
                    filters[key] = int(val)
                except ValueError:
                    pass
            else:
                filters[key] = val

        self.on_search(filters)

    def _clear_filters(self):
        for var in self._vars.values():
            var.set("Any")
