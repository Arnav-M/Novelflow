"""Settings dialog for the Novelflow GUI.

Default audiobook format/voice/engine, playback-speed persistence,
and a keyboard-shortcut reference. Mixed into NovelflowApp (see gui.py).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from novelflow.gui_theme import (
    configure_dark_combobox,
    make_accent_button,
    space,
)

_SHORTCUTS = (
    ("Ctrl+Enter", "Convert to markdown"),
    ("Ctrl+L", "Clear the activity log"),
    ("Space", "Play / pause the player"),
)

_AUDIO_FORMATS = ("m4b", "mp3", "m4a")


class SettingsMixin:
    """Settings dialog and preference application."""

    def _open_settings(self) -> None:
        existing = getattr(self, "_settings_dialog", None)
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.lift()
                    existing.focus_force()
                    return
            except tk.TclError:
                pass

        dlg = tk.Toplevel(self)
        dlg.title("Settings")
        dlg.configure(bg=self.colors["bg"])
        dlg.transient(self)
        dlg.resizable(False, False)
        self._settings_dialog = dlg
        scale = self._ui_scale
        pad = space(4, scale)
        gap = space(2, scale)

        outer = ttk.Frame(dlg, padding=pad)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(1, weight=1)
        row = 0

        def add_label(text: str) -> None:
            ttk.Label(outer, text=text).grid(row=row, column=0, sticky="w", padx=(0, gap), pady=(0, gap))

        def add_heading(text: str) -> None:
            nonlocal row
            pady = (0 if row == 0 else space(3, scale), gap)
            ttk.Label(outer, text=text, style="SectionHeading.TLabel").grid(
                row=row, column=0, columnspan=2, sticky="w", pady=pady,
            )
            row += 1

        add_heading("Audiobook defaults")
        add_label("Format")
        fmt_var = tk.StringVar(value=self._default_audio_format())
        fmt_combo = ttk.Combobox(
            outer, textvariable=fmt_var, state="readonly", width=12,
            style="Dark.TCombobox", values=_AUDIO_FORMATS,
        )
        fmt_combo.grid(row=row, column=1, sticky="w", pady=(0, gap))
        configure_dark_combobox(fmt_combo, self.colors)

        def on_format(_event=None) -> None:
            self._gui_prefs["default_audio_format"] = fmt_var.get()
            self._save_gui_prefs()
            self.audio_format_var.set(fmt_var.get())

        fmt_combo.bind("<<ComboboxSelected>>", on_format)
        row += 1

        add_label("Voice")
        from novelflow.tts_voices import voices_for_engine

        voices = voices_for_engine(self._engine_key())
        labels = [f"{v.label} ({v.id})" for v in voices]
        saved_voice = str(self._gui_prefs.get("default_voice", ""))
        voice_var = tk.StringVar(
            value=next((lbl for v, lbl in zip(voices, labels) if v.id == saved_voice), self.tts_voice_var.get()),
        )
        voice_combo = ttk.Combobox(
            outer, textvariable=voice_var, state="readonly", width=28,
            style="Dark.TCombobox", values=labels,
        )
        voice_combo.grid(row=row, column=1, sticky="w", pady=(0, gap))
        configure_dark_combobox(voice_combo, self.colors)

        def on_voice(_event=None) -> None:
            label = voice_var.get()
            voice_id = next((v.id for v, lbl in zip(voices, labels) if lbl == label), "")
            self._gui_prefs["default_voice"] = voice_id
            self._save_gui_prefs()
            self.tts_voice_var.set(label)

        voice_combo.bind("<<ComboboxSelected>>", on_voice)
        row += 1

        add_label("Engine")
        engine_var = tk.StringVar(value=self._engine_key())
        engine_combo = ttk.Combobox(
            outer, textvariable=engine_var, state="readonly", width=12,
            style="Dark.TCombobox", values=("edge",),
        )
        engine_combo.grid(row=row, column=1, sticky="w", pady=(0, gap))
        configure_dark_combobox(engine_combo, self.colors)

        def on_engine(_event=None) -> None:
            self._gui_prefs["default_engine"] = engine_var.get()
            self._save_gui_prefs()
            self._refresh_voice_list()

        engine_combo.bind("<<ComboboxSelected>>", on_engine)
        row += 1

        add_heading("Player")
        remember_var = tk.BooleanVar(value=bool(self._gui_prefs.get("remember_speed", False)))

        def on_remember() -> None:
            self._gui_prefs["remember_speed"] = remember_var.get()
            if remember_var.get():
                self._gui_prefs["speed"] = self.speed_var.get()
            self._save_gui_prefs()

        ttk.Checkbutton(
            outer, text="Remember playback speed between sessions",
            variable=remember_var, command=on_remember, takefocus=0,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, gap))
        row += 1

        add_heading("Keyboard shortcuts")
        for keys, action in _SHORTCUTS:
            ttk.Label(outer, text=keys, style="Muted.TLabel").grid(
                row=row, column=0, sticky="w", padx=(0, gap),
            )
            ttk.Label(outer, text=action).grid(row=row, column=1, sticky="w")
            row += 1

        def close() -> None:
            self._settings_dialog = None
            dlg.destroy()

        foot = ttk.Frame(outer)
        foot.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(space(3, scale), 0))
        make_accent_button(foot, "Done", close, self.colors).pack(side=tk.RIGHT)
        dlg.protocol("WM_DELETE_WINDOW", close)

        # Center over the main window.
        dlg.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - dlg.winfo_reqwidth()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - dlg.winfo_reqheight()) // 3
        dlg.geometry(f"+{max(0, x)}+{max(0, y)}")
        dlg.grab_set()

    def _default_audio_format(self) -> str:
        fmt = str(self._gui_prefs.get("default_audio_format", "m4b"))
        return fmt if fmt in _AUDIO_FORMATS else "m4b"

    def _apply_startup_prefs(self) -> None:
        """Apply persisted defaults (format, speed) to the freshly built UI."""
        self.audio_format_var.set(self._default_audio_format())
        if self._gui_prefs.get("remember_speed"):
            speed = str(self._gui_prefs.get("speed", ""))
            if speed in ("0.75×", "1.0×", "1.25×", "1.5×", "1.75×", "2.0×"):
                self.speed_var.set(speed)
