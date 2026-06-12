"""Design tokens and theme for Novelflow.

Follows common desktop UI practice:
- 8pt spacing grid (Material / iOS HIG)
- M3-inspired type roles (body 14px, title 16–22px)
- Layered dark surfaces with subtle borders (not flat purple-on-purple)
- Gentle window scaling — typography stays stable; layout breathes on large screens
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# --- Design tokens -----------------------------------------------------------

_REF_WIDTH = 1024
_REF_HEIGHT = 768
_MIN_FONT_SCALE = 0.62  # small windows shrink the whole UI to fit (no scrolling)
_MAX_FONT_SCALE = 1.14  # subtle bump on large monitors only

# Material-3-ish roles at scale 1.0 (desktop body ≈ 14px)
_TYPE = {
    "display": 22,
    "title": 16,
    "body": 14,
    "label": 13,
    "caption": 12,
    "overline": 11,
    "button": 14,
    "mono": 13,
    "step": 12,
}

# 8pt grid — spacing values are multiples of 4/8
_SPACE = {
    1: 4,
    2: 8,
    3: 12,
    4: 16,
    5: 20,
    6: 24,
    8: 32,
    10: 40,
}


def space(units: float, scale: float = 1.0) -> int:
    u = float(units)
    if u == 0.5:
        px = _SPACE[1] / 2
    elif u == int(u) and int(u) in _SPACE:
        px = _SPACE[int(u)]
    else:
        px = u * 8
    return max(1, int(round(px * scale)))


CONFIGURE_DEBOUNCE_MS = 16


def schedule_debounced_configure(
    widget: tk.Misc,
    callback,
    *,
    ms: int = CONFIGURE_DEBOUNCE_MS,
    after_attr: str = "_debounce_configure_after",
) -> None:
    """Run ``callback`` once, ``ms`` after the last configure in a burst."""
    after_id = getattr(widget, after_attr, None)
    if after_id is not None:
        try:
            widget.after_cancel(after_id)
        except tk.TclError:
            pass

    def fire() -> None:
        setattr(widget, after_attr, None)
        try:
            if widget.winfo_exists():
                callback()
        except tk.TclError:
            pass

    setattr(widget, after_attr, widget.after(ms, fire))


def cancel_debounced_configure(
    widget: tk.Misc, *, after_attr: str = "_debounce_configure_after",
) -> None:
    after_id = getattr(widget, after_attr, None)
    if after_id is not None:
        try:
            widget.after_cancel(after_id)
        except tk.TclError:
            pass
        setattr(widget, after_attr, None)


def bind_debounced_configure(
    widget: tk.Misc,
    callback,
    *,
    ms: int = CONFIGURE_DEBOUNCE_MS,
    filter_same_size: bool = True,
) -> None:
    """Bind ``callback`` to ``<Configure>``, coalesced to one call per burst."""
    size_attr = "_debounce_last_configure_size"

    def on_configure(event) -> None:
        if filter_same_size:
            size = (event.width, event.height)
            if size == getattr(widget, size_attr, None):
                return
            setattr(widget, size_attr, size)
        schedule_debounced_configure(widget, callback, ms=ms)

    widget.bind("<Configure>", on_configure)


def configure_gutter_grid(
    frame,
    *,
    scale: float = 1.0,
    gap_units: float = 0.5,
) -> dict[str, int]:
    """Five-column grid: left | gap | center (expand) | gap | right.

    Gap columns reserve ``space(gap_units, scale)`` via ``minsize`` so
    inter-column padding scales with the UI and does not rely on widget padx.
    """
    gap_px = space(gap_units, scale)
    left, gap_l, center, gap_r, right = 0, 1, 2, 3, 4
    frame.columnconfigure(left, weight=0)
    frame.columnconfigure(gap_l, weight=0, minsize=gap_px)
    frame.columnconfigure(center, weight=1)
    frame.columnconfigure(gap_r, weight=0, minsize=gap_px)
    frame.columnconfigure(right, weight=0)
    return {
        "left": left,
        "gap_l": gap_l,
        "center": center,
        "gap_r": gap_r,
        "right": right,
        "gap_px": gap_px,
    }


def set_grid_column_gaps(
    frame,
    gap_units: float,
    *,
    scale: float = 1.0,
    gap_columns: tuple[int, int] = (1, 3),
) -> int:
    """Refresh fixed-width gap columns after a UI scale change."""
    gap_px = space(gap_units, scale)
    for col in gap_columns:
        frame.columnconfigure(col, weight=0, minsize=gap_px)
    return gap_px


def control_metrics(scale: float = 1.0) -> dict[str, int]:
    """Shared heights and widths for form controls."""
    return {
        "path_ipady": space(2, scale),
        "combobox_min_chars": 28,
        "combobox_max_chars": 48,
        "dropzone_min_h": space(16, scale),
    }


def fit_combobox(
    combo: ttk.Combobox,
    values: tuple[str, ...] | list[str],
    *,
    scale: float = 1.0,
    min_chars: int | None = None,
    max_chars: int | None = None,
) -> None:
    """Size a readonly combobox to its longest option (character width, clamped)."""
    m = control_metrics(scale)
    lo = min_chars if min_chars is not None else m["combobox_min_chars"]
    hi = max_chars if max_chars is not None else m["combobox_max_chars"]
    current = combo.get().strip()
    candidates = list(values) + ([current] if current else [])
    longest = max((len(str(v)) for v in candidates), default=lo)
    combo.configure(width=max(lo, min(longest + 1, hi)))


def enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            from ctypes import windll

            windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def window_content_scale(width: int, height: int) -> float:
    """Gentle font scale — shrinks on compact windows, bumps slightly on large ones."""
    if width <= 1 or height <= 1:
        return 1.0
    ratio = min(width / _REF_WIDTH, height / _REF_HEIGHT)
    if ratio >= 1.0:
        boost = min(_MAX_FONT_SCALE - 1.0, (ratio - 1.0) * 0.22)
        return 1.0 + boost
    # Shrink the whole UI proportionally as the window gets smaller so all
    # content keeps fitting instead of clipping or needing a scrollbar.
    # ``ratio`` reaches the floor scale a little before the hard minsize so
    # the smallest windows are still fully usable.
    floor_ratio = 0.5  # ~512x384 worth of window hits the smallest scale
    t = max(0.0, min(1.0, (ratio - floor_ratio) / (1.0 - floor_ratio)))
    return _MIN_FONT_SCALE + (1.0 - _MIN_FONT_SCALE) * t


def ui_scale(root: tk.Misc) -> float:
    try:
        root.update_idletasks()
        return window_content_scale(root.winfo_width(), root.winfo_height())
    except tk.TclError:
        return 1.0


def scaled_font(family: str, size: int, scale: float, *, weight: str = "normal") -> tuple:
    pt = max(10, int(round(size * scale)))
    if weight == "bold":
        return (family, pt, "bold")
    return (family, pt)


def typeface(role: str, scale: float, *, weight: str = "normal") -> tuple:
    if role == "mono":
        return scaled_font("Cascadia Mono", _TYPE["mono"], scale, weight=weight)
    return scaled_font("Segoe UI", _TYPE[role], scale, weight=weight)


def track_font(widget: tk.Misc, role: str, colors: dict[str, str], *, weight: str = "normal") -> None:
    colors.setdefault("_font_registry", []).append((widget, role, weight))


def refresh_font_registry(colors: dict[str, str], scale: float) -> None:
    for widget, role, weight in colors.get("_font_registry", []):
        try:
            widget.configure(font=typeface(role, scale, weight=weight))
        except tk.TclError:
            pass


_THEMES: dict[str, dict[str, str]] = {
    # Layered dark surfaces — bg < surface < card, subtle border.
    "dark": {
        "bg": "#12121a",
        "surface": "#1a1a24",
        "card": "#222230",
        "card_hover": "#2a2a3a",
        "text": "#ececf4",
        "muted": "#9494a8",
        "accent": "#6d5ce8",
        "accent_hover": "#7f70f0",
        "accent_soft": "#2e2a42",
        "glow": "#a99cf5",
        "border": "#32324a",
        "border_subtle": "#282836",
        "log_bg": "#16161f",
        "log_fg": "#d8d8e4",
        "hero_bg": "#16161f",
        "hero_kicker": "#8b7cf0",
        "hero_title": "#f4f4f8",
        "hero_subtitle": "#a8a8b8",
        "header_bg": "#1a1a24",
        "header_border": "#32324a",
        "header_text": "#f0f0f6",
        "tab_idle": "#1a1a24",
        "tab_active": "#222230",
        "tab_border": "#6d5ce8",
        "field_label": "#b0b0c0",
        "browse_bg": "#2a2a3a",
        "browse_hover": "#363648",
        "browse_fg": "#ececf4",
        "success": "#6d5ce8",
        "ok": "#3fb27f",
        "danger": "#e5484d",
        "on_accent": "#ffffff",
        "glow_alt": "#c084fc",
        "footer_bg": "#0a0a0f",
        "footer_purple_dark": "#2a1f4a",
        "footer_danger_bg": "#1a0a10",
        "footer_danger": "#b83248",
        "footer_danger_dark": "#5a1830",
        "toast_shadow": "#050508",
        "timeline_played": "#4a42a0",
        "timeline_track": "#3a3f5a",
    },
}

DEFAULT_THEME = "dark"


def available_themes() -> tuple[str, ...]:
    return tuple(_THEMES)


def _palette(theme: str = DEFAULT_THEME) -> dict[str, str]:
    return dict(_THEMES.get(theme, _THEMES[DEFAULT_THEME]))


def apply_theme(root: tk.Tk, *, scale: float = 1.0, theme: str = DEFAULT_THEME) -> dict[str, str]:
    colors = _palette(theme)
    colors["_theme"] = theme if theme in _THEMES else DEFAULT_THEME
    colors["_font_registry"] = []

    root.configure(bg=colors["bg"])
    root.option_add("*Font", typeface("body", scale))

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    _apply_style_fonts(style, colors, scale)
    _configure_combobox_style(style, colors, scale)
    _configure_scrollbar_style(style, colors)
    _apply_global_widget_colors(root, colors)

    colors["_scale"] = str(scale)
    colors["_style"] = style
    return colors


def refresh_theme_scale(root: tk.Tk, colors: dict[str, str], scale: float) -> dict[str, str]:
    colors["_scale"] = str(scale)
    root.option_add("*Font", typeface("body", scale))
    style = colors.get("_style") or ttk.Style(root)
    colors["_style"] = style
    _apply_style_fonts(style, colors, scale)
    _configure_combobox_style(style, colors, scale)
    _configure_scrollbar_style(style, colors)
    refresh_font_registry(colors, scale)
    refresh_canvas_buttons(colors, scale)
    for log_widget in colors.get("_log_widgets", []):
        configure_log_widget(log_widget, colors)
    return colors


def refresh_canvas_buttons(colors: dict[str, str], scale: float) -> None:
    """Rescale and repaint every live CanvasButton; prune destroyed ones."""
    alive = []
    for btn in colors.get("_canvas_buttons", []):
        try:
            if btn.winfo_exists():
                btn.rescale(scale)
                alive.append(btn)
        except tk.TclError:
            pass
    colors["_canvas_buttons"] = alive


def _apply_style_fonts(style: ttk.Style, colors: dict[str, str], scale: float) -> None:
    s = scale
    style.configure(".", background=colors["bg"], foreground=colors["text"], font=typeface("body", s))
    style.configure("TFrame", background=colors["bg"])
    style.configure("Card.TFrame", background=colors["card"])
    style.configure("Surface.TFrame", background=colors["surface"])

    style.configure("TLabel", background=colors["bg"], foreground=colors["text"], font=typeface("body", s))
    style.configure("Card.TLabel", background=colors["card"], foreground=colors["text"], font=typeface("body", s))
    style.configure(
        "FormLabel.TLabel",
        background=colors["bg"],
        foreground=colors["field_label"],
        font=typeface("label", s),
    )
    style.configure(
        "CardFormLabel.TLabel",
        background=colors["card"],
        foreground=colors["field_label"],
        font=typeface("label", s),
    )
    style.configure("Muted.TLabel", background=colors["bg"], foreground=colors["muted"], font=typeface("caption", s))
    style.configure(
        "CardMuted.TLabel", background=colors["card"], foreground=colors["muted"], font=typeface("caption", s),
    )
    style.configure(
        "PlayerTime.TLabel",
        background=colors["card"],
        foreground=colors["muted"],
        font=typeface("mono", s),
    )
    style.configure(
        "Heading.TLabel",
        background=colors["bg"],
        foreground=colors["header_text"],
        font=typeface("title", s, weight="bold"),
    )
    style.configure(
        "SectionHeading.TLabel",
        background=colors["bg"],
        foreground=colors["hero_title"],
        font=typeface("display", s, weight="bold"),
    )
    style.configure(
        "SubsectionHeading.TLabel",
        background=colors["bg"],
        foreground=colors["hero_kicker"],
        font=typeface("title", s, weight="bold"),
    )
    style.configure(
        "CardSectionHeading.TLabel",
        background=colors["card"],
        foreground=colors["hero_title"],
        font=typeface("display", s, weight="bold"),
    )
    style.configure(
        "CardSubsectionHeading.TLabel",
        background=colors["card"],
        foreground=colors["hero_kicker"],
        font=typeface("title", s, weight="bold"),
    )
    style.configure(
        "CardHeading.TLabel",
        background=colors["card"],
        foreground=colors["header_text"],
        font=typeface("title", s, weight="bold"),
    )
    style.configure(
        "PlayerChapterTitle.TLabel",
        background=colors["card"],
        foreground=colors["header_text"],
        font=typeface("display", s, weight="bold"),
    )
    style.configure(
        "PlayerFileTitle.TLabel",
        background=colors["bg"],
        foreground=colors["text"],
        font=typeface("title", s, weight="bold"),
    )

    style.configure("TNotebook", background=colors["bg"], borderwidth=0, tabmargins=(0, 0, 0, 0))
    style.configure(
        "TNotebook.Tab",
        background=colors["tab_idle"],
        foreground=colors["muted"],
        padding=(space(4, s), space(2, s)),
        font=typeface("label", s),
        borderwidth=0,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", colors["tab_active"]), ("active", colors["tab_idle"])],
        foreground=[("selected", colors["text"]), ("active", colors["muted"])],
    )

    style.configure(
        "TEntry",
        fieldbackground=colors["surface"],
        foreground=colors["text"],
        insertcolor=colors["text"],
        bordercolor=colors["border"],
        lightcolor=colors["border"],
        darkcolor=colors["border"],
        padding=(space(3, s), space(2, s)),
        font=typeface("body", s),
    )
    style.map(
        "TEntry",
        fieldbackground=[("readonly", colors["surface"]), ("disabled", colors["card"])],
        foreground=[("readonly", colors["text"]), ("disabled", colors["muted"])],
    )

    indicator = max(18, int(20 * s))
    style.configure(
        "Card.TCheckbutton",
        background=colors["card"],
        foreground=colors["text"],
        focuscolor=colors["card"],
        indicatorcolor=colors["surface"],
        indicatorrelief="flat",
        indicatorsize=indicator,
        padding=(space(1, s), space(2, s)),
        font=typeface("body", s),
    )
    style.map(
        "Card.TCheckbutton",
        background=[("active", colors["card"]), ("focus", colors["card"])],
        foreground=[("active", colors["text"]), ("focus", colors["text"])],
        indicatorcolor=[("selected", colors["accent"]), ("!selected", colors["border"])],
    )
    style.configure(
        "Surface.TCheckbutton",
        background=colors["bg"],
        foreground=colors["text"],
        focuscolor=colors["bg"],
        indicatorcolor=colors["surface"],
        indicatorsize=indicator,
        padding=(space(1, s), space(2, s)),
        font=typeface("body", s),
    )
    style.map(
        "Surface.TCheckbutton",
        background=[("active", colors["bg"]), ("focus", colors["bg"])],
        indicatorcolor=[("selected", colors["accent"]), ("!selected", colors["border"])],
    )

    style.configure(
        "StepDone.TLabel",
        background=colors["header_bg"],
        foreground=colors["accent"],
        font=typeface("step", s, weight="bold"),
    )
    style.configure(
        "StepIdle.TLabel",
        background=colors["header_bg"],
        foreground=colors["muted"],
        font=typeface("step", s),
    )
    style.configure(
        "Accent.Horizontal.TProgressbar",
        troughcolor=colors["surface"],
        background=colors["accent"],
        bordercolor=colors["border"],
        lightcolor=colors["accent_hover"],
        darkcolor=colors["accent"],
        thickness=space(1, s),
    )
    style.configure(
        "Success.Horizontal.TProgressbar",
        troughcolor=colors["surface"],
        background=colors["ok"],
        bordercolor=colors["border"],
        lightcolor=colors["ok"],
        darkcolor=colors["ok"],
        thickness=space(1, s),
    )
    style.configure(
        "Danger.Horizontal.TProgressbar",
        troughcolor=colors["surface"],
        background=colors["danger"],
        bordercolor=colors["border"],
        lightcolor=colors["danger"],
        darkcolor=colors["danger"],
        thickness=space(1, s),
    )


def _configure_combobox_style(style: ttk.Style, colors: dict[str, str], scale: float = 1.0) -> None:
    try:
        style.layout("Dark.TCombobox", style.layout("TCombobox"))
    except tk.TclError:
        pass

    combo_opts = {
        "fieldbackground": colors["surface"],
        "background": colors["browse_bg"],
        "foreground": colors["text"],
        "arrowcolor": colors["muted"],
        "bordercolor": colors["border"],
        "lightcolor": colors["border"],
        "darkcolor": colors["border"],
        "selectbackground": colors["accent"],
        "selectforeground": colors.get("on_accent", "#ffffff"),
        "padding": (space(4, scale), space(3, scale)),
        "font": typeface("body", scale),
    }
    combo_map = {
        "fieldbackground": [("readonly", colors["surface"]), ("disabled", colors["card"])],
        "foreground": [("readonly", colors["text"]), ("disabled", colors["muted"])],
        "background": [("active", colors["browse_hover"]), ("!disabled", colors["browse_bg"])],
        "arrowcolor": [("disabled", colors["muted"]), ("!disabled", colors["muted"])],
    }
    for name in ("TCombobox", "Dark.TCombobox"):
        style.configure(name, **combo_opts)
        style.map(name, **combo_map)


def _configure_scrollbar_style(style: ttk.Style, colors: dict[str, str]) -> None:
    for name in ("TScrollbar", "Vertical.TScrollbar"):
        style.configure(
            name,
            background=colors["browse_bg"],
            troughcolor=colors["bg"],
            bordercolor=colors["border_subtle"],
            arrowcolor=colors["muted"],
            darkcolor=colors["border_subtle"],
            lightcolor=colors["border_subtle"],
        )
    style.map(
        "TScrollbar",
        background=[("active", colors["browse_hover"]), ("!disabled", colors["browse_bg"])],
    )


def _apply_global_widget_colors(root: tk.Misc, colors: dict[str, str]) -> None:
    opts = {
        "*Listbox.Background": colors["surface"],
        "*Listbox.Foreground": colors["text"],
        "*Listbox.selectBackground": colors["accent"],
        "*Listbox.selectForeground": colors.get("on_accent", "#ffffff"),
        "*Scrollbar.Background": colors["browse_bg"],
        "*Scrollbar.TroughColor": colors["bg"],
        "*Scrollbar.ActiveBackground": colors["browse_hover"],
    }
    for pattern, value in opts.items():
        root.option_add(pattern, value)


def configure_dark_combobox(combo: ttk.Combobox, colors: dict[str, str]) -> None:
    surface = colors["surface"]
    text = colors["text"]
    accent = colors["accent"]

    def style_popup() -> None:
        try:
            popdown = combo.tk.call("ttk::combobox::PopdownWindow", combo)
            if not popdown:
                return
            listbox = combo.nametowidget(f"{popdown}.f.l")
            scale = float(colors.get("_scale", "1"))
            listbox.configure(
                background=surface,
                foreground=text,
                selectbackground=accent,
                selectforeground=colors.get("on_accent", "#ffffff"),
                highlightthickness=0,
                activestyle="none",
                font=typeface("body", scale),
            )
        except (tk.TclError, KeyError):
            pass

    existing = combo.cget("postcommand")
    if existing and str(existing).strip():
        def chained() -> None:
            if callable(existing):
                existing()
            else:
                combo.tk.call(existing)
            style_popup()

        combo.configure(postcommand=chained)
    else:
        combo.configure(postcommand=style_popup)

    combo.bind("<Button-1>", lambda _e: combo.after(1, style_popup), add="+")
    combo.bind("<Down>", lambda _e: combo.after(1, style_popup), add="+")


def position_floating_tooltip(
    tip: tk.Toplevel,
    anchor: tk.Misc,
    x_root: int,
    y_root: int,
    *,
    offset_x: int = 12,
    offset_y: int = 18,
    prefer_above: bool = False,
) -> None:
    """Place a borderless tooltip on the same monitor as the anchor window."""
    tip.update_idletasks()
    try:
        tw = tip.winfo_reqwidth()
        th = tip.winfo_reqheight()
        root = anchor.winfo_toplevel()
        rx = root.winfo_rootx()
        ry = root.winfo_rooty()
        rw = max(root.winfo_width(), 1)
        rh = max(root.winfo_height(), 1)

        x = x_root + offset_x
        y = y_root - th - abs(offset_y) if prefer_above else y_root + offset_y

        if x + tw > rx + rw - 8:
            x = x_root - tw - offset_x
        if y + th > ry + rh - 8:
            y = y_root - th - abs(offset_y)
        if y < ry + 8:
            y = y_root + abs(offset_y)

        x = max(rx + 8, min(x, rx + rw - tw - 8))
        y = max(ry + 8, min(y, ry + rh - th - 8))
        tip.geometry(f"+{x}+{y}")
    except tk.TclError:
        tip.geometry(f"+{x_root + offset_x}+{y_root + offset_y}")


def attach_tooltip(widget: tk.Misc, text: str, colors: dict[str, str], *, delay_ms: int = 450) -> None:
    """Floating dark chip tooltip near the cursor on hover."""
    state: dict[str, object] = {"after": None, "tip": None}

    def hide(_event=None) -> None:
        after_id = state["after"]
        if after_id is not None:
            try:
                widget.after_cancel(after_id)
            except tk.TclError:
                pass
            state["after"] = None
        tip = state["tip"]
        if tip is not None:
            try:
                tip.destroy()
            except tk.TclError:
                pass
            state["tip"] = None

    def show(event) -> None:
        hide()
        try:
            scale = float(colors.get("_scale", "1"))
            tip = tk.Toplevel(widget)
            tip.wm_overrideredirect(True)
            try:
                tip.attributes("-topmost", True)
            except tk.TclError:
                pass
            tip.configure(bg=colors["border"])
            inner = tk.Frame(tip, bg=colors["surface"], padx=space(2, scale), pady=space(1, scale))
            inner.pack(padx=1, pady=1)
            tk.Label(
                inner, text=text, bg=colors["surface"], fg=colors["text"],
                font=typeface("caption", scale),
            ).pack()
            position_floating_tooltip(tip, widget, event.x_root, event.y_root)
            state["tip"] = tip
        except tk.TclError:
            pass

    def schedule(event) -> None:
        hide()
        state["after"] = widget.after(delay_ms, lambda e=event: show(e))

    widget.bind("<Enter>", schedule, add="+")
    widget.bind("<Leave>", hide, add="+")
    widget.bind("<Button>", hide, add="+")
    widget.bind("<Destroy>", hide, add="+")


def corner_radius(scale: float = 1.0) -> int:
    return max(8, int(10 * scale))


def draw_round_rect(
    canvas: tk.Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    radius: int,
    *,
    fill: str = "",
    outline: str = "",
    width: int = 1,
    tags: str = "",
) -> None:
    """Filled/stroked rounded rectangle on a canvas."""
    r = min(radius, int((x2 - x1) / 2), int((y2 - y1) / 2))
    if r <= 0:
        canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline=outline, width=width, tags=tags)
        return
    kw = {"fill": fill, "outline": outline, "width": width, "tags": tags}
    canvas.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90, style="pieslice", **kw)
    canvas.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90, style="pieslice", **kw)
    canvas.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90, style="pieslice", **kw)
    canvas.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90, style="pieslice", **kw)
    canvas.create_rectangle(x1 + r, y1, x2 - r, y2, **kw)
    canvas.create_rectangle(x1, y1 + r, x2, y2 - r, **kw)


def draw_round_rect_top(
    canvas: tk.Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    radius: int,
    *,
    fill: str = "",
    outline: str = "",
    tags: str = "",
) -> None:
    """Rounded top corners, square bottom — for bottom docked bars."""
    r = min(radius, int((x2 - x1) / 2), int((y2 - y1) / 2))
    if r <= 0:
        canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline=outline, tags=tags)
        return
    kw = {"fill": fill, "outline": outline, "tags": tags}
    canvas.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90, style="pieslice", **kw)
    canvas.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90, style="pieslice", **kw)
    canvas.create_rectangle(x1 + r, y1, x2 - r, y1 + r, **kw)
    canvas.create_rectangle(x1, y1 + r, x2, y2, **kw)


def _paint_round_card(
    canvas: tk.Canvas,
    win: int,
    inner: tk.Misc,
    *,
    width: int,
    height: int,
    radius: int,
    page_bg: str,
    card_fill: str,
    border: str,
) -> None:
    if width < 4 or height < 4:
        return
    canvas.configure(bg=page_bg)
    canvas.delete("card_bg")
    draw_round_rect(canvas, 0, 0, width, height, radius, fill=border, tags="card_bg")
    draw_round_rect(canvas, 1, 1, width - 1, height - 1, max(1, radius - 1), fill=card_fill, tags="card_bg")
    canvas.tag_lower("card_bg")
    inset = radius + 1
    inner_w = max(width - 2 * inset, 1)
    inner_h = max(height - 2 * inset, 1)
    canvas.coords(win, inset, inset)
    canvas.itemconfigure(win, width=inner_w, height=inner_h)


def make_card(parent: tk.Misc, colors: dict[str, str], *, padding: int | None = None) -> tk.Frame:
    """Raised surface with rounded corners."""
    return _make_round_surface(
        parent, colors, padding=padding, fill=colors["card"], page_bg=colors["bg"],
    )


def make_round_surface(
    parent: tk.Misc,
    colors: dict[str, str],
    *,
    padding: int | None = None,
    fill: str | None = None,
    page_bg: str | None = None,
    border: str | None = None,
    fixed_height: int | None = None,
) -> tk.Frame:
    """Rounded panel shell (tab outlines, toasts, etc.)."""
    return _make_round_surface(
        parent,
        colors,
        padding=padding,
        fill=fill or colors["bg"],
        page_bg=page_bg or colors["bg"],
        border=border or colors["border"],
        fixed_height=fixed_height,
    )


def _make_round_surface(
    parent: tk.Misc,
    colors: dict[str, str],
    *,
    padding: int | None,
    fill: str,
    page_bg: str,
    border: str | None = None,
    fixed_height: int | None = None,
) -> tk.Frame:
    scale = float(colors.get("_scale", "1"))
    pad = padding if padding is not None else space(4, scale)
    r = corner_radius(scale)
    border = border or colors["border_subtle"]

    outer = tk.Frame(parent, bg=page_bg)
    canvas = tk.Canvas(outer, bg=page_bg, highlightthickness=0, bd=0)
    canvas.pack(fill=tk.BOTH, expand=True)
    if fixed_height is not None:
        canvas.configure(height=fixed_height)

    inner = tk.Frame(canvas, bg=fill)
    inner._card_pad = pad  # type: ignore[attr-defined]
    win = canvas.create_window(0, 0, window=inner, anchor="nw")
    state = {"w": 0, "h": 0}

    def _paint(w: int, h: int) -> None:
        locked = getattr(outer, "_fixed_height", None)
        if locked is not None:
            h = locked
        if w < 4 or h < 4:
            return
        if w == state["w"] and h == state["h"]:
            return
        state["w"], state["h"] = w, h
        _paint_round_card(canvas, win, inner, width=w, height=h, radius=r, page_bg=page_bg, card_fill=fill, border=border)

    def _on_canvas_configure(_event=None) -> None:
        def repaint() -> None:
            if not canvas.winfo_exists():
                return
            locked = getattr(outer, "_fixed_height", None)
            w = max(canvas.winfo_width(), 1)
            h = locked if locked is not None else max(canvas.winfo_height(), 1)
            if w <= 1 or h <= 1:
                return
            _paint(w, h)

        schedule_debounced_configure(canvas, repaint)

    def _on_inner_configure(_event=None) -> None:
        if getattr(outer, "_fixed_height", None) is not None:
            return

        def resize_to_content() -> None:
            if not canvas.winfo_exists():
                return
            inner.update_idletasks()
            min_h = inner.winfo_reqheight() + 2 * (r + 1)
            cur_h = max(canvas.winfo_height(), 1)
            if min_h > cur_h:
                canvas.configure(height=min_h)
                w = max(canvas.winfo_width(), 1)
                _paint(w, min_h)

        schedule_debounced_configure(inner, resize_to_content)

    canvas.bind("<Configure>", _on_canvas_configure)
    if fixed_height is None:
        inner.bind("<Configure>", _on_inner_configure, add="+")
    outer._card_inner = inner  # type: ignore[attr-defined]
    outer._card_canvas = canvas  # type: ignore[attr-defined]
    outer._fixed_height = fixed_height  # type: ignore[attr-defined]
    return outer


def fit_round_surface_to_content(shell: tk.Frame, *, scale: float = 1.0) -> int:
    """Resize a round-surface canvas to hug its inner frame (grow or shrink)."""
    canvas = shell._card_canvas  # type: ignore[attr-defined]
    inner = shell._card_inner  # type: ignore[attr-defined]
    inner.update_idletasks()
    r = corner_radius(scale)
    min_h = max(inner.winfo_reqheight() + 2 * (r + 1), 4)
    try:
        canvas.configure(height=min_h)
        w = max(canvas.winfo_width(), 1)
        if w >= 4 and min_h >= 4:
            canvas.event_generate("<Configure>")
    except tk.TclError:
        pass
    return min_h


def set_round_surface_height(shell: tk.Frame, height: int) -> None:
    """Update a round surface created with fixed-height locking."""
    shell._fixed_height = max(height, 1)  # type: ignore[attr-defined]
    canvas = shell._card_canvas  # type: ignore[attr-defined]
    try:
        canvas.configure(height=shell._fixed_height)  # type: ignore[attr-defined]
        w = max(canvas.winfo_width(), 1)
        h = shell._fixed_height  # type: ignore[attr-defined]
        if w >= 4 and h >= 4:
            canvas.event_generate("<Configure>")
    except tk.TclError:
        pass


def button_corner_radius(scale: float = 1.0) -> int:
    return max(6, int(8 * scale))


def _widget_bg(widget: tk.Misc) -> str:
    try:
        bg = widget.cget("bg")
        if bg:
            return bg
    except tk.TclError:
        pass
    return "#1a1a24"


class CanvasButton(tk.Frame):
    """Rounded push button — tk.Button corners are square on Windows."""

    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        command,
        *,
        colors: dict[str, str],
        variant: str = "secondary",
        font_role: str = "label",
        font_weight: str | None = None,
        pad_x: int | None = None,
        pad_y: int | None = None,
    ) -> None:
        super().__init__(parent, bg=_widget_bg(parent))
        self._colors = colors
        self._command = command
        self._text = text
        self._variant = variant
        self._font_role = font_role
        self._font_weight = font_weight
        self._scale = float(colors.get("_scale", "1"))
        self._pad_x = pad_x if pad_x is not None else space(4, self._scale)
        self._pad_y = pad_y if pad_y is not None else space(2, self._scale)
        # Unscaled padding so the button can re-derive its size when the UI
        # scale changes (see rescale / refresh_theme_scale).
        self._pad_x_base = self._pad_x / max(self._scale, 0.01)
        self._pad_y_base = self._pad_y / max(self._scale, 0.01)
        self._state = tk.NORMAL
        self._hover = False
        self._canvas = tk.Canvas(self, highlightthickness=0, bd=0, cursor="hand2")
        self._canvas.pack()
        self._canvas.bind("<Button-1>", self._on_click)
        self._canvas.bind("<Enter>", self._on_enter)
        self._canvas.bind("<Leave>", self._on_leave)
        colors.setdefault("_canvas_buttons", []).append(self)
        self.after_idle(self._redraw)

    def rescale(self, scale: float) -> None:
        """Recompute size/padding for a new UI scale and redraw."""
        self._scale = scale
        self._pad_x = max(1, int(round(self._pad_x_base * scale)))
        self._pad_y = max(1, int(round(self._pad_y_base * scale)))
        self._redraw()

    def _font(self) -> tkfont.Font:
        weight = self._font_weight or "normal"
        return tkfont.Font(font=typeface(self._font_role, self._scale, weight=weight))

    def _palette(self) -> tuple[str, str, str]:
        c = self._colors
        disabled = self._state == tk.DISABLED
        if self._variant == "accent":
            if disabled:
                return c["border_subtle"], c["muted"], c["border_subtle"]
            bg = c["accent_hover"] if self._hover else c["accent"]
            return bg, c.get("on_accent", "#ffffff"), bg
        if self._variant == "browse":
            if disabled:
                return c["surface"], c["muted"], c["border"]
            bg = c["browse_hover"] if self._hover else c["browse_bg"]
            return bg, c["browse_fg"] if not self._hover else c["text"], c["border"]
        if self._variant == "ghost":
            if disabled:
                return _widget_bg(self), c["muted"], _widget_bg(self)
            bg = c["surface"] if self._hover else c["bg"]
            fg = c["text"] if self._hover else c["muted"]
            return bg, fg, bg
        if self._variant == "compact":
            if disabled:
                return c["surface"], c["muted"], c["border"]
            bg = c["card_hover"] if self._hover else c["surface"]
            border = c["accent"] if self._hover and not disabled else c["border"]
            return bg, c["hero_kicker"], border
        if self._variant == "player":
            if disabled:
                return c["card"], c["muted"], c["border_subtle"]
            bg = c["card_hover"] if self._hover else c["card"]
            fg = c["accent"] if self._hover else c["text"]
            return bg, fg, c["border_subtle"]
        if self._variant == "icon":
            if disabled:
                return _widget_bg(self), c["muted"], _widget_bg(self)
            bg = c["surface"] if self._hover else _widget_bg(self)
            return bg, c["text"] if self._hover else c["muted"], c["border_subtle"]
        # secondary
        if disabled:
            return c["surface"], c["muted"], c["border"]
        bg = c["card_hover"] if self._hover else c["surface"]
        border = c["accent"] if self._hover else c["border"]
        return bg, c["text"], border

    def _redraw(self) -> None:
        try:
            font = self._font()
            tw = font.measure(self._text)
            th = font.metrics("linespace")
            w = max(tw + 2 * self._pad_x, 8)
            h = max(th + 2 * self._pad_y, 8)
            self._canvas.configure(width=w, height=h, bg=_widget_bg(self))
            self._canvas.delete("all")
            fill, fg, outline = self._palette()
            r = button_corner_radius(self._scale)
            draw_round_rect(self._canvas, 1, 1, w - 1, h - 1, r, fill=fill, outline=outline, width=1)
            self._canvas.create_text(w / 2, h / 2, text=self._text, fill=fg, font=font)
            cursor = "arrow" if self._state == tk.DISABLED else "hand2"
            self._canvas.configure(cursor=cursor)
        except tk.TclError:
            pass

    def _on_click(self, _event=None) -> None:
        if self._state != tk.DISABLED and self._command:
            self._command()

    def _on_enter(self, _event=None) -> None:
        if self._state != tk.DISABLED:
            self._hover = True
            self._redraw()

    def _on_leave(self, _event=None) -> None:
        self._hover = False
        self._redraw()

    def configure(self, cnf=None, **kw) -> None:
        if cnf:
            kw = {**cnf, **kw}
        if "text" in kw:
            self._text = kw.pop("text")
        if "state" in kw:
            self._state = kw.pop("state")
            if self._state == tk.DISABLED:
                self._hover = False
        if "bg" in kw:
            super().configure(bg=kw.pop("bg"))
        kw.pop("fg", None)
        kw.pop("padx", None)
        kw.pop("pady", None)
        kw.pop("highlightbackground", None)
        if kw:
            super().configure(**kw)
        self._redraw()

    config = configure

    def cget(self, key: str):
        if key == "state":
            return self._state
        if key == "text":
            return self._text
        return super().cget(key)

    def __getitem__(self, key: str):
        return self.cget(key)

    def __setitem__(self, key: str, value) -> None:
        self.configure(**{key: value})

    def bind(self, sequence=None, func=None, add=None):
        return self._canvas.bind(sequence, func, add)


def make_accent_button(parent: tk.Misc, text: str, command, colors: dict[str, str]) -> CanvasButton:
    scale = float(colors.get("_scale", "1"))
    return CanvasButton(
        parent, text, command, colors=colors, variant="accent",
        font_role="button", font_weight="bold",
        pad_x=space(5, scale), pad_y=space(2, scale),
    )


def make_path_entry(parent: tk.Misc, variable: tk.StringVar, colors: dict[str, str]) -> tk.Entry:
    scale = float(colors.get("_scale", "1"))
    entry = tk.Entry(
        parent,
        textvariable=variable,
        bg=colors["surface"],
        fg=colors["text"],
        insertbackground=colors["text"],
        relief=tk.FLAT,
        highlightthickness=1,
        highlightbackground=colors["border"],
        highlightcolor=colors["accent"],
        font=typeface("body", scale),
        insertwidth=1,
    )
    track_font(entry, "body", colors)
    return entry


def make_browse_button(parent: tk.Misc, text: str, command, colors: dict[str, str]) -> CanvasButton:
    scale = float(colors.get("_scale", "1"))
    return CanvasButton(
        parent, text, command, colors=colors, variant="browse",
        font_role="label", pad_x=space(3, scale), pad_y=space(2, scale),
    )


def make_secondary_button(parent: tk.Misc, text: str, command, colors: dict[str, str]) -> CanvasButton:
    scale = float(colors.get("_scale", "1"))
    return CanvasButton(
        parent, text, command, colors=colors, variant="secondary",
        font_role="label", pad_x=space(4, scale), pad_y=space(2, scale),
    )


def make_ghost_button(parent: tk.Misc, text: str, command, colors: dict[str, str]) -> CanvasButton:
    scale = float(colors.get("_scale", "1"))
    return CanvasButton(
        parent, text, command, colors=colors, variant="ghost",
        font_role="caption", pad_x=space(3, scale), pad_y=space(2, scale),
    )


def make_compact_dropdown(parent: tk.Misc, text: str, command, colors: dict[str, str]) -> CanvasButton:
    """Small agent-style dropdown trigger (label + ▾)."""
    scale = float(colors.get("_scale", "1"))
    return CanvasButton(
        parent, f"{text}  \u25be", command, colors=colors, variant="compact",
        font_role="caption", pad_x=space(3, scale), pad_y=space(2, scale),
    )


def configure_log_widget(widget: tk.Text, colors: dict[str, str]) -> None:
    scale = float(colors.get("_scale", "1"))
    widget.configure(
        bg=colors["log_bg"], fg=colors["log_fg"], insertbackground=colors["log_fg"],
        relief=tk.FLAT, bd=0,
        padx=space(4, scale), pady=space(3, scale),
        font=tkfont.Font(family="Cascadia Mono", size=max(11, int(round(_TYPE["mono"] * scale)))),
        selectbackground=colors["accent"],
        selectforeground="#ffffff",
        highlightthickness=1, highlightbackground=colors["border_subtle"],
    )
    for child in widget.children.values():
        try:
            child.configure(
                bg=colors["browse_bg"],
                troughcolor=colors["bg"],
                activebackground=colors["browse_hover"],
            )
        except tk.TclError:
            pass
    log_widgets = colors.setdefault("_log_widgets", [])
    if widget not in log_widgets:
        log_widgets.append(widget)


def set_window_icon(root: tk.Tk) -> None:
    from novelflow.paths import asset_path

    icon = asset_path("icon.ico")
    if not icon.is_file():
        return
    try:
        root.iconbitmap(default=str(icon))
    except tk.TclError:
        pass


def set_accent_button_state(btn: tk.Misc, colors: dict[str, str], *, enabled: bool) -> None:
    btn.configure(state=tk.NORMAL if enabled else tk.DISABLED)
