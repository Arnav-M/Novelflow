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


def space(units: int, scale: float = 1.0) -> int:
    return max(1, int(round(_SPACE.get(units, units * 8) * scale)))


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


def _palette() -> dict[str, str]:
    """Layered dark surfaces — bg < surface < card, subtle border."""
    return {
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
    }


def apply_theme(root: tk.Tk, *, scale: float = 1.0) -> dict[str, str]:
    colors = _palette()
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
    refresh_font_registry(colors, scale)
    log_widget = colors.get("_log_widget")
    if log_widget is not None:
        configure_log_widget(log_widget, colors)
    return colors


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
        "CardHeading.TLabel",
        background=colors["card"],
        foreground=colors["header_text"],
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
        "selectforeground": "#ffffff",
        "padding": (space(3, scale), space(2, scale)),
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
        "*Listbox.selectForeground": "#ffffff",
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
                selectforeground="#ffffff",
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


def make_card(parent: tk.Misc, colors: dict[str, str], *, padding: int | None = None) -> tk.Frame:
    """Raised surface with 1px border — standard card pattern."""
    scale = float(colors.get("_scale", "1"))
    pad = padding if padding is not None else space(4, scale)
    outer = tk.Frame(parent, bg=colors["border_subtle"])
    inner = tk.Frame(outer, bg=colors["card"])
    inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
    inner._card_pad = pad  # type: ignore[attr-defined]
    outer._card_inner = inner  # type: ignore[attr-defined]
    return outer


def make_accent_button(parent: tk.Misc, text: str, command, colors: dict[str, str]) -> tk.Button:
    scale = float(colors.get("_scale", "1"))
    btn = tk.Button(
        parent, text=text, command=command,
        bg=colors["accent"], fg="#ffffff",
        activebackground=colors["accent_hover"], activeforeground="#ffffff",
        relief=tk.FLAT, bd=0,
        padx=space(5, scale), pady=space(2, scale),
        cursor="hand2",
        font=typeface("button", scale, weight="bold"),
    )
    track_font(btn, "button", colors, weight="bold")

    def on_enter(_e) -> None:
        if str(btn["state"]) != tk.DISABLED:
            btn.configure(bg=colors["accent_hover"])

    def on_leave(_e) -> None:
        if str(btn["state"]) != tk.DISABLED:
            btn.configure(bg=colors["accent"])

    btn.bind("<Enter>", on_enter)
    btn.bind("<Leave>", on_leave)
    return btn


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
    )
    track_font(entry, "body", colors)
    return entry


def make_browse_button(parent: tk.Misc, text: str, command, colors: dict[str, str]) -> tk.Button:
    scale = float(colors.get("_scale", "1"))
    btn = tk.Button(
        parent, text=text, command=command,
        bg=colors["browse_bg"], fg=colors["browse_fg"],
        activebackground=colors["browse_hover"], activeforeground=colors["text"],
        relief=tk.FLAT, bd=0,
        padx=space(3, scale), pady=space(2, scale),
        highlightthickness=0,
        cursor="hand2", font=typeface("label", scale),
    )
    track_font(btn, "label", colors)

    def on_enter(_e) -> None:
        btn.configure(bg=colors["browse_hover"])

    def on_leave(_e) -> None:
        btn.configure(bg=colors["browse_bg"])

    btn.bind("<Enter>", on_enter)
    btn.bind("<Leave>", on_leave)
    return btn


def make_secondary_button(parent: tk.Misc, text: str, command, colors: dict[str, str]) -> tk.Button:
    scale = float(colors.get("_scale", "1"))
    btn = tk.Button(
        parent, text=text, command=command,
        bg=colors["surface"], fg=colors["text"],
        activebackground=colors["card_hover"], activeforeground=colors["text"],
        relief=tk.FLAT, bd=0,
        padx=space(4, scale), pady=space(2, scale),
        highlightthickness=1,
        highlightbackground=colors["border"],
        highlightcolor=colors["border"],
        cursor="hand2", font=typeface("label", scale),
    )
    track_font(btn, "label", colors)

    def on_enter(_e) -> None:
        if str(btn["state"]) != tk.DISABLED:
            btn.configure(bg=colors["card_hover"], highlightbackground=colors["accent"])

    def on_leave(_e) -> None:
        if str(btn["state"]) != tk.DISABLED:
            btn.configure(bg=colors["surface"], highlightbackground=colors["border"])

    btn.bind("<Enter>", on_enter)
    btn.bind("<Leave>", on_leave)
    return btn


def make_ghost_button(parent: tk.Misc, text: str, command, colors: dict[str, str]) -> tk.Button:
    scale = float(colors.get("_scale", "1"))
    btn = tk.Button(
        parent, text=text, command=command,
        bg=colors["bg"], fg=colors["muted"],
        activebackground=colors["surface"], activeforeground=colors["text"],
        relief=tk.FLAT, bd=0,
        padx=space(3, scale), pady=space(2, scale),
        cursor="hand2", font=typeface("caption", scale),
    )
    track_font(btn, "caption", colors)

    def on_enter(_e) -> None:
        if str(btn["state"]) != tk.DISABLED:
            btn.configure(bg=colors["surface"], fg=colors["text"])

    def on_leave(_e) -> None:
        if str(btn["state"]) != tk.DISABLED:
            btn.configure(bg=colors["bg"], fg=colors["muted"])

    btn.bind("<Enter>", on_enter)
    btn.bind("<Leave>", on_leave)
    return btn


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
    colors["_log_widget"] = widget


def set_window_icon(root: tk.Tk) -> None:
    from novelflow.paths import asset_path

    icon = asset_path("icon.ico")
    if not icon.is_file():
        return
    try:
        root.iconbitmap(default=str(icon))
    except tk.TclError:
        pass


def set_accent_button_state(btn: tk.Button, colors: dict[str, str], *, enabled: bool) -> None:
    if enabled:
        btn.configure(state=tk.NORMAL, bg=colors["accent"], fg="#ffffff")
    else:
        btn.configure(state=tk.DISABLED, bg=colors["border_subtle"], fg=colors["muted"])
