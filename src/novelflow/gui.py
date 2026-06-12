"""Desktop GUI for Novelflow."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont, scrolledtext, ttk

from novelflow.gui_theme import (
    apply_theme,
    attach_tooltip,
    bind_debounced_configure,
    configure_log_widget,
    control_metrics,
    corner_radius,
    draw_round_rect,
    draw_round_rect_top,
    enable_dpi_awareness,
    fit_combobox,
    fit_round_surface_to_content,
    CanvasButton,
    make_browse_button,
    make_card,
    make_ghost_button,
    make_path_entry,
    make_round_surface,
    refresh_font_registry,
    refresh_theme_scale,
    schedule_debounced_configure,
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
from novelflow.gui_audiobook_tab import (
    _SECTION_PRESET_DEFAULT,
    _SECTION_PRESETS,
    AudiobookTabMixin,
)
from novelflow.gui_document_tab import DocumentTabMixin
from novelflow.gui_jobs import JobRunner
from novelflow.gui_player_tab import (
    _PLAYER_CHAPTER_SUB_PLACEHOLDER,
    _PLAYER_CHAPTER_TITLE_PLACEHOLDER,
    PlayerTabMixin,
)
from novelflow.gui_settings import SettingsMixin
from novelflow.player import AudioPlayer

try:  # Optional: drag-and-drop support.
    from tkinterdnd2 import DND_FILES, TkinterDnD

    _DND_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    DND_FILES = None
    TkinterDnD = None
    _DND_AVAILABLE = False

# Tab content fills the main area; progress lives in the footer.
_MAIN_SPLIT_TAB_ROW = 0
_TAB_NAV_DEFS = (("📄", "Document"), ("🎧", "Audiobook"), ("▶", "Player"))


class NovelflowApp(DocumentTabMixin, AudiobookTabMixin, PlayerTabMixin, SettingsMixin, tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Novelflow")
        self._busy = False
        self._pulse_step = 0
        self._last_output: Path | None = None
        self._last_audiobook: Path | None = None
        self._window_resize_after: str | None = None

        self._apply_window_geometry()
        self._ui_scale = ui_scale(self)
        self._gui_prefs = self._load_gui_prefs()
        self._theme_name = "dark"
        if self._gui_prefs.get("theme", "dark") != "dark":
            self._gui_prefs["theme"] = "dark"
            self._save_gui_prefs()
        self.colors = apply_theme(self, scale=self._ui_scale, theme=self._theme_name)
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
        # Each background job gets its own cancel event so cancelling one job
        # can never abort an unrelated one.
        self._jobs = JobRunner(self._ui)
        self._closing = False
        self._drain_after: str | None = None
        self._tick_after: str | None = None
        self._shimmer_after: str | None = None
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
        self._speed_prep_gen = 0  # invalidates stale async speed preps
        self._play_started_at = 0.0
        self._player_started = False
        self._resume_fraction = 0.0
        self.player_title_var = tk.StringVar(value="No audiobook loaded yet")
        self.player_book_name_var = tk.StringVar(value="")
        self.player_mini_chapter_var = tk.StringVar(value="")
        self.player_chapter_title_var = tk.StringVar(value=_PLAYER_CHAPTER_TITLE_PLACEHOLDER)
        self.player_chapter_sub_var = tk.StringVar(value=_PLAYER_CHAPTER_SUB_PLACEHOLDER)
        self.player_chapter_elapsed_var = tk.StringVar(value="00:00")
        self.player_chapter_total_var = tk.StringVar(value="00:00")
        self.player_book_elapsed_var = tk.StringVar(value="00:00")
        self.player_book_total_var = tk.StringVar(value="00:00")
        self.seek_var = tk.DoubleVar(value=0.0)
        self.book_seek_var = tk.DoubleVar(value=0.0)
        self.volume_var = tk.DoubleVar(value=85.0)
        self.mini_seek_var = tk.DoubleVar(value=0.0)
        self.mini_volume_var = tk.DoubleVar(value=85.0)
        self.speed_var = tk.StringVar(value="1.0×")
        self._resume_store = self._load_resume_store()
        self._resume_save_tick = 0
        try:
            vol = float(self._gui_prefs.get("volume", 85))
            self.volume_var.set(vol)
            self.mini_volume_var.set(vol)
        except (TypeError, ValueError):
            self.volume_var.set(85.0)
            self.mini_volume_var.set(85.0)
        self._player.set_volume(self.volume_var.get() / 100.0)
        self._vol_save_after: str | None = None
        self.audiobook_lib_dir_var = tk.StringVar(
            value=self._gui_prefs.get("audiobook_library_dir", ""),
        )
        self.audiobook_lib_pick_var = tk.StringVar(value="")
        self._audiobook_lib_entries: list[tuple[str, Path]] = []
        self._workflow_sync_after: str | None = None
        self._tab_index = 0
        self.output_var.trace_add("write", lambda *_: self._schedule_workflow_sync())
        self.audio_format_var.trace_add("write", lambda *_: self._schedule_workflow_sync())

        self._build_ui()
        self._apply_startup_prefs()
        self.bind("<Configure>", self._on_window_resize)
        self.bind("<Control-Return>", lambda _e: self._start_convert())
        self.bind("<Control-l>", lambda _e: self._clear_log())
        self.bind("<space>", self._space_toggle_player)
        self._drain_after = self.after(50, self._drain_ui_queue)
        self._tick_after = self.after(300, self._tick_player)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        if len(sys.argv) > 1 and sys.argv[1].lower().endswith((".pdf", ".md")):
            self.after(100, lambda: self._set_source_path(sys.argv[1]))
        self.after(150, self._refresh_audiobook_library)
        self.after_idle(self._apply_responsive_layout)
        self.after_idle(self._sync_bottom_panel_for_tab)
        self.after(2000, self._prune_speed_cache_async)

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
        if self._closing:
            self._drain_after = None
            return
        while True:
            try:
                func, args, kwargs = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                func(*args, **kwargs)
            except tk.TclError:
                # Widget went away (e.g. while closing) — drop the update.
                pass
            except Exception:  # noqa: BLE001 - keep the queue draining
                import traceback

                traceback.print_exc()
        self._drain_after = self.after(50, self._drain_ui_queue)

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
        # Pages scroll when content overflows, so a small window stays usable.
        self.minsize(420, 340)
        try:
            self.state("zoomed")  # open maximized on Windows
        except tk.TclError:
            pass

    def _rebuild_ui(self) -> None:
        """Tear down and rebuild every widget with the current theme.

        Tk widgets snapshot their colors at creation, so a live theme switch
        rebuilds the widget tree. App state (vars, player, prefs) survives.
        """
        tab_index = getattr(self, "_tab_index", 0)
        for child in list(self.winfo_children()):
            try:
                child.destroy()
            except tk.TclError:
                pass
        self._sections_picker = None
        self._doc_advanced_popup = None
        self._doc_adv_popup_open = False
        self._settings_dialog = None
        self._work_tab_size_key = None

        self.colors = apply_theme(self, scale=self._ui_scale, theme=self._theme_name)
        self._build_ui()
        self._select_tab(tab_index)
        self._sync_workflow_from_inputs()
        self._refresh_audiobook_library()
        if self._player_playable:
            self._set_player_controls(enabled=True)
            self._update_play_button()
        self.after_idle(self._apply_responsive_layout)
        self.after_idle(self._sync_bottom_panel_for_tab)
        self.after_idle(self._sync_bottom_mini_player)

    def _update_ui_scale(self, *, force: bool = False) -> None:
        self.update_idletasks()
        new_scale = window_content_scale(self.winfo_width(), self.winfo_height())
        if not force and abs(new_scale - self._ui_scale) < 0.015:
            return
        self._ui_scale = new_scale
        self.colors = refresh_theme_scale(self, self.colors, new_scale)
        self._configure_player_styles()  # slider thumb size tracks the scale
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
            audio_content = getattr(self, "_audio_work_content", None)
            try:
                if audio_content is not None and audio_content.winfo_exists():
                    audio_content.update_idletasks()
                    matched = audio_content.winfo_reqheight()
            except tk.TclError:  # stale widget from a previous UI build
                matched = None
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

        # Explicit bg: an unstyled tk.Frame flashes white during mini player slides.
        self._bottom_stack = tk.Frame(outer, bg=self.colors["bg"])
        self._bottom_stack.pack(side=tk.BOTTOM, fill=tk.X)
        self._build_footer(self._bottom_stack)

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
        doc_page, audio_page, player_page = self._tab_content_pages

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
        self._build_bottom_mini_player(self._bottom_stack)

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

        hero_row = tk.Frame(self._hero_inner, bg=hero_bg)
        hero_row.pack(fill=tk.X)

        text_col = tk.Frame(hero_row, bg=hero_bg)
        text_col.pack(side=tk.LEFT, fill=tk.X, expand=True)

        kicker = tk.Label(text_col, text="NOVELFLOW", bg=hero_bg, fg=self.colors["hero_kicker"], anchor="w")
        kicker.pack(fill=tk.X)
        track_font(kicker, "overline", self.colors, weight="bold")

        title = tk.Label(
            text_col, text="PDF to markdown and audiobook", bg=hero_bg, fg=self.colors["hero_title"], anchor="w",
        )
        title.pack(fill=tk.X)
        track_font(title, "title", self.colors, weight="bold")

        actions_outer = tk.Frame(hero_row, bg=hero_bg)
        actions_outer.pack(side=tk.RIGHT, fill=tk.Y)
        actions_inner = tk.Frame(actions_outer, bg=hero_bg)
        actions_inner.pack(expand=True)

        self._settings_btn = self._make_icon_button(
            actions_inner, "\u2699", self._open_settings, title="Settings", bg=hero_bg,
        )
        self._settings_btn.pack(side=tk.RIGHT)

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
            fg = self.colors["on_accent"] if active else muted
            item.configure(bg=bg)
            icon_lbl.configure(bg=bg, fg=fg)
            name_lbl.configure(bg=bg, fg=fg)
        self._sync_bottom_panel_for_tab()
        self._sync_bottom_mini_player()

    def _tab_nav_metrics(self) -> dict[str, int]:
        """Scaled sizes for the icon + label sidebar rail."""
        scale = self._ui_scale
        label_font = tkfont.Font(font=typeface("caption", scale))
        text_w = max((label_font.measure(label) for _icon, label in _TAB_NAV_DEFS), default=0)
        icon_font = tkfont.Font(font=typeface("title", scale))
        icon_w = max((icon_font.measure(icon) for icon, _label in _TAB_NAV_DEFS), default=0)
        return {
            "sidebar_w": max(space(16, scale), text_w + space(4, scale)),
            "sidebar_compact_w": max(space(10, scale), icon_w + space(6, scale)),
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
        self._sidebar_compact = False
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
        self._tab_content_pages: list[ttk.Frame] = []
        self._page_scrollers: list[dict] = []

        nav_side = m["side"]
        top_pad = tk.Frame(self._icon_lane, bg=self.colors["surface"], height=m["top_pad"])
        top_pad.pack(fill=tk.X)
        top_pad.pack_propagate(False)
        self._tab_nav_top_rule = tk.Frame(self._icon_lane, bg=self.colors["border"], height=1)
        self._tab_nav_top_rule.pack(fill=tk.X, padx=nav_side)

        for idx, (icon, label) in enumerate(_TAB_NAV_DEFS):
            self._tab_nav_items.append(self._make_tab_nav_item(self._icon_lane, idx, icon, label))
            outer, page = self._make_scrollable_page()
            self._tab_pages.append(outer)
            self._tab_content_pages.append(page)

        self._tab_nav_bottom_rule = tk.Frame(self._icon_lane, bg=self.colors["border"], height=1)
        self._tab_nav_bottom_rule.pack(fill=tk.X, padx=nav_side, pady=(0, space(2, self._ui_scale)))

        # Replaces (not adds to) any previous binding, so UI rebuilds stay clean.
        self.bind("<MouseWheel>", self._on_page_mousewheel)

        self._select_tab(0)

    def _make_scrollable_page(self) -> tuple[ttk.Frame, ttk.Frame]:
        """Tab page that grows a vertical scrollbar when content overflows."""
        outer = ttk.Frame(self._page_host)
        outer.place(relx=0, rely=0, relwidth=1, relheight=1)
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        canvas = tk.Canvas(
            outer, bg=self.colors["bg"], highlightthickness=0, bd=0, yscrollincrement=20,
        )
        canvas.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview, style="Vertical.TScrollbar")
        canvas.configure(yscrollcommand=vsb.set)
        page = ttk.Frame(canvas, padding=self._tab_pad)
        window = canvas.create_window(0, 0, window=page, anchor="nw")
        scroller = {"canvas": canvas, "vsb": vsb, "page": page, "shown": False}
        self._page_scrollers.append(scroller)

        def sync_work() -> None:
            try:
                cw = max(canvas.winfo_width(), 1)
                ch = max(canvas.winfo_height(), 1)
                req_h = page.winfo_reqheight()
                need = req_h > ch + 2
                # When everything fits, stretch the page to fill the canvas so
                # vertically expanding layouts behave exactly as before.
                canvas.itemconfigure(window, width=cw, height=req_h if need else ch)
                canvas.configure(scrollregion=(0, 0, cw, max(req_h, ch)))
                if need and not scroller["shown"]:
                    scroller["shown"] = True
                    vsb.grid(row=0, column=1, sticky="ns")
                elif not need and scroller["shown"]:
                    scroller["shown"] = False
                    vsb.grid_remove()
                    canvas.yview_moveto(0)
            except tk.TclError:
                pass

        def schedule_sync(_event=None) -> None:
            schedule_debounced_configure(canvas, sync_work)

        canvas.bind("<Configure>", schedule_sync, add="+")
        page.bind("<Configure>", schedule_sync, add="+")
        return outer, page

    def _on_page_mousewheel(self, event) -> None:
        """Scroll the active tab page when it overflows.

        Bound on the root toplevel, so it fires for wheel events over any
        descendant; widgets with native wheel behavior are skipped.
        """
        scrollers = getattr(self, "_page_scrollers", None)
        if not scrollers or not (0 <= self._tab_index < len(scrollers)):
            return
        scroller = scrollers[self._tab_index]
        if not scroller["shown"] or not event.delta:
            return
        widget = event.widget
        if isinstance(widget, str):
            return
        node = widget
        while node is not None and node is not self:
            if isinstance(node, (tk.Text, tk.Listbox, ttk.Combobox)):
                return  # these consume the wheel themselves
            node = getattr(node, "master", None)
        if node is None:
            return  # widget lives in another toplevel (popup, dialog)
        try:
            scroller["canvas"].yview_scroll(-2 if event.delta > 0 else 2, "units")
        except tk.TclError:
            pass

    def _set_sidebar_compact(self, compact: bool) -> None:
        """Icon-only sidebar on narrow windows; icon + name otherwise."""
        if not hasattr(self, "_sidebar") or getattr(self, "_sidebar_compact", None) == compact:
            return
        self._sidebar_compact = compact
        m = self._tab_nav_metrics()
        gap = m["icon_name_gap"]
        for _item, _icon_lbl, name_lbl in getattr(self, "_tab_nav_items", ()):
            if compact:
                name_lbl.pack_forget()
            else:
                name_lbl.pack(pady=(gap, 0))
        self._sidebar_width = self._sidebar_target_width()
        self._sidebar.configure(width=self._sidebar_width)

    def _sidebar_target_width(self) -> int:
        m = self._tab_nav_metrics()
        if getattr(self, "_sidebar_compact", False):
            return m["sidebar_compact_w"]
        return m["sidebar_w"]

    def _sync_tab_nav_layout(self) -> None:
        if not hasattr(self, "_sidebar"):
            return
        target_w = self._sidebar_target_width()
        if target_w != self._sidebar_width:
            self._sidebar_width = target_w
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
        size = (event.width, event.height)
        if size == getattr(self, "_last_window_size", None):
            return
        self._last_window_size = size
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
        self._set_sidebar_compact(width < 640)
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
        self._sync_work_tab_heights()
        self._sync_player_chrome_layout()
        self._sync_drop_zone_height()

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
        footer_bg = self.colors["footer_bg"]
        self._footer_container = tk.Frame(parent, bg=footer_bg)
        self._footer_container.pack(side=tk.BOTTOM, fill=tk.X)
        self._footer_container.columnconfigure(0, weight=1)

        self._footer_canvas = tk.Canvas(
            self._footer_container, height=m["height"], bg=footer_bg,
            highlightthickness=0, bd=0,
        )
        self._footer_canvas.grid(row=0, column=0, sticky="ew")
        bind_debounced_configure(self._footer_canvas, self._draw_footer_bar)

        self.cancel_btn = make_ghost_button(
            self._footer_container, "\u2715", self._cancel_convert, self.colors,
        )
        self.cancel_btn.configure(bg=footer_bg)
        self.cancel_btn.place(relx=1.0, rely=0.5, anchor="e", x=-m["btn_pad_x"])
        self.cancel_btn.configure(state=tk.DISABLED)
        self.after_idle(self._sync_footer_title)

    def _footer_title_font(self) -> tkfont.Font:
        return tkfont.Font(font=typeface("label", self._ui_scale, weight="bold"))

    def _footer_bar_colors(self) -> tuple[str, str, str]:
        """Background, gradient start (purple), gradient end (dark purple)."""
        c = self.colors
        idle = c["footer_bg"]
        purple = c["accent"]
        purple_dark = c["footer_purple_dark"]
        style = getattr(self, "_footer_progress_style", "idle")
        if style == "Danger.Horizontal.TProgressbar":
            return (c["footer_danger_bg"], c["footer_danger"], c["footer_danger_dark"])
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
            draw_key = (w, h, int(self._current_progress_pct), self._busy, self._footer_progress_style)
            if (
                not self._busy
                and draw_key == getattr(self, "_footer_draw_key", None)
                and canvas.find_all()
            ):
                return
            self._footer_draw_key = draw_key
            canvas.delete("all")
            pct = self._current_progress_pct / 100.0
            bg, mid, hi = self._footer_bar_colors()
            r = corner_radius(self._ui_scale)
            draw_round_rect_top(canvas, 0, 0, w, h, r, fill=bg, tags="bg")
            fill_w = int(w * pct)
            if self._busy and pct <= 0.01:
                # Indeterminate: a soft purple band sweeps across while we
                # wait for the first real progress percentage.
                period = 1.6
                t = (time.monotonic() % period) / period
                band_w = max(80, int(w * 0.25))
                x_center = int(t * (w + 2 * band_w)) - band_w
                steps = 20
                slice_w = max(2, band_w // steps)
                for i in range(steps):
                    x0 = x_center - band_w // 2 + i * slice_w
                    x1 = x0 + slice_w
                    if x1 <= 0 or x0 >= w:
                        continue
                    intensity = 1.0 - abs(i / max(steps - 1, 1) * 2 - 1)
                    color = self._lerp_color(bg, mid, intensity * 0.75)
                    canvas.create_rectangle(
                        max(x0, 0), 0, min(x1, w), h, fill=color, outline="", tags="fill",
                    )
            elif fill_w > 0 and (self._busy or pct > 0.01):
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
                fill=self.colors["on_accent"],
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

    _TOAST_STACK_MAX = 4

    def _build_toast(self) -> None:
        # Toast widgets are created on demand so several can stack at once.
        self._toasts: list[dict] = []

    def _toast_bottom_offset(self) -> int:
        offset = self._footer_metrics()["height"] + space(8, self._ui_scale)
        if getattr(self, "_mini_player_visible", False):
            offset += self._mini_player_shell_height()
        return offset

    def _paint_toast_border(self, toast: tk.Misc, accent: str) -> None:
        canvas = getattr(toast, "_card_canvas", None)
        if canvas is None:
            return
        try:
            w, h = max(canvas.winfo_width(), 1), max(canvas.winfo_height(), 1)
            r = corner_radius(self._ui_scale)
            canvas.delete("card_bg")
            draw_round_rect(canvas, 2, 3, w, h + 2, r, fill=self.colors["toast_shadow"], tags="card_bg")
            draw_round_rect(canvas, 0, 0, w - 2, h, r, fill=accent, tags="card_bg")
            draw_round_rect(
                canvas, 1, 1, w - 3, h - 1, max(1, r - 1),
                fill=self.colors["surface"], tags="card_bg",
            )
            canvas.tag_lower("card_bg")
        except tk.TclError:
            pass

    def _fit_toast_size(self, toast: tk.Misc) -> None:
        """Size toast to fit message on one line (no wrapping)."""
        canvas = getattr(toast, "_card_canvas", None)
        inner = getattr(toast, "_card_inner", None)
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
        accent = {"error": self.colors["danger"],
                  "warn": self.colors.get("glow", self.colors["accent"]),
                  "success": self.colors.get("success", self.colors["accent"])}.get(kind, self.colors["accent"])
        icon = {"error": "\u2716", "warn": "\u26a0", "success": "\u2714"}.get(kind, "\u2139")

        toast = make_round_surface(
            self, self.colors, fill=self.colors["surface"], border=self.colors["border"],
            padding=space(1, self._ui_scale),
        )
        entry: dict = {"widget": toast, "after": None}
        inner = toast._card_inner  # type: ignore[attr-defined]
        inner.pack_propagate(True)
        body = tk.Frame(inner, bg=self.colors["surface"])
        body.pack(fill=tk.BOTH, expand=True, padx=space(4, self._ui_scale), pady=space(3, self._ui_scale))
        tk.Label(
            body, text=icon, bg=self.colors["surface"], fg=accent,
            font=typeface("title", self._ui_scale),
        ).pack(side=tk.LEFT, padx=(0, space(2, self._ui_scale)))
        msg = tk.Label(
            body, text=message, bg=self.colors["surface"], fg=self.colors["text"],
            anchor="w", justify="left", wraplength=0,
        )
        msg.pack(side=tk.LEFT, padx=(0, space(2, self._ui_scale)))
        track_font(msg, "body", self.colors)
        action_host = tk.Frame(body, bg=self.colors["surface"])
        action_host.pack(side=tk.LEFT)
        for label, callback in (actions or []):
            def run_action(cb=callback, e=entry) -> None:
                self._dismiss_toast(e)
                cb()
            action_btn = make_ghost_button(action_host, label, run_action, self.colors)
            action_btn.configure(bg=self.colors["surface"])
            action_btn.pack(side=tk.LEFT, padx=(0, space(1, self._ui_scale)))
        close = make_ghost_button(body, "\u2715", lambda e=entry: self._dismiss_toast(e), self.colors)
        close.configure(bg=self.colors["surface"])
        close.pack(side=tk.RIGHT, padx=(space(2, self._ui_scale), 0))

        self._fit_toast_size(toast)
        self._paint_toast_border(toast, accent)
        self._toasts.append(entry)
        while len(self._toasts) > self._TOAST_STACK_MAX:
            self._dismiss_toast(self._toasts[0], reposition=False)
        entry["after"] = self.after(duration_ms, lambda e=entry: self._dismiss_toast(e))
        self._reposition_toasts()

    def _dismiss_toast(self, entry: dict, *, reposition: bool = True) -> None:
        if entry not in self._toasts:
            return
        self._toasts.remove(entry)
        if entry["after"] is not None:
            try:
                self.after_cancel(entry["after"])
            except tk.TclError:
                pass
        try:
            entry["widget"].destroy()
        except tk.TclError:
            pass
        if reposition:
            self._reposition_toasts()

    def _reposition_toasts(self) -> None:
        """Newest toast sits at the bottom; older ones stack upward."""
        gap = space(2, self._ui_scale)
        y = -self._toast_bottom_offset()
        for entry in reversed(self._toasts):
            toast = entry["widget"]
            try:
                toast.place(relx=0.5, rely=1.0, anchor="s", y=y)
                toast.lift()
                toast.update_idletasks()
                y -= max(toast.winfo_reqheight(), toast.winfo_height()) + gap
            except tk.TclError:
                continue

    def _hide_toast(self) -> None:
        """Dismiss every visible toast."""
        for entry in list(self._toasts):
            self._dismiss_toast(entry, reposition=False)

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
                self._set_audiobook_library_folder(folder, persist=False)
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
        if hasattr(self, "_cover_tile"):
            self._update_cover_tile()


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
            attach_tooltip(btn, title, self.colors)
        return btn














































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
        if busy:
            self._start_footer_shimmer()

    def _start_footer_shimmer(self) -> None:
        if getattr(self, "_shimmer_after", None) is not None:
            return
        self._shimmer_after = self.after(50, self._animate_footer_shimmer)

    def _animate_footer_shimmer(self) -> None:
        """Animate the indeterminate sweep until real progress arrives."""
        self._shimmer_after = None
        if self._closing or not self._busy or self._current_progress_pct > 1.0:
            self._draw_footer_bar()  # repaint the final static state
            return
        self._draw_footer_bar()
        self._shimmer_after = self.after(50, self._animate_footer_shimmer)

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
        self._progress_start = time.monotonic()
        self._eta_ema = None
        self._set_busy(True, status)
        self._set_progress(0)
        self._apply_progress_style("Accent.Horizontal.TProgressbar")
        self._log("—" * 52)

    # ---- conversion / audiobook actions -------------------------------------

    def _validated_source(self, *, missing_msg: str) -> Path | None:
        """Normalized, existing source path — or None after toasting the problem."""
        source = self._normalize_path(self.source_var.get())
        if not source:
            self._show_toast(missing_msg, kind="warn")
            return None
        src = Path(source)
        if not src.is_file():
            self._show_toast(f"File not found: {source}", kind="error")
            return None
        return src



    def _cancel_convert(self) -> None:
        if not self._busy:
            return
        self._jobs.cancel()
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
            self._set_audiobook_library_folder(str(self._last_audiobook.parent), persist=False)
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
        palette = [self.colors["accent"], self.colors["glow"], self.colors["glow_alt"], self.colors["accent"]]

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









        # Volume and speed stay editable at all times — the chosen values are
        # remembered and applied as soon as playback starts.















































    def _on_close(self) -> None:
        self._closing = True
        self._jobs.cancel()  # let any running job stop at its next checkpoint
        for after_id in (self._drain_after, self._tick_after, self._shimmer_after):
            if after_id is not None:
                try:
                    self.after_cancel(after_id)
                except tk.TclError:
                    pass
        self._drain_after = None
        self._tick_after = None
        self._shimmer_after = None
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
