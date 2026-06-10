"""Premium dark theme for Novelflow."""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk


def apply_theme(root: tk.Tk) -> dict[str, str]:
    colors = {
        "bg": "#12101a",
        "surface": "#1c1828",
        "card": "#242033",
        "text": "#f5f3ff",
        "muted": "#9b93b8",
        "accent": "#7c6cf0",
        "accent_hover": "#9585ff",
        "accent_soft": "#2e2850",
        "glow": "#c4b5fd",
        "border": "#3a3352",
        "log_bg": "#16141f",
        "log_fg": "#e2e0f0",
        "hero_grad_top": "#2a2248",
        "hero_grad_bottom": "#12101a",
        "browse_bg": "#3a3648",
        "browse_hover": "#4a455c",
        "browse_fg": "#d8d4ec",
    }

    root.configure(bg=colors["bg"])
    root.option_add("*Font", ("Segoe UI", 10))

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=colors["bg"], foreground=colors["text"])
    style.configure("TFrame", background=colors["bg"])
    style.configure("Card.TFrame", background=colors["card"])
    style.configure("TLabel", background=colors["bg"], foreground=colors["text"])
    style.configure("Card.TLabel", background=colors["card"], foreground=colors["text"])
    style.configure("Muted.TLabel", background=colors["bg"], foreground=colors["muted"])
    style.configure("CardMuted.TLabel", background=colors["card"], foreground=colors["muted"])
    style.configure(
        "TEntry",
        fieldbackground=colors["surface"],
        foreground=colors["text"],
        insertcolor=colors["text"],
        bordercolor=colors["border"],
        lightcolor=colors["border"],
        darkcolor=colors["border"],
        padding=10,
    )
    style.map(
        "TEntry",
        fieldbackground=[("readonly", colors["surface"]), ("disabled", colors["surface"])],
        foreground=[("readonly", colors["text"]), ("disabled", colors["muted"])],
        insertcolor=[("readonly", colors["text"]), ("!disabled", colors["text"])],
    )
    style.configure(
        "Card.TCheckbutton",
        background=colors["card"],
        foreground=colors["muted"],
        focuscolor=colors["card"],
        indicatorcolor=colors["surface"],
        indicatorrelief="flat",
        padding=(2, 4),
    )
    style.map(
        "Card.TCheckbutton",
        background=[("active", colors["card"]), ("focus", colors["card"])],
        foreground=[("active", colors["muted"]), ("focus", colors["muted"])],
        focuscolor=[("focus", colors["card"])],
        highlightcolor=[("focus", colors["card"])],
        indicatorcolor=[("selected", colors["accent"]), ("!selected", colors["border"])],
    )
    style.configure("StepDone.TLabel", background=colors["card"], foreground=colors["glow"], font=("Segoe UI", 9, "bold"))
    style.configure("StepIdle.TLabel", background=colors["card"], foreground=colors["muted"], font=("Segoe UI", 9))
    style.configure(
        "Accent.Horizontal.TProgressbar",
        troughcolor=colors["surface"],
        background=colors["accent"],
        bordercolor=colors["border"],
        lightcolor=colors["accent_hover"],
        darkcolor=colors["accent"],
        thickness=10,
    )

    return colors


def draw_hero_gradient(canvas: tk.Canvas, width: int, height: int, colors: dict[str, str]) -> None:
    """Paint a vertical gradient using a few bands (fast on window resize)."""
    if width <= 0 or height <= 0:
        return

    canvas.delete("grad")
    top = _hex_to_rgb(colors["hero_grad_top"])
    bottom = _hex_to_rgb(colors["hero_grad_bottom"])
    bands = min(max(height // 4, 8), 28)
    band_h = max(height / bands, 1)

    for band in range(bands):
        y0 = int(band * band_h)
        y1 = int((band + 1) * band_h) if band < bands - 1 else height
        ratio = (y0 + y1) / max(2 * height, 1)
        r = int(top[0] + (bottom[0] - top[0]) * ratio)
        g = int(top[1] + (bottom[1] - top[1]) * ratio)
        b = int(top[2] + (bottom[2] - top[2]) * ratio)
        fill = f"#{r:02x}{g:02x}{b:02x}"
        canvas.create_rectangle(0, y0, width, y1, fill=fill, outline=fill, tags="grad")

    canvas.tag_lower("grad")
    canvas.tag_raise("hero_ui")
    canvas.tag_raise("accent_bar")


def pulse_accent_bar(canvas: tk.Canvas, colors: dict[str, str], *, step: int = 0) -> None:
    palette = [colors["accent"], colors["glow"], "#e879f9", colors["accent"]]
    canvas.itemconfigure("accent_bar", fill=palette[step % len(palette)])


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def make_accent_button(parent: tk.Misc, text: str, command, colors: dict[str, str]) -> tk.Button:
    btn = tk.Button(
        parent, text=text, command=command,
        bg=colors["accent"], fg="white",
        activebackground=colors["accent_hover"], activeforeground="white",
        relief=tk.FLAT, bd=0, padx=22, pady=11, cursor="hand2", font=("Segoe UI Semibold", 10),
    )

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
    return tk.Entry(
        parent,
        textvariable=variable,
        bg=colors["surface"],
        fg=colors["text"],
        insertbackground=colors["text"],
        relief=tk.FLAT,
        highlightthickness=1,
        highlightbackground=colors["border"],
        highlightcolor=colors["accent"],
        font=("Segoe UI", 10),
    )


def make_browse_button(parent: tk.Misc, text: str, command, colors: dict[str, str]) -> tk.Button:
    btn = tk.Button(
        parent, text=text, command=command,
        bg=colors["browse_bg"], fg=colors["browse_fg"],
        activebackground=colors["browse_hover"], activeforeground=colors["text"],
        relief=tk.FLAT, bd=0, padx=14, pady=8,
        highlightthickness=0,
        cursor="hand2", font=("Segoe UI", 10),
    )

    def on_enter(_e) -> None:
        btn.configure(bg=colors["browse_hover"])

    def on_leave(_e) -> None:
        btn.configure(bg=colors["browse_bg"])

    btn.bind("<Enter>", on_enter)
    btn.bind("<Leave>", on_leave)
    return btn


def make_secondary_button(parent: tk.Misc, text: str, command, colors: dict[str, str]) -> tk.Button:
    return tk.Button(
        parent, text=text, command=command,
        bg=colors["card"], fg=colors["text"],
        activebackground=colors["accent_soft"], activeforeground=colors["glow"],
        relief=tk.FLAT, bd=0, padx=16, pady=9,
        highlightthickness=1, highlightbackground=colors["border"], highlightcolor=colors["border"],
        cursor="hand2", font=("Segoe UI", 10),
    )


def make_ghost_button(parent: tk.Misc, text: str, command, colors: dict[str, str]) -> tk.Button:
    return tk.Button(
        parent, text=text, command=command,
        bg=colors["surface"], fg=colors["muted"],
        activebackground=colors["card"], activeforeground=colors["text"],
        relief=tk.FLAT, bd=0, padx=12, pady=8, cursor="hand2", font=("Segoe UI", 10),
    )


def configure_log_widget(widget: tk.Text, colors: dict[str, str]) -> None:
    widget.configure(
        bg=colors["log_bg"], fg=colors["log_fg"], insertbackground=colors["log_fg"],
        relief=tk.FLAT, bd=0, padx=14, pady=12,
        font=tkfont.Font(family="Cascadia Mono", size=10),
        selectbackground=colors["accent"],
        highlightthickness=1, highlightbackground=colors["border"],
    )


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
        btn.configure(state=tk.NORMAL, bg=colors["accent"], fg="white")
    else:
        btn.configure(state=tk.DISABLED, bg=colors["border"], fg=colors["muted"])
