"""Player tab for the Novelflow GUI.

Library picker, transport controls, chapter/book timelines, playback speed,
volume, and resume persistence. Mixed into NovelflowApp (see gui.py).
"""

from __future__ import annotations

import json
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from novelflow.book_structure import find_cover_image_path
from novelflow.cover_art import clear_cover_photo_cache, find_cover_for_audiobook, load_cover_photo
from novelflow.gui_theme import (
    CanvasButton,
    attach_tooltip,
    bind_debounced_configure,
    cancel_debounced_configure,
    configure_dark_combobox,
    CONFIGURE_DEBOUNCE_MS,
    configure_gutter_grid,
    draw_round_rect,
    fit_round_surface_to_content,
    make_browse_button,
    make_card,
    schedule_debounced_configure,
    make_path_entry,
    make_secondary_button,
    position_floating_tooltip,
    space,
    track_font,
    typeface,
)
from novelflow.player import is_pygame_playable, scan_audiobook_folder

_PLAYER_CHAPTER_TITLE_PLACEHOLDER = "Chapter title"
_PLAYER_CHAPTER_SUB_PLACEHOLDER = "\u2014"


class SeekBar(tk.Canvas):
    """Spotify-style seek bar: accent progress fill + round thumb on a canvas.

    Tracks a 0..1000 DoubleVar (same contract as the ttk.Scale it replaces);
    mouse handling stays with the owner via normal event bindings.
    """

    def __init__(
        self, parent: tk.Misc, variable: tk.DoubleVar, colors: dict[str, str], *,
        scale: float = 1.0, bg: str | None = None, slim: bool = False, maximum: float = 1000.0,
        width: int = 60,
    ) -> None:
        self._colors = colors
        self._slim = slim
        self._maximum = maximum
        if slim:
            self._thumb_r = max(4, int(4 * scale))
        else:
            self._thumb_r = max(6, int(7 * scale))
        surface = bg or colors["card"]
        # Canvas defaults to 376px wide; always pass a sane requested width and
        # let grid/pack stretch beyond it when the cell allows.
        super().__init__(
            parent, width=width, height=self._thumb_r * 2 + 4, bg=surface,
            highlightthickness=0, bd=0, cursor="hand2",
        )
        self._var = variable
        self._enabled = True
        self._last_size = (0, 0)
        self._pending_configure_size: tuple[int, int] | None = None
        self._trace = variable.trace_add("write", lambda *_: self._redraw())
        self.bind("<Configure>", self._on_configure)
        self.bind("<Destroy>", self._on_destroy, add="+")

    def _on_configure(self, event) -> None:
        size = (event.width, event.height)
        if size == self._last_size:
            return
        self._pending_configure_size = size
        schedule_debounced_configure(self, self._flush_configure_redraw)

    def _flush_configure_redraw(self) -> None:
        size = self._pending_configure_size
        if size is None:
            return
        self._last_size = size
        self._redraw()

    def _on_destroy(self, _event=None) -> None:
        cancel_debounced_configure(self)
        try:
            self._var.trace_remove("write", self._trace)
        except tk.TclError:
            pass

    def rescale(self, scale: float) -> None:
        if self._slim:
            self._thumb_r = max(4, int(4 * scale))
        else:
            self._thumb_r = max(6, int(7 * scale))
        self.configure(height=self._thumb_r * 2 + 4)
        self._redraw()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self._redraw()

    def fraction_from_x(self, x: int) -> float:
        pad = self._thumb_r
        inner = max(self.winfo_width() - 2 * pad, 1)
        return min(max((x - pad) / inner, 0.0), 1.0)

    def _redraw(self) -> None:
        try:
            if not self.winfo_exists():
                return
            w = self.winfo_width()
            h = self.winfo_height()
            if w <= 1 or h <= 1:
                return
            self._last_size = (w, h)
            self.delete("all")
            c = self._colors
            pad = self._thumb_r
            inner = max(w - 2 * pad, 1)
            track_h = max(3 if self._slim else 4, int(self._thumb_r * (0.55 if self._slim else 0.7)))
            y0 = (h - track_h) // 2
            y1 = y0 + track_h
            r = track_h // 2
            frac = min(max(self._var.get() / self._maximum, 0.0), 1.0)
            trough = c["border_subtle"] if self._enabled else c["border_subtle"]
            draw_round_rect(self, pad, y0, w - pad, y1, r, fill=trough, outline="")
            if self._enabled:
                fill_x = pad + int(frac * inner)
                if fill_x - pad >= 2:
                    draw_round_rect(self, pad, y0, fill_x, y1, r, fill=c["accent"], outline="")
                cy = h // 2
                self.create_oval(
                    fill_x - self._thumb_r, cy - self._thumb_r,
                    fill_x + self._thumb_r, cy + self._thumb_r,
                    fill=c["on_accent"], outline="",
                )
        except tk.TclError:
            pass


_MINI_PLAYER_ANIM_STEPS = 9
_MINI_PLAYER_ANIM_MS = 12


class PlayerTabMixin:
    """Player tab UI and playback logic."""

    def _make_round_play_button(
        self, parent: tk.Misc, command, *, compact: bool = False, mini: bool = False, bg: str | None = None,
    ) -> tk.Canvas:
        """Spotify-style circular play/pause control drawn on a canvas."""
        scale = self._ui_scale
        if compact:
            if mini:
                diameter = max(32, int(36 * scale))
            else:
                diameter = max(40, int(48 * scale))
        else:
            diameter = max(88, int(98 * scale))
        pad = 2
        surface = bg or self.colors["card"]
        canvas = tk.Canvas(
            parent, width=diameter, height=diameter, bg=surface,
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
        if compact:
            tri = max(11, int(diameter * 0.36))
        else:
            tri = max(8, int(diameter * 0.22))
        # Nudge left so the triangle reads centered inside the circle.
        shift = max(1, tri // 6)
        x0 = cx - tri // 2 - shift
        x1 = cx + tri // 2 - shift
        y0, y1 = cy - tri // 2, cy + tri // 2
        canvas._play_icon = canvas.create_polygon(
            x0, y0, x0, y1, x1, cy,
            fill=self.colors["on_accent"], outline="", state="normal",
        )
        bar_h = int(diameter * (0.32 if compact else 0.26))
        bar_w = max(3, int(diameter * (0.09 if compact else 0.075)))
        bar_gap = max(5, int(diameter * (0.11 if compact else 0.12)))
        x_l1 = cx - bar_gap // 2
        x_r0 = cx + bar_gap // 2
        canvas._pause_left = canvas.create_rectangle(  # type: ignore[attr-defined]
            x_l1 - bar_w, cy - bar_h // 2, x_l1, cy + bar_h // 2,
            fill=self.colors["on_accent"], outline="", state="hidden",
        )
        canvas._pause_right = canvas.create_rectangle(  # type: ignore[attr-defined]
            x_r0, cy - bar_h // 2, x_r0 + bar_w, cy + bar_h // 2,
            fill=self.colors["on_accent"], outline="", state="hidden",
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
        self, parent: tk.Misc, label: str, command, *, large: bool = False, tip: str = "",
        bg: str | None = None,
    ) -> CanvasButton:
        """Transport control for the player row."""
        scale = self._ui_scale
        surface = bg or self.colors["card"]
        btn = CanvasButton(
            parent, label, command, colors=self.colors, variant="player",
            font_role="title" if large else "body",
            font_weight="bold" if large else None,
            pad_x=space(4 if large else 3, scale),
            pad_y=space(3 if large else 2, scale),
        )
        btn.configure(bg=surface)
        if tip:
            attach_tooltip(btn, tip, self.colors)
        return btn

    def _set_play_button_enabled(self, *, enabled: bool) -> None:
        for btn in (
            getattr(self, "play_btn", None),
            getattr(self, "_mini_play_btn", None),
        ):
            if btn is None:
                continue
            btn._play_enabled = enabled  # type: ignore[attr-defined]
            fill = self.colors["accent"] if enabled else self.colors["border_subtle"]
            icon_fill = self.colors["on_accent"] if enabled else self.colors["muted"]
            btn.itemconfigure(btn._play_oval, fill=fill)  # type: ignore[attr-defined]
            btn.itemconfigure(btn._play_icon, fill=icon_fill)  # type: ignore[attr-defined]
            for item in (btn._pause_left, btn._pause_right):  # type: ignore[attr-defined]
                btn.itemconfigure(item, fill=icon_fill)
            btn.configure(cursor="hand2" if enabled else "arrow")

    def _audiobook_display_name(self, path: Path | None) -> str:
        if path is None:
            return ""
        stem = path.stem.replace(".audiobook", "")
        return stem.replace("-", " ").replace("_", " ")

    def _sync_player_book_name(self) -> None:
        name_var = getattr(self, "player_book_name_var", None)
        if name_var is None:
            return
        if self._player_playable and self._player_path is not None:
            name_var.set(self._audiobook_display_name(self._player_path))
        else:
            name_var.set("")

    def _mini_player_metrics(self) -> dict[str, int]:
        scale = self._ui_scale
        inset = 2
        row_gap = 2
        cover_size = max(96, int(112 * scale))
        meta_w = max(220, int(340 * scale))
        transport_h = max(36, int(40 * scale))
        seek_row_h = max(18, int(22 * scale))
        inner_h = cover_size - row_gap
        row0_h = min(max(transport_h, inner_h // 2), inner_h - seek_row_h)
        row1_h = inner_h - row0_h
        bar_h = cover_size + inset * 2
        return {
            "height": bar_h,
            "cover_size": cover_size,
            "meta_w": meta_w,
            "row0_h": row0_h,
            "row1_h": row1_h,
            "inset": inset,
            "row_gap": row_gap,
            "seek_bar_w": max(240, int(360 * scale)),
            "peek_tab_w": max(10, int(12 * scale)),
            "peek_tab_h": max(40, cover_size),
            "edge_pad": space(2, scale),
            "right_pad": 4,
            "meta_text_pad": 4,
        }

    def _mini_player_shell_height(self) -> int:
        return self._mini_player_metrics()["height"] + 1

    def _lock_mini_shell_height(self) -> None:
        """Keep the bar lane a fixed height whether expanded or collapsed."""
        shell_body = getattr(self, "_mini_player_shell_body", None)
        peek = getattr(self, "_mini_player_peek", None)
        peek_tab = getattr(self, "_mini_peek_tab", None)
        if shell_body is None:
            return
        m = self._mini_player_metrics()
        h = m["height"]
        try:
            if shell_body.winfo_exists():
                shell_body.pack_propagate(False)
                shell_body.configure(height=h)
            if peek is not None and peek.winfo_exists():
                peek.pack_propagate(False)
                peek.configure(height=h)
            if peek_tab is not None and peek_tab.winfo_exists():
                peek_tab.configure(height=m["peek_tab_h"])
        except tk.TclError:
            pass

    def _reposition_toasts_if_ready(self) -> None:
        if hasattr(self, "_reposition_toasts") and hasattr(self, "_toasts"):
            self._reposition_toasts()

    def _mini_player_target_height(self) -> int:
        """Fixed lane height for the mini player shell."""
        return self._mini_player_metrics()["height"]

    def _cancel_mini_player_anim(self) -> None:
        after_id = getattr(self, "_mini_player_anim_after", None)
        if after_id is not None:
            try:
                self.after_cancel(after_id)
            except tk.TclError:
                pass
        self._mini_player_anim_after = None

    def _release_mini_shell(self) -> None:
        """Restore shell sizing when the mini player is fully removed."""
        shell_body = getattr(self, "_mini_player_shell_body", None)
        if shell_body is None:
            return
        try:
            if shell_body.winfo_exists():
                shell_body.pack_propagate(True)
                shell_body.configure(height="")
        except tk.TclError:
            pass

    def _slide_mini_player(self, *, show: bool, on_done=None) -> None:
        """Slide the bar in/out from behind the footer.

        The active pane keeps its full fixed-pixel layout and is moved with
        place() while the shell clips it, so nothing inside re-layouts or
        redraws between frames — the bar just shifts vertically.
        """
        shell_body = getattr(self, "_mini_player_shell_body", None)
        body = getattr(self, "_mini_player_body", None)
        peek = getattr(self, "_mini_player_peek", None)
        if shell_body is None or body is None or peek is None:
            if on_done is not None:
                on_done()
            return
        pane = peek if getattr(self, "_mini_player_collapsed", False) else body
        target_h = self._mini_player_target_height()
        try:
            if not shell_body.winfo_exists() or not pane.winfo_exists():
                return
            self._cancel_mini_player_anim()
            shell_body.pack_propagate(False)
            start = max(shell_body.winfo_height(), 1)
        except tk.TclError:
            return
        end = target_h if show else 1
        # Detach the pane from pack and drive it with place for the slide.
        pane.pack_forget()
        if pane is body:
            pane_place: dict = {"x": 0, "relwidth": 1.0, "height": target_h}
        else:
            pane_place = {"x": 0}
        steps = _MINI_PLAYER_ANIM_STEPS

        def finish() -> None:
            try:
                pane.place_forget()
            except tk.TclError:
                pass
            if on_done is not None:
                on_done()
            self._release_mini_shell()
            self._apply_mini_player_collapsed_layout()
            self._reposition_toasts_if_ready()

        def step(i: int) -> None:
            self._mini_player_anim_after = None
            try:
                if not shell_body.winfo_exists():
                    return
                t = i / steps
                ease = 1.0 - (1.0 - t) ** 3  # ease-out cubic
                h = max(1, int(start + (end - start) * ease))
                shell_body.configure(height=h)
                # Bottom-align the pane so it emerges from / sinks behind the footer.
                pane.place(y=h - target_h, **pane_place)
                if i >= steps:
                    finish()
                    return
                self._mini_player_anim_after = self.after(
                    _MINI_PLAYER_ANIM_MS, lambda: step(i + 1),
                )
            except tk.TclError:
                pass

        step(0)

    def _toggle_mini_player_collapsed(self) -> None:
        self._mini_player_collapsed = not getattr(self, "_mini_player_collapsed", False)
        self._gui_prefs["mini_player_collapsed"] = self._mini_player_collapsed
        self._save_gui_prefs()
        self._apply_mini_player_collapsed_layout()

    def _draw_mini_peek_tab(self) -> None:
        tab = getattr(self, "_mini_peek_tab", None)
        if tab is None:
            return
        try:
            if not tab.winfo_exists():
                return
            w = max(int(tab.cget("width")), tab.winfo_width(), 1)
            h = max(int(tab.cget("height")), tab.winfo_height(), 1)
            hover = getattr(self, "_mini_peek_hover", False)
            draw_key = (w, h, hover)
            if getattr(tab, "_peek_draw_key", None) == draw_key and tab.find_all():
                return
            tab._peek_draw_key = draw_key  # type: ignore[attr-defined]
            tab.delete("all")
            c = self.colors
            r = max(3, int(5 * self._ui_scale))
            fill = c["accent"] if hover else c["border_subtle"]
            text = c["on_accent"] if hover else c["text"]
            draw_round_rect(tab, 0, 0, w, h, r, fill=fill, outline="")
            tab.create_text(
                w // 2, h // 2, text="\u203a", fill=text, anchor="center",
                font=typeface("body", self._ui_scale, weight="bold"),
            )
        except tk.TclError:
            pass

    def _apply_mini_player_collapsed_layout(self) -> None:
        body = getattr(self, "_mini_player_body", None)
        peek = getattr(self, "_mini_player_peek", None)
        divider = getattr(self, "_mini_player_divider", None)
        shell_body = getattr(self, "_mini_player_shell_body", None)
        if body is None or peek is None:
            return
        try:
            if not body.winfo_exists():
                return
            collapsed = self._mini_player_collapsed
            if divider is not None and divider.winfo_exists():
                if collapsed:
                    divider.pack_forget()
                elif not divider.winfo_ismapped():
                    divider.pack(fill=tk.X, before=shell_body)
            if collapsed:
                body.pack_forget()
                peek.pack(side=tk.LEFT, fill=tk.Y)
                self._draw_mini_peek_tab()
            else:
                peek.pack_forget()
                body.pack(fill=tk.BOTH, expand=True)
                self._update_cover_tile()
            self._lock_mini_shell_height()
            self._reposition_toasts_if_ready()
        except tk.TclError:
            pass

    def _build_bottom_mini_player(self, parent: tk.Misc) -> None:
        """Spotify-style now-playing bar above the footer."""
        scale = self._ui_scale
        gap = space(2, scale)
        ts_gap = space(1, scale)
        m = self._mini_player_metrics()
        bg = self.colors["surface"]
        self._mini_player_collapsed = bool(self._gui_prefs.get("mini_player_collapsed", False))

        self._mini_player_shell = tk.Frame(parent, bg=bg)
        self._mini_player_visible = False

        self._mini_player_divider = tk.Frame(self._mini_player_shell, bg=self.colors["border"], height=1)
        self._mini_player_divider.pack(fill=tk.X)

        # Plain frame — canvas create_window does not clip on Windows, so seek
        # timestamps were painting below the bar into the footer lane.
        self._mini_player_shell_body = tk.Frame(
            self._mini_player_shell, height=m["height"], bg=bg,
        )
        self._mini_player_shell_body.pack_propagate(False)
        self._mini_player_shell_body.pack(fill=tk.X)
        shell_body = self._mini_player_shell_body

        # Collapsed peek — dash tab only, same vertical lane as the full bar.
        self._mini_player_peek = tk.Frame(shell_body, bg=bg, height=m["height"])
        self._mini_player_peek.pack_propagate(False)
        self._mini_player_peek.rowconfigure(0, weight=1)
        self._mini_player_peek.rowconfigure(1, weight=0)
        self._mini_player_peek.rowconfigure(2, weight=1)
        self._mini_peek_tab = tk.Canvas(
            self._mini_player_peek,
            width=m["peek_tab_w"], height=m["peek_tab_h"],
            bg=bg, highlightthickness=0, bd=0, cursor="hand2",
        )
        self._mini_peek_tab.grid(row=1, column=0, padx=(m["edge_pad"], 0), sticky="w")
        self._mini_peek_tab.bind("<Button-1>", lambda _e: self._toggle_mini_player_collapsed())
        bind_debounced_configure(self._mini_peek_tab, self._draw_mini_peek_tab)
        self._mini_peek_hover = False

        def peek_hover(state: bool) -> None:
            self._mini_peek_hover = state
            self._draw_mini_peek_tab()

        self._mini_peek_tab.bind("<Enter>", lambda _e: peek_hover(True))
        self._mini_peek_tab.bind("<Leave>", lambda _e: peek_hover(False))
        attach_tooltip(self._mini_peek_tab, "Show player", self.colors)

        self._mini_player_body = tk.Frame(shell_body, bg=bg)
        bar = tk.Frame(self._mini_player_body, bg=bg)
        bar.pack(
            fill=tk.BOTH, expand=True,
            padx=(m["edge_pad"], m["right_pad"]), pady=m["inset"],
        )
        cover_size = m["cover_size"]
        meta_w = m["meta_w"]
        row0_h = m["row0_h"]
        row1_h = m["row1_h"]
        row_gap = m["row_gap"]
        right_pad = m["right_pad"]
        meta_text_pad = m["meta_text_pad"]
        text_wrap = max(meta_w - meta_text_pad * 2, 120)
        row0_pad = (0, row_gap)

        self._mini_hide_btn = self._make_icon_button(
            bar, "\u2039", self._toggle_mini_player_collapsed,
            title="Hide player", bg=bg, small=True,
        )
        self._mini_hide_btn.pack(side=tk.LEFT, padx=(0, space(1, scale)))

        self._mini_cover_tile = tk.Canvas(
            bar, width=cover_size, height=cover_size, bg=bg, highlightthickness=0, bd=0,
            cursor="hand2",
        )
        self._mini_cover_tile.pack(side=tk.LEFT, padx=(0, space(1, scale)))

        meta_col = tk.Frame(bar, bg=bg, width=meta_w, height=cover_size)
        self._mini_center = meta_col
        meta_col.pack(side=tk.LEFT, padx=(0, gap))
        meta_col.pack_propagate(False)
        meta_col.rowconfigure(0, minsize=row0_h, weight=0)
        meta_col.rowconfigure(1, minsize=row1_h, weight=0)

        name_cell = tk.Frame(meta_col, bg=bg, width=meta_w, height=row0_h)
        self._mini_name_cell = name_cell
        name_cell.grid(row=0, column=0, sticky="nw", pady=row0_pad)
        name_cell.grid_propagate(False)
        name_cell.pack_propagate(False)
        self._mini_book_name = tk.Label(
            name_cell, textvariable=self.player_book_name_var, bg=bg, fg=self.colors["text"],
            anchor="nw", justify=tk.LEFT, wraplength=text_wrap, cursor="hand2",
        )
        self._mini_book_name.pack(side=tk.TOP, anchor="nw", fill=tk.X, padx=(0, meta_text_pad))
        track_font(self._mini_book_name, "caption", self.colors, weight="bold")

        chapter_cell = tk.Frame(meta_col, bg=bg, width=meta_w, height=row1_h)
        self._mini_chapter_cell = chapter_cell
        chapter_cell.grid(row=1, column=0, sticky="sw")
        chapter_cell.grid_propagate(False)
        chapter_cell.pack_propagate(False)
        self._mini_chapter_line = tk.Label(
            chapter_cell, textvariable=self.player_mini_chapter_var, bg=bg, fg=self.colors["muted"],
            anchor="sw", justify=tk.LEFT, wraplength=text_wrap, cursor="hand2",
        )
        self._mini_chapter_line.pack(side=tk.BOTTOM, anchor="sw", fill=tk.X, padx=(0, meta_text_pad))
        track_font(self._mini_chapter_line, "caption", self.colors)

        def open_player(_e=None) -> None:
            try:
                self.notebook.select(2)
            except tk.TclError:
                pass

        for w in (self._mini_cover_tile, self._mini_book_name, self._mini_chapter_line):
            w.bind("<Button-1>", open_player)
            attach_tooltip(w, "Open player", self.colors)

        vol_outer = tk.Frame(bar, bg=bg, height=cover_size)
        self._mini_player_right = vol_outer
        vol_outer.pack(side=tk.RIGHT, padx=(gap, right_pad + 10))
        vol_outer.pack_propagate(False)
        vol_outer.rowconfigure(0, weight=1)
        vol_outer.rowconfigure(1, weight=0)
        vol_outer.rowconfigure(2, weight=1)
        vol_row = tk.Frame(vol_outer, bg=bg)
        vol_row.grid(row=1, column=0)
        self._mini_vol_icon = tk.Label(
            vol_row, text="🔈", bg=bg, fg=self.colors["muted"], font=typeface("body", scale),
        )
        self._mini_vol_icon.pack(side=tk.LEFT, padx=(0, space(1, scale)))
        self._mini_volume_scale = SeekBar(
            vol_row, self.mini_volume_var, self.colors,
            scale=scale * 0.75, bg=bg, slim=True, maximum=100.0,
            width=max(72, int(88 * scale)),
        )
        self._mini_volume_scale.pack(side=tk.LEFT)
        self._bind_mini_volume_bar(self._mini_volume_scale)

        transport_cell = tk.Frame(bar, bg=bg)
        self._mini_transport_cell = transport_cell
        transport = tk.Frame(transport_cell, bg=bg)
        transport.pack(anchor="center")
        btn_pad = (0, space(1, scale))
        self._mini_prev_btn = self._make_player_icon_button(
            transport, "|◀", self._player_prev, tip="Previous chapter", bg=bg,
        )
        self._mini_prev_btn.pack(side=tk.LEFT, padx=btn_pad)
        play_host = tk.Frame(transport, bg=bg)
        play_host.pack(side=tk.LEFT, padx=btn_pad)
        self._mini_play_btn = self._make_round_play_button(
            play_host, self._player_toggle, compact=True, mini=True, bg=bg,
        )
        self._mini_play_btn.pack()
        attach_tooltip(self._mini_play_btn, "Play / pause (Space)", self.colors)
        self._mini_next_btn = self._make_player_icon_button(
            transport, "▶|", self._player_next, tip="Next chapter", bg=bg,
        )
        self._mini_next_btn.pack(side=tk.LEFT, padx=btn_pad)
        transport_cell.place(relx=0.5, y=0, anchor="n")
        transport_cell.lift()

        seek_track = tk.Frame(bar, bg=bg)
        self._mini_seek_track = seek_track
        seek_row = tk.Frame(seek_track, bg=bg)
        self._mini_seek_row = seek_row
        seek_row.pack(side=tk.BOTTOM, anchor="center")
        seek_row.columnconfigure(0, weight=0)
        seek_row.columnconfigure(1, weight=0)
        seek_row.columnconfigure(2, weight=0)

        self._mini_elapsed = tk.Label(
            seek_row, textvariable=self.player_chapter_elapsed_var, bg=bg, fg=self.colors["muted"], anchor="e",
        )
        self._mini_elapsed.grid(row=0, column=0, sticky="e", padx=(0, ts_gap))
        track_font(self._mini_elapsed, "caption", self.colors)

        self._mini_seek_scale = SeekBar(
            seek_row, self.mini_seek_var, self.colors, scale=scale * 0.8, bg=bg, slim=True,
            width=m["seek_bar_w"],
        )
        self._mini_seek_scale.grid(row=0, column=1)
        self._bind_chapter_seek_bar(self._mini_seek_scale, use_mini=True)

        self._mini_total = tk.Label(
            seek_row, textvariable=self.player_chapter_total_var, bg=bg, fg=self.colors["muted"], anchor="w",
        )
        self._mini_total.grid(row=0, column=2, sticky="w", padx=(ts_gap, 0))
        track_font(self._mini_total, "caption", self.colors)
        seek_track.place(relx=0.5, y=cover_size, anchor="s")
        seek_track.lift()

        self._draw_mini_peek_tab()
        self._apply_mini_player_collapsed_layout()

    def _set_seek_ui(self, fraction: float) -> None:
        value = max(0.0, min(1.0, fraction)) * 1000.0
        self.seek_var.set(value)
        self.mini_seek_var.set(value)

    def _set_volume_ui(self, level: float) -> None:
        level = max(0.0, min(100.0, level))
        self.volume_var.set(level)
        self.mini_volume_var.set(level)
        self._player.set_volume(level / 100.0)
        self._refresh_volume_ui()
        if self._vol_save_after is not None:
            self.after_cancel(self._vol_save_after)
        self._vol_save_after = self.after(800, self._persist_volume_pref)

    def _bind_main_volume_bar(self, bar: SeekBar) -> None:
        bar.bind("<Button-1>", lambda e: self._on_main_volume_event(e))
        bar.bind("<B1-Motion>", lambda e: self._on_main_volume_event(e))
        bar.bind("<ButtonRelease-1>", lambda _e: None)

    def _bind_mini_volume_bar(self, bar: SeekBar) -> None:
        bar.bind("<Button-1>", lambda e: self._on_mini_volume_event(e))
        bar.bind("<B1-Motion>", lambda e: self._on_mini_volume_event(e))
        bar.bind("<ButtonRelease-1>", lambda _e: None)

    def _on_main_volume_event(self, event) -> str | None:
        widget = event.widget
        if not isinstance(widget, SeekBar):
            return None
        self._set_volume_ui(widget.fraction_from_x(event.x) * widget._maximum)
        return "break"

    def _on_mini_volume_event(self, event) -> str | None:
        widget = event.widget
        if not isinstance(widget, SeekBar):
            return None
        self._set_volume_ui(widget.fraction_from_x(event.x) * widget._maximum)
        return "break"

    def _bind_chapter_seek_bar(self, seek_bar: SeekBar, *, use_mini: bool = False) -> None:
        seek_bar.bind("<Button-1>", lambda e: self._on_seek_press(e, use_mini=use_mini))
        seek_bar.bind("<B1-Motion>", lambda e: self._on_seek_motion(e, use_mini=use_mini))
        seek_bar.bind("<ButtonRelease-1>", self._on_seek_release)

    def _sync_bottom_mini_player(self) -> None:
        """Show the bottom bar on non-Player tabs when an audiobook is loaded."""
        shell = getattr(self, "_mini_player_shell", None)
        if shell is None:
            return
        try:
            if not shell.winfo_exists():
                return
            tab_index = getattr(self, "_tab_index", 0)
            playable = getattr(self, "_player_playable", False)
            show = playable and tab_index != 2
            was_visible = getattr(self, "_mini_player_visible", False)
            self._mini_player_visible = show
            self._cancel_mini_player_anim()
            if show:
                already_mapped = shell.winfo_ismapped()
                shell.pack(side=tk.BOTTOM, fill=tk.X)
                self._lock_mini_shell_height()
                self._apply_mini_player_collapsed_layout()
                if not already_mapped:
                    self._update_cover_tile()
                self._reposition_toasts_if_ready()
            elif was_visible:
                shell.pack_forget()
                self._release_mini_shell()
                self._reposition_toasts_if_ready()
        except tk.TclError:
            pass

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

        self._build_player_library_card(top)
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

        player_shell = ttk.Frame(cbody, style="Card.TFrame")
        player_shell.grid(row=0, column=0, sticky="nsew")
        player_shell.columnconfigure(0, weight=1)
        player_shell.rowconfigure(0, weight=1)

        main = ttk.Frame(player_shell, style="Card.TFrame")
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=70)
        main.rowconfigure(1, weight=30)

        self._build_player_transport(main)
        self._build_book_progress(main)
        self._build_chapter_panel(cbody)

        player_footer = ttk.Frame(cbody, style="Card.TFrame")
        player_footer.grid(row=1, column=0, columnspan=2, sticky="e", pady=(space(2, self._ui_scale), 0))
        self.player_open_ext_btn = self._make_icon_button(
            player_footer, "↗", self._open_audiobook_file, title="Open externally",
            bg=self.colors["card"], small=True,
        )
        self.player_open_ext_btn.pack(side=tk.RIGHT)
        self._make_icon_button(
            player_footer, "☰", self._toggle_chapter_panel, title="Chapter list",
            bg=self.colors["card"], small=True,
        ).pack(side=tk.RIGHT, padx=(0, space(2, self._ui_scale)))

        self._refresh_volume_ui()
        self._set_player_controls(enabled=False)
        self._sync_player_empty_state()
        self.after_idle(self._sync_player_chrome_layout)
        self.after_idle(self._sync_work_tab_heights)

    def _build_chapter_panel(self, cbody: ttk.Frame) -> None:
        """Collapsible chapter sidebar: titles + durations, double-click to play."""
        scale = self._ui_scale
        cbody.columnconfigure(1, weight=0)
        panel = ttk.Frame(cbody, style="Card.TFrame")
        panel.grid(row=0, column=1, sticky="ns", padx=(space(4, scale), 0))
        panel.rowconfigure(1, weight=1)
        self._chapter_panel = panel
        self._chapter_panel_visible = False
        self._chapter_list_index = -1

        ttk.Label(panel, text="Chapters", style="CardFormLabel.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, space(1, scale)),
        )
        self._chapter_list = tk.Listbox(
            panel, activestyle="none", highlightthickness=0, borderwidth=0,
            bg=self.colors["surface"], fg=self.colors["text"],
            selectbackground=self.colors["accent"], selectforeground=self.colors["on_accent"],
            width=32,
        )
        chap_scroll = ttk.Scrollbar(
            panel, orient=tk.VERTICAL, command=self._chapter_list.yview, style="Vertical.TScrollbar",
        )
        self._chapter_list.configure(yscrollcommand=chap_scroll.set)
        self._chapter_list.grid(row=1, column=0, sticky="nsew")
        chap_scroll.grid(row=1, column=1, sticky="ns")
        track_font(self._chapter_list, "caption", self.colors)
        self._chapter_list.bind("<Double-Button-1>", self._on_chapter_list_jump)
        self._chapter_list.bind("<Return>", self._on_chapter_list_jump)
        ttk.Label(panel, text="Double-click to play", style="CardMuted.TLabel").grid(
            row=2, column=0, sticky="w", pady=(space(1, scale), 0),
        )
        panel.grid_remove()
        self._refresh_chapter_list()

    def _toggle_chapter_panel(self) -> None:
        if not hasattr(self, "_chapter_panel"):
            return
        self._chapter_panel_visible = not self._chapter_panel_visible
        if self._chapter_panel_visible:
            self._refresh_chapter_list()
            self._chapter_panel.grid()
        else:
            self._chapter_panel.grid_remove()

    def _refresh_chapter_list(self) -> None:
        listbox = getattr(self, "_chapter_list", None)
        if listbox is None:
            return
        try:
            if not listbox.winfo_exists():
                return
            listbox.delete(0, tk.END)
            for i, chapter in enumerate(self._player_chapters):
                dur = self._fmt_time(chapter.duration_ms) if chapter.duration_ms > 0 else "--:--"
                listbox.insert(tk.END, f"{i + 1:>3}  {chapter.title}   {dur}")
            self._chapter_list_index = -1
            self._sync_chapter_list_selection()
        except tk.TclError:
            pass

    def _sync_chapter_list_selection(self) -> None:
        """Keep the current chapter highlighted in the sidebar."""
        listbox = getattr(self, "_chapter_list", None)
        if listbox is None or not self._player_chapters:
            return
        idx = self._player.index
        if idx == self._chapter_list_index:
            return
        try:
            if not listbox.winfo_exists():
                return
            self._chapter_list_index = idx
            listbox.selection_clear(0, tk.END)
            if 0 <= idx < listbox.size():
                listbox.selection_set(idx)
                listbox.see(idx)
        except tk.TclError:
            pass

    def _on_chapter_list_jump(self, _event=None) -> None:
        if not self._player_playable:
            return
        selection = self._chapter_list.curselection()
        if not selection:
            return
        idx = int(selection[0])
        if 0 <= idx < len(self._player_chapters):
            self._play_index(idx)

    def _sync_player_empty_state(self) -> None:
        """Swap the transport cluster with the empty-state hint card."""
        if not hasattr(self, "_player_empty_view"):
            return
        if self._player_path is None:
            self._playback_cluster.grid_remove()
            self._player_empty_view.grid()
        else:
            self._player_empty_view.grid_remove()
            self._playback_cluster.grid()

    def _build_player_library_card(self, top: ttk.Frame) -> None:
        """Library folder + audiobook picker card at the top of the tab."""
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

    def _build_player_transport(self, main: ttk.Frame) -> None:
        """Chapter title, seek bar, volume, transport buttons, and speed combo."""
        gap = space(3, self._ui_scale)
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

        # Friendly hint shown instead of the transport before anything loads.
        empty = ttk.Frame(playback_zone, style="Card.TFrame")
        empty.grid(row=1, column=0, sticky="ew")
        empty.columnconfigure(0, weight=1)
        self._player_empty_view = empty
        empty_inner = ttk.Frame(empty, style="Card.TFrame")
        empty_inner.grid(row=0, column=0)
        tk.Label(
            empty_inner, text="\U0001f3a7", bg=self.colors["card"], fg=self.colors["muted"],
            font=typeface("title", self._ui_scale * 1.8),
        ).pack(pady=(0, space(2, self._ui_scale)))
        ttk.Label(
            empty_inner, text="Pick an audiobook from your library above",
            style="CardFormLabel.TLabel", anchor="center",
        ).pack()
        ttk.Label(
            empty_inner, text="or create one from the Audiobook tab",
            style="CardMuted.TLabel", anchor="center",
        ).pack(pady=(space(1, self._ui_scale), 0))

        title_block = ttk.Frame(playback_cluster, style="Card.TFrame")
        title_block.grid(row=0, column=0, sticky="ew")
        title_block.columnconfigure(0, weight=1)
        now_playing = ttk.Frame(title_block, style="Card.TFrame")
        now_playing.grid(row=0, column=0)  # centered on the full card width
        self._cover_photo: tk.PhotoImage | None = None
        self._cover_tile = tk.Canvas(
            now_playing, bg=self.colors["card"], highlightthickness=0, bd=0,
        )
        self._cover_tile.pack(pady=(0, space(3, self._ui_scale)))
        text_col = ttk.Frame(now_playing, style="Card.TFrame")
        text_col.pack()
        ttk.Label(
            text_col, textvariable=self.player_chapter_title_var,
            style="PlayerChapterTitle.TLabel", anchor="center",
        ).pack(anchor="center")
        ttk.Label(
            text_col, textvariable=self.player_chapter_sub_var,
            style="CardHeading.TLabel", anchor="center",
        ).pack(anchor="center", pady=(space(1, self._ui_scale), 0))
        self._update_cover_tile()

        transport_bar = ttk.Frame(playback_cluster, style="Card.TFrame")
        transport_bar.grid(row=1, column=0, sticky="ew", pady=(space(4, self._ui_scale), 0))
        transport_bar.columnconfigure(0, weight=1)
        transport = ttk.Frame(transport_bar, style="Card.TFrame")
        transport.grid(row=0, column=0)
        btn_pad = (0, gap)
        self.prev_btn = self._make_player_icon_button(
            transport, "|◀", self._player_prev, large=True, tip="Previous chapter",
        )
        self.prev_btn.pack(side=tk.LEFT, padx=btn_pad)
        self.back10_btn = self._make_player_icon_button(
            transport, "↺10", lambda: self._seek_relative(-10000), large=True, tip="Back 10 seconds",
        )
        self.back10_btn.pack(side=tk.LEFT, padx=btn_pad)

        play_host = tk.Frame(transport, bg=self.colors["card"])
        play_host.pack(side=tk.LEFT, padx=(gap, gap))
        self.play_btn = self._make_round_play_button(play_host, self._player_toggle)
        self.play_btn.pack()
        attach_tooltip(self.play_btn, "Play / pause (Space)", self.colors)

        self.fwd10_btn = self._make_player_icon_button(
            transport, "10↻", lambda: self._seek_relative(10000), large=True, tip="Forward 10 seconds",
        )
        self.fwd10_btn.pack(side=tk.LEFT, padx=btn_pad)
        self.next_btn = self._make_player_icon_button(
            transport, "▶|", self._player_next, large=True, tip="Next chapter",
        )
        self.next_btn.pack(side=tk.LEFT, padx=btn_pad)

        player_strip = self._player_centered_strip(
            playback_cluster, row=2,
            pady=(space(4, self._ui_scale), space(2, self._ui_scale)),
            width_pct=60,
        )
        self._player_strip = player_strip
        # Breathing room between the time stamps and the seek bar.
        self._player_strip_gap_units = 1.5
        pc = configure_gutter_grid(player_strip, scale=self._ui_scale, gap_units=self._player_strip_gap_units)
        self._player_strip_gap_cols = (pc["gap_l"], pc["gap_r"])
        main_colspan = pc["right"] - pc["center"] + 1
        ctrl_pad = (space(2, self._ui_scale), 0)
        ts_gap = space(1, self._ui_scale)

        ttk.Label(
            player_strip, textvariable=self.player_chapter_elapsed_var,
            style="PlayerTime.TLabel", anchor="e",
        ).grid(row=0, column=pc["left"], sticky="e")

        # Seek + total share one span so the timestamp sits tight against the bar
        # and its right edge lines up with the speed combo below.
        seek_track = ttk.Frame(player_strip, style="Card.TFrame")
        seek_track.grid(row=0, column=pc["center"], columnspan=main_colspan, sticky="ew")
        seek_track.columnconfigure(0, weight=1)
        self.seek_scale = SeekBar(seek_track, self.seek_var, self.colors, scale=self._ui_scale)
        self.seek_scale.grid(row=0, column=0, sticky="ew")
        self.seek_scale.bind("<Button-1>", self._on_seek_press)
        self.seek_scale.bind("<B1-Motion>", self._on_seek_motion)
        self.seek_scale.bind("<ButtonRelease-1>", self._on_seek_release)
        ttk.Label(
            seek_track, textvariable=self.player_chapter_total_var,
            style="PlayerTime.TLabel", anchor="e",
        ).grid(row=0, column=1, sticky="e", padx=(ts_gap, 0))

        self._vol_icon = tk.Label(
            player_strip, text="🔈", bg=self.colors["card"], fg=self.colors["muted"],
            font=typeface("title", self._ui_scale),
        )
        self._vol_icon.grid(row=1, column=pc["left"], sticky="w", pady=ctrl_pad)

        vol_strip = tk.Frame(player_strip, bg=self.colors["card"])
        vol_strip.grid(row=1, column=pc["left"], sticky="sw", padx=(space(4, self._ui_scale), 0), pady=ctrl_pad)
        self.volume_scale = SeekBar(
            vol_strip, self.volume_var, self.colors, scale=self._ui_scale * 0.85,
            bg=self.colors["card"], slim=True, maximum=100.0,
            width=max(int(100 * self._ui_scale), 88),
        )
        self.volume_scale.pack(side=tk.LEFT)
        self._bind_main_volume_bar(self.volume_scale)

        speed_row = ttk.Frame(player_strip, style="Card.TFrame")
        speed_row.grid(row=1, column=pc["right"], sticky="e", pady=ctrl_pad)
        ttk.Label(speed_row, text="Speed", style="CardMuted.TLabel").pack(side=tk.LEFT, padx=(0, gap))
        self.speed_combo = ttk.Combobox(
            speed_row, textvariable=self.speed_var, state="readonly", width=6, style="Dark.TCombobox",
            values=("0.75×", "1.0×", "1.25×", "1.5×", "1.75×", "2.0×"),
        )
        self.speed_combo.pack(side=tk.LEFT)
        configure_dark_combobox(self.speed_combo, self.colors)
        self.speed_combo.bind("<<ComboboxSelected>>", self._on_speed_change)

    def _build_book_progress(self, main: ttk.Frame) -> None:
        """Book progress header, times, and the chapter timeline strip."""
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
        self._book_tl_resize_after = self.after(CONFIGURE_DEBOUNCE_MS, self._finish_book_timeline_redraw)

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
            return self.colors["timeline_played"]
        if index == current:
            return self.colors["accent"]
        return self.colors["timeline_track"]

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
        position_floating_tooltip(
            self._book_tl_tip, self._book_tl, x_root, y_root,
            offset_x=12, offset_y=28, prefer_above=True,
        )
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
                play_color = self.colors["on_accent"]
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

    def _refresh_volume_ui(self) -> None:
        vol = self.volume_var.get()
        icon = "🔇" if vol < 1 else "🔈" if vol < 34 else "🔉" if vol < 67 else "🔊"
        self._vol_icon.configure(text=icon)
        mini_icon = getattr(self, "_mini_vol_icon", None)
        if mini_icon is not None:
            try:
                if mini_icon.winfo_exists():
                    mini_icon.configure(text=icon)
            except tk.TclError:
                pass

    def _begin_preview_playback(self, clip: Path) -> None:
        """Play a voice preview without corrupting audiobook playback state.

        Previews share the single pygame music stream, so bookmark the current
        chapter position first; the next play press resumes through the normal
        speed-aware path instead of restarting the raw file at 1.0x.
        """
        if self._player_started:
            self._resume_fraction = self._current_fraction()
            self._remember_position()
            self._player_started = False
            self._was_busy = False
        self._player.play_preview(clip)
        if hasattr(self, "play_btn"):
            self._update_play_button()

    def _set_audiobook_library_folder(self, folder: str, *, persist: bool = True) -> None:
        """Point the library at ``folder``.

        ``persist=False`` for automatic workflow syncs so they don't overwrite
        the folder the user explicitly chose.
        """
        resolved = self._normalize_path(folder)
        if not resolved:
            return
        self.audiobook_lib_dir_var.set(resolved)
        if hasattr(self, "audiobook_lib_dir_entry"):
            self._sync_entry(self.audiobook_lib_dir_entry, resolved)
        if persist:
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

    def _configure_player_styles(self) -> None:
        scale = self._ui_scale
        for name in ("seek_scale", "volume_scale", "_mini_seek_scale", "_mini_volume_scale"):
            bar = getattr(self, name, None)
            if isinstance(bar, SeekBar):
                try:
                    bar.rescale(scale * (0.8 if name == "_mini_seek_scale" else 0.75 if name == "_mini_volume_scale" else 0.85 if name == "volume_scale" else 1.0))
                except tk.TclError:
                    pass
        style = self.colors.get("_style")
        if style is None:
            return
        try:
            thumb = max(12, int(16 * self._ui_scale))
            knob = self.colors["on_accent"]
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
                    lightcolor=knob,
                    darkcolor=knob,
                    sliderthickness=thumb,
                    sliderlength=thumb,
                )
                style.map(
                    name,
                    background=[("active", knob), ("!disabled", knob)],
                    troughcolor=[("!disabled", trough)],
                )
        except tk.TclError:
            pass

    def _cover_prefs_key(self, audio_path: Path) -> str:
        return str(audio_path.resolve())

    def _stored_cover_path(self, audio_path: Path) -> Path | None:
        raw = self._gui_prefs.get("audiobook_covers", {}).get(self._cover_prefs_key(audio_path))
        if not raw:
            return None
        candidate = Path(raw)
        return candidate.resolve() if candidate.is_file() else None

    def _persist_cover_binding(self, audio_path: Path, cover_path: Path) -> None:
        covers = self._gui_prefs.setdefault("audiobook_covers", {})
        covers[self._cover_prefs_key(audio_path)] = str(cover_path.resolve())
        self._save_gui_prefs()

    def _resolve_cover_image_path(self) -> Path | None:
        audio = self._player_path
        md = self._current_markdown_path()
        if audio is not None:
            stored = self._stored_cover_path(audio)
            if stored is not None:
                return stored
        discovered: Path | None = None
        if audio is not None:
            discovered = find_cover_for_audiobook(audio, markdown_path=md)
        elif md is not None:
            discovered = find_cover_image_path(md)
        if discovered is not None and audio is not None:
            self._persist_cover_binding(audio, discovered)
        return discovered

    def _paint_cover_on_canvas(
        self,
        canvas: tk.Canvas,
        *,
        size: int,
        photo_attr: str,
        radius_scale: float = 1.0,
    ) -> None:
        scale = self._ui_scale
        cover_path = self._resolve_cover_image_path()
        path_key = str(cover_path) if cover_path is not None else ""
        paint_key = (path_key, size, radius_scale)
        if getattr(canvas, "_cover_paint_key", None) == paint_key and canvas.find_all():
            return
        canvas._cover_paint_key = paint_key  # type: ignore[attr-defined]
        canvas.configure(width=size, height=size)
        canvas.delete("all")
        setattr(self, photo_attr, None)

        if cover_path is not None:
            photo = load_cover_photo(cover_path, max_size=size, master=canvas)
            if photo is not None:
                setattr(self, photo_attr, photo)
                radius = max(6, int(10 * scale * radius_scale))
                bg = canvas.cget("bg")
                draw_round_rect(canvas, 0, 0, size, size, radius, fill=self.colors["accent_soft"], outline="")
                canvas.create_image(size // 2, size // 2, image=photo)
                return

        glyph = "\u266a"
        if self._player_path is not None:
            name = self._player_path.stem.replace(".audiobook", "").strip()
            if name:
                glyph = name[0].upper()
        radius = max(6, int(10 * scale * radius_scale))
        draw_round_rect(canvas, 0, 0, size, size, radius, fill=self.colors["accent_soft"], outline="")
        canvas.create_text(
            size // 2, size // 2, text=glyph, fill=self.colors["glow"],
            font=typeface("title", scale * 1.2 * radius_scale, weight="bold"),
        )

    def _update_cover_tile(self) -> None:
        """Cover art on the player tab and in the bottom mini player."""
        scale = self._ui_scale
        main_tile = getattr(self, "_cover_tile", None)
        if main_tile is not None:
            try:
                if main_tile.winfo_exists():
                    self._paint_cover_on_canvas(
                        main_tile, size=max(144, int(176 * scale)), photo_attr="_cover_photo",
                    )
            except tk.TclError:
                pass
        header_tile = getattr(self, "_mini_cover_tile", None)
        if header_tile is not None:
            try:
                if header_tile.winfo_exists():
                    cover_size = self._mini_player_metrics()["cover_size"]
                    self._paint_cover_on_canvas(
                        header_tile, size=cover_size, photo_attr="_mini_cover_photo",
                        radius_scale=0.85,
                    )
            except tk.TclError:
                pass

    def _set_player_chapter_placeholders(self) -> None:
        self.player_chapter_title_var.set(_PLAYER_CHAPTER_TITLE_PLACEHOLDER)
        self.player_chapter_sub_var.set(_PLAYER_CHAPTER_SUB_PLACEHOLDER)
        self.player_mini_chapter_var.set("")
        self._sync_player_book_name()
        self._update_cover_tile()

    def _set_player_controls(self, *, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for btn in (self.prev_btn, self.next_btn, self.back10_btn, self.fwd10_btn):
            btn.configure(state=state)
        for btn in (getattr(self, "_mini_prev_btn", None), getattr(self, "_mini_next_btn", None)):
            if btn is not None:
                btn.configure(state=state)
        self._set_play_button_enabled(enabled=enabled)
        self.seek_scale.set_enabled(enabled)
        vol_bar = getattr(self, "volume_scale", None)
        if isinstance(vol_bar, SeekBar):
            vol_bar.set_enabled(enabled)
        mini_seek = getattr(self, "_mini_seek_scale", None)
        if mini_seek is not None:
            mini_seek.set_enabled(enabled)
        mini_vol = getattr(self, "_mini_volume_scale", None)
        if isinstance(mini_vol, SeekBar):
            mini_vol.set_enabled(enabled)
        self._book_timeline_enabled = enabled
        if hasattr(self, "_book_tl"):
            self._book_tl.configure(cursor="hand2" if enabled else "arrow")
            self._draw_book_timeline()
        if not enabled:
            self._set_player_chapter_placeholders()
        self._sync_bottom_mini_player()

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
        self._invalidate_speed_prep()
        self._player.stop()
        self._was_busy = False
        self._player_started = False
        self._resume_fraction = 0.0
        clear_cover_photo_cache()
        for tile in (getattr(self, "_cover_tile", None), getattr(self, "_mini_cover_tile", None)):
            if tile is not None:
                tile._cover_paint_key = None  # type: ignore[attr-defined]
        # Skip the blocking ffprobe fallback; durations are filled in async below.
        chapters = self._player.load(audio_path, probe_durations=False)
        self._player_chapters = chapters
        self._player_path = audio_path
        self._player_playable = bool(chapters) and all(
            c.file is not None and is_pygame_playable(c.file) for c in chapters
        )
        self._last_audiobook = audio_path
        self._sync_player_book_name()
        self._update_cover_tile()
        self._sync_player_empty_state()
        self._refresh_chapter_list()
        self._sync_library_pick_for_path(audio_path)
        self.audio_open_btn.configure(state=tk.NORMAL)
        self.audio_play_btn.configure(state=tk.NORMAL)
        self._player.set_volume(self.volume_var.get() / 100.0)
        self._apply_speed_from_combo()
        if self._player_playable:
            self.player_title_var.set(f"Loaded: {audio_path.name}  ·  {len(chapters)} chapter(s)")
            self._set_player_controls(enabled=True)
            saved = self._resume_store.get(self._resume_key(audio_path))
            if saved is None:
                saved = self._resume_store.get(str(audio_path))  # legacy unresolved key
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
            self._probe_missing_durations_async(chapters)
        else:
            self.player_title_var.set(
                f"{audio_path.name} — in-app preview not supported for this format; use Open externally."
            )
            self._set_player_controls(enabled=False)

    def _probe_missing_durations_async(self, chapters: list) -> None:
        """ffprobe any zero-duration chapters off the UI thread, then refresh."""
        if not any(c.duration_ms <= 0 and c.file is not None for c in chapters):
            return

        def work() -> None:
            from novelflow.player import probe_chapter_durations

            if probe_chapter_durations(chapters):
                def refresh() -> None:
                    if self._player_chapters is chapters:
                        self._update_player_time()
                        self._draw_book_timeline()
                        self._refresh_chapter_list()

                self._ui(refresh)

        threading.Thread(target=work, daemon=True).start()

    def _prune_speed_cache_async(self) -> None:
        def work() -> None:
            from novelflow.player import prune_speed_cache

            prune_speed_cache()

        threading.Thread(target=work, daemon=True).start()

    def _restart_from_beginning(self) -> None:
        self._hide_toast()
        self._resume_fraction = 0.0
        self._player_started = False
        self._player.index = 0
        self._play_index(0)

    def _update_play_button(self) -> None:
        playing = self._player.is_playing
        for btn in (
            getattr(self, "play_btn", None),
            getattr(self, "_mini_play_btn", None),
        ):
            if btn is None:
                continue
            if playing:
                btn.itemconfigure(btn._play_icon, state="hidden")  # type: ignore[attr-defined]
                btn.itemconfigure(btn._pause_left, state="normal")  # type: ignore[attr-defined]
                btn.itemconfigure(btn._pause_right, state="normal")  # type: ignore[attr-defined]
            else:
                btn.itemconfigure(btn._play_icon, state="normal")  # type: ignore[attr-defined]
                btn.itemconfigure(btn._pause_left, state="hidden")  # type: ignore[attr-defined]
                btn.itemconfigure(btn._pause_right, state="hidden")  # type: ignore[attr-defined]

    def _invalidate_speed_prep(self) -> None:
        """Drop any in-flight async speed prep (chapter/book changed)."""
        self._speed_prep_gen += 1
        self._preparing_speed = False

    def _play_index(self, index: int, start_fraction: float = 0.0) -> bool:
        if not self._player_playable or not (0 <= index < len(self._player_chapters)):
            return False
        self._invalidate_speed_prep()
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
        # The generation guard discards the result if the user switched
        # chapters or loaded another book while ffmpeg was running.
        self._preparing_speed = True
        gen = self._speed_prep_gen
        self.status_var.set(f"Preparing {self.speed_var.get()} playback…")

        def work() -> None:
            variant = make_speed_variant(chapter.file, speed)

            def done() -> None:
                if gen != self._speed_prep_gen:
                    return  # superseded — a newer play/load owns the player now
                self._preparing_speed = False
                if 0 <= index < len(self._player_chapters):
                    self._player.play_resolved(index, variant or chapter.file, start_ms)
                    self._after_play_started()
                    self.status_var.set("" if variant else "Speed unavailable — playing at 1.0×")

            self._ui(done)

        threading.Thread(target=work, daemon=True).start()
        return True

    def _after_play_started(self) -> None:
        self._player_started = True
        self._was_busy = False
        self._play_started_at = time.monotonic()
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
        if self._gui_prefs.get("remember_speed"):
            self._gui_prefs["speed"] = self.speed_var.get()
            self._save_gui_prefs()
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

    def _seek_fraction_from_event(self, event) -> float:
        widget = event.widget
        if hasattr(widget, "fraction_from_x"):
            return widget.fraction_from_x(event.x)
        return self.seek_scale.fraction_from_x(event.x)

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

    def _on_seek_press(self, event, *, use_mini: bool = False):
        if not self._player_playable:
            return "break"
        self._user_seeking = True
        self._set_seek_ui(self._seek_fraction_from_event(event))
        self._preview_seek_label()
        return "break"

    def _on_seek_motion(self, event, *, use_mini: bool = False):
        if not self._user_seeking:
            return "break"
        self._set_seek_ui(self._seek_fraction_from_event(event))
        self._preview_seek_label()
        return "break"

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
            seek_val = 0 if dur <= 0 else pos / dur * 1000.0
            self.seek_var.set(seek_val)
            self.mini_seek_var.set(seek_val)
        book_total = self._total_book_duration_ms()
        book_pos = min(self._total_book_position_ms(), book_total)
        if not self._user_book_seeking:
            self.book_seek_var.set(0 if book_total <= 0 else book_pos / book_total * 1000.0)
        self._set_player_time_labels(
            chapter_pos=pos, chapter_dur=dur, book_pos=book_pos, book_total=book_total,
        )
        self._sync_chapter_list_selection()
        idx = self._player.index
        total = len(self._player_chapters)
        if self._player_playable and 0 <= idx < total:
            self.player_chapter_title_var.set(self._player_chapters[idx].title)
            self.player_chapter_sub_var.set(f"Part {idx + 1} of {total}")
            self.player_mini_chapter_var.set(f"Chapter {idx + 1}")
            self._sync_player_book_name()
        else:
            self._set_player_chapter_placeholders()
        if hasattr(self, "_book_tl"):
            self._draw_book_timeline()

    def _tick_player(self) -> None:
        if self._closing:
            self._tick_after = None
            return
        try:
            if self._player_playable and self._player.is_playing and not self._preparing_speed:
                busy = self._player.is_busy()
                if busy:
                    self._was_busy = True
                elif self._was_busy or time.monotonic() - self._play_started_at > 0.7:
                    # Current chapter finished — advance or stop at the end.
                    # The grace period catches chapters shorter than one poll
                    # interval, which would otherwise never register as busy.
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
            self._tick_after = None
            return
        except Exception:  # noqa: BLE001 - never let one bad tick spam the loop
            import traceback

            traceback.print_exc()
        self._tick_after = self.after(300, self._tick_player)

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

    @staticmethod
    def _resume_key(audio_path: Path) -> str:
        """Stable resume-store key — resolves symlinks/relative path aliases."""
        try:
            return str(Path(audio_path).resolve())
        except OSError:
            return str(audio_path)

    def _remember_position(self) -> None:
        if not (self._player_playable and self._player_path and self._player_started):
            return
        key = self._resume_key(self._player_path)
        if key != str(self._player_path):
            self._resume_store.pop(str(self._player_path), None)  # migrate legacy key
        self._resume_store[key] = {
            "index": self._player.index,
            "fraction": self._current_fraction(),
        }
        self._persist_resume_store()
