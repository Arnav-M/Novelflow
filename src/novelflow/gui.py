"""Desktop GUI for Novelflow."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, scrolledtext, ttk

from novelflow.gui_theme import (
    apply_theme,
    configure_dark_combobox,
    configure_gutter_grid,
    configure_log_widget,
    control_metrics,
    corner_radius,
    draw_round_rect,
    draw_round_rect_top,
    enable_dpi_awareness,
    fit_combobox,
    fit_round_surface_to_content,
    CanvasButton,
    make_accent_button,
    make_browse_button,
    make_card,
    make_compact_dropdown,
    make_ghost_button,
    make_path_entry,
    make_round_surface,
    make_secondary_button,
    refresh_font_registry,
    refresh_theme_scale,
    set_accent_button_state,
    set_grid_column_gaps,
    set_round_surface_height,
    set_window_icon,
    space,
    track_font,
    typeface,
    ui_scale,
    window_content_scale,
)
from novelflow.player import AudioPlayer, is_pygame_playable, scan_audiobook_folder

try:  # Optional: drag-and-drop support.
    from tkinterdnd2 import DND_FILES, TkinterDnD

    _DND_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    DND_FILES = None
    TkinterDnD = None
    _DND_AVAILABLE = False

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
_PLAYER_CHAPTER_TITLE_PLACEHOLDER = "Chapter title"
_PLAYER_CHAPTER_SUB_PLACEHOLDER = "—"

# Tab content fills the main area; progress lives in the footer.
_MAIN_SPLIT_TAB_ROW = 0
_TAB_NAV_DEFS = (("📄", "Document"), ("🎧", "Audiobook"), ("▶", "Player"))


class ReflowBar(ttk.Frame):
    """A button bar that wraps its buttons onto new rows when space is tight."""

    def __init__(self, parent, *, gap: int = 8, anchor: str = "w", **kwargs) -> None:
        super().__init__(parent, **kwargs)
        self._gap = gap
        self._anchor = anchor
        self._buttons: list[tk.Widget] = []
        self._last_layout: tuple | None = None
        self._reflowing = False
        self.bind("<Configure>", lambda _e: self._reflow())

    def add(self, widget: tk.Widget) -> tk.Widget:
        self._buttons.append(widget)
        self._last_layout = None
        self.after_idle(self._reflow)
        return widget

    def reflow(self) -> None:
        self._last_layout = None
        self._reflow()

    def _reflow(self) -> None:
        if self._reflowing:
            return
        try:
            self._reflow_inner()
        except tk.TclError:
            pass

    def _reflow_inner(self) -> None:
        width = self.winfo_width()
        if not self._buttons:
            return
        if width <= 1:
            self._reflowing = True
            try:
                est = sum(
                    btn.winfo_reqwidth() + self._gap for btn in self._buttons
                ) or width
                width = max(width, est)
                if width <= 1:
                    for col, btn in enumerate(self._buttons):
                        btn.grid(row=0, column=col, sticky="w", padx=(0, self._gap), pady=(0, self._gap))
                    self._last_layout = tuple((0, c, "w") for c in range(len(self._buttons)))
                    self.after_idle(self._reflow)
                    return
            finally:
                self._reflowing = False
        # Compute the (row, col) grid positions first.
        placements: list[tuple[int, int, str]] = []
        x = 0
        row = col = 0
        for btn in self._buttons:
            try:
                req = btn.winfo_reqwidth() + self._gap
            except tk.TclError:
                continue
            if col > 0 and x + req > width:
                row += 1
                col = 0
                x = 0
            sticky = self._anchor if col == 0 and row > 0 else "w"
            placements.append((row, col, sticky))
            x += req
            col += 1
        # Skip re-gridding when nothing changed — re-gridding emits <Configure>
        # which would otherwise recurse and spam the event loop.
        layout = tuple(placements)
        if layout == self._last_layout:
            return
        self._last_layout = layout
        self._reflowing = True
        try:
            for btn, (r, c, sticky) in zip(self._buttons, placements):
                btn.grid(row=r, column=c, sticky=sticky, padx=(0, self._gap), pady=(0, self._gap))
        finally:
            self._reflowing = False


class NovelflowApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Novelflow")
        self._busy = False
        self._pulse_step = 0
        self._last_output: Path | None = None
        self._last_audiobook: Path | None = None
        self._window_resize_after: str | None = None
        self._reflow_bars: list[ReflowBar] = []

        self._apply_window_geometry()
        self._ui_scale = ui_scale(self)
        self.colors = apply_theme(self, scale=self._ui_scale)
        set_window_icon(self)
        self._enable_dnd()

        # State
        self.source_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.keep_raw_var = tk.BooleanVar(value=False)
        self.tts_voice_var = tk.StringVar(value="")
        self.audio_format_var = tk.StringVar(value="m4b")
        self._section_vars: dict[str, tk.BooleanVar] = {}
        self._section_meta: dict[str, tuple] = {}  # id -> (kind, words)
        self._section_titles: dict[str, str] = {}
        self._section_rows: list[tuple] = []  # picker-only row widgets when open
        self._sections_frame: ttk.Frame | None = None
        self._audiobook_tab_page: ttk.Frame | None = None
        self._sections_picker: tk.Toplevel | None = None
        self._doc_advanced_popup: tk.Toplevel | None = None
        self._doc_adv_popup_open = False
        self.section_search_var = tk.StringVar()
        self._picker_search_var = tk.StringVar()
        self.section_preset_var = tk.StringVar(value=_SECTION_PRESET_DEFAULT)
        self.section_count_var = tk.StringVar(value="")
        self.estimate_var = tk.StringVar(value="Load a document to see an estimate.")

        self.status_var = tk.StringVar(value="Ready — choose a PDF or markdown file to begin")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_meta_var = tk.StringVar(value="")
        self._footer_title_var = tk.StringVar(value="")
        self._footer_progress_style = "idle"
        self._current_progress_pct = 0.0
        self._current_progress_label = ""

        self._ui_queue: queue.Queue = queue.Queue()
        self._cancel_event = threading.Event()
        self._phase_audiobook = False
        self._progress_start: float | None = None
        self._eta_ema: float | None = None

        # Player state
        self._player = AudioPlayer()
        self._player_chapters: list = []
        self._player_path: Path | None = None
        self._player_playable = False
        self._user_seeking = False
        self._user_book_seeking = False
        self._book_timeline_enabled = False
        self._was_busy = False
        self._preparing_speed = False
        self._player_started = False
        self._resume_fraction = 0.0
        self.player_title_var = tk.StringVar(value="No audiobook loaded yet")
        self.player_chapter_title_var = tk.StringVar(value=_PLAYER_CHAPTER_TITLE_PLACEHOLDER)
        self.player_chapter_sub_var = tk.StringVar(value=_PLAYER_CHAPTER_SUB_PLACEHOLDER)
        self.player_chapter_elapsed_var = tk.StringVar(value="00:00")
        self.player_chapter_total_var = tk.StringVar(value="00:00")
        self.player_book_elapsed_var = tk.StringVar(value="00:00")
        self.player_book_total_var = tk.StringVar(value="00:00")
        self.seek_var = tk.DoubleVar(value=0.0)
        self.book_seek_var = tk.DoubleVar(value=0.0)
        self.volume_var = tk.DoubleVar(value=85.0)
        self.speed_var = tk.StringVar(value="1.0×")
        self._resume_store = self._load_resume_store()
        self._resume_save_tick = 0
        self._gui_prefs = self._load_gui_prefs()
        try:
            self.volume_var.set(float(self._gui_prefs.get("volume", 85)))
        except (TypeError, ValueError):
            self.volume_var.set(85.0)
        self._player.set_volume(self.volume_var.get() / 100.0)
        self._vol_save_after: str | None = None
        self.audiobook_lib_dir_var = tk.StringVar(
            value=self._gui_prefs.get("audiobook_library_dir", ""),
        )
        self.audiobook_lib_pick_var = tk.StringVar(value="")
        self._audiobook_lib_entries: list[tuple[str, Path]] = []
        self._workflow_sync_after: str | None = None
        self.output_var.trace_add("write", lambda *_: self._schedule_workflow_sync())
        self.audio_format_var.trace_add("write", lambda *_: self._schedule_workflow_sync())

        self._build_ui()
        self.bind("<Configure>", self._on_window_resize)
        self.bind("<Control-Return>", lambda _e: self._start_convert())
        self.bind("<Control-l>", lambda _e: self._clear_log())
        self.bind("<space>", self._space_toggle_player)
        self.after(50, self._drain_ui_queue)
        self.after(300, self._tick_player)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        if len(sys.argv) > 1 and sys.argv[1].lower().endswith((".pdf", ".md")):
            self.after(100, lambda: self._set_source_path(sys.argv[1]))
        self.after(150, self._refresh_audiobook_library)
        self.after_idle(self._apply_responsive_layout)
        self.after_idle(self._sync_bottom_panel_for_tab)

    def report_callback_exception(self, exc, val, tb) -> None:  # noqa: N802
        # Print one real traceback (rate-limited) instead of Tk's opaque
        # "Exception in Tkinter callback" with no detail.
        import traceback

        last = getattr(self, "_last_cb_exc", None)
        sig = (exc, str(val))
        if sig != last:
            self._last_cb_exc = sig
            traceback.print_exception(exc, val, tb)

    # ---- infrastructure -----------------------------------------------------

    def _track_reflow_bar(self, bar: ReflowBar) -> ReflowBar:
        self._reflow_bars.append(bar)
        return bar

    def _enable_dnd(self) -> None:
        self._dnd_ok = False
        if not _DND_AVAILABLE:
            return
        try:
            TkinterDnD._require(self)
            self._dnd_ok = True
        except Exception:  # noqa: BLE001 - DnD is a nicety, never fatal
            self._dnd_ok = False

    def _drain_ui_queue(self) -> None:
        while True:
            try:
                func, args, kwargs = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                func(*args, **kwargs)
            except tk.TclError:
                pass
        self.after(50, self._drain_ui_queue)

    def _ui(self, func, /, *args, **kwargs) -> None:
        self._ui_queue.put((func, args, kwargs))

    def _apply_window_geometry(self) -> None:
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        width = max(720, min(int(sw * 0.56), 1180))
        height = max(620, min(int(sh * 0.80), 960))
        x = max(0, (sw - width) // 2)
        y = max(0, (sh - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")  # restore size when un-maximizing
        self.minsize(480, 420)
        try:
            self.state("zoomed")  # open maximized on Windows
        except tk.TclError:
            pass

    def _update_ui_scale(self, *, force: bool = False) -> None:
        self.update_idletasks()
        new_scale = window_content_scale(self.winfo_width(), self.winfo_height())
        if not force and abs(new_scale - self._ui_scale) < 0.015:
            return
        self._ui_scale = new_scale
        self.colors = refresh_theme_scale(self, self.colors, new_scale)
        self._refresh_footer_theme()
        self._work_tab_size_key = None
        self._doc_drop_measure_key = None
        self._sync_form_control_sizes()
        if hasattr(self, "_player_strip"):
            set_grid_column_gaps(
                self._player_strip,
                self._player_strip_gap_units,
                scale=new_scale,
                gap_columns=self._player_strip_gap_cols,
            )

    def _sync_form_control_sizes(self) -> None:
        if not hasattr(self, "voice_combo"):
            return
        scale = self._ui_scale
        from novelflow.tts_voices import voices_for_engine

        labels = tuple(f"{v.label} ({v.id})" for v in voices_for_engine("edge"))
        fit_combobox(self.voice_combo, labels, scale=scale, min_chars=18, max_chars=32)
        fit_combobox(
            self.format_combo, ("m4b", "mp3", "m4a"), scale=scale, min_chars=6, max_chars=8,
        )
        fit_combobox(
            self.section_preset_combo, _SECTION_PRESETS, scale=scale, min_chars=14, max_chars=22,
        )
        self._sync_drop_zone_height(force=True)

    def _drop_zone_canvas_inset(self) -> int:
        return 2 * (corner_radius(self._ui_scale) + 1)

    def _sync_drop_zone_height(self, *, force: bool = False) -> None:
        """Match drop-zone canvas height to the Audiobook content row."""
        if not hasattr(self, "_doc_drop_shell"):
            return
        scale = self._ui_scale
        measure_key = (round(scale, 3), self.winfo_width(), self.winfo_height())
        inset = self._drop_zone_canvas_inset()

        if force or getattr(self, "_doc_drop_measure_key", None) != measure_key:
            self._doc_empty_content.update_idletasks()
            self._doc_selected_content.update_idletasks()
            content_max = max(
                self._doc_empty_content.winfo_reqheight(),
                self._doc_selected_content.winfo_reqheight(),
            )
            floor = content_max + inset
            matched = None
            if hasattr(self, "_audio_work_content"):
                self._audio_work_content.update_idletasks()
                matched = self._audio_work_content.winfo_reqheight()
            canvas_h = max(floor, matched) if matched is not None else floor
            self._doc_drop_zone_height = canvas_h
            self._doc_drop_measure_key = measure_key
        else:
            canvas_h = getattr(self, "_doc_drop_zone_height", inset + space(12, scale))

        set_round_surface_height(self._doc_drop_shell, canvas_h)

    def _fit_work_tab_cards(self) -> None:
        """Shrink grey card canvases to body content (they only auto-grow today)."""
        scale = self._ui_scale
        for card in (getattr(self, "_doc_card", None), getattr(self, "_audio_card", None)):
            if card is not None:
                fit_round_surface_to_content(card, scale=scale)

    def _reflow_action_bars(self) -> None:
        for bar in self._reflow_bars:
            try:
                bar.reflow()
            except tk.TclError:
                pass

    def _footer_metrics(self) -> dict[str, int]:
        """Footer download bar — ~7% of window height."""
        scale = self._ui_scale
        win_h = max(self.winfo_height(), 1)
        base = space(2, scale) * 2 + space(6, scale) + space(2, scale)
        return {
            "height": max(base, int(win_h * 0.07)),
            "btn_pad_x": space(3, scale),
            "btn_pad_y": space(2, scale),
        }

    def _sync_footer_layout(self) -> None:
        if not hasattr(self, "_footer_canvas"):
            return
        m = self._footer_metrics()
        try:
            self._footer_canvas.configure(height=m["height"])
            self._draw_footer_bar()
        except tk.TclError:
            pass

    def _refresh_footer_theme(self) -> None:
        if not hasattr(self, "_footer_canvas"):
            return
        self._sync_footer_layout()

    def _apply_progress_style(self, style: str) -> None:
        self._footer_progress_style = style
        self._draw_footer_bar()

    # ---- layout -------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=0)
        outer.pack(fill=tk.BOTH, expand=True)

        self._build_hero(outer)
        self._build_footer(outer)

        self._main_split = ttk.Frame(outer)
        self._main_split.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self._main_split.columnconfigure(0, weight=1)
        self._main_split.rowconfigure(_MAIN_SPLIT_TAB_ROW, weight=1)

        self._content_gutter = ttk.Frame(self._main_split)
        self._content_gutter.grid(row=_MAIN_SPLIT_TAB_ROW, column=0, sticky="nsew")
        self._content_gutter.columnconfigure(1, weight=1)
        self._content_gutter.rowconfigure(0, weight=1)
        self._content_lane_pad: int | None = None
        self._tab_pad = 0

        self._doc_log_host: ttk.Frame | None = None
        self._audio_log_host: ttk.Frame | None = None

        self._build_tab_nav(self._content_gutter)
        doc_page, audio_page, player_page = self._tab_pages

        self._build_document_tab(doc_page)
        self._build_audiobook_tab(audio_page)
        self.after_idle(lambda: self._sync_drop_zone_height(force=True))
        self._log_panels: list[dict[str, tk.Misc]] = []
        self._build_activity_log_panel(self._doc_log_host)
        self._build_activity_log_panel(self._audio_log_host)
        self.log = self._log_panels[0]["text"]  # type: ignore[assignment]
        self._log_user_override = None
        self._log_collapsed = False
        self._set_log_collapsed(True)
        self._build_player_tab(player_page)

        self.after_idle(self._sync_bottom_panel_for_tab)
        self._refresh_voice_list()
        self._build_toast()
        self._build_drop_overlay()
        self._register_window_dnd()
        refresh_font_registry(self.colors, self._ui_scale)
        self._apply_content_gutter(self.winfo_width())
        self.after_idle(self._sync_footer_layout)

    def _build_hero(self, parent: ttk.Frame) -> None:
        hero_bg = self.colors["hero_bg"]
        hero = tk.Frame(parent, bg=hero_bg)
        hero.pack(fill=tk.X)
        self._hero_inner = tk.Frame(hero, bg=hero_bg)
        self._hero_inner.pack(fill=tk.X, padx=space(6, self._ui_scale), pady=(space(4, self._ui_scale), space(3, self._ui_scale)))
        inner = self._hero_inner

        kicker = tk.Label(inner, text="NOVELFLOW", bg=hero_bg, fg=self.colors["hero_kicker"], anchor="w")
        kicker.pack(fill=tk.X)
        track_font(kicker, "overline", self.colors, weight="bold")

        title = tk.Label(
            inner, text="PDF to markdown and audiobook", bg=hero_bg, fg=self.colors["hero_title"], anchor="w",
        )
        title.pack(fill=tk.X)
        track_font(title, "title", self.colors, weight="bold")

        self._accent_bar = tk.Frame(hero, bg=self.colors["accent"], height=2)
        self._accent_bar.pack(fill=tk.X)

    def _select_tab(self, index: int) -> None:
        if not (0 <= index < len(self._tab_pages)):
            return
        self._tab_index = index
        self._tab_pages[index].tkraise()
        accent = self.colors["accent"]
        surface = self.colors["surface"]
        muted = self.colors["muted"]
        for i, (item, icon_lbl, name_lbl) in enumerate(getattr(self, "_tab_nav_items", ())):
            active = i == index
            bg = accent if active else surface
            fg = "#ffffff" if active else muted
            item.configure(bg=bg)
            icon_lbl.configure(bg=bg, fg=fg)
            name_lbl.configure(bg=bg, fg=fg)
        self._sync_bottom_panel_for_tab()

    def _tab_nav_metrics(self) -> dict[str, int]:
        """Scaled sizes for the icon + label sidebar rail."""
        scale = self._ui_scale
        label_font = tkfont.Font(font=typeface("caption", scale))
        text_w = max((label_font.measure(label) for _icon, label in _TAB_NAV_DEFS), default=0)
        return {
            "sidebar_w": max(space(16, scale), text_w + space(4, scale)),
            "item_pad_y": space(4, scale),
            "icon_name_gap": space(1, scale),
            "top_pad": space(4, scale),
            "side": space(2, scale),
        }

    def _make_tab_nav_item(self, parent: tk.Misc, idx: int, icon: str, label: str) -> tuple[tk.Frame, tk.Label, tk.Label]:
        m = self._tab_nav_metrics()
        scale = self._ui_scale
        surface = self.colors["surface"]
        side = m["side"]
        if idx > 0:
            rule = tk.Frame(parent, bg=self.colors["border"], height=1)
            rule.pack(fill=tk.X, padx=side, pady=(0, m["item_pad_y"]))
            self._tab_nav_dividers.append(rule)
        item = tk.Frame(parent, bg=surface, cursor="hand2")
        item.pack(fill=tk.X, padx=side, pady=(0, m["item_pad_y"]))
        icon_lbl = tk.Label(
            item, text=icon, bg=surface, fg=self.colors["muted"],
            font=typeface("title", scale), cursor="hand2",
        )
        icon_lbl.pack()
        name_lbl = tk.Label(
            item, text=label, bg=surface, fg=self.colors["muted"],
            font=typeface("caption", scale), cursor="hand2",
        )
        name_lbl.pack(pady=(m["icon_name_gap"], 0))

        def _select(_event=None, i=idx) -> None:
            self._select_tab(i)

        for widget in (item, icon_lbl, name_lbl):
            widget.bind("<Button-1>", _select)
        return item, icon_lbl, name_lbl

    def _build_tab_nav(self, parent: tk.Misc) -> None:
        """Vertical sidebar: icon with section name stacked below."""
        m = self._tab_nav_metrics()
        self._sidebar_width = m["sidebar_w"]
        self._tab_index = 0

        self._sidebar = tk.Frame(parent, bg=self.colors["surface"], width=self._sidebar_width)
        self._sidebar.grid(row=0, column=0, sticky="ns")
        self._sidebar.grid_propagate(False)
        self._sidebar.bind("<Configure>", self._sync_sidebar_fill, add="+")
        self._sidebar_fill = tk.Frame(self._sidebar, bg=self.colors["surface"])
        self._sidebar_fill.place(x=0, y=0, relwidth=1, relheight=1)
        self._icon_lane = tk.Frame(self._sidebar, bg=self.colors["surface"])
        self._icon_lane.place(x=0, y=0, relwidth=1, anchor="nw")
        self._sidebar_rule = tk.Frame(self._sidebar, bg=self.colors["border"], width=1)
        self._sidebar_rule.place(relx=1.0, rely=0, relheight=1, anchor="ne", width=1)

        lane_pad = self._content_body_pad()
        self._page_host = ttk.Frame(parent, style="TFrame")
        self._page_host.grid(row=0, column=1, sticky="nsew", padx=(lane_pad, lane_pad), pady=(lane_pad, lane_pad))

        self._tab_nav_items: list[tuple[tk.Frame, tk.Label, tk.Label]] = []
        self._tab_nav_dividers: list[tk.Frame] = []
        self._tab_pages: list[ttk.Frame] = []

        nav_side = m["side"]
        top_pad = tk.Frame(self._icon_lane, bg=self.colors["surface"], height=m["top_pad"])
        top_pad.pack(fill=tk.X)
        top_pad.pack_propagate(False)
        self._tab_nav_top_rule = tk.Frame(self._icon_lane, bg=self.colors["border"], height=1)
        self._tab_nav_top_rule.pack(fill=tk.X, padx=nav_side)

        for idx, (icon, label) in enumerate(_TAB_NAV_DEFS):
            self._tab_nav_items.append(self._make_tab_nav_item(self._icon_lane, idx, icon, label))
            page = ttk.Frame(self._page_host, padding=self._tab_pad)
            page.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._tab_pages.append(page)

        self._tab_nav_bottom_rule = tk.Frame(self._icon_lane, bg=self.colors["border"], height=1)
        self._tab_nav_bottom_rule.pack(fill=tk.X, padx=nav_side, pady=(0, space(2, self._ui_scale)))

        self._select_tab(0)

    def _sync_tab_nav_layout(self) -> None:
        if not hasattr(self, "_sidebar"):
            return
        m = self._tab_nav_metrics()
        if m["sidebar_w"] != self._sidebar_width:
            self._sidebar_width = m["sidebar_w"]
            self._sidebar.configure(width=self._sidebar_width)
        icon_font = typeface("title", self._ui_scale)
        name_font = typeface("caption", self._ui_scale)
        for _item, icon_lbl, name_lbl in getattr(self, "_tab_nav_items", ()):
            icon_lbl.configure(font=icon_font)
            name_lbl.configure(font=name_font)
        self._sync_form_control_sizes()

    def _sync_sidebar_fill(self, _event=None) -> None:
        try:
            self._sidebar_fill.place_configure(x=0, y=0, relwidth=1, relheight=1)
            self._sidebar_rule.place_configure(relx=1.0, rely=0, relheight=1, anchor="ne", width=1)
        except tk.TclError:
            pass

    @property
    def notebook(self):
        """Compatibility shim for code that selects tabs by index."""
        return self

    def select(self, index: int) -> None:
        self._select_tab(index)

    def index(self, _tab_id=None) -> int:
        return self._tab_index

    def _on_window_resize(self, event) -> None:
        if event.widget is not self:
            return
        if self._window_resize_after is not None:
            self.after_cancel(self._window_resize_after)
        self._window_resize_after = self.after(80, self._finish_window_resize)

    def _finish_window_resize(self) -> None:
        self._window_resize_after = None
        try:
            for panel in getattr(self, "_log_panels", ()):
                panel["text"].configure(wrap=tk.NONE)
            self._apply_responsive_layout()
            for panel in getattr(self, "_log_panels", ()):
                panel["text"].configure(wrap=tk.WORD)
        except tk.TclError:
            pass

    @staticmethod
    def _log_lines_for_height(height: int) -> int:
        if height < 560:
            return 2
        if height < 620:
            return 3
        if height < 740:
            return 5
        return 7

    def _apply_responsive_layout(self) -> None:
        # Guard against re-entrancy: configuring widgets below can emit
        # <Configure> events that would otherwise recurse into this method.
        if getattr(self, "_in_responsive_layout", False):
            return
        self._in_responsive_layout = True
        try:
            self._apply_responsive_layout_inner()
        finally:
            self._in_responsive_layout = False

    def _apply_responsive_layout_inner(self) -> None:
        width = max(self.winfo_width(), 1)
        height = max(self.winfo_height(), 1)
        self._apply_content_gutter(width)
        self._update_ui_scale(force=height < 560 or width < 640)
        self._sync_tab_nav_layout()
        self._sync_footer_layout()
        if hasattr(self, "_log_panels"):
            lines = self._log_lines_for_height(height)
            for panel in self._log_panels:
                panel["text"].configure(height=lines)
        if hasattr(self, "_log_panels") and self._log_user_override is not None:
            self._set_log_collapsed(self._log_user_override)
        if hasattr(self, "_hero_inner"):
            compact = height < 560 or width < 640
            pad_x = space(3 if compact else 6, self._ui_scale)
            pad_y = space(2 if compact else 4, self._ui_scale)
            self._hero_inner.pack_configure(padx=pad_x, pady=(pad_y, space(2 if compact else 3, self._ui_scale)))
        for bar in self._reflow_bars:
            try:
                bar.reflow()
            except tk.TclError:
                pass
        self._sync_work_tab_heights()
        self._sync_player_chrome_layout()
        self._sync_drop_zone_height()
        self.after_idle(self._reflow_action_bars)

    def _sync_work_tab_heights(self) -> None:
        """Match Document / Audiobook card heights so activity logs align."""
        if not hasattr(self, "_doc_card") or not hasattr(self, "_audio_card"):
            return
        try:
            self._sync_drop_zone_height(force=True)
            for top in (getattr(self, "_doc_work_top", None), getattr(self, "_audio_work_top", None)):
                if top is not None:
                    top.grid_configure(sticky="new")
            self._fit_work_tab_cards()
            self.update_idletasks()
            if hasattr(self, "_doc_drop_shell"):
                c = self._doc_drop_canvas
                w, h = max(c.winfo_width(), 1), getattr(self._doc_drop_shell, "_fixed_height", None) or max(c.winfo_height(), 1)
                if w >= 4 and h >= 4 and len(c.find_withtag("card_bg")) == 0:
                    c.event_generate("<Configure>")
        except tk.TclError:
            pass

    def _content_body_pad(self, window_width: int | None = None) -> int:
        """Uniform inset for tab body: sidebar edge → right edge, top → footer."""
        scale = self._ui_scale
        width = window_width if window_width is not None else max(self.winfo_width(), 1)
        return space(2, scale) if width < 640 else space(3, scale)

    def _apply_content_gutter(self, window_width: int) -> None:
        if not hasattr(self, "_page_host"):
            return
        pad = self._content_body_pad(window_width)
        if self._content_lane_pad == pad:
            return
        self._content_lane_pad = pad
        self._page_host.grid_configure(padx=(pad, pad), pady=(pad, pad))

    def _make_section_heading(self, parent: tk.Misc, text: str) -> ttk.Frame:
        """Page-level section title with accent underline."""
        block = ttk.Frame(parent)
        ttk.Label(block, text=text, style="SectionHeading.TLabel").pack(anchor="w")
        tk.Frame(block, bg=self.colors["accent"], height=2).pack(
            fill=tk.X, pady=(space(1, self._ui_scale), 0),
        )
        return block

    def _make_subsection_heading(self, parent: tk.Misc, text: str, **pack_kw) -> ttk.Label:
        """In-page subsection title (e.g. Sections, Activity log)."""
        lbl = ttk.Label(parent, text=text, style="SubsectionHeading.TLabel")
        if pack_kw:
            lbl.pack(**pack_kw)
        return lbl

    def _work_tab_shell_pad(self) -> str:
        """Asymmetric inset for Document / Audiobook tab shells — tight top, room below."""
        s = self._ui_scale
        side = space(4, s)
        return f"{side} {space(1, s)} {side} {space(4, s)}"

    def _work_tab_subtitle_pady(self) -> tuple[int, int]:
        s = self._ui_scale
        return (space(1, s), space(2, s))

    def _work_tab_action_gap(self) -> int:
        return space(4, self._ui_scale)

    def _work_tab_body_padding(self) -> tuple[int, int, int, int]:
        """Card body inset — tight bottom so action row sits flush above the card edge."""
        s = self._ui_scale
        side = space(5, s)
        return (side, side, side, space(2, s))

    def _make_work_tab_card(self, parent: tk.Misc) -> tuple[tk.Frame, ttk.Frame, ttk.Frame, ttk.Frame]:
        """Shared grey card shell: content row + action row (Document / Audiobook)."""
        card = make_card(parent, self.colors)
        card.pack(fill=tk.X)
        body = ttk.Frame(card._card_inner, style="Card.TFrame", padding=self._work_tab_body_padding())  # type: ignore[attr-defined]
        body.pack(fill=tk.X, anchor="nw")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=0)
        body.rowconfigure(1, weight=0)
        content = ttk.Frame(body, style="Card.TFrame")
        content.grid(row=0, column=0, sticky="ew")
        content.columnconfigure(0, weight=1)
        action_row = ttk.Frame(body, style="Card.TFrame")
        action_row.grid(row=1, column=0, sticky="ew", pady=(self._work_tab_action_gap(), 0))
        action_row.columnconfigure(0, weight=1)
        return card, body, content, action_row

    def _player_tab_shell_pad(self) -> str:
        """Player tab inset — tight top, minimal bottom."""
        s = self._ui_scale
        side = space(4, s)
        return f"{side} {space(1, s)} {side} {space(2, s)}"

    def _make_tab_outline(
        self,
        parent: ttk.Frame,
        *,
        expand: bool = False,
        padding: str | int | tuple[int, ...] | None = None,
    ) -> tuple[ttk.Frame, tk.Frame]:
        """Rounded shell wrapping tab body (borderless — blends with page bg)."""
        pad = padding if padding is not None else space(4, self._ui_scale)
        shell = make_round_surface(
            parent,
            self.colors,
            fill=self.colors["bg"],
            page_bg=self.colors["bg"],
            border=self.colors["bg"],
            padding=0,
        )
        if expand:
            shell.pack(fill=tk.BOTH, expand=True)
            inner = ttk.Frame(shell._card_inner, padding=pad)  # type: ignore[attr-defined]
            inner.pack(fill=tk.BOTH, expand=True)
        else:
            shell.pack(fill=tk.X, anchor="n")
            inner = ttk.Frame(shell._card_inner, padding=pad)  # type: ignore[attr-defined]
            inner.pack(fill=tk.X, anchor="n")
        return inner, shell

    # ---- footer progress bar (full-width) -----------------------------------

    def _build_footer(self, parent: ttk.Frame) -> None:
        m = self._footer_metrics()
        self._footer_container = tk.Frame(parent, bg="#0a0a0f")
        self._footer_container.pack(side=tk.BOTTOM, fill=tk.X)
        self._footer_container.columnconfigure(0, weight=1)

        self._footer_canvas = tk.Canvas(
            self._footer_container, height=m["height"], bg="#0a0a0f",
            highlightthickness=0, bd=0,
        )
        self._footer_canvas.grid(row=0, column=0, sticky="ew")
        self._footer_canvas.bind("<Configure>", lambda _e: self._draw_footer_bar())

        self.cancel_btn = make_ghost_button(
            self._footer_container, "\u2715", self._cancel_convert, self.colors,
        )
        self.cancel_btn.configure(bg="#0a0a0f")
        self.cancel_btn.place(relx=1.0, rely=0.5, anchor="e", x=-m["btn_pad_x"])
        self.cancel_btn.configure(state=tk.DISABLED)
        self.after_idle(self._sync_footer_title)

    def _footer_title_font(self) -> tkfont.Font:
        return tkfont.Font(font=typeface("label", self._ui_scale, weight="bold"))

    def _footer_bar_colors(self) -> tuple[str, str, str]:
        """Background, gradient start (purple), gradient end (dark purple)."""
        c = self.colors
        idle = "#0a0a0f"
        purple = c["accent"]
        purple_dark = "#2a1f4a"
        style = getattr(self, "_footer_progress_style", "idle")
        if style == "Danger.Horizontal.TProgressbar":
            return ("#1a0a10", "#b83248", "#5a1830")
        if style == "Success.Horizontal.TProgressbar":
            return (idle, purple, purple_dark)
        if self._busy or self._current_progress_pct > 0.01:
            return (idle, purple, purple_dark)
        return (idle, idle, purple_dark)

    def _draw_footer_bar(self) -> None:
        if not hasattr(self, "_footer_canvas"):
            return
        try:
            canvas = self._footer_canvas
            w = max(canvas.winfo_width(), 1)
            h = max(canvas.winfo_height(), 1)
            canvas.delete("all")
            pct = self._current_progress_pct / 100.0
            bg, mid, hi = self._footer_bar_colors()
            r = corner_radius(self._ui_scale)
            draw_round_rect_top(canvas, 0, 0, w, h, r, fill=bg, tags="bg")
            fill_w = int(w * pct)
            if fill_w > 0 and (self._busy or pct > 0.01):
                steps = max(24, min(80, fill_w // 4))
                for i in range(steps):
                    x0 = int(i / steps * fill_w)
                    x1 = int((i + 1) / steps * fill_w)
                    if x1 <= x0:
                        x1 = x0 + 1
                    t = i / max(steps - 1, 1)
                    color = self._lerp_color(mid, hi, t)
                    canvas.create_rectangle(x0, 0, x1, h, fill=color, outline="", tags="fill")
            canvas.create_text(
                w / 2, h / 2,
                text=self._footer_title_var.get(),
                fill="#ffffff",
                font=self._footer_title_font(),
                tags="footer_title",
            )
        except tk.TclError:
            pass

    @staticmethod
    def _lerp_color(a: str, b: str, t: float) -> str:
        def _hex(c: str) -> tuple[int, int, int]:
            c = c.lstrip("#")
            return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)

        r0, g0, b0 = _hex(a)
        r1, g1, b1 = _hex(b)
        r = int(r0 + (r1 - r0) * t)
        g = int(g0 + (g1 - g0) * t)
        bl = int(b0 + (b1 - b0) * t)
        return f"#{r:02x}{g:02x}{bl:02x}"

    def _sync_footer_title(self) -> None:
        src = self._normalize_path(self.source_var.get()) if self.source_var.get().strip() else None
        name = Path(src).name if src else ""
        pct = self._current_progress_pct
        style = getattr(self, "_footer_progress_style", "idle")
        show_pct = (
            self._busy
            or pct > 0.01
            or style in ("Success.Horizontal.TProgressbar", "Danger.Horizontal.TProgressbar")
        )
        if show_pct and name:
            self._footer_title_var.set(f"{name} — {pct:.0f}%")
        elif show_pct:
            self._footer_title_var.set(f"{pct:.0f}%")
        elif name:
            self._footer_title_var.set(name)
        else:
            self._footer_title_var.set("Ready — choose a PDF or markdown file to begin")
        self._draw_footer_bar()

    # ---- activity log (inside Document / Audiobook outlines) ----------------

    def _build_activity_log_panel(self, parent: ttk.Frame) -> None:
        """One activity-log block per tab host (widgets cannot move across notebook tabs)."""
        if not hasattr(self, "_log_collapsed"):
            self._log_collapsed = True
            self._log_user_override: bool | None = None
        gap = space(3, self._ui_scale)

        head = ttk.Frame(parent)
        head.pack(fill=tk.X, pady=(gap, gap))
        chevron = ttk.Label(head, text="▸", style="SubsectionHeading.TLabel", cursor="hand2")
        chevron.pack(side=tk.LEFT, padx=(0, space(1, self._ui_scale)))
        log_title = self._make_subsection_heading(head, "Activity log", side=tk.LEFT)
        log_title.configure(cursor="hand2")
        for w in (chevron, log_title):
            w.bind("<Button-1>", lambda _e: self._toggle_log())
        make_ghost_button(head, "Clear", self._clear_log, self.colors).pack(side=tk.RIGHT)

        card = make_card(parent, self.colors)
        card.pack(fill=tk.BOTH, expand=True)
        log_inner = card._card_inner  # type: ignore[attr-defined]
        text = scrolledtext.ScrolledText(log_inner, height=7, state=tk.DISABLED, wrap=tk.WORD)
        text.pack(fill=tk.BOTH, expand=True, padx=space(2, self._ui_scale), pady=space(2, self._ui_scale))
        configure_log_widget(text, self.colors)
        self._log_panels.append({"head": head, "card": card, "chevron": chevron, "text": text})

    def _sync_bottom_panel_for_tab(self) -> None:
        """Footer progress is always visible on every tab."""
        return

    def _sync_progress_display(self) -> None:
        pct = self._current_progress_pct
        label = self._current_progress_label
        eta = self._eta_text(pct) if self._progress_start is not None else ""
        parts = [f"{pct:.0f}%"]
        if label:
            parts.append(label)
        if eta:
            parts.append(eta)
        self.progress_meta_var.set("   ·   ".join(parts) if parts else "")
        self._sync_footer_title()
        self._draw_footer_bar()

    def _toggle_log(self) -> None:
        desired_collapsed = not self._log_collapsed
        self._log_user_override = desired_collapsed  # manual choice wins over auto
        self._set_log_collapsed(desired_collapsed)

    def _set_log_collapsed(self, collapsed: bool) -> None:
        if collapsed == self._log_collapsed:
            return
        self._log_collapsed = collapsed
        for panel in getattr(self, "_log_panels", ()):
            if collapsed:
                panel["card"].pack_forget()
                panel["chevron"].configure(text="▸")
            else:
                panel["card"].pack(fill=tk.BOTH, expand=True)
                panel["chevron"].configure(text="▾")
        self._sync_progress_display()

    # ---- toast notifications ------------------------------------------------

    def _build_toast(self) -> None:
        self._toast_after: str | None = None
        self._toast = make_round_surface(
            self, self.colors, fill=self.colors["surface"], border=self.colors["border"],
            padding=space(1, self._ui_scale),
        )
        inner = self._toast._card_inner  # type: ignore[attr-defined]
        inner.pack_propagate(True)
        pad = space(4, self._ui_scale)
        body = tk.Frame(inner, bg=self.colors["surface"])
        body.pack(fill=tk.BOTH, expand=True, padx=pad, pady=space(3, self._ui_scale))
        self._toast_icon = tk.Label(
            body, text="", bg=self.colors["surface"], fg=self.colors["accent"],
            font=typeface("title", self._ui_scale),
        )
        self._toast_icon.pack(side=tk.LEFT, padx=(0, space(2, self._ui_scale)))
        self._toast_msg = tk.Label(
            body, text="", bg=self.colors["surface"], fg=self.colors["text"],
            anchor="w", justify="left", wraplength=0,
        )
        self._toast_msg.pack(side=tk.LEFT, padx=(0, space(2, self._ui_scale)))
        track_font(self._toast_msg, "body", self.colors)
        self._toast_actions = tk.Frame(body, bg=self.colors["surface"])
        self._toast_actions.pack(side=tk.LEFT)
        close = make_ghost_button(body, "\u2715", self._hide_toast, self.colors)
        close.configure(bg=self.colors["surface"])
        close.pack(side=tk.RIGHT, padx=(space(2, self._ui_scale), 0))

    def _toast_bottom_offset(self) -> int:
        return self._footer_metrics()["height"] + space(8, self._ui_scale)

    def _paint_toast_border(self, accent: str) -> None:
        canvas = getattr(self._toast, "_card_canvas", None)
        if canvas is None:
            return
        try:
            w, h = max(canvas.winfo_width(), 1), max(canvas.winfo_height(), 1)
            r = corner_radius(self._ui_scale)
            canvas.delete("card_bg")
            draw_round_rect(canvas, 2, 3, w, h + 2, r, fill="#050508", tags="card_bg")
            draw_round_rect(canvas, 0, 0, w - 2, h, r, fill=accent, tags="card_bg")
            draw_round_rect(
                canvas, 1, 1, w - 3, h - 1, max(1, r - 1),
                fill=self.colors["surface"], tags="card_bg",
            )
            canvas.tag_lower("card_bg")
        except tk.TclError:
            pass

    def _fit_toast_size(self) -> None:
        """Size toast to fit message on one line (no wrapping)."""
        canvas = getattr(self._toast, "_card_canvas", None)
        inner = getattr(self._toast, "_card_inner", None)
        if canvas is None or inner is None:
            return
        try:
            for item in canvas.find_all():
                if canvas.type(item) == "window":
                    canvas.itemconfigure(item, width=0)
                    break
            inner.update_idletasks()
            r = corner_radius(self._ui_scale)
            inset = 2 * (r + 1)
            margin = space(8, self._ui_scale)
            req_w = inner.winfo_reqwidth() + inset
            req_h = inner.winfo_reqheight() + inset
            max_w = max(self.winfo_width() - 2 * margin, req_w)
            toast_w = min(req_w, max_w)
            toast_h = max(req_h, 4)
            canvas.configure(width=toast_w, height=toast_h)
            canvas.event_generate("<Configure>")
        except tk.TclError:
            pass

    def _show_toast(
        self, message: str, *, kind: str = "info", actions: list[tuple] | None = None, duration_ms: int = 6500,
    ) -> None:
        accent = {"error": self.colors.get("danger", "#ef4444"),
                  "warn": self.colors.get("glow", self.colors["accent"]),
                  "success": self.colors["accent"]}.get(kind, self.colors["accent"])
        icon = {"error": "\u2716", "warn": "\u26a0", "success": "\u2714"}.get(kind, "\u2139")
        self._toast_icon.configure(text=icon, fg=accent)
        self._toast_msg.configure(text=message, wraplength=0)
        for child in self._toast_actions.winfo_children():
            child.destroy()
        for label, callback in (actions or []):
            action_btn = make_ghost_button(self._toast_actions, label, callback, self.colors)
            action_btn.configure(bg=self.colors["surface"])
            action_btn.pack(side=tk.LEFT, padx=(0, space(1, self._ui_scale)))
        self._fit_toast_size()
        self._paint_toast_border(accent)
        self._toast.place(relx=0.5, rely=1.0, anchor="s", y=-self._toast_bottom_offset())
        self._toast.lift()
        if self._toast_after is not None:
            self.after_cancel(self._toast_after)
        self._toast_after = self.after(duration_ms, self._hide_toast)

    def _hide_toast(self) -> None:
        if self._toast_after is not None:
            self.after_cancel(self._toast_after)
            self._toast_after = None
        self._toast.place_forget()

    def _copy_to_clipboard(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("Path copied to clipboard")

    # ---- whole-window drag-and-drop overlay ---------------------------------

    def _build_drop_overlay(self) -> None:
        self._drop_overlay = tk.Frame(self, bg=self.colors["hero_bg"])
        box = make_round_surface(
            self._drop_overlay, self.colors,
            fill=self.colors["surface"], border=self.colors["accent"],
        )
        box.place(relx=0.5, rely=0.5, anchor="center")
        inner = box._card_inner  # type: ignore[attr-defined]
        msg = tk.Label(
            inner, text="Drop your PDF or markdown here", bg=self.colors["surface"], fg=self.colors["text"],
            padx=space(8, self._ui_scale), pady=space(6, self._ui_scale),
        )
        msg.pack()
        track_font(msg, "title", self.colors, weight="bold")

    def _register_window_dnd(self) -> None:
        if not self._dnd_ok:
            return
        try:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<DropEnter>>", self._on_drop_enter)
            self.dnd_bind("<<DropLeave>>", self._on_drop_leave)
            self.dnd_bind("<<Drop>>", self._on_window_drop)
        except Exception:  # noqa: BLE001
            pass

    def _on_drop_enter(self, _event):
        self._drop_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._drop_overlay.lift()
        return _event.action if hasattr(_event, "action") else None

    def _on_drop_leave(self, _event):
        self._drop_overlay.place_forget()

    def _on_window_drop(self, event):
        self._drop_overlay.place_forget()
        self._on_file_drop(event)

    # ---- Document tab -------------------------------------------------------

    def _build_document_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        inner, self._doc_outline_shell = self._make_tab_outline(
            parent, expand=True, padding=self._work_tab_shell_pad(),
        )
        inner.columnconfigure(0, weight=1)
        inner.rowconfigure(1, weight=1)
        top = ttk.Frame(inner)
        top.grid(row=0, column=0, sticky="new")
        top.columnconfigure(0, weight=1)
        self._doc_work_top = top
        self._make_section_heading(top, "Source document").pack(anchor="w")
        ttk.Label(
            top,
            text="Drop or choose a PDF (or an existing .md). PDFs are converted to clean markdown.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=self._work_tab_subtitle_pady())

        card, body, content, action_row = self._make_work_tab_card(top)
        self._doc_card = card
        self._doc_card_body = body
        self._doc_work_content = content
        self._doc_action_row = action_row

        self._doc_drop_host = ttk.Frame(content, style="Card.TFrame")
        self._doc_drop_host.grid(row=0, column=0, sticky="ew")
        self._doc_drop_host.columnconfigure(0, weight=1)

        drop_shell = make_round_surface(
            self._doc_drop_host,
            self.colors,
            fill=self.colors["surface"],
            page_bg=self.colors["card"],
            border=self.colors["border"],
        )
        self._doc_drop_shell = drop_shell
        drop_shell.pack(fill=tk.X)
        self._doc_drop_canvas = drop_shell._card_canvas  # type: ignore[attr-defined]
        drop_inner = drop_shell._card_inner  # type: ignore[attr-defined]
        drop_inner.columnconfigure(0, weight=1)
        drop_inner.rowconfigure(0, weight=1)

        self._doc_empty_view = ttk.Frame(drop_inner, style="Card.TFrame")
        self._doc_empty_view.grid(row=0, column=0, sticky="nsew")
        self._doc_empty_view.columnconfigure(0, weight=1)
        self._doc_empty_view.rowconfigure(0, weight=1)
        self._doc_empty_view.rowconfigure(1, weight=0)
        self._doc_empty_view.rowconfigure(2, weight=1)
        empty_pad = space(3, self._ui_scale)
        empty_content = ttk.Frame(self._doc_empty_view, style="Card.TFrame", padding=(empty_pad, empty_pad))
        empty_content.grid(row=1, column=0)
        self._doc_empty_content = empty_content
        empty_content.columnconfigure(0, weight=1)
        arrow_font = tkfont.Font(family="Segoe UI", size=max(28, int(36 * self._ui_scale)))
        tk.Label(
            empty_content, text="\u2193", bg=self.colors["card"], fg=self.colors["muted"],
            font=arrow_font,
        ).pack(pady=(0, space(2, self._ui_scale)))
        ttk.Label(
            empty_content, text="Drop PDF or markdown here", style="CardFormLabel.TLabel", anchor="center",
        ).pack(fill=tk.X, pady=(0, space(2, self._ui_scale)))
        make_secondary_button(empty_content, "Choose file\u2026", self._browse_source, self.colors).pack(
            pady=(0, space(1, self._ui_scale)),
        )
        ttk.Label(empty_content, text="PDF \u00b7 Markdown (.md)", style="CardMuted.TLabel", anchor="center").pack(
            fill=tk.X,
        )
        self._register_drop_target(drop_inner)
        self._register_drop_target(self._doc_empty_view)

        self._doc_selected_view = ttk.Frame(drop_inner, style="Card.TFrame")
        self._doc_selected_view.grid(row=0, column=0, sticky="nsew")
        self._doc_selected_view.columnconfigure(0, weight=1)
        self._doc_selected_view.rowconfigure(0, weight=1)
        self._doc_selected_view.rowconfigure(1, weight=0)
        self._doc_selected_view.rowconfigure(2, weight=1)
        sel_pad = space(4, self._ui_scale)
        sel_content = ttk.Frame(self._doc_selected_view, style="Card.TFrame", padding=(sel_pad, sel_pad))
        sel_content.grid(row=1, column=0)
        self._doc_selected_content = sel_content
        sel_content.columnconfigure(0, weight=1)
        self._doc_filename_var = tk.StringVar()
        self._doc_path_var = tk.StringVar()
        ttk.Label(
            sel_content, textvariable=self._doc_filename_var, style="SectionHeading.TLabel", anchor="center",
        ).grid(row=0, column=0, sticky="ew")
        self._doc_path_label = ttk.Label(
            sel_content, textvariable=self._doc_path_var, style="CardMuted.TLabel", anchor="center",
        )
        self._doc_path_label.grid(
            row=1, column=0, sticky="ew", pady=(space(1, self._ui_scale), space(2, self._ui_scale)),
        )
        sel_actions_outer = ttk.Frame(sel_content, style="Card.TFrame")
        sel_actions_outer.grid(row=2, column=0, sticky="ew")
        sel_actions_outer.columnconfigure(0, weight=1)
        sel_actions_outer.columnconfigure(1, weight=0)
        sel_actions_outer.columnconfigure(2, weight=1)
        sel_actions = ttk.Frame(sel_actions_outer, style="Card.TFrame")
        sel_actions.grid(row=0, column=1)
        act_gap = space(2, self._ui_scale)
        make_secondary_button(sel_actions, "Change file", self._browse_source, self.colors).pack(
            side=tk.LEFT, padx=(0, act_gap),
        )
        make_ghost_button(sel_actions, "Clear", self._clear_source_path, self.colors).pack(side=tk.LEFT)
        self._register_drop_target(self._doc_selected_view)

        self._doc_adv_popup_open = False
        self.output_entry: tk.Entry | None = None

        bar = self._track_reflow_bar(ReflowBar(action_row, gap=space(2, self._ui_scale), style="Card.TFrame"))
        bar.grid(row=0, column=0, sticky="w")
        self.convert_btn = make_accent_button(bar, "Convert to markdown", self._start_convert, self.colors)
        bar.add(self.convert_btn)
        self.open_btn = make_secondary_button(bar, "Open folder", self._open_output_folder, self.colors)
        bar.add(self.open_btn)
        self.open_file_btn = make_secondary_button(bar, "Open markdown", self._open_output_file, self.colors)
        bar.add(self.open_file_btn)
        self.open_btn.configure(state=tk.DISABLED)
        self.open_file_btn.configure(state=tk.DISABLED)
        self._doc_adv_btn = make_compact_dropdown(
            action_row, "Advanced", self._toggle_doc_advanced_popup, self.colors,
        )
        self._doc_adv_btn.grid(row=0, column=1, sticky="e", padx=(space(3, self._ui_scale), 0))
        self.bind("<Button-1>", self._on_doc_adv_dismiss, add="+")
        bar.reflow()

        self._doc_log_host = ttk.Frame(inner)
        self._doc_log_host.grid(row=1, column=0, sticky="nsew")

        self._sync_document_source_view()
        self._sync_drop_zone_height(force=True)
        self.after_idle(self._sync_work_tab_heights)

    def _ensure_doc_advanced_popup(self) -> tk.Toplevel:
        if self._doc_advanced_popup is not None:
            try:
                if self._doc_advanced_popup.winfo_exists():
                    return self._doc_advanced_popup
            except tk.TclError:
                pass
        pop = tk.Toplevel(self)
        pop.withdraw()
        pop.overrideredirect(True)
        pop.configure(bg=self.colors["border"])
        shell = make_round_surface(
            pop,
            self.colors,
            fill=self.colors["card"],
            page_bg=self.colors["border"],
            border=self.colors["border"],
            padding=space(4, self._ui_scale),
        )
        shell.pack()
        self._doc_adv_popup_shell = shell
        form = tk.Frame(shell._card_inner, bg=self.colors["card"])  # type: ignore[attr-defined]
        form.pack()
        self.output_entry = self._field_row(
            form, 0, "Markdown out", self.output_var, self._browse_output, on_card=True,
        )
        self._blend_path_entry(self.output_entry)
        opts = tk.Frame(form, bg=self.colors["card"])
        opts.grid(row=1, column=0, columnspan=3, sticky="w", pady=(space(2, self._ui_scale), 0))
        ttk.Checkbutton(
            opts, text="Save raw extracted text (.raw.md)",
            variable=self.keep_raw_var, style="Card.TCheckbutton", takefocus=0,
        ).pack(anchor="w")
        pop.bind("<Escape>", lambda _e: self._close_doc_advanced_popup())
        self._doc_advanced_popup = pop
        return pop

    @staticmethod
    def _widget_at_root(widget: tk.Misc, rx: int, ry: int) -> bool:
        try:
            wx = widget.winfo_rootx()
            wy = widget.winfo_rooty()
            return wx <= rx <= wx + widget.winfo_width() and wy <= ry <= wy + widget.winfo_height()
        except tk.TclError:
            return False

    def _is_doc_adv_popup_descendant(self, widget: tk.Misc) -> bool:
        pop = self._doc_advanced_popup
        if pop is None:
            return False
        w: tk.Misc | None = widget
        while w is not None:
            if w == pop:
                return True
            w = w.master
        return False

    def _on_doc_adv_dismiss(self, event) -> None:
        if not self._doc_adv_popup_open or getattr(self, "_doc_adv_ignore_dismiss", False):
            return
        if self._is_doc_adv_popup_descendant(event.widget):
            return
        if self._widget_at_root(self._doc_adv_btn, event.x_root, event.y_root):
            return
        self._close_doc_advanced_popup()

    def _toggle_doc_advanced_popup(self) -> None:
        if self._doc_adv_popup_open:
            self._close_doc_advanced_popup()
            return
        pop = self._ensure_doc_advanced_popup()
        self.update_idletasks()
        btn = self._doc_adv_btn
        shell = self._doc_adv_popup_shell
        shell.update_idletasks()
        w = shell.winfo_reqwidth()
        h = shell.winfo_reqheight()
        x = btn.winfo_rootx() + btn.winfo_width() - w
        y = btn.winfo_rooty() + btn.winfo_height() + space(1, self._ui_scale)
        pop.geometry(f"{w}x{h}+{x}+{y}")
        pop.deiconify()
        pop.lift()
        self._doc_adv_popup_open = True
        self._doc_adv_ignore_dismiss = True
        self.after(120, lambda: setattr(self, "_doc_adv_ignore_dismiss", False))

    def _close_doc_advanced_popup(self) -> None:
        if self._doc_advanced_popup is not None:
            try:
                self._doc_advanced_popup.withdraw()
            except tk.TclError:
                pass
        self._doc_adv_popup_open = False

    def _sync_output_entry(self, value: str) -> None:
        if self.output_entry is not None:
            self._sync_entry(self.output_entry, value)

    @staticmethod
    def _truncate_path(path: str, max_len: int = 72) -> str:
        if len(path) <= max_len:
            return path
        head = max_len // 2 - 2
        tail = max_len - head - 1
        return f"{path[:head]}\u2026{path[-tail:]}"

    def _sync_document_source_view(self) -> None:
        if not hasattr(self, "_doc_empty_view"):
            return
        path = self._normalize_path(self.source_var.get())
        if path:
            src = Path(path)
            self._doc_filename_var.set(src.name)
            self._doc_path_var.set(self._truncate_path(path))
            self._doc_empty_view.grid_remove()
            self._doc_selected_view.grid()
        else:
            self._doc_filename_var.set("")
            self._doc_path_var.set("")
            self._doc_selected_view.grid_remove()
            self._doc_empty_view.grid()

    def _clear_source_path(self) -> None:
        self.source_var.set("")
        self.output_var.set("")
        if hasattr(self, "output_entry") and self.output_entry is not None:
            self._sync_output_entry("")
        self._sync_workflow_from_inputs()
        self.status_var.set("Ready — choose a PDF or markdown file to begin")

    # ---- cross-tab workflow sync --------------------------------------------

    def _schedule_workflow_sync(self) -> None:
        if self._workflow_sync_after is not None:
            try:
                self.after_cancel(self._workflow_sync_after)
            except tk.TclError:
                pass
        self._workflow_sync_after = self.after(150, self._run_scheduled_workflow_sync)

    def _run_scheduled_workflow_sync(self) -> None:
        self._workflow_sync_after = None
        self._sync_workflow_from_inputs()

    def _current_markdown_path(self) -> Path | None:
        source = self._normalize_path(self.source_var.get())
        if not source:
            return None
        src = Path(source)
        if src.suffix.lower() == ".md":
            return src
        output_raw = self.output_var.get().strip()
        if output_raw:
            return Path(self._normalize_path(output_raw))
        return self._markdown_target(src)

    @staticmethod
    def _audiobook_label_for_markdown(md: Path) -> str:
        return md.stem

    @staticmethod
    def _markdown_audiobook_aliases(md: Path) -> set[str]:
        stem = md.stem
        aliases = {stem, stem.lower()}
        if stem.endswith(".readable"):
            short = stem[: -len(".readable")]
            aliases.update({short, short.lower()})
        return aliases

    def _card_settings_divider(self, parent: tk.Misc, row: int, *, colspan: int = 2) -> None:
        tk.Frame(parent, bg=self.colors["border"], height=1).grid(
            row=row, column=0, columnspan=colspan, sticky="ew",
        )

    def _expected_audiobook_path(self) -> Path | None:
        md = self._current_markdown_path()
        if md is None:
            return None
        fmt = self.audio_format_var.get().strip() or "m4b"
        return self._audiobook_output_path(md, fmt)

    def _clear_sections_state(self, *, message: str = "Load a document to see an estimate.") -> None:
        self._clear_section_checkboxes()
        self.section_count_var.set("")
        self.estimate_var.set(message)

    def _sync_audiobook_action_buttons(self) -> None:
        lib_path = self._selected_library_audiobook()
        has_audiobook = bool(
            (self._last_audiobook is not None and Path(self._last_audiobook).exists())
            or lib_path is not None
        )
        if hasattr(self, "audio_open_btn"):
            self.audio_open_btn.configure(state=tk.NORMAL if has_audiobook else tk.DISABLED)
        if hasattr(self, "audio_play_btn"):
            self.audio_play_btn.configure(state=tk.NORMAL if has_audiobook else tk.DISABLED)
        if hasattr(self, "audiobook_lib_open_btn"):
            self.audiobook_lib_open_btn.configure(
                state=tk.NORMAL if lib_path is not None else tk.DISABLED,
            )

    def _select_library_audiobook_for_markdown(self, md: Path) -> None:
        if not hasattr(self, "audiobook_lib_combo"):
            return
        label = self._audiobook_label_for_markdown(md)
        labels = [entry[0] for entry in self._audiobook_lib_entries]
        aliases = self._markdown_audiobook_aliases(md)
        pick = label if label in labels else ""
        if not pick:
            for lib_label in labels:
                if lib_label in aliases or lib_label.lower() in aliases:
                    pick = lib_label
                    break
        expected = self._expected_audiobook_path()
        if expected is not None:
            for lib_label, lib_path in self._audiobook_lib_entries:
                if lib_path.resolve() == expected.resolve():
                    pick = lib_label
                    break
                sidecar = expected.with_name(f"{expected.stem}.chapters.json")
                if lib_path.resolve() == sidecar.resolve():
                    pick = lib_label
                    break
        if pick:
            self.audiobook_lib_pick_var.set(pick)
        elif self.audiobook_lib_pick_var.get() not in labels:
            self.audiobook_lib_pick_var.set("")
        lib_path = self._selected_library_audiobook()
        if lib_path is not None:
            self._last_audiobook = lib_path
        elif expected is not None and expected.is_file():
            self._last_audiobook = expected
        self._sync_audiobook_action_buttons()

    def _sync_player_document_label(self) -> None:
        if not hasattr(self, "player_title_var"):
            return
        md = self._current_markdown_path()
        if md is None:
            if self._player_path is None:
                self.player_title_var.set("No audiobook loaded yet")
            return
        expected = self._expected_audiobook_path()
        expected_name = expected.name if expected else None
        if self._player_path is not None and self._player_playable:
            loaded = self._player_path.resolve()
            matches = expected is not None and loaded == expected.resolve()
            if not matches:
                for lib_label, lib_path in self._audiobook_lib_entries:
                    if lib_label == self._audiobook_label_for_markdown(md) and lib_path.resolve() == loaded:
                        matches = True
                        break
            if matches:
                chapters = len(self._player_chapters)
                self.player_title_var.set(f"Loaded: {self._player_path.name}  ·  {chapters} chapter(s)")
                return
            self.player_title_var.set(
                f"Playing {self._player_path.name} — document is now {md.name}",
            )
            return
        lib_path = self._selected_library_audiobook()
        if lib_path is not None:
            self.player_title_var.set(f"{lib_path.name} selected for {md.name}")
            return
        if expected is not None and expected.is_file():
            self.player_title_var.set(f"{expected.name} ready for {md.name}")
        elif expected_name:
            self.player_title_var.set(f"No {expected_name} yet for {md.name}")
        else:
            self.player_title_var.set(f"Document: {md.name}")

    def _sync_workflow_from_inputs(self) -> None:
        if not hasattr(self, "_doc_empty_view"):
            return
        md = self._current_markdown_path()
        if md is not None and md.is_file():
            self._load_sections_from_markdown(md)
        elif not self.source_var.get().strip():
            self._clear_sections_state()
        else:
            self._clear_sections_state(
                message="Convert to markdown or choose an existing .md to see sections.",
            )

        if md is not None:
            folder = str(md.parent)
            if self._normalize_path(self.audiobook_lib_dir_var.get()) != folder:
                self._set_audiobook_library_folder(folder)
            else:
                self._refresh_audiobook_library()
            self._select_library_audiobook_for_markdown(md)
        elif hasattr(self, "audiobook_lib_combo"):
            self._refresh_audiobook_library()
            self._last_audiobook = None
            self._sync_audiobook_action_buttons()

        self._sync_player_document_label()
        self._sync_document_source_view()
        self._sync_footer_title()

    # ---- Audiobook tab ------------------------------------------------------

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

        sections_label = ttk.Frame(settings, style="Card.TFrame")
        sections_label.grid(row=grid_row, column=0, sticky="w", pady=row_pady)
        ttk.Label(sections_label, text="Sections", style="CardFormLabel.TLabel", width=label_w).pack(side=tk.LEFT)
        ttk.Label(sections_label, textvariable=self.section_count_var, style="CardMuted.TLabel").pack(
            side=tk.LEFT, padx=(space(1, self._ui_scale), 0),
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

        bar = self._track_reflow_bar(ReflowBar(action_row, gap=space(2, self._ui_scale), style="Card.TFrame"))
        self._audio_action_bar = bar
        bar.grid(row=0, column=0, sticky="w")
        self.make_audiobook_btn = make_accent_button(bar, "Create audiobook", self._start_audiobook, self.colors)
        bar.add(self.make_audiobook_btn)
        self.audio_open_btn = make_secondary_button(bar, "Open audiobook", self._open_audiobook_file, self.colors)
        bar.add(self.audio_open_btn)
        self.audio_play_btn = make_secondary_button(bar, "Play in app", self._play_last_in_app, self.colors)
        bar.add(self.audio_play_btn)
        self.audio_open_btn.configure(state=tk.DISABLED)
        self.audio_play_btn.configure(state=tk.DISABLED)
        bar.reflow()

        self._audio_log_host = ttk.Frame(inner)
        self._audio_log_host.grid(row=1, column=0, sticky="nsew")
        self.after_idle(self._sync_work_tab_heights)

    def _inline_chip(self, parent: tk.Misc, label: str, *, pack: bool = True) -> ttk.Frame:
        """Compact card that hugs its label + contents."""
        outer = make_card(parent, self.colors)
        if pack:
            outer.pack(anchor="w", pady=(0, space(2, self._ui_scale)))
        pad = space(2, self._ui_scale)
        body = ttk.Frame(outer._card_inner, style="Card.TFrame", padding=(space(3, self._ui_scale), pad))  # type: ignore[attr-defined]
        body.pack(anchor="w")
        body._chip_outer = outer  # type: ignore[attr-defined]
        ttk.Label(body, text=label, style="CardMuted.TLabel").pack(side=tk.LEFT)
        return body

    def _make_icon_button(
        self, parent: tk.Misc, icon: str, command, *, title: str = "", bg: str | None = None,
        small: bool = False,
    ) -> CanvasButton:
        scale = self._ui_scale
        base_bg = bg or self.colors["bg"]
        btn = CanvasButton(
            parent, icon, command, colors=self.colors, variant="icon",
            font_role="caption" if small else "body",
            pad_x=space(2 if small else 3, scale),
            pad_y=space(1 if small else 2, scale),
        )
        btn.configure(bg=base_bg)
        if title:
            def _tip_in(_e, t=title) -> None:
                self.status_var.set(t)
            def _tip_out(_e) -> None:
                if not self._busy:
                    self.status_var.set("Ready — choose a PDF or markdown file to begin")
            btn.bind("<Enter>", _tip_in, add="+")
            btn.bind("<Leave>", _tip_out, add="+")
        return btn

    def _make_round_play_button(self, parent: tk.Misc, command) -> tk.Canvas:
        """Spotify-style circular play/pause control drawn on a canvas."""
        scale = self._ui_scale
        diameter = max(88, int(98 * scale))
        pad = 2
        bg = self.colors["card"]
        canvas = tk.Canvas(
            parent, width=diameter, height=diameter, bg=bg,
            highlightthickness=0, bd=0, cursor="hand2",
        )
        canvas._play_diameter = diameter  # type: ignore[attr-defined]
        canvas._play_enabled = True  # type: ignore[attr-defined]
        canvas._play_command = command  # type: ignore[attr-defined]
        canvas._play_oval = canvas.create_oval(
            pad, pad, diameter - pad, diameter - pad,
            fill=self.colors["accent"], outline="",
        )
        cx, cy = diameter // 2, diameter // 2
        tri = max(8, int(diameter * 0.22))
        # Nudge left so the triangle reads centered inside the circle.
        shift = max(1, tri // 6)
        x0 = cx - tri // 2 - shift
        x1 = cx + tri // 2 - shift
        y0, y1 = cy - tri // 2, cy + tri // 2
        canvas._play_icon = canvas.create_polygon(
            x0, y0, x0, y1, x1, cy,
            fill="#ffffff", outline="", state="normal",
        )
        bar_h = int(diameter * 0.26)
        bar_w = max(3, int(diameter * 0.075))
        bar_gap = max(5, int(diameter * 0.12))
        x_l1 = cx - bar_gap // 2
        x_r0 = cx + bar_gap // 2
        canvas._pause_left = canvas.create_rectangle(  # type: ignore[attr-defined]
            x_l1 - bar_w, cy - bar_h // 2, x_l1, cy + bar_h // 2,
            fill="#ffffff", outline="", state="hidden",
        )
        canvas._pause_right = canvas.create_rectangle(  # type: ignore[attr-defined]
            x_r0, cy - bar_h // 2, x_r0 + bar_w, cy + bar_h // 2,
            fill="#ffffff", outline="", state="hidden",
        )

        def _click(_e) -> None:
            if canvas._play_enabled:  # type: ignore[attr-defined]
                command()

        def on_enter(_e) -> None:
            if canvas._play_enabled:  # type: ignore[attr-defined]
                canvas.itemconfigure(canvas._play_oval, fill=self.colors["accent_hover"])

        def on_leave(_e) -> None:
            if canvas._play_enabled:  # type: ignore[attr-defined]
                canvas.itemconfigure(canvas._play_oval, fill=self.colors["accent"])

        canvas.bind("<Button-1>", _click)
        canvas.bind("<Enter>", on_enter)
        canvas.bind("<Leave>", on_leave)
        return canvas

    def _make_player_icon_button(
        self, parent: tk.Misc, label: str, command, *, large: bool = False,
    ) -> CanvasButton:
        """Transport control for the player row."""
        scale = self._ui_scale
        btn = CanvasButton(
            parent, label, command, colors=self.colors, variant="player",
            font_role="title" if large else "body",
            font_weight="bold" if large else None,
            pad_x=space(4 if large else 3, scale),
            pad_y=space(3 if large else 2, scale),
        )
        btn.configure(bg=self.colors["card"])
        return btn

    def _set_play_button_enabled(self, *, enabled: bool) -> None:
        btn = self.play_btn
        btn._play_enabled = enabled  # type: ignore[attr-defined]
        fill = self.colors["accent"] if enabled else self.colors["border_subtle"]
        icon_fill = "#ffffff" if enabled else self.colors["muted"]
        btn.itemconfigure(btn._play_oval, fill=fill)  # type: ignore[attr-defined]
        btn.itemconfigure(btn._play_icon, fill=icon_fill)  # type: ignore[attr-defined]
        for item in (btn._pause_left, btn._pause_right):  # type: ignore[attr-defined]
            btn.itemconfigure(item, fill=icon_fill)
        btn.configure(cursor="hand2" if enabled else "arrow")

    def _player_centered_strip(
        self, parent: ttk.Frame, *, row: int, pady, width_pct: int = 60,
    ) -> ttk.Frame:
        """Center a control row at ``width_pct`` of the available width."""
        side = max(1, (100 - width_pct) // 2)
        center = max(1, width_pct)
        outer = ttk.Frame(parent, style="Card.TFrame")
        outer.grid(row=row, column=0, sticky="ew", pady=pady)
        outer.columnconfigure(0, weight=side)
        outer.columnconfigure(1, weight=center)
        outer.columnconfigure(2, weight=side)
        inner = ttk.Frame(outer, style="Card.TFrame")
        inner.grid(row=0, column=1, sticky="ew")
        return inner

    # ---- Player tab ---------------------------------------------------------

    def _build_player_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        inner, self._player_outline_shell = self._make_tab_outline(
            parent, expand=True, padding=self._player_tab_shell_pad(),
        )
        inner.columnconfigure(0, weight=1)
        inner.rowconfigure(0, weight=0)
        inner.rowconfigure(1, weight=1)

        top = ttk.Frame(inner)
        top.grid(row=0, column=0, sticky="new")
        top.columnconfigure(0, weight=1)
        self._player_work_top = top
        self._make_section_heading(top, "Player").pack(anchor="w")
        ttk.Label(top, textvariable=self.player_title_var, style="PlayerFileTitle.TLabel").pack(
            anchor="w", pady=self._work_tab_subtitle_pady(),
        )

        lib_card = make_card(top, self.colors)
        lib_card.pack(fill=tk.X, pady=(0, space(2, self._ui_scale)))
        self._player_lib_card = lib_card
        lib_pad = space(3, self._ui_scale)
        lib_body = ttk.Frame(
            lib_card._card_inner, style="Card.TFrame",
            padding=(lib_pad, lib_pad, lib_pad, space(2, self._ui_scale)),
        )  # type: ignore[attr-defined]
        lib_body.pack(fill=tk.X, anchor="nw")
        lib_body.columnconfigure(1, weight=1)
        gap = space(2, self._ui_scale)

        ttk.Label(lib_body, text="Library folder", style="CardFormLabel.TLabel", width=12).grid(
            row=0, column=0, sticky="w", pady=(0, gap),
        )
        lib_dir_row = ttk.Frame(lib_body, style="Card.TFrame")
        lib_dir_row.grid(row=0, column=1, columnspan=2, sticky="ew", pady=(0, gap))
        lib_dir_row.columnconfigure(0, weight=1)
        self.audiobook_lib_dir_entry = make_path_entry(lib_dir_row, self.audiobook_lib_dir_var, self.colors)
        self.audiobook_lib_dir_entry.grid(row=0, column=0, sticky="ew")
        make_browse_button(lib_dir_row, "Choose folder…", self._browse_audiobook_library_folder, self.colors).grid(
            row=0, column=1, padx=(gap, 0),
        )
        self._make_icon_button(lib_dir_row, "↻", self._refresh_audiobook_library, title="Refresh library").grid(
            row=0, column=2, padx=(gap, 0),
        )

        ttk.Label(lib_body, text="Audiobook", style="CardFormLabel.TLabel", width=12).grid(row=1, column=0, sticky="w")
        self.audiobook_lib_combo = ttk.Combobox(
            lib_body, textvariable=self.audiobook_lib_pick_var, state="readonly",
            style="Dark.TCombobox",
        )
        self.audiobook_lib_combo.grid(row=1, column=1, sticky="ew", pady=(0, space(1, self._ui_scale)))
        configure_dark_combobox(self.audiobook_lib_combo, self.colors)
        self.audiobook_lib_combo.bind("<<ComboboxSelected>>", self._on_audiobook_library_pick)
        self.audiobook_lib_open_btn = make_secondary_button(
            lib_body, "Open", self._open_selected_audiobook, self.colors,
        )
        self.audiobook_lib_open_btn.grid(row=1, column=2, sticky="w", padx=(gap, 0))
        self.audiobook_lib_open_btn.configure(state=tk.DISABLED)

        self._configure_player_styles()

        self._player_controls_card = make_card(inner, self.colors)
        self._player_controls_card.grid(
            row=1, column=0, sticky="nsew", pady=(space(2, self._ui_scale), space(1, self._ui_scale)),
        )
        card_pad = space(5, self._ui_scale)
        cbody = ttk.Frame(
            self._player_controls_card._card_inner,
            style="Card.TFrame",
            padding=(card_pad, card_pad, card_pad, space(3, self._ui_scale)),
        )  # type: ignore[attr-defined]
        cbody.pack(fill=tk.BOTH, expand=True)
        cbody.columnconfigure(0, weight=1)
        cbody.rowconfigure(0, weight=1)
        cbody.rowconfigure(1, weight=0)

        gap = space(3, self._ui_scale)
        player_shell = ttk.Frame(cbody, style="Card.TFrame")
        player_shell.grid(row=0, column=0, sticky="nsew")
        player_shell.columnconfigure(0, weight=1)
        player_shell.rowconfigure(0, weight=1)

        main = ttk.Frame(player_shell, style="Card.TFrame")
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=70)
        main.rowconfigure(1, weight=30)

        playback_zone = ttk.Frame(main, style="Card.TFrame")
        playback_zone.grid(row=0, column=0, sticky="nsew")
        playback_zone.columnconfigure(0, weight=1)
        playback_zone.rowconfigure(0, weight=1)
        playback_zone.rowconfigure(1, weight=0)
        playback_zone.rowconfigure(2, weight=1)

        playback_cluster = ttk.Frame(playback_zone, style="Card.TFrame")
        playback_cluster.grid(row=1, column=0, sticky="ew")
        playback_cluster.columnconfigure(0, weight=1)
        self._playback_cluster = playback_cluster

        title_block = ttk.Frame(playback_cluster, style="Card.TFrame")
        title_block.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            title_block, textvariable=self.player_chapter_title_var,
            style="PlayerChapterTitle.TLabel", anchor="center",
        ).pack(fill=tk.X)
        ttk.Label(
            title_block, textvariable=self.player_chapter_sub_var,
            style="CardHeading.TLabel", anchor="center",
        ).pack(fill=tk.X, pady=(space(1, self._ui_scale), 0))

        player_strip = self._player_centered_strip(
            playback_cluster, row=1,
            pady=(space(4, self._ui_scale), space(2, self._ui_scale)),
            width_pct=60,
        )
        self._player_strip = player_strip
        self._player_strip_gap_units = 0.5
        pc = configure_gutter_grid(player_strip, scale=self._ui_scale, gap_units=self._player_strip_gap_units)
        self._player_strip_gap_cols = (pc["gap_l"], pc["gap_r"])
        ctrl_pad = (space(2, self._ui_scale), 0)

        ttk.Label(
            player_strip, textvariable=self.player_chapter_elapsed_var,
            style="PlayerTime.TLabel", anchor="w",
        ).grid(row=0, column=pc["left"], sticky="w")
        self.seek_scale = ttk.Scale(
            player_strip, from_=0, to=1000, orient=tk.HORIZONTAL, variable=self.seek_var,
            style="Player.Horizontal.TScale", command=self._on_seek_drag,
        )
        self.seek_scale.grid(
            row=0, column=pc["center"], sticky="ew", ipady=space(2, self._ui_scale),
        )
        self.seek_scale.bind("<Button-1>", self._on_seek_press)
        self.seek_scale.bind("<B1-Motion>", self._on_seek_motion)
        self.seek_scale.bind("<ButtonRelease-1>", self._on_seek_release)
        ttk.Label(
            player_strip, textvariable=self.player_chapter_total_var,
            style="PlayerTime.TLabel", anchor="e",
        ).grid(row=0, column=pc["right"], sticky="e")

        self._vol_icon = tk.Label(
            player_strip, text="🔈", bg=self.colors["card"], fg=self.colors["muted"],
            font=typeface("title", self._ui_scale),
        )
        self._vol_icon.grid(row=1, column=pc["left"], sticky="w", pady=ctrl_pad)

        center_controls = ttk.Frame(player_strip, style="Card.TFrame")
        center_controls.grid(row=1, column=pc["center"], sticky="ew", pady=ctrl_pad)
        center_controls.columnconfigure(0, weight=0)
        center_controls.columnconfigure(1, weight=1)
        center_controls.columnconfigure(2, weight=0)

        vol_strip = tk.Frame(center_controls, bg=self.colors["card"])
        vol_strip.grid(row=0, column=0, sticky="w")
        self.volume_scale = ttk.Scale(
            vol_strip, from_=0, to=100, orient=tk.HORIZONTAL, variable=self.volume_var,
            command=self._on_volume_change, style="Player.Horizontal.TScale",
            length=max(int(100 * self._ui_scale), 88),
        )
        self.volume_scale.pack(side=tk.LEFT)
        self._vol_pct_var = tk.StringVar(value="85%")
        self._vol_pct = tk.Label(
            vol_strip, textvariable=self._vol_pct_var, anchor="w",
            bg=self.colors["card"], fg=self.colors["muted"], width=4,
        )
        self._vol_pct.pack(side=tk.LEFT, padx=(gap, 0))
        track_font(self._vol_pct, "caption", self.colors)

        transport = ttk.Frame(center_controls, style="Card.TFrame")
        transport.grid(row=0, column=1)
        btn_pad = (0, gap)
        self.prev_btn = self._make_player_icon_button(transport, "|◀", self._player_prev, large=True)
        self.prev_btn.pack(side=tk.LEFT, padx=btn_pad)
        self.back10_btn = self._make_player_icon_button(
            transport, "↺10", lambda: self._seek_relative(-10000), large=True,
        )
        self.back10_btn.pack(side=tk.LEFT, padx=btn_pad)

        play_host = tk.Frame(transport, bg=self.colors["card"])
        play_host.pack(side=tk.LEFT, padx=(gap, gap))
        self.play_btn = self._make_round_play_button(play_host, self._player_toggle)
        self.play_btn.pack()

        self.fwd10_btn = self._make_player_icon_button(
            transport, "10↻", lambda: self._seek_relative(10000), large=True,
        )
        self.fwd10_btn.pack(side=tk.LEFT, padx=btn_pad)
        self.next_btn = self._make_player_icon_button(transport, "▶|", self._player_next, large=True)
        self.next_btn.pack(side=tk.LEFT, padx=btn_pad)

        ttk.Label(center_controls, text="Speed", style="CardMuted.TLabel").grid(
            row=0, column=2, sticky="e", padx=(gap, 0),
        )

        self.speed_combo = ttk.Combobox(
            player_strip, textvariable=self.speed_var, state="readonly", width=6, style="Dark.TCombobox",
            values=("0.75×", "1.0×", "1.25×", "1.5×", "1.75×", "2.0×"),
        )
        self.speed_combo.grid(row=1, column=pc["right"], sticky="e", pady=ctrl_pad)
        configure_dark_combobox(self.speed_combo, self.colors)
        self.speed_combo.bind("<<ComboboxSelected>>", self._on_speed_change)

        book_block = ttk.Frame(main, style="Card.TFrame")
        book_block.grid(row=1, column=0, sticky="nsew")
        book_block.columnconfigure(0, weight=1)
        book_block.rowconfigure(0, weight=1)
        book_block.rowconfigure(1, weight=0)

        book_bottom = ttk.Frame(book_block, style="Card.TFrame")
        book_bottom.grid(row=1, column=0, sticky="esw")
        book_bottom.columnconfigure(0, weight=1)

        book_hdr = ttk.Frame(book_bottom, style="Card.TFrame")
        book_hdr.grid(row=0, column=0, sticky="ew", pady=(0, space(2, self._ui_scale)))
        book_hdr.columnconfigure(1, weight=1)
        ttk.Label(book_hdr, text="Book progress", style="CardMuted.TLabel").grid(row=0, column=0, sticky="w")
        book_times = ttk.Frame(book_hdr, style="Card.TFrame")
        book_times.grid(row=0, column=1, sticky="e")
        ttk.Label(
            book_times, textvariable=self.player_book_elapsed_var,
            style="PlayerTime.TLabel", anchor="e",
        ).pack(side=tk.LEFT)
        ttk.Label(book_times, text=" / ", style="CardMuted.TLabel").pack(side=tk.LEFT)
        ttk.Label(
            book_times, textvariable=self.player_book_total_var,
            style="PlayerTime.TLabel", anchor="e",
        ).pack(side=tk.LEFT)

        book_tl_wrap = ttk.Frame(book_bottom, style="Card.TFrame")
        book_tl_wrap.grid(row=1, column=0, sticky="esw")
        book_tl_wrap.columnconfigure(0, weight=1)
        self._player_book_block = book_block
        self._book_hdr = book_hdr
        self._book_bottom = book_bottom
        self._build_book_timeline(book_tl_wrap)
        book_block.bind("<Configure>", lambda _e: self._resize_book_timeline(), add="+")

        player_footer = ttk.Frame(cbody, style="Card.TFrame")
        player_footer.grid(row=1, column=0, sticky="e", pady=(space(2, self._ui_scale), 0))
        self.player_open_ext_btn = self._make_icon_button(
            player_footer, "↗", self._open_audiobook_file, title="Open externally",
            bg=self.colors["card"], small=True,
        )
        self.player_open_ext_btn.pack(side=tk.RIGHT)

        self._refresh_volume_ui()
        self._set_player_controls(enabled=False)
        self.after_idle(self._sync_player_chrome_layout)
        self.after_idle(self._sync_work_tab_heights)

    def _book_timeline_min_height(self) -> int:
        return max(56, int(64 * self._ui_scale))

    def _book_timeline_height(self) -> int:
        """Half of the book-block area below the header, bottom-anchored."""
        min_h = self._book_timeline_min_height()
        half_floor = max(28, min_h // 2)
        try:
            self._player_book_block.update_idletasks()
            block_h = self._player_book_block.winfo_height()
            hdr_h = self._book_hdr.winfo_height() if hasattr(self, "_book_hdr") else 0
            area_h = max(block_h - hdr_h, min_h)
            if area_h > 1:
                return max(half_floor, max(area_h, min_h) // 2)
        except (tk.TclError, AttributeError):
            pass
        return half_floor

    def _resize_book_timeline(self) -> None:
        if not hasattr(self, "_book_tl"):
            return
        try:
            h = self._book_timeline_height()
            if abs(h - self._book_tl.winfo_height()) >= 2:
                self._book_tl.configure(height=h)
                self._draw_book_timeline()
        except tk.TclError:
            pass

    def _sync_player_chrome_layout(self) -> None:
        """Tight library card + bottom-anchored book timeline sizing."""
        try:
            if hasattr(self, "_player_lib_card"):
                fit_round_surface_to_content(self._player_lib_card, scale=self._ui_scale)
            self._resize_book_timeline()
        except tk.TclError:
            pass

    # ---- book timeline (DAW-style chapter strips) ---------------------------

    def _build_book_timeline(self, parent: ttk.Frame) -> None:
        self._book_tl_wrap = parent
        self._book_tl_regions: list[tuple[int, int, str, int]] = []
        self._book_tl = tk.Canvas(
            parent, height=self._book_timeline_min_height() // 2, bg=self.colors["card"],
            highlightthickness=0, bd=0, cursor="hand2",
        )
        self._book_tl.grid(row=0, column=0, sticky="esw")
        self._book_tl_resize_after: str | None = None
        self._book_tl_last_width = 0
        parent.bind("<Configure>", self._schedule_book_timeline_redraw, add="+")
        self._book_tl.bind("<Button-1>", self._on_book_seek_press)
        self._book_tl.bind("<B1-Motion>", self._on_book_seek_motion)
        self._book_tl.bind("<ButtonRelease-1>", self._on_book_seek_release)
        self._book_tl.bind("<Motion>", self._on_book_tl_hover)
        self._book_tl.bind("<Leave>", lambda _e: self._hide_book_tl_tooltip())
        self._book_tl_tip: tk.Toplevel | None = None
        self._draw_book_timeline()

    def _schedule_book_timeline_redraw(self, _event=None) -> None:
        if self._book_tl_resize_after is not None:
            return
        self._book_tl_resize_after = self.after(80, self._finish_book_timeline_redraw)

    def _finish_book_timeline_redraw(self) -> None:
        self._book_tl_resize_after = None
        try:
            width = self._book_tl_wrap.winfo_width()
        except tk.TclError:
            return
        if width <= 1 or abs(width - self._book_tl_last_width) < 4:
            return
        self._draw_book_timeline()

    def _book_timeline_fill(self, index: int, *, current: int, enabled: bool) -> str:
        """Audible-style: completed, current, and upcoming chapter segments."""
        if not enabled:
            return self.colors["border_subtle"]
        if index < current:
            return "#4a42a0"
        if index == current:
            return self.colors["accent"]
        return "#3a3f5a"

    def _ensure_book_tl_tooltip(self) -> None:
        if self._book_tl_tip is not None:
            try:
                if self._book_tl_tip.winfo_exists():
                    return
            except tk.TclError:
                pass
        tip = tk.Toplevel(self)
        tip.wm_overrideredirect(True)
        tip.configure(bg=self.colors["border"])
        frame = tk.Frame(tip, bg=self.colors["card"], padx=space(2, self._ui_scale), pady=space(1, self._ui_scale))
        frame.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        self._book_tl_tip_label = tk.Label(
            frame, text="", bg=self.colors["card"], fg=self.colors["text"], anchor="w",
        )
        self._book_tl_tip_label.pack()
        track_font(self._book_tl_tip_label, "caption", self.colors)
        tip.withdraw()
        self._book_tl_tip = tip

    def _show_book_tl_tooltip(self, x_root: int, y_root: int, text: str) -> None:
        self._ensure_book_tl_tooltip()
        self._book_tl_tip_label.configure(text=text)
        self._book_tl_tip.update_idletasks()
        self._book_tl_tip.geometry(f"+{x_root + 12}+{y_root - 28}")
        self._book_tl_tip.deiconify()
        self._book_tl_tip.lift()

    def _hide_book_tl_tooltip(self) -> None:
        if self._book_tl_tip is not None:
            try:
                self._book_tl_tip.withdraw()
            except tk.TclError:
                pass

    def _book_tl_chapter_at(self, x: int) -> str | None:
        for x0, x1, title, _idx in self._book_tl_regions:
            if x0 <= x <= x1:
                return title
        return None

    def _on_book_tl_hover(self, event) -> None:
        if self._user_book_seeking:
            self._hide_book_tl_tooltip()
            return
        label = self._book_tl_chapter_at(event.x)
        if label:
            self._show_book_tl_tooltip(event.x_root, event.y_root, label)
        else:
            self._hide_book_tl_tooltip()

    def _draw_book_timeline(self, _event=None) -> None:
        if not hasattr(self, "_book_tl"):
            return
        try:
            width = self._book_tl_wrap.winfo_width()
            if width <= 1:
                return
            self._book_tl_last_width = width
            h = self._book_timeline_height()
            self._book_tl.configure(width=width)
            self._book_tl.delete("all")
            self._book_tl_regions.clear()

            pad_x, pad_y = 4, max(2, int(4 * self._ui_scale))
            inner_w = max(width - pad_x * 2, 1)
            top = pad_y + 1
            bot = h - pad_y - 1
            seg_r = max(2, min(3, int(2 * self._ui_scale)))

            chapters = self._player_chapters
            if not chapters:
                r = min(seg_r, max(1, inner_w // 2), max(1, (bot - top) // 2))
                draw_round_rect(
                    self._book_tl, pad_x, top, pad_x + inner_w, bot, r,
                    fill=self.colors["border_subtle"], outline="",
                )
                return

            durations = [self._player.effective_duration_ms(i) for i in range(len(chapters))]
            total = sum(durations) or 1
            current = self._player.index if self._player_playable else -1
            enabled = self._book_timeline_enabled and self._player_playable
            n = len(chapters)
            gap = max(2, int(3 * self._ui_scale))
            total_gaps = gap * (n - 1) if n > 1 else 0
            usable = max(inner_w - total_gaps, n)
            x_cursor = pad_x

            for i, dur in enumerate(durations):
                seg_w = max(int(dur / total * usable), 2)
                x0 = x_cursor
                x1 = x0 + seg_w
                x_cursor = x1 + (gap if i < n - 1 else 0)
                fill = self._book_timeline_fill(i, current=current, enabled=enabled)
                self._book_tl_regions.append((x0, x1, chapters[i].title, i))
                r = min(seg_r, max(1, (x1 - x0) // 2), max(1, (bot - top) // 2))
                draw_round_rect(self._book_tl, x0, top, x1, bot, r, fill=fill, outline="")
                if i == current and enabled:
                    draw_round_rect(
                        self._book_tl, x0, top, x1, bot, r,
                        fill="", outline=self.colors["glow"], width=1,
                    )

            frac = self.book_seek_var.get() / 1000.0
            play_x = pad_x + int(frac * inner_w)
            if enabled:
                play_color = "#ffffff"
                line_w = max(2, int(3 * self._ui_scale))
                cap = max(4, int(5 * self._ui_scale))
                self._book_tl.create_line(
                    play_x, 0, play_x, h, fill=play_color, width=line_w, tags=("playhead",),
                )
                self._book_tl.create_polygon(
                    play_x - cap, 0, play_x + cap, 0, play_x, cap,
                    fill=play_color, outline="", tags=("playhead",),
                )
                self._book_tl.tag_raise("playhead")
            else:
                self._book_tl.create_line(
                    play_x, top, play_x, bot, fill=self.colors["muted"], width=2, tags=("playhead",),
                )
        except tk.TclError:
            pass

    # ---- volume ---------------------------------------------------------------

    def _refresh_volume_ui(self) -> None:
        vol = self.volume_var.get()
        icon = "🔇" if vol < 1 else "🔈" if vol < 34 else "🔉" if vol < 67 else "🔊"
        self._vol_icon.configure(text=icon)
        self._vol_pct_var.set(f"{int(round(vol))}%")

    # ---- sections (audiobook tab) -------------------------------------------

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
        source = self._normalize_path(self.source_var.get())
        if not source:
            self._show_toast("Choose a PDF or markdown file on the Document tab first.", kind="info")
            return
        src = Path(source)
        if src.suffix.lower() == ".md":
            self._load_sections_from_markdown(src)
            return
        md = self._markdown_target(src)
        if md.is_file():
            self._load_sections_from_markdown(md)
            return
        if not src.is_file():
            self._show_toast(f"File not found: {source}", kind="error")
            return
        self._cancel_event.clear()
        self._set_busy(True, "Scanning sections…")

        def run() -> None:
            try:
                from novelflow.convert import ConversionCancelled, convert_pdf

                result = convert_pdf(source, str(md), cancel_check=self._cancel_event.is_set)
                self._ui(self._load_sections_from_markdown, result)
                self._ui(self.status_var.set, f"Sections loaded from {result.name}")
            except ConversionCancelled:
                self._ui(self.status_var.set, "Section scan cancelled")
            except Exception as exc:
                self._ui(lambda e=str(exc): self._show_toast(e, kind="error"))
            finally:
                self._ui(self._set_busy, False)

        threading.Thread(target=run, daemon=True).start()

    def _load_sections_from_markdown(self, markdown_path: Path) -> None:
        from novelflow.book_structure import default_audiobook_disabled_ids, parse_book_sections

        try:
            manifest = parse_book_sections(markdown_path.read_text(encoding="utf-8"))
        except Exception:
            return
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

        def _on_wheel(event) -> str:
            if not event.delta:
                return "break"
            canvas.update_idletasks()
            first, last = canvas.yview()
            span = float(last) - float(first)
            if span >= 1.0:
                return "break"
            step = span * 0.12 * (-1 if event.delta > 0 else 1)
            canvas.yview_moveto(max(0.0, min(1.0 - span, float(first) + step)))
            return "break"

        def _bind_tree(widget: tk.Misc) -> None:
            widget.bind("<MouseWheel>", _on_wheel, add="+")
            widget.bind("<Enter>", lambda _e, c=canvas: c.focus_set(), add="+")
            for child in widget.winfo_children():
                _bind_tree(child)

        canvas.bind("<MouseWheel>", _on_wheel)
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

        # Full-height checklist (left).
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

        # Selected summary (right) — same height as list.
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
            selectbackground=self.colors["accent"], selectforeground="#ffffff",
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

    # ---- voices -------------------------------------------------------------

    def _engine_key(self) -> str:
        return "edge"

    def _refresh_voice_list(self) -> None:
        from novelflow.tts_voices import default_voice, voices_for_engine

        voices = voices_for_engine("edge")
        labels = [f"{v.label} ({v.id})" for v in voices]
        self.voice_combo.configure(values=labels)
        fit_combobox(self.voice_combo, labels, scale=self._ui_scale, min_chars=18, max_chars=32)
        default = default_voice("edge")
        for idx, voice in enumerate(voices):
            if voice.id == default:
                self.voice_combo.current(idx)
                return
        if labels:
            self.voice_combo.current(0)

    def _selected_voice_id(self) -> str:
        from novelflow.tts_voices import default_voice, voices_for_engine

        label = self.tts_voice_var.get()
        for voice in voices_for_engine("edge"):
            if f"({voice.id})" in label:
                return voice.id
        return default_voice("edge")

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
        self._set_preview_busy(True)
        self.status_var.set(f"Synthesizing preview ({voice})…")

        def run() -> None:
            try:
                import tempfile

                from novelflow.tts_engines import get_engine

                cache = Path(tempfile.gettempdir()) / "novelflow_voice_previews"
                cache.mkdir(exist_ok=True)
                clip = cache / f"{voice}.mp3"
                if not (clip.is_file() and clip.stat().st_size > 1024):
                    get_engine("edge").synthesize_section(_PREVIEW_TEXT, clip, voice=voice)
                self._ui(self._player.play_preview, clip)
                self._ui(self.status_var.set, f"Previewing voice: {voice}")
            except Exception as exc:  # noqa: BLE001
                self._ui(self.status_var.set, f"Preview failed: {exc}")
            finally:
                self._ui(self._set_preview_busy, False)

        threading.Thread(target=run, daemon=True).start()

    # ---- progress / eta -----------------------------------------------------

    def _phase_label(self, pct: float) -> str:
        if pct <= 0:
            return ""
        if self._phase_audiobook:
            if pct < 8:
                return "Extracting and refining PDF…"
            if pct < 88:
                return "Narrating chapters…"
            return "Finalizing audiobook file…"
        if pct < 44:
            return "Extracting text from PDF…"
        if pct < 70:
            return "Refining chapters and scene headers…"
        return "Finishing up…"

    @staticmethod
    def _format_eta(seconds: float) -> str:
        seconds = int(round(seconds))
        if seconds < 60:
            return f"~{max(seconds, 1)}s left"
        if seconds < 3600:
            minutes, secs = divmod(seconds, 60)
            return f"~{minutes}m {secs:02d}s left"
        hours, rem = divmod(seconds, 3600)
        return f"~{hours}h {rem // 60:02d}m left"

    def _eta_text(self, pct: float) -> str:
        if self._progress_start is None or pct >= 99.5:
            return ""
        elapsed = time.monotonic() - self._progress_start
        if pct < 3 or elapsed < 2:
            return "estimating…"
        remaining = elapsed * (100.0 - pct) / pct
        if self._eta_ema is None:
            self._eta_ema = remaining
        else:
            self._eta_ema = 0.3 * remaining + 0.7 * self._eta_ema
        return self._format_eta(self._eta_ema)

    def _set_progress(self, pct: float, label: str = "") -> None:
        pct = max(0.0, min(100.0, pct))
        self.progress_var.set(pct)
        self._current_progress_pct = pct
        self._current_progress_label = label if label else self._phase_label(pct)
        self._sync_progress_display()

    def _reset_progress(self) -> None:
        self._progress_start = None
        self._eta_ema = None
        self.progress_var.set(0.0)
        self._current_progress_pct = 0.0
        self._current_progress_label = ""
        self.progress_meta_var.set("")
        self._sync_footer_title()
        self._draw_footer_bar()

    # ---- log ----------------------------------------------------------------

    def _log(self, message: str) -> None:
        line = message + "\n"
        for panel in getattr(self, "_log_panels", ()):
            widget = panel["text"]
            widget.configure(state=tk.NORMAL)
            widget.insert(tk.END, line)
            widget.see(tk.END)
            widget.configure(state=tk.DISABLED)

    def _clear_log(self) -> None:
        for panel in getattr(self, "_log_panels", ()):
            widget = panel["text"]
            widget.configure(state=tk.NORMAL)
            widget.delete("1.0", tk.END)
            widget.configure(state=tk.DISABLED)

    # ---- form helpers -------------------------------------------------------

    def _field_row(
        self,
        parent,
        row: int,
        label: str,
        variable: tk.StringVar,
        browse_cmd,
        *,
        on_card: bool = True,
    ) -> tk.Entry:
        gap = space(3, self._ui_scale)
        ipady = control_metrics(self._ui_scale)["path_ipady"]
        label_style = "CardFormLabel.TLabel" if on_card else "FormLabel.TLabel"
        ttk.Label(parent, text=label, style=label_style, width=12).grid(row=row, column=0, sticky="w", pady=gap)
        entry = make_path_entry(parent, variable, self.colors)
        entry.grid(row=row, column=1, sticky="ew", padx=(gap, gap), pady=gap, ipady=ipady)
        browse = make_browse_button(parent, "Browse", browse_cmd, self.colors)
        browse.grid(row=row, column=2, pady=gap, ipady=ipady)
        entry._browse_btn = browse  # type: ignore[attr-defined]
        return entry

    def _blend_path_entry(self, entry: tk.Entry, *, surface: str | None = None) -> None:
        """Path field blended into its surface — no harsh focus ring."""
        bg = surface if surface is not None else self.colors["card"]
        subtle = self.colors["border_subtle"]
        entry.configure(highlightbackground=bg, highlightcolor=subtle)
        browse = getattr(entry, "_browse_btn", None)
        if browse is not None:
            browse.configure(highlightbackground=bg, highlightcolor=subtle)

    @staticmethod
    def _sync_entry(entry: tk.Entry, value: str) -> None:
        entry.delete(0, tk.END)
        if value:
            entry.insert(0, value)
        entry.xview_moveto(1.0)

    @staticmethod
    def _normalize_path(raw: str) -> str:
        cleaned = raw.strip().strip('"').strip("'")
        if not cleaned:
            return ""
        return str(Path(cleaned).expanduser().resolve())

    @staticmethod
    def _markdown_target(source: Path) -> Path:
        return source.with_suffix(".readable.md")

    # ---- drag and drop ------------------------------------------------------

    def _register_drop_target(self, widget: tk.Widget) -> None:
        if not self._dnd_ok:
            return
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_file_drop)
        except Exception:  # noqa: BLE001
            pass

    def _on_file_drop(self, event) -> None:
        try:
            paths = self.tk.splitlist(event.data)
        except tk.TclError:
            paths = [event.data]
        for raw in paths:
            p = Path(raw)
            if p.suffix.lower() in (".pdf", ".md"):
                self._set_source_path(str(p))
                return

    # ---- source selection ---------------------------------------------------

    def _browse_source(self) -> None:
        self.lift()
        self.focus_force()
        path = filedialog.askopenfilename(
            parent=self, title="Select PDF or markdown",
            filetypes=[("PDF or markdown", "*.pdf *.md"), ("PDF files", "*.pdf"), ("Markdown", "*.md"), ("All files", "*.*")],
        )
        if path:
            self._set_source_path(path)

    def _set_source_path(self, path: str) -> None:
        resolved = self._normalize_path(path)
        if not resolved:
            return
        src = Path(resolved)
        self.source_var.set(resolved)
        if src.suffix.lower() == ".md":
            self.output_var.set(resolved)
            self._sync_output_entry(resolved)
        else:
            md = self._markdown_target(src)
            self.output_var.set(str(md))
            self._sync_output_entry(str(md))
        self._sync_workflow_from_inputs()
        self.status_var.set(f"Selected: {src.name}")
        self.update_idletasks()

    def _browse_output(self) -> None:
        self.lift()
        self.focus_force()
        initialdir = initialfile = None
        src = self._normalize_path(self.source_var.get())
        if src:
            p = Path(src)
            initialdir = str(p.parent)
            initialfile = self._markdown_target(p).name
        path = filedialog.asksaveasfilename(
            parent=self, title="Save markdown as", initialdir=initialdir, initialfile=initialfile,
            defaultextension=".md", filetypes=[("Markdown", "*.md"), ("All files", "*.*")],
        )
        if path:
            resolved = self._normalize_path(path)
            self.output_var.set(resolved)
            self._sync_output_entry(resolved)
            self._sync_workflow_from_inputs()

    # ---- busy state ---------------------------------------------------------

    def _set_busy(self, busy: bool, status: str | None = None) -> None:
        self._busy = busy
        set_accent_button_state(self.convert_btn, self.colors, enabled=not busy)
        self.cancel_btn.configure(state=tk.NORMAL if busy else tk.DISABLED)
        if hasattr(self, "make_audiobook_btn"):
            set_accent_button_state(self.make_audiobook_btn, self.colors, enabled=not busy)
        if status is not None:
            self.status_var.set(status)
        elif busy:
            self.status_var.set("Working…")
        else:
            self.status_var.set("Ready")
        self._sync_footer_title()
        self._draw_footer_bar()

    def _audiobook_output_path(self, markdown_path: Path, audio_format: str) -> Path:
        stem = markdown_path.stem
        if stem.endswith(".readable"):
            stem = stem[: -len(".readable")]
        return markdown_path.with_name(f"{stem}.audiobook.{audio_format}")

    def _begin_run(self, *, make_audiobook: bool, status: str) -> None:
        self.open_btn.configure(state=tk.DISABLED)
        self.open_file_btn.configure(state=tk.DISABLED)
        self.audio_open_btn.configure(state=tk.DISABLED)
        self.audio_play_btn.configure(state=tk.DISABLED)
        self._last_audiobook = None
        self._phase_audiobook = make_audiobook
        self._cancel_event.clear()
        self._progress_start = time.monotonic()
        self._eta_ema = None
        self._set_busy(True, status)
        self._set_progress(0)
        self._apply_progress_style("Accent.Horizontal.TProgressbar")
        self._log("—" * 52)

    # ---- conversion / audiobook actions -------------------------------------

    def _start_convert(self) -> None:
        if self._busy:
            return
        source = self._normalize_path(self.source_var.get())
        if not source:
            self._show_toast("Choose a PDF or markdown file first.", kind="warn")
            return
        src = Path(source)
        if not src.is_file():
            self._show_toast(f"File not found: {source}", kind="error")
            return
        if src.suffix.lower() == ".md":
            self._show_toast("That's already markdown — use the Audiobook tab to narrate it.", kind="info")
            return

        output_raw = self.output_var.get().strip()
        output = self._normalize_path(output_raw) if output_raw else None
        keep_raw = self.keep_raw_var.get()
        self._begin_run(make_audiobook=False, status="Converting to markdown…")

        def run() -> None:
            try:
                from novelflow.convert import ConversionCancelled, convert_pdf

                result = convert_pdf(
                    source, output, keep_raw=keep_raw,
                    progress=lambda msg: self._ui(self._log, msg),
                    on_progress=lambda pct: self._ui(self._set_progress, pct),
                    cancel_check=self._cancel_event.is_set,
                )
                self._ui(self._on_success, result, None)
            except ConversionCancelled:
                self._ui(self._on_cancelled)
            except Exception as exc:
                self._ui(self._on_error, str(exc))

        threading.Thread(target=run, daemon=True).start()

    def _start_audiobook(self) -> None:
        if self._busy:
            return
        source = self._normalize_path(self.source_var.get())
        if not source:
            self._show_toast("Choose a PDF or markdown file on the Document tab first.", kind="warn")
            self.notebook.select(0)
            return
        src = Path(source)
        if not src.is_file():
            self._show_toast(f"File not found: {source}", kind="error")
            return

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
        self._begin_run(make_audiobook=True, status="Creating audiobook…")

        def run() -> None:
            try:
                from novelflow.convert import ConversionCancelled, convert_pdf

                if use_existing_md:
                    from novelflow.audiobook import create_audiobook

                    self._ui(self._log, f"Using markdown: {md_path.name}")
                    create_audiobook(
                        md_path, engine="edge", voice=tts_voice, audio_format=audio_format,
                        disabled_section_ids=disabled, chapters_and_title_only=chapters_only,
                        progress=lambda msg: self._ui(self._log, msg),
                        on_progress=lambda pct: self._ui(self._set_progress, pct),
                        cancel_check=self._cancel_event.is_set,
                    )
                    result = md_path
                else:
                    result = convert_pdf(
                        source, str(md_path), audiobook=True, tts_engine="edge", tts_voice=tts_voice,
                        audio_format=audio_format, disabled_section_ids=disabled,
                        chapters_and_title_only=chapters_only,
                        progress=lambda msg: self._ui(self._log, msg),
                        on_progress=lambda pct: self._ui(self._set_progress, pct),
                        cancel_check=self._cancel_event.is_set,
                    )
                audio_path = self._audiobook_output_path(result, audio_format)
                self._ui(self._on_success, result, audio_path)
            except ConversionCancelled:
                self._ui(self._on_cancelled)
            except Exception as exc:
                self._ui(self._on_error, str(exc))

        threading.Thread(target=run, daemon=True).start()

    def _cancel_convert(self) -> None:
        if not self._busy:
            return
        self._cancel_event.set()
        self.cancel_btn.configure(state=tk.DISABLED)
        self.status_var.set("Cancelling…")
        self._log("Cancellation requested — stopping at the next safe point…")

    def _on_success(self, output_path: Path, audio_path: Path | None = None) -> None:
        self._last_output = output_path
        self._last_audiobook = audio_path if audio_path and audio_path.is_file() else None
        self._progress_start = None
        self._set_progress(100)
        self._set_busy(False)
        self.open_btn.configure(state=tk.NORMAL)
        if output_path.suffix.lower() == ".md" and output_path.is_file():
            self.open_file_btn.configure(state=tk.NORMAL)
        self.status_var.set(f"Done — {output_path.name}")
        self._log(f"Saved: {output_path}")
        if output_path.suffix.lower() == ".md":
            self._load_sections_from_markdown(output_path)
        if self._last_audiobook:
            self.audio_open_btn.configure(state=tk.NORMAL)
            self._log(f"Audiobook: {self._last_audiobook}")
            self._set_audiobook_library_folder(str(self._last_audiobook.parent))
            self._load_into_player(self._last_audiobook)
            final = self._last_audiobook
            self._show_toast(
                f"Audiobook ready: {final.name}",
                kind="success",
                actions=[
                    ("Play in app", self._play_last_in_app),
                    ("Reveal", self._open_output_folder),
                    ("Copy path", lambda: self._copy_to_clipboard(str(final))),
                ],
            )
        else:
            self._show_toast(
                f"Markdown ready: {output_path.name}",
                kind="success",
                actions=[
                    ("Open", self._open_output_file),
                    ("Reveal", self._open_output_folder),
                    ("Copy path", lambda: self._copy_to_clipboard(str(output_path))),
                ],
            )
        self._apply_progress_style("Success.Horizontal.TProgressbar")
        self._flash_success()

    def _on_cancelled(self) -> None:
        self._progress_start = None
        self._set_busy(False)
        self._current_progress_pct = self.progress_var.get()
        self._current_progress_label = "Cancelled"
        self._sync_progress_display()
        self.status_var.set("Conversion cancelled")
        self._log("Conversion cancelled. Completed section audio is kept and will resume next run.")

    def _on_error(self, message: str) -> None:
        self._reset_progress()
        self._set_busy(False)
        # Full red bar makes the failure obvious at a glance.
        self._apply_progress_style("Danger.Horizontal.TProgressbar")
        self.progress_var.set(100.0)
        self._current_progress_pct = 100.0
        self._current_progress_label = "Failed"
        self._sync_progress_display()
        self.status_var.set("Conversion failed")
        self._log(f"Error: {message}")
        self._show_toast(message, kind="error", duration_ms=10000)

    def _flash_success(self) -> None:
        self._pulse_step = 0
        palette = [self.colors["accent"], self.colors["glow"], "#c084fc", self.colors["accent"]]

        def tick() -> None:
            self._accent_bar.configure(bg=palette[self._pulse_step % len(palette)])
            self._pulse_step += 1
            if self._pulse_step < 8:
                self.after(90, tick)
            else:
                self._accent_bar.configure(bg=self.colors["accent"])

        tick()

    # ---- open helpers -------------------------------------------------------

    def _open_audiobook_file(self) -> None:
        path = self._resolve_playable_audiobook() or self._last_audiobook
        if not path:
            return
        resolved = self._resolve_external_audiobook_path(path)
        if resolved is None:
            self._show_toast(
                "No merged audiobook file found — use Play in app (section audio is still available).",
                kind="info",
            )
            return
        self._open_path(resolved)

    @staticmethod
    def _resolve_external_audiobook_path(path: Path) -> Path | None:
        path = Path(path)
        if path.is_file() and not path.name.endswith(".chapters.json"):
            return path
        if path.name.endswith(".chapters.json"):
            base = path.name.removesuffix(".chapters.json")
            for ext in (".m4b", ".mp3", ".m4a"):
                candidate = path.parent / f"{base}{ext}"
                if candidate.is_file():
                    return candidate
        return None

    def _open_output_folder(self) -> None:
        if self._last_output:
            self._open_path(self._last_output.parent)

    def _open_output_file(self) -> None:
        if self._last_output and self._last_output.is_file():
            self._open_path(self._last_output)

    def _open_path(self, path: Path) -> None:
        target = str(path)
        if sys.platform == "win32":
            os.startfile(target)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.run(["open", target], check=False)
        else:
            subprocess.run(["xdg-open", target], check=False)

    # ---- audiobook library --------------------------------------------------

    def _prefs_file(self) -> Path:
        from novelflow.user_paths import user_data_dir

        return user_data_dir() / "gui_prefs.json"

    def _load_gui_prefs(self) -> dict:
        import json

        try:
            return json.loads(self._prefs_file().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_gui_prefs(self) -> None:
        import json

        try:
            self._prefs_file().write_text(json.dumps(self._gui_prefs, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _set_audiobook_library_folder(self, folder: str) -> None:
        resolved = self._normalize_path(folder)
        if not resolved:
            return
        self.audiobook_lib_dir_var.set(resolved)
        if hasattr(self, "audiobook_lib_dir_entry"):
            self._sync_entry(self.audiobook_lib_dir_entry, resolved)
        self._gui_prefs["audiobook_library_dir"] = resolved
        self._save_gui_prefs()
        self._refresh_audiobook_library()

    def _browse_audiobook_library_folder(self) -> None:
        self.lift()
        self.focus_force()
        initialdir = self.audiobook_lib_dir_var.get().strip() or None
        if not initialdir and self.source_var.get().strip():
            initialdir = str(Path(self._normalize_path(self.source_var.get())).parent)
        folder = filedialog.askdirectory(parent=self, title="Choose audiobook folder", initialdir=initialdir)
        if folder:
            self._set_audiobook_library_folder(folder)

    def _refresh_audiobook_library(self) -> None:
        if not hasattr(self, "audiobook_lib_combo"):
            return
        folder_raw = self.audiobook_lib_dir_var.get().strip()
        if not folder_raw:
            self._audiobook_lib_entries = []
            self.audiobook_lib_combo.configure(values=[])
            self.audiobook_lib_pick_var.set("")
            self.audiobook_lib_open_btn.configure(state=tk.DISABLED)
            return
        folder = Path(self._normalize_path(folder_raw))
        self._audiobook_lib_entries = scan_audiobook_folder(folder)
        labels = [label for label, _path in self._audiobook_lib_entries]
        self.audiobook_lib_combo.configure(values=labels)
        if not labels:
            self.audiobook_lib_pick_var.set("")
            self.audiobook_lib_open_btn.configure(state=tk.DISABLED)
            return
        pick = self.audiobook_lib_pick_var.get()
        if pick not in labels:
            md = self._current_markdown_path()
            if md is not None:
                self._select_library_audiobook_for_markdown(md)
            else:
                self.audiobook_lib_pick_var.set(labels[0])
        self.audiobook_lib_open_btn.configure(state=tk.NORMAL)

    def _selected_library_audiobook(self) -> Path | None:
        pick = self.audiobook_lib_pick_var.get().strip()
        if not pick:
            return None
        for label, path in self._audiobook_lib_entries:
            if label == pick:
                return path
        return None

    def _open_selected_audiobook(self) -> None:
        path = self._selected_library_audiobook()
        if path is None:
            self._show_toast("Choose an audiobook from the list first.", kind="warn")
            return
        self._load_into_player(path)
        self.notebook.select(2)

    def _on_audiobook_library_pick(self, _event=None) -> None:
        path = self._selected_library_audiobook()
        if path is not None:
            self._last_audiobook = path
        self._sync_audiobook_action_buttons()
        self._sync_player_document_label()

    # ---- player -------------------------------------------------------------

    def _configure_player_styles(self) -> None:
        style = self.colors.get("_style")
        if style is None:
            return
        try:
            thumb = max(12, int(16 * self._ui_scale))
            for name, trough in (
                ("Player.Horizontal.TScale", self.colors["border_subtle"]),
                ("Player.Book.Horizontal.TScale", self.colors["surface"]),
                ("Player.Vertical.TScale", self.colors["border_subtle"]),
            ):
                style.configure(
                    name,
                    background=self.colors["card"],
                    troughcolor=trough,
                    bordercolor=self.colors["card"],
                    borderwidth=0,
                    lightcolor="#ffffff",
                    darkcolor="#ffffff",
                    sliderthickness=thumb,
                    sliderlength=thumb,
                )
                style.map(
                    name,
                    background=[("active", "#ffffff"), ("!disabled", "#ffffff")],
                    troughcolor=[("!disabled", trough)],
                )
        except tk.TclError:
            pass

    def _set_player_chapter_placeholders(self) -> None:
        self.player_chapter_title_var.set(_PLAYER_CHAPTER_TITLE_PLACEHOLDER)
        self.player_chapter_sub_var.set(_PLAYER_CHAPTER_SUB_PLACEHOLDER)

    def _set_player_controls(self, *, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for btn in (self.prev_btn, self.next_btn, self.back10_btn, self.fwd10_btn):
            btn.configure(state=state)
        self._set_play_button_enabled(enabled=enabled)
        self.seek_scale.configure(state=state)
        self._book_timeline_enabled = enabled
        if hasattr(self, "_book_tl"):
            self._book_tl.configure(cursor="hand2" if enabled else "arrow")
            self._draw_book_timeline()
        if not enabled:
            self._set_player_chapter_placeholders()
        # Volume and speed stay editable at all times — the chosen values are
        # remembered and applied as soon as playback starts.

    def _play_last_in_app(self) -> None:
        path = self._resolve_playable_audiobook()
        if path is None:
            self._show_toast("No playable audiobook found for this document.", kind="warn")
            return
        self._load_into_player(path)
        self.notebook.select(2)
        self._player_toggle()

    def _resolve_playable_audiobook(self) -> Path | None:
        """Best playable path: library pick, last run, expected file, or chapter sidecar."""
        candidates: list[Path | None] = [
            self._selected_library_audiobook(),
            self._last_audiobook,
            self._expected_audiobook_path(),
        ]
        seen: set[str] = set()
        for raw in candidates:
            if raw is None:
                continue
            path = Path(raw)
            key = str(path.resolve()) if path.exists() else str(path)
            if key in seen:
                continue
            seen.add(key)
            if path.is_file():
                return path
            merged = self._resolve_external_audiobook_path(path)
            if merged is not None and merged.is_file():
                return path if path.name.endswith(".chapters.json") else path
        expected = self._expected_audiobook_path()
        if expected is not None:
            sidecar = expected.with_name(f"{expected.stem}.chapters.json")
            if sidecar.is_file():
                return sidecar
        md = self._current_markdown_path()
        if md is not None:
            aliases = self._markdown_audiobook_aliases(md)
            for lib_label, lib_path in self._audiobook_lib_entries:
                if lib_label in aliases or lib_label.lower() in aliases:
                    return lib_path
        return None

    def _sync_library_pick_for_path(self, audio_path: Path) -> None:
        if not hasattr(self, "audiobook_lib_combo"):
            return
        resolved = audio_path.resolve()
        for lib_label, lib_path in self._audiobook_lib_entries:
            if lib_path.resolve() == resolved:
                self.audiobook_lib_pick_var.set(lib_label)
                self._sync_audiobook_action_buttons()
                return
        md = self._current_markdown_path()
        if md is not None:
            self._select_library_audiobook_for_markdown(md)

    def _apply_speed_from_combo(self) -> None:
        try:
            self._player.set_speed(float(self.speed_var.get().replace("\u00d7", "")))
        except ValueError:
            self._player.set_speed(1.0)

    def _load_into_player(self, audio_path: Path) -> None:
        if not self._player.available:
            self.player_title_var.set("Audio playback unavailable (pygame not installed).")
            return
        self._player.stop()
        self._was_busy = False
        self._player_started = False
        self._resume_fraction = 0.0
        chapters = self._player.load(audio_path)
        self._player_chapters = chapters
        self._player_path = audio_path
        self._player_playable = bool(chapters) and all(
            c.file is not None and is_pygame_playable(c.file) for c in chapters
        )
        self._last_audiobook = audio_path
        self._sync_library_pick_for_path(audio_path)
        self.audio_open_btn.configure(state=tk.NORMAL)
        self.audio_play_btn.configure(state=tk.NORMAL)
        self._player.set_volume(self.volume_var.get() / 100.0)
        self._apply_speed_from_combo()
        if self._player_playable:
            self.player_title_var.set(f"Loaded: {audio_path.name}  ·  {len(chapters)} chapter(s)")
            self._set_player_controls(enabled=True)
            saved = self._resume_store.get(str(audio_path))
            if saved and 0 <= int(saved.get("index", 0)) < len(chapters):
                idx = int(saved["index"])
                self._player.index = idx
                self._resume_fraction = float(saved.get("fraction", 0.0))
                self._show_toast(
                    f"Resuming where you left off — Chapter {idx + 1}.",
                    actions=[("Start over", self._restart_from_beginning)],
                )
            self._update_player_time()
            self._draw_book_timeline()
        else:
            self.player_title_var.set(
                f"{audio_path.name} — in-app preview not supported for this format; use Open externally."
            )
            self._set_player_controls(enabled=False)

    def _restart_from_beginning(self) -> None:
        self._hide_toast()
        self._resume_fraction = 0.0
        self._player_started = False
        self._player.index = 0
        self._play_index(0)

    def _update_play_button(self) -> None:
        btn = self.play_btn
        playing = self._player.is_playing
        if playing:
            btn.itemconfigure(btn._play_icon, state="hidden")  # type: ignore[attr-defined]
            btn.itemconfigure(btn._pause_left, state="normal")  # type: ignore[attr-defined]
            btn.itemconfigure(btn._pause_right, state="normal")  # type: ignore[attr-defined]
        else:
            btn.itemconfigure(btn._play_icon, state="normal")  # type: ignore[attr-defined]
            btn.itemconfigure(btn._pause_left, state="hidden")  # type: ignore[attr-defined]
            btn.itemconfigure(btn._pause_right, state="hidden")  # type: ignore[attr-defined]

    def _play_index(self, index: int, start_fraction: float = 0.0) -> bool:
        if not self._player_playable or not (0 <= index < len(self._player_chapters)):
            return False
        chapter = self._player_chapters[index]
        speed = self._player.speed
        eff_dur = max(int(chapter.duration_ms / speed), 1)
        start_ms = int(max(0.0, min(1.0, start_fraction)) * eff_dur)
        self._player.index = index

        if abs(speed - 1.0) < 0.01 or chapter.file is None:
            self._player.play_resolved(index, chapter.file, start_ms)
            self._after_play_started()
            return True

        from novelflow.player import cached_speed_variant, make_speed_variant

        cached = cached_speed_variant(chapter.file, speed)
        if cached is not None:
            self._player.play_resolved(index, cached, start_ms)
            self._after_play_started()
            return True

        # Render the time-stretched variant off the UI thread, then play it.
        self._preparing_speed = True
        self.status_var.set(f"Preparing {self.speed_var.get()} playback…")

        def work() -> None:
            variant = make_speed_variant(chapter.file, speed)

            def done() -> None:
                self._preparing_speed = False
                if 0 <= self._player.index < len(self._player_chapters):
                    self._player.play_resolved(index, variant or chapter.file, start_ms)
                    self._after_play_started()
                    self.status_var.set("" if variant else "Speed unavailable — playing at 1.0×")

            self._ui(done)

        threading.Thread(target=work, daemon=True).start()
        return True

    def _after_play_started(self) -> None:
        self._player_started = True
        self._was_busy = False
        self._update_play_button()
        self._update_player_time()

    def _player_toggle(self) -> None:
        if not self._player_playable or self._preparing_speed:
            return
        if not self._player_started:
            frac = self._resume_fraction
            self._resume_fraction = 0.0
            self._play_index(self._player.index, start_fraction=frac)
            return
        self._player.toggle_pause()
        if self._player.is_playing:
            self._was_busy = False
        else:
            self._remember_position()
        self._update_play_button()

    def _player_prev(self) -> None:
        if self._player_playable:
            self._play_index(self._player.index - 1)

    def _player_next(self) -> None:
        if self._player_playable:
            self._play_index(self._player.index + 1)

    def _current_chapter_duration_ms(self) -> int:
        return self._player.effective_duration_ms(self._player.index)

    def _total_book_duration_ms(self) -> int:
        return sum(self._player.effective_duration_ms(i) for i in range(len(self._player_chapters)))

    def _total_book_position_ms(self) -> int:
        if not self._player_chapters:
            return 0
        idx = self._player.index
        prior = sum(self._player.effective_duration_ms(i) for i in range(idx))
        if self._player_started:
            pos = self._player.position_ms()
        else:
            pos = int(self._resume_fraction * self._player.effective_duration_ms(idx))
        return prior + pos

    def _current_fraction(self) -> float:
        eff = self._current_chapter_duration_ms()
        if eff <= 0:
            return 0.0
        return min(max(self._player.position_ms() / eff, 0.0), 1.0)

    def _current_book_fraction(self) -> float:
        total = self._total_book_duration_ms()
        if total <= 0:
            return 0.0
        return min(max(self._total_book_position_ms() / total, 0.0), 1.0)

    def _seek_to_book_fraction(self, fraction: float) -> None:
        total = self._total_book_duration_ms()
        if total <= 0:
            return
        target_ms = int(max(0.0, min(1.0, fraction)) * total)
        acc = 0
        last = len(self._player_chapters) - 1
        for i in range(len(self._player_chapters)):
            dur = self._player.effective_duration_ms(i)
            if acc + dur > target_ms or i == last:
                frac = (target_ms - acc) / dur if dur > 0 else 0.0
                self._play_index(i, start_fraction=frac)
                return
            acc += dur

    def _on_volume_change(self, _value=None) -> None:
        self._player.set_volume(self.volume_var.get() / 100.0)
        self._refresh_volume_ui()
        # Debounce pref saving so dragging the slider doesn't hammer the disk.
        if self._vol_save_after is not None:
            self.after_cancel(self._vol_save_after)
        self._vol_save_after = self.after(800, self._persist_volume_pref)

    def _persist_volume_pref(self) -> None:
        self._vol_save_after = None
        self._gui_prefs["volume"] = int(round(self.volume_var.get()))
        self._save_gui_prefs()

    def _on_speed_change(self, _event=None) -> None:
        frac = self._current_fraction() if self._player_started else 0.0
        self._apply_speed_from_combo()
        if self._player_started and self._player_playable:
            self._play_index(self._player.index, start_fraction=frac)
        else:
            self._update_player_time()

    def _seek_relative(self, delta_ms: int) -> None:
        """Skip forward/back by ``delta_ms``, rolling across chapter edges."""
        if not self._player_playable:
            return
        idx = self._player.index
        eff = self._player.effective_duration_ms(idx)
        pos = self._player.position_ms() if self._player_started else int(self._resume_fraction * eff)
        target = pos + delta_ms
        last = len(self._player_chapters) - 1
        while target < 0 and idx > 0:
            idx -= 1
            eff = self._player.effective_duration_ms(idx)
            target += eff
        while target > eff and idx < last:
            target -= eff
            idx += 1
            eff = self._player.effective_duration_ms(idx)
        target = max(0, min(target, eff))
        self._play_index(idx, start_fraction=(target / eff if eff > 0 else 0.0))

    def _seek_fraction_from_event(self, event, widget=None) -> float:
        w = widget if widget is not None else event.widget
        width = max(w.winfo_width(), 1)
        return min(max(event.x / width, 0.0), 1.0)

    def _set_player_time_labels(
        self, *, chapter_pos: int, chapter_dur: int, book_pos: int, book_total: int,
    ) -> None:
        self.player_chapter_elapsed_var.set(self._fmt_time(chapter_pos))
        self.player_chapter_total_var.set(self._fmt_time(chapter_dur))
        self.player_book_elapsed_var.set(self._fmt_time(book_pos))
        self.player_book_total_var.set(self._fmt_time(book_total))

    def _preview_seek_label(self) -> None:
        dur = self._current_chapter_duration_ms()
        pos = int(self.seek_var.get() / 1000.0 * dur)
        self.player_chapter_elapsed_var.set(self._fmt_time(pos))
        self.player_chapter_total_var.set(self._fmt_time(dur))

    def _preview_book_seek_label(self) -> None:
        total = self._total_book_duration_ms()
        pos = int(self.book_seek_var.get() / 1000.0 * total)
        self.player_book_elapsed_var.set(self._fmt_time(pos))
        self.player_book_total_var.set(self._fmt_time(total))

    def _on_seek_press(self, event):
        if not self._player_playable:
            return "break"
        self._user_seeking = True
        self.seek_var.set(self._seek_fraction_from_event(event) * 1000.0)
        self._preview_seek_label()
        return "break"

    def _on_seek_motion(self, event):
        if not self._user_seeking:
            return "break"
        self.seek_var.set(self._seek_fraction_from_event(event) * 1000.0)
        self._preview_seek_label()
        return "break"

    def _on_seek_drag(self, _value: str) -> None:
        if self._user_seeking:
            self._preview_seek_label()

    def _on_seek_release(self, _event) -> None:
        if not self._user_seeking:
            return
        self._user_seeking = False
        if not self._player_playable:
            return
        self._play_index(self._player.index, start_fraction=self.seek_var.get() / 1000.0)

    def _book_timeline_fraction_from_event(self, event) -> float:
        width = max(self._book_tl.winfo_width(), 1)
        pad_x = 4
        inner_w = max(width - pad_x * 2, 1)
        x = max(pad_x, min(event.x, width - pad_x))
        return min(max((x - pad_x) / inner_w, 0.0), 1.0)

    def _on_book_seek_press(self, event):
        if not self._player_playable or not self._book_timeline_enabled:
            return "break"
        self._hide_book_tl_tooltip()
        self._user_book_seeking = True
        self.book_seek_var.set(self._book_timeline_fraction_from_event(event) * 1000.0)
        self._preview_book_seek_label()
        self._draw_book_timeline()
        return "break"

    def _on_book_seek_motion(self, event):
        if not self._user_book_seeking:
            return "break"
        self.book_seek_var.set(self._book_timeline_fraction_from_event(event) * 1000.0)
        self._preview_book_seek_label()
        self._draw_book_timeline()
        return "break"

    def _on_book_seek_release(self, _event) -> None:
        if not self._user_book_seeking:
            return
        self._user_book_seeking = False
        if not self._player_playable:
            return
        self._seek_to_book_fraction(self.book_seek_var.get() / 1000.0)

    @staticmethod
    def _fmt_time(ms: int) -> str:
        total = max(0, int(ms // 1000))
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _update_player_time(self) -> None:
        dur = self._current_chapter_duration_ms()
        if self._player_started:
            pos = min(self._player.position_ms(), dur)
        else:
            pos = int(self._resume_fraction * dur) if dur > 0 else 0
        if not self._user_seeking:
            self.seek_var.set(0 if dur <= 0 else pos / dur * 1000.0)
        book_total = self._total_book_duration_ms()
        book_pos = min(self._total_book_position_ms(), book_total)
        if not self._user_book_seeking:
            self.book_seek_var.set(0 if book_total <= 0 else book_pos / book_total * 1000.0)
        self._set_player_time_labels(
            chapter_pos=pos, chapter_dur=dur, book_pos=book_pos, book_total=book_total,
        )
        idx = self._player.index
        total = len(self._player_chapters)
        if self._player_playable and 0 <= idx < total:
            self.player_chapter_title_var.set(self._player_chapters[idx].title)
            self.player_chapter_sub_var.set(f"Chapter {idx + 1} of {total}")
        else:
            self._set_player_chapter_placeholders()
        if hasattr(self, "_book_tl"):
            self._draw_book_timeline()

    def _tick_player(self) -> None:
        try:
            if self._player_playable and self._player.is_playing:
                busy = self._player.is_busy()
                if busy:
                    self._was_busy = True
                elif self._was_busy:
                    # Current chapter finished — advance or stop at the end.
                    self._was_busy = False
                    if not self._play_index(self._player.index + 1):
                        self._player.stop()
                        self._player_started = False
                        self._update_play_button()
                if not self._user_seeking and not self._user_book_seeking:
                    self._update_player_time()
                self._resume_save_tick += 1
                if self._resume_save_tick >= 16:  # ~ every 5 seconds
                    self._resume_save_tick = 0
                    self._remember_position()
        except tk.TclError:
            # Window/widget went away mid-tick (e.g. during close) — stop quietly.
            return
        except Exception:  # noqa: BLE001 - never let one bad tick spam the loop
            import traceback

            traceback.print_exc()
        self.after(300, self._tick_player)

    def _space_toggle_player(self, event):
        # Only hijack space when the Player tab is active and focus isn't in a text field.
        if isinstance(event.widget, (tk.Entry, tk.Text)):
            return
        try:
            if self._tab_index == 2 and self._player_playable:
                self._player_toggle()
                return "break"
        except tk.TclError:
            pass

    # ---- resume persistence -------------------------------------------------

    def _resume_file(self) -> Path:
        from novelflow.user_paths import user_data_dir

        return user_data_dir() / "player_resume.json"

    def _load_resume_store(self) -> dict:
        import json

        try:
            return json.loads(self._resume_file().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _persist_resume_store(self) -> None:
        import json

        try:
            self._resume_file().write_text(json.dumps(self._resume_store), encoding="utf-8")
        except OSError:
            pass

    def _remember_position(self) -> None:
        if not (self._player_playable and self._player_path and self._player_started):
            return
        self._resume_store[str(self._player_path)] = {
            "index": self._player.index,
            "fraction": self._current_fraction(),
        }
        self._persist_resume_store()

    def _on_close(self) -> None:
        try:
            self._remember_position()
            self._player.close()
        except Exception:  # noqa: BLE001
            pass
        self.destroy()


def main() -> None:
    enable_dpi_awareness()
    app = NovelflowApp()
    app.mainloop()


if __name__ == "__main__":
    main()
