"""Audiobook tab for the Novelflow GUI.

Voice/format settings, section selection (presets + picker dialog), and the
create-audiobook action. Mixed into NovelflowApp (see gui.py).
"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from novelflow.gui_jobs import JobCancelled
from novelflow.gui_theme import (
    configure_dark_combobox,
    fit_combobox,
    make_accent_button,
    make_card,
    make_ghost_button,
    make_path_entry,
    make_secondary_button,
    space,
    track_font,
)

_PREVIEW_TEXT = (
    "This is a preview of how your audiobook will sound with the selected voice."
)

_SECTION_PRESETS = (
    "All sections",
    "Title + chapters",
    "Chapters only",
    "None",
)
_SECTION_PRESET_DEFAULT = "Title + chapters"


class AudiobookTabMixin:
    """Audiobook tab UI, section management, voices, and creation action."""

    def _clear_sections_state(self, *, message: str = "Load a document to see an estimate.") -> None:
        self._sections_loaded_key = None
        self._clear_section_checkboxes()
        self.section_count_var.set("")
        self.estimate_var.set(message)

    def _build_audiobook_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        inner, self._audio_outline_shell = self._make_tab_outline(
            parent, expand=True, padding=self._work_tab_shell_pad(),
        )
        self._audiobook_tab_page = parent
        inner.columnconfigure(0, weight=1)
        inner.rowconfigure(1, weight=1)
        top = ttk.Frame(inner)
        top.grid(row=0, column=0, sticky="new")
        top.columnconfigure(0, weight=1)
        self._audio_work_top = top
        self._make_section_heading(top, "Audiobook").pack(anchor="w")
        ttk.Label(
            top,
            text="Pick a voice, format, and sections, then create the audiobook. Works from a PDF or an existing .md.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=self._work_tab_subtitle_pady())

        card, body, content, action_row = self._make_work_tab_card(top)
        self._audio_card = card
        self._audio_card_body = body
        self._audio_work_content = content
        self._audio_action_row = action_row

        settings = ttk.Frame(content, style="Card.TFrame")
        settings.grid(row=0, column=0, sticky="ew")
        self._audio_settings_body = settings
        settings.columnconfigure(0, weight=0)
        settings.columnconfigure(1, weight=1)
        label_w = 12
        row_gap = space(3, self._ui_scale)
        value_pad_x = space(3, self._ui_scale)
        row_pady = (row_gap, row_gap)
        grid_row = 0

        ttk.Label(settings, text="Voice", style="CardFormLabel.TLabel", width=label_w).grid(
            row=grid_row, column=0, sticky="w", pady=row_pady,
        )
        voice_row = ttk.Frame(settings, style="Card.TFrame")
        voice_row.grid(row=grid_row, column=1, sticky="w", padx=(value_pad_x, 0), pady=row_pady)
        voice_gap = space(2, self._ui_scale)
        self.voice_combo = ttk.Combobox(voice_row, textvariable=self.tts_voice_var, state="readonly", style="Dark.TCombobox")
        self.voice_combo.pack(side=tk.LEFT)
        configure_dark_combobox(self.voice_combo, self.colors)
        self.preview_btn = make_secondary_button(voice_row, "\u25b6 Preview", self._preview_voice, self.colors)
        self.preview_btn.pack(side=tk.LEFT, padx=(voice_gap, 0))
        grid_row += 1
        self._card_settings_divider(settings, grid_row)
        grid_row += 1

        ttk.Label(settings, text="Format", style="CardFormLabel.TLabel", width=label_w).grid(
            row=grid_row, column=0, sticky="w", pady=row_pady,
        )
        self.format_combo = ttk.Combobox(
            settings, textvariable=self.audio_format_var, state="readonly", style="Dark.TCombobox",
            values=("m4b", "mp3", "m4a"),
        )
        self.format_combo.grid(row=grid_row, column=1, sticky="w", padx=(value_pad_x, 0), pady=row_pady)
        configure_dark_combobox(self.format_combo, self.colors)
        fit_combobox(
            self.format_combo, ("m4b", "mp3", "m4a"), scale=self._ui_scale, min_chars=6, max_chars=8,
        )
        grid_row += 1
        self._card_settings_divider(settings, grid_row)
        grid_row += 1

        ttk.Label(settings, text="Estimate", style="CardFormLabel.TLabel", width=label_w).grid(
            row=grid_row, column=0, sticky="w", pady=row_pady,
        )
        ttk.Label(settings, textvariable=self.estimate_var, style="CardMuted.TLabel").grid(
            row=grid_row, column=1, sticky="w", padx=(value_pad_x, 0), pady=row_pady,
        )
        grid_row += 1
        self._card_settings_divider(settings, grid_row)
        grid_row += 1

        # The selection count lives in the value column (sec_tools below) — if
        # it sat next to the "Sections" label it would widen the whole label
        # column once sections load, shifting every row's controls right.
        ttk.Label(settings, text="Sections", style="CardFormLabel.TLabel", width=label_w).grid(
            row=grid_row, column=0, sticky="w", pady=row_pady,
        )

        sec_tools = ttk.Frame(settings, style="Card.TFrame")
        sec_tools.grid(row=grid_row, column=1, sticky="w", padx=(value_pad_x, 0), pady=row_pady)
        gap = space(2, self._ui_scale)
        self._make_icon_button(
            sec_tools, "↻", self._refresh_sections, title="Refresh sections", bg=self.colors["card"],
        ).pack(side=tk.LEFT, padx=(0, gap))
        ttk.Label(sec_tools, text="Preset", style="CardMuted.TLabel").pack(side=tk.LEFT, padx=(0, space(1, self._ui_scale)))
        self.section_preset_combo = ttk.Combobox(
            sec_tools, textvariable=self.section_preset_var, state="readonly",
            style="Dark.TCombobox", values=_SECTION_PRESETS,
        )
        self.section_preset_combo.pack(side=tk.LEFT, padx=(0, gap))
        configure_dark_combobox(self.section_preset_combo, self.colors)
        fit_combobox(
            self.section_preset_combo, _SECTION_PRESETS, scale=self._ui_scale, min_chars=14, max_chars=22,
        )
        self.section_preset_combo.bind("<<ComboboxSelected>>", self._on_section_preset_pick)
        make_secondary_button(sec_tools, "Select sections", self._open_sections_picker, self.colors).pack(
            side=tk.LEFT,
        )
        ttk.Label(sec_tools, textvariable=self.section_count_var, style="CardMuted.TLabel").pack(
            side=tk.LEFT, padx=(gap, 0),
        )

        gap = space(2, self._ui_scale)
        bar = ttk.Frame(action_row, style="Card.TFrame")
        self._audio_action_bar = bar
        bar.grid(row=0, column=0, sticky="w")
        self.make_audiobook_btn = make_accent_button(bar, "Create audiobook", self._start_audiobook, self.colors)
        self.make_audiobook_btn.pack(side=tk.LEFT, padx=(0, gap))
        self.audio_open_btn = make_secondary_button(bar, "Open audiobook", self._open_audiobook_file, self.colors)
        self.audio_open_btn.pack(side=tk.LEFT, padx=(0, gap))
        self.audio_play_btn = make_secondary_button(bar, "Play in app", self._play_last_in_app, self.colors)
        self.audio_play_btn.pack(side=tk.LEFT)
        self.audio_open_btn.configure(state=tk.DISABLED)
        self.audio_play_btn.configure(state=tk.DISABLED)

        self._audio_log_host = ttk.Frame(inner)
        self._audio_log_host.grid(row=1, column=0, sticky="nsew")
        self.after_idle(self._sync_work_tab_heights)

    def _clear_section_checkboxes(self) -> None:
        self._section_vars.clear()
        self._section_meta.clear()
        self._section_titles.clear()
        self._section_rows.clear()
        self._picker_row_widgets = {}
        if self._sections_picker is not None:
            try:
                if self._sections_picker.winfo_exists():
                    self._sections_picker.destroy()
            except tk.TclError:
                pass
            self._sections_picker = None

    def _on_section_preset_pick(self, _event=None) -> None:
        preset = self.section_preset_var.get()
        if preset in _SECTION_PRESETS:
            self._apply_section_preset(preset)

    def _apply_section_preset(self, preset: str) -> None:
        from novelflow.book_structure import SectionKind

        if not self._section_vars:
            self._show_toast("Load sections first (Refresh).", kind="warn")
            return
        for sid, var in self._section_vars.items():
            kind = getattr(var, "_section_kind", None) or self._section_meta.get(sid, (None, 0))[0]
            if preset == "All sections":
                var.set(True)
            elif preset == "None":
                var.set(False)
            elif preset == "Title + chapters":
                var.set(kind in (SectionKind.TITLE, SectionKind.CHAPTER))
            elif preset == "Chapters only":
                var.set(kind == SectionKind.CHAPTER)
        self._on_section_toggle()
        if preset in _SECTION_PRESETS:
            self.section_preset_var.set(preset)
        self._refresh_sections_picker_summary()

    def _sections_select_solo(self, section_id: str) -> None:
        """Select exactly one section — handy for previewing a single chapter."""
        if section_id not in self._section_vars:
            return
        for sid, var in self._section_vars.items():
            var.set(sid == section_id)
        self._on_section_toggle()
        self._refresh_sections_picker_summary()

    def _on_section_toggle(self) -> None:
        self._update_section_counts()
        self._update_estimate()
        self._refresh_sections_picker_summary()

    def _apply_section_filter(self, query: str = "") -> None:
        q = query.strip().lower() if query else self._picker_search_var.get().strip().lower()
        for sid, block in getattr(self, "_picker_row_widgets", {}).items():
            title = self._section_titles.get(sid, "").lower()
            if not q or q in title:
                if not block.winfo_ismapped():
                    block.pack(fill=tk.X)
            else:
                block.pack_forget()

    def _update_section_counts(self) -> None:
        total = len(self._section_vars)
        if not total:
            self.section_count_var.set("")
            return
        selected = sum(1 for v in self._section_vars.values() if v.get())
        self.section_count_var.set(f"{selected} of {total} selected")

    def _update_estimate(self) -> None:
        from novelflow.book_structure import SectionKind

        if not self._section_meta:
            self.estimate_var.set("Load a document to see an estimate.")
            return
        words = 0
        chapters = 0
        for sid, var in self._section_vars.items():
            if not var.get():
                continue
            kind, w = self._section_meta.get(sid, (None, 0))
            words += w
            if kind == SectionKind.CHAPTER:
                chapters += 1
        if words == 0:
            self.estimate_var.set("No sections selected.")
            return
        # ~155 wpm is a typical Edge narration pace.
        minutes = words / 155.0
        self.estimate_var.set(
            f"≈ {words:,} words · {chapters} chapter(s) · ~{self._fmt_duration(minutes)} of audio"
        )

    @staticmethod
    def _fmt_duration(minutes: float) -> str:
        total_min = int(round(minutes))
        if total_min < 60:
            return f"{max(total_min, 1)} min"
        hours, mins = divmod(total_min, 60)
        return f"{hours} hr {mins:02d} min"

    def _refresh_sections(self) -> None:
        if self._busy:
            self._show_toast("Finish or cancel the current job first.", kind="info")
            return
        source = self._normalize_path(self.source_var.get())
        if not source:
            self._show_toast("Choose a PDF or markdown file on the Document tab first.", kind="info")
            return
        src = Path(source)
        if src.suffix.lower() == ".md":
            self._load_sections_from_markdown(src, force=True)
            return
        md = self._markdown_target(src)
        if md.is_file():
            self._load_sections_from_markdown(md, force=True)
            return
        if not src.is_file():
            self._show_toast(f"File not found: {source}", kind="error")
            return
        self._set_busy(True, "Scanning sections…")

        def work(cancel: threading.Event) -> Path:
            from novelflow.convert import ConversionCancelled, convert_pdf

            try:
                return convert_pdf(source, str(md), cancel_check=cancel.is_set)
            except ConversionCancelled as exc:
                raise JobCancelled from exc

        def fail(message: str) -> None:
            self._set_busy(False)
            self._show_toast(message, kind="error")

        self._jobs.run(
            work,
            on_done=self._finish_section_scan,
            on_cancelled=lambda: self._set_busy(False, "Section scan cancelled"),
            on_error=fail,
        )

    def _finish_section_scan(self, result: Path) -> None:
        self._set_busy(False)
        self._load_sections_from_markdown(result, force=True)
        self.status_var.set(f"Sections loaded from {result.name}")

    @staticmethod
    def _sections_key(markdown_path: Path) -> tuple[str, float] | None:
        try:
            return (str(markdown_path.resolve()), markdown_path.stat().st_mtime)
        except OSError:
            return None

    def _load_sections_from_markdown(self, markdown_path: Path, *, force: bool = False) -> None:
        from novelflow.book_structure import default_audiobook_disabled_ids, parse_book_sections

        # Workflow syncs fire on every output/format tweak — don't wipe the
        # user's section choices unless the document actually changed.
        key = self._sections_key(markdown_path)
        if not force and self._section_vars and key is not None and key == getattr(self, "_sections_loaded_key", None):
            return
        try:
            manifest = parse_book_sections(markdown_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            self._log(f"Could not read sections from {markdown_path.name}: {exc}")
            self._show_toast(f"Could not read sections from {markdown_path.name}.", kind="error")
            return
        self._sections_loaded_key = key
        disabled = default_audiobook_disabled_ids(manifest)
        self._clear_section_checkboxes()
        for section in manifest.sections:
            var = tk.BooleanVar(value=section.id not in disabled)
            var._section_kind = section.kind  # type: ignore[attr-defined]
            self._section_vars[section.id] = var
            self._section_meta[section.id] = (section.kind, len(section.text.split()))
            self._section_titles[section.id] = section.title
        self.section_preset_var.set(_SECTION_PRESET_DEFAULT)
        self._update_section_counts()
        self._update_estimate()

    def _disabled_section_ids(self) -> set[str]:
        return {sid for sid, var in self._section_vars.items() if not var.get()}

    def _refresh_sections_picker_summary(self) -> None:
        if not getattr(self, "_picker_selected_list", None):
            return
        try:
            if not self._picker_selected_list.winfo_exists():
                return
        except tk.TclError:
            return
        self._picker_selected_list.delete(0, tk.END)
        for sid, var in self._section_vars.items():
            if var.get():
                title = self._section_titles.get(sid, sid)
                self._picker_selected_list.insert(tk.END, title)
        if hasattr(self, "_picker_count_var"):
            total = len(self._section_vars)
            selected = sum(1 for v in self._section_vars.values() if v.get())
            self._picker_count_var.set(f"{selected} of {total} selected")

    def _audiobook_tab_geometry(self) -> tuple[int, int, int, int]:
        """Return (x, y, width, height) of the audiobook tab page in screen coords."""
        tab = self._audiobook_tab_page
        if tab is None:
            self.update_idletasks()
            return (
                self.winfo_rootx() + space(4, self._ui_scale),
                self.winfo_rooty() + 120,
                max(self.winfo_width() - space(8, self._ui_scale), 480),
                max(self.winfo_height() - 200, 360),
            )
        tab.update_idletasks()
        return (
            tab.winfo_rootx(),
            tab.winfo_rooty(),
            max(tab.winfo_width(), 480),
            max(tab.winfo_height(), 320),
        )

    def _sections_picker_geometry(self) -> tuple[int, int, int, int]:
        """Return centered popup geometry: ~half screen wide, tab-height tall."""
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        _, _, _, tab_h = self._audiobook_tab_geometry()
        w = max(520, int(sw * 0.5))
        h = max(360, min(tab_h, int(sh * 0.78)))
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        return x, y, w, h

    @staticmethod
    def _bind_smooth_wheel(canvas: tk.Canvas, root: tk.Misc) -> None:
        """Pixel-smooth vertical scroll for canvas-hosted lists."""

        def _scroll(direction: int) -> str:
            canvas.update_idletasks()
            first, last = canvas.yview()
            span = float(last) - float(first)
            if span >= 1.0:
                return "break"
            step = span * 0.12 * direction
            canvas.yview_moveto(max(0.0, min(1.0 - span, float(first) + step)))
            return "break"

        def _on_wheel(event) -> str:
            if not event.delta:
                return "break"
            return _scroll(-1 if event.delta > 0 else 1)

        def _bind_tree(widget: tk.Misc) -> None:
            widget.bind("<MouseWheel>", _on_wheel, add="+")
            # X11 reports the wheel as Button-4/Button-5 instead of <MouseWheel>.
            widget.bind("<Button-4>", lambda _e: _scroll(-1), add="+")
            widget.bind("<Button-5>", lambda _e: _scroll(1), add="+")
            widget.bind("<Enter>", lambda _e, c=canvas: c.focus_set(), add="+")
            for child in widget.winfo_children():
                _bind_tree(child)

        canvas.bind("<MouseWheel>", _on_wheel)
        canvas.bind("<Button-4>", lambda _e: _scroll(-1))
        canvas.bind("<Button-5>", lambda _e: _scroll(1))
        canvas.bind("<Enter>", lambda _e: canvas.focus_set())
        _bind_tree(root)

    def _open_sections_picker(self) -> None:
        if not self._section_vars:
            self._show_toast("Load sections first — choose a document and press ↻.", kind="warn")
            return
        if self._sections_picker is not None:
            try:
                if self._sections_picker.winfo_exists():
                    self._sections_picker.lift()
                    self._sections_picker.focus_force()
                    return
            except tk.TclError:
                pass

        px, py, pw, ph = self._sections_picker_geometry()
        dlg = tk.Toplevel(self)
        dlg.title("Select sections")
        dlg.configure(bg=self.colors["bg"])
        dlg.transient(self)
        dlg.grab_set()
        dlg.geometry(f"{pw}x{ph}+{px}+{py}")
        dlg.minsize(480, 320)
        self._sections_picker = dlg
        pad = space(3, self._ui_scale)

        outer = ttk.Frame(dlg, padding=pad)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=3)
        outer.columnconfigure(1, weight=2)
        outer.rowconfigure(2, weight=1)

        self._build_picker_tools(outer)
        canvas, picker_frame = self._build_picker_checklist(outer)
        self._build_picker_summary(outer, canvas, picker_frame)

        def _close() -> None:
            self._sections_picker = None
            self._picker_row_widgets = {}
            dlg.destroy()

        foot = ttk.Frame(outer)
        foot.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(space(2, self._ui_scale), 0))
        ttk.Label(
            foot,
            text="Double-click selected to jump · “Only” picks one section",
            style="Muted.TLabel",
        ).pack(side=tk.LEFT)
        make_accent_button(foot, "Done", _close, self.colors).pack(side=tk.RIGHT)

        self._refresh_sections_picker_summary()
        dlg.protocol("WM_DELETE_WINDOW", _close)

    def _build_picker_tools(self, outer: ttk.Frame) -> None:
        """Heading, preset chip, and search chip rows of the picker dialog."""
        head = ttk.Frame(outer)
        head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, space(2, self._ui_scale)))
        self._make_subsection_heading(head, "Select sections", side=tk.LEFT)
        self._picker_count_var = tk.StringVar()
        ttk.Label(head, textvariable=self._picker_count_var, style="Muted.TLabel").pack(
            side=tk.LEFT, padx=(space(2, self._ui_scale), 0),
        )

        tools = ttk.Frame(outer)
        tools.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, space(2, self._ui_scale)))
        preset_chip = self._inline_chip(tools, "Preset", pack=False)
        preset_chip._chip_outer.pack(side=tk.LEFT, padx=(0, space(2, self._ui_scale)))  # type: ignore[attr-defined]
        picker_preset = ttk.Combobox(
            preset_chip, textvariable=self.section_preset_var, state="readonly", width=14,
            style="Dark.TCombobox", values=_SECTION_PRESETS,
        )
        picker_preset.pack(side=tk.LEFT, padx=(space(1, self._ui_scale), 0))
        configure_dark_combobox(picker_preset, self.colors)
        picker_preset.bind("<<ComboboxSelected>>", self._on_section_preset_pick)
        search_chip = self._inline_chip(tools, "Search", pack=False)
        search_chip._chip_outer.pack(side=tk.LEFT)  # type: ignore[attr-defined]
        self._picker_search_var = tk.StringVar()
        picker_search = make_path_entry(search_chip, self._picker_search_var, self.colors)
        picker_search.pack(side=tk.LEFT, padx=(space(1, self._ui_scale), 0), ipady=space(1, self._ui_scale))
        self._picker_search_var.trace_add("write", lambda *_a: self._apply_section_filter())

    def _build_picker_checklist(self, outer: ttk.Frame) -> tuple[tk.Canvas, tk.Frame]:
        """Full-height scrollable section checklist (left side of the picker)."""
        list_card = make_card(outer, self.colors)
        list_card.grid(row=2, column=0, sticky="nsew", padx=(0, space(2, self._ui_scale)))
        list_inner = list_card._card_inner  # type: ignore[attr-defined]
        list_inner.rowconfigure(0, weight=1)
        list_inner.columnconfigure(0, weight=1)
        canvas = tk.Canvas(
            list_inner, bg=self.colors["card"], highlightthickness=0, bd=0,
            yscrollincrement=1,
        )
        vscroll = ttk.Scrollbar(list_inner, orient=tk.VERTICAL, command=canvas.yview, style="Vertical.TScrollbar")
        picker_frame = tk.Frame(canvas, bg=self.colors["card"], bd=0, highlightthickness=0)
        picker_window = canvas.create_window((0, 0), window=picker_frame, anchor="nw")

        def _sync_scroll_region(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _sync_canvas_width(event, win=picker_window) -> None:
            canvas.itemconfigure(win, width=event.width)

        picker_frame.bind("<Configure>", _sync_scroll_region)
        canvas.bind("<Configure>", _sync_canvas_width)
        canvas.configure(yscrollcommand=vscroll.set)
        canvas.grid(row=0, column=0, sticky="nsew", padx=space(2, self._ui_scale), pady=space(2, self._ui_scale))
        vscroll.grid(row=0, column=1, sticky="ns", pady=space(2, self._ui_scale))

        self._picker_row_widgets = {}
        from novelflow.book_structure import SectionKind
        divider = self.colors["border_subtle"]
        row_pad = space(2, self._ui_scale)

        for sid in self._section_vars:
            kind = self._section_meta.get(sid, (None, 0))[0]
            title = self._section_titles.get(sid, sid)
            kind_label = kind.value.replace("_", " ") if isinstance(kind, SectionKind) else "section"
            block = tk.Frame(picker_frame, bg=self.colors["card"], bd=0, highlightthickness=0)
            block.pack(fill=tk.X)
            row = tk.Frame(block, bg=self.colors["card"], bd=0, highlightthickness=0)
            row.pack(fill=tk.X, padx=space(2, self._ui_scale), pady=row_pad)
            ttk.Checkbutton(
                row, text=f"{title}  ({kind_label})", variable=self._section_vars[sid],
                style="Card.TCheckbutton", takefocus=0, command=self._on_section_toggle,
            ).pack(side=tk.LEFT, anchor="w")
            make_ghost_button(row, "Only", lambda s=sid: self._sections_select_solo(s), self.colors).pack(side=tk.RIGHT)
            tk.Frame(block, bg=divider, height=1).pack(fill=tk.X)
            self._picker_row_widgets[sid] = block

        self._bind_smooth_wheel(canvas, picker_frame)
        return canvas, picker_frame

    def _build_picker_summary(self, outer: ttk.Frame, canvas: tk.Canvas, picker_frame: tk.Frame) -> None:
        """Selected-sections summary list (right side of the picker)."""
        sel_card = make_card(outer, self.colors)
        sel_card.grid(row=2, column=1, sticky="nsew")
        sel_inner = sel_card._card_inner  # type: ignore[attr-defined]
        sel_inner.rowconfigure(1, weight=1)
        sel_inner.columnconfigure(0, weight=1)
        ttk.Label(sel_inner, text="Selected", style="CardFormLabel.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w",
            padx=space(2, self._ui_scale), pady=(space(2, self._ui_scale), space(1, self._ui_scale)),
        )
        sel_scroll = ttk.Scrollbar(sel_inner, orient=tk.VERTICAL, style="Vertical.TScrollbar")
        self._picker_selected_list = tk.Listbox(
            sel_inner, activestyle="none", highlightthickness=0, borderwidth=0,
            bg=self.colors["surface"], fg=self.colors["text"],
            selectbackground=self.colors["accent"], selectforeground=self.colors["on_accent"],
            yscrollcommand=sel_scroll.set,
        )
        sel_scroll.configure(command=self._picker_selected_list.yview)
        self._picker_selected_list.grid(
            row=1, column=0, sticky="nsew",
            padx=space(2, self._ui_scale), pady=(0, space(2, self._ui_scale)),
        )
        sel_scroll.grid(row=1, column=1, sticky="ns", pady=(0, space(2, self._ui_scale)))
        track_font(self._picker_selected_list, "body", self.colors)

        def _jump_to_selected(_event=None) -> None:
            sel = self._picker_selected_list.curselection()
            if not sel:
                return
            title = self._picker_selected_list.get(sel[0])
            for sid, t in self._section_titles.items():
                if t == title:
                    block = self._picker_row_widgets.get(sid)
                    if block is None:
                        return
                    canvas.update_idletasks()
                    frame_h = max(picker_frame.winfo_height(), 1)
                    canvas.yview_moveto(max(0.0, min(1.0, block.winfo_y() / frame_h)))
                    return

        self._picker_selected_list.bind("<Double-Button-1>", _jump_to_selected)

    def _engine_key(self) -> str:
        return str(self._gui_prefs.get("default_engine", "edge"))

    def _refresh_voice_list(self) -> None:
        from novelflow.tts_voices import default_voice, voices_for_engine

        engine = self._engine_key()
        voices = voices_for_engine(engine)
        labels = [f"{v.label} ({v.id})" for v in voices]
        self.voice_combo.configure(values=labels)
        fit_combobox(self.voice_combo, labels, scale=self._ui_scale, min_chars=18, max_chars=32)
        preferred = str(self._gui_prefs.get("default_voice", "")) or default_voice(engine)
        for idx, voice in enumerate(voices):
            if voice.id == preferred:
                self.voice_combo.current(idx)
                return
        for idx, voice in enumerate(voices):
            if voice.id == default_voice(engine):
                self.voice_combo.current(idx)
                return
        if labels:
            self.voice_combo.current(0)

    def _selected_voice_id(self) -> str:
        from novelflow.tts_voices import default_voice, voices_for_engine

        engine = self._engine_key()
        label = self.tts_voice_var.get()
        for voice in voices_for_engine(engine):
            if f"({voice.id})" in label:
                return voice.id
        return default_voice(engine)

    def _set_preview_busy(self, busy: bool) -> None:
        self.preview_btn.configure(
            state=tk.DISABLED if busy else tk.NORMAL,
            text="\u2026 Loading" if busy else "\u25b6 Preview",
        )

    def _preview_voice(self) -> None:
        if self._busy:
            self.status_var.set("Finish the current job before previewing a voice.")
            return
        if not self._player.available:
            self.status_var.set("Voice preview needs audio support (pygame).")
            return
        voice = self._selected_voice_id()
        engine = self._engine_key()
        self._set_preview_busy(True)
        self.status_var.set(f"Synthesizing preview ({voice})…")

        def work(_cancel: threading.Event) -> Path:
            import tempfile

            from novelflow.tts_engines import get_engine

            cache = Path(tempfile.gettempdir()) / "novelflow_voice_previews"
            cache.mkdir(exist_ok=True)
            clip = cache / f"{voice}.mp3"
            if not (clip.is_file() and clip.stat().st_size > 1024):
                get_engine(engine).synthesize_section(_PREVIEW_TEXT, clip, voice=voice)
            return clip

        def done(clip: Path) -> None:
            self._set_preview_busy(False)
            self._begin_preview_playback(clip)
            self.status_var.set(f"Previewing voice: {voice}")

        def fail(message: str) -> None:
            self._set_preview_busy(False)
            self.status_var.set(f"Preview failed: {message}")

        self._jobs.run(work, on_done=done, on_error=fail)

    def _start_audiobook(self) -> None:
        if self._busy:
            return
        src = self._validated_source(missing_msg="Choose a PDF or markdown file on the Document tab first.")
        if src is None:
            if not self.source_var.get().strip():
                self.notebook.select(0)
            return
        source = str(src)

        is_md = src.suffix.lower() == ".md"
        if is_md:
            md_path = src
        else:
            output_raw = self.output_var.get().strip()
            md_path = Path(self._normalize_path(output_raw)) if output_raw else self._markdown_target(src)

        audio_format = self.audio_format_var.get()
        tts_voice = self._selected_voice_id()
        disabled = self._disabled_section_ids() if self._section_vars else None
        chapters_only = not self._section_vars
        use_existing_md = is_md or md_path.is_file()
        engine = self._engine_key()
        self._begin_run(make_audiobook=True, status="Creating audiobook…")

        def work(cancel: threading.Event) -> Path:
            from novelflow.convert import ConversionCancelled, convert_pdf

            try:
                if use_existing_md:
                    from novelflow.audiobook import create_audiobook

                    self._ui(self._log, f"Using markdown: {md_path.name}")
                    create_audiobook(
                        md_path, engine=engine, voice=tts_voice, audio_format=audio_format,
                        disabled_section_ids=disabled, chapters_and_title_only=chapters_only,
                        progress=lambda msg: self._ui(self._log, msg),
                        on_progress=lambda pct: self._ui(self._set_progress, pct),
                        cancel_check=cancel.is_set,
                    )
                    return md_path
                return convert_pdf(
                    source, str(md_path), audiobook=True, tts_engine=engine, tts_voice=tts_voice,
                    audio_format=audio_format, disabled_section_ids=disabled,
                    chapters_and_title_only=chapters_only,
                    progress=lambda msg: self._ui(self._log, msg),
                    on_progress=lambda pct: self._ui(self._set_progress, pct),
                    cancel_check=cancel.is_set,
                )
            except ConversionCancelled as exc:
                raise JobCancelled from exc

        def finish(result: Path) -> None:
            self._on_success(result, self._audiobook_output_path(result, audio_format))

        self._jobs.run(
            work,
            on_done=finish,
            on_cancelled=self._on_cancelled,
            on_error=self._on_error,
        )
