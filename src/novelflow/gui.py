"""Desktop GUI for Novelflow."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from novelflow.gui_theme import (
    apply_theme,
    configure_log_widget,
    draw_hero_gradient,
    make_accent_button,
    make_browse_button,
    make_ghost_button,
    make_path_entry,
    make_secondary_button,
    pulse_accent_bar,
    set_accent_button_state,
    set_window_icon,
)


class NovelflowApp(tk.Tk):
    STEPS = ["Select PDF", "Convert", "Readable .md"]

    def __init__(self) -> None:
        super().__init__()
        self.title("Novelflow")
        self.geometry("820x620")
        self.minsize(700, 520)
        self._busy = False
        self._pulse_step = 0
        self._last_output: Path | None = None
        self._hero_size = (0, 0)
        self._hero_resize_after: str | None = None
        self._window_resize_after: str | None = None
        self.colors = apply_theme(self)
        set_window_icon(self)

        self.pdf_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.keep_raw_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Ready — choose a PDF to begin")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_label_var = tk.StringVar(value="")
        self.step_labels: list[ttk.Label] = []

        self._build_ui()
        self.bind("<Configure>", self._on_window_resize)
        self.bind("<Control-Return>", lambda _e: self._start_convert())
        self.bind("<Control-l>", lambda _e: self._clear_log())
        if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".pdf"):
            self.after(100, lambda: self._set_pdf_path(sys.argv[1]))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=0)
        outer.pack(fill=tk.BOTH, expand=True)

        self.hero_canvas = tk.Canvas(outer, height=108, highlightthickness=0, bd=0, bg=self.colors["bg"])
        self.hero_canvas.pack(fill=tk.X)
        self.hero_canvas.bind("<Configure>", self._on_hero_resize)

        self._hero_kicker = self.hero_canvas.create_text(
            20, 14, text="NOVELFLOW", anchor="nw", fill=self.colors["glow"],
            font=("Segoe UI", 9, "bold"), tags="hero_ui",
        )
        self._hero_title = self.hero_canvas.create_text(
            20, 34, text="PDF → readable markdown", anchor="nw", fill=self.colors["text"],
            font=("Segoe UI Semibold", 20), tags="hero_ui",
        )
        self._hero_subtitle = self.hero_canvas.create_text(
            20, 66,
            text="Paragraphs, chapters, scene headers, and OCR cleanup — one click.",
            anchor="nw", fill=self.colors["muted"], font=("Segoe UI", 9), width=720, tags="hero_ui",
        )
        self.hero_canvas.create_rectangle(0, 102, 2000, 108, fill=self.colors["accent"], tags="accent_bar", width=0)
        self.hero_canvas.update_idletasks()
        self.after_idle(self._redraw_hero)

        content = ttk.Frame(outer, padding=20)
        content.pack(fill=tk.BOTH, expand=True)

        self._build_step_rail(content)
        self._build_form(content)
        self._build_progress(content)
        self._build_log(content)

    def _on_hero_resize(self, event) -> None:
        size = (event.width, event.height)
        if size == self._hero_size:
            return
        self._hero_size = size
        if self._hero_resize_after is not None:
            self.after_cancel(self._hero_resize_after)
        self._hero_resize_after = self.after(32, self._redraw_hero)

    def _redraw_hero(self) -> None:
        self._hero_resize_after = None
        width = self.hero_canvas.winfo_width()
        height = self.hero_canvas.winfo_height()
        if width <= 1 or height <= 1:
            return
        draw_hero_gradient(self.hero_canvas, width, height, self.colors)
        self.hero_canvas.coords("accent_bar", 0, height - 6, width, height)
        self.hero_canvas.itemconfigure(self._hero_subtitle, width=max(width - 48, 320))

    def _on_window_resize(self, event) -> None:
        if event.widget is not self:
            return
        # WORD wrap reflow on every pixel of a drag is the main log-panel lag source.
        self.log.configure(wrap=tk.NONE)
        if self._window_resize_after is not None:
            self.after_cancel(self._window_resize_after)
        self._window_resize_after = self.after(120, self._finish_window_resize)

    def _finish_window_resize(self) -> None:
        self._window_resize_after = None
        self.log.configure(wrap=tk.WORD)

    def _build_step_rail(self, parent: ttk.Frame) -> None:
        rail = tk.Frame(parent, bg=self.colors["card"], highlightthickness=1, highlightbackground=self.colors["border"])
        rail.pack(fill=tk.X, pady=(0, 14))
        inner = ttk.Frame(rail, style="Card.TFrame", padding=12)
        inner.pack(fill=tk.X)
        for i, name in enumerate(self.STEPS):
            cell = ttk.Frame(inner, style="Card.TFrame")
            cell.pack(side=tk.LEFT, expand=True, fill=tk.X)
            lbl = ttk.Label(cell, text=f"{i + 1}. {name}", style="StepIdle.TLabel")
            lbl.pack()
            self.step_labels.append(lbl)
        self._set_step(0)

    def _set_step(self, index: int) -> None:
        for i, lbl in enumerate(self.step_labels):
            lbl.configure(style="StepDone.TLabel" if i <= index else "StepIdle.TLabel")

    def _flash_success(self) -> None:
        self._pulse_step = 0

        def tick() -> None:
            pulse_accent_bar(self.hero_canvas, self.colors, step=self._pulse_step)
            self._pulse_step += 1
            if self._pulse_step < 8:
                self.after(90, tick)
            else:
                self.hero_canvas.itemconfigure("accent_bar", fill=self.colors["accent"])

        tick()

    def _build_form(self, parent: ttk.Frame) -> None:
        card = tk.Frame(parent, bg=self.colors["card"], highlightthickness=1, highlightbackground=self.colors["border"])
        card.pack(fill=tk.X, pady=(0, 14))
        body = ttk.Frame(card, style="Card.TFrame", padding=18)
        body.pack(fill=tk.X)

        self.pdf_entry = self._field_row(body, 0, "Input PDF", self.pdf_var, self._browse_pdf)
        self.output_entry = self._field_row(body, 1, "Output file", self.output_var, self._browse_output)

        ttk.Checkbutton(
            body, text="Also save raw extracted text (.raw.md)",
            variable=self.keep_raw_var, style="Card.TCheckbutton", takefocus=0,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 14))

        actions = ttk.Frame(body, style="Card.TFrame")
        actions.grid(row=3, column=0, columnspan=3, sticky="w")
        self.convert_btn = make_accent_button(actions, "▶  Convert PDF", self._start_convert, self.colors)
        self.convert_btn.pack(side=tk.LEFT)
        self.open_btn = make_secondary_button(actions, "Open folder", self._open_output_folder, self.colors)
        self.open_btn.pack(side=tk.LEFT, padx=(10, 0))
        self.open_btn.configure(state=tk.DISABLED)
        self.open_file_btn = make_secondary_button(actions, "Open .md", self._open_output_file, self.colors)
        self.open_file_btn.pack(side=tk.LEFT, padx=(10, 0))
        self.open_file_btn.configure(state=tk.DISABLED)

        body.columnconfigure(1, weight=1)

    def _build_progress(self, parent: ttk.Frame) -> None:
        wrap = ttk.Frame(parent)
        wrap.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(wrap, textvariable=self.progress_label_var, style="Muted.TLabel").pack(anchor="w")
        self.progress = ttk.Progressbar(
            wrap, variable=self.progress_var, maximum=100,
            style="Accent.Horizontal.TProgressbar", mode="determinate",
        )
        self.progress.pack(fill=tk.X, pady=(4, 0))

    def _set_progress(self, pct: float, label: str = "") -> None:
        self.progress_var.set(max(0.0, min(100.0, pct)))
        if label:
            self.progress_label_var.set(label)

    def _reset_progress(self) -> None:
        self.progress_var.set(0.0)
        self.progress_label_var.set("")

    def _build_log(self, parent: ttk.Frame) -> None:
        header = ttk.Frame(parent)
        header.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(header, text="Activity log", font=("Segoe UI Semibold", 10)).pack(side=tk.LEFT)
        make_ghost_button(header, "Clear", self._clear_log, self.colors).pack(side=tk.RIGHT)

        log_wrap = tk.Frame(parent, bg=self.colors["border"])
        log_wrap.pack(fill=tk.BOTH, expand=True)
        self.log = scrolledtext.ScrolledText(log_wrap, height=11, state=tk.DISABLED, wrap=tk.WORD)
        self.log.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        configure_log_widget(self.log, self.colors)

        tk.Label(
            parent, textvariable=self.status_var, bg=self.colors["bg"], fg=self.colors["muted"],
            font=("Segoe UI", 9), anchor="w",
        ).pack(fill=tk.X, pady=(10, 0))

    def _field_row(self, parent, row: int, label: str, variable: tk.StringVar, browse_cmd) -> tk.Entry:
        ttk.Label(parent, text=label, style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=8)
        entry = make_path_entry(parent, variable, self.colors)
        entry.grid(row=row, column=1, sticky="ew", padx=(12, 12), pady=8, ipady=4)
        make_browse_button(parent, "Browse", browse_cmd, self.colors).grid(row=row, column=2, pady=8)
        return entry

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

    def _browse_pdf(self) -> None:
        self.lift()
        self.focus_force()
        path = filedialog.askopenfilename(
            parent=self,
            title="Select PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self._set_pdf_path(path)

    def _set_pdf_path(self, path: str) -> None:
        resolved = self._normalize_path(path)
        if not resolved:
            return
        self.pdf_var.set(resolved)
        self._sync_entry(self.pdf_entry, resolved)
        if not self.output_var.get().strip():
            output = str(Path(resolved).with_suffix(".readable.md"))
            self.output_var.set(output)
            self._sync_entry(self.output_entry, output)
        self.status_var.set(f"Selected: {Path(resolved).name}")
        self._set_step(0)
        self.update_idletasks()

    def _browse_output(self) -> None:
        self.lift()
        self.focus_force()
        initialdir = None
        initialfile = ""
        pdf_path = self._normalize_path(self.pdf_var.get())
        if pdf_path:
            pdf = Path(pdf_path)
            initialdir = str(pdf.parent)
            initialfile = pdf.with_suffix(".readable.md").name
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Save markdown as",
            initialdir=initialdir,
            initialfile=initialfile,
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("All files", "*.*")],
        )
        if path:
            resolved = self._normalize_path(path)
            self.output_var.set(resolved)
            self._sync_entry(self.output_entry, resolved)

    def _log(self, message: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, message + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _clear_log(self) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        self.log.configure(state=tk.DISABLED)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        set_accent_button_state(self.convert_btn, self.colors, enabled=not busy)
        self.status_var.set("Converting…" if busy else "Ready")

    def _start_convert(self) -> None:
        if self._busy:
            return

        pdf = self._normalize_path(self.pdf_var.get())
        if not pdf:
            messagebox.showwarning("Novelflow", "Choose a PDF file first.")
            return
        if not Path(pdf).is_file():
            messagebox.showerror("Novelflow", f"PDF not found:\n{pdf}")
            return

        output_raw = self.output_var.get().strip()
        output = self._normalize_path(output_raw) if output_raw else None
        keep_raw = self.keep_raw_var.get()
        self.open_btn.configure(state=tk.DISABLED)
        self.open_file_btn.configure(state=tk.DISABLED)
        self._set_busy(True)
        self._set_step(1)
        self._set_progress(0, "Starting conversion…")
        self._log("—" * 52)

        def run() -> None:
            try:
                from novelflow.convert import convert_pdf

                result = convert_pdf(
                    pdf, output, keep_raw=keep_raw,
                    progress=lambda msg: self.after(0, self._log, msg),
                    on_progress=lambda pct: self.after(0, self._set_progress, pct, "Converting…"),
                )
                self.after(0, self._on_success, result)
            except Exception as exc:
                self.after(0, self._on_error, str(exc))

        threading.Thread(target=run, daemon=True).start()

    def _on_success(self, output_path: Path) -> None:
        self._last_output = output_path
        self._set_progress(100, "Complete")
        self._set_busy(False)
        self._set_step(2)
        self.open_btn.configure(state=tk.NORMAL)
        self.open_file_btn.configure(state=tk.NORMAL)
        self.status_var.set(f"Done — {output_path.name}")
        self._flash_success()
        messagebox.showinfo("Novelflow", f"Saved:\n{output_path}")

    def _on_error(self, message: str) -> None:
        self._reset_progress()
        self._set_busy(False)
        self._set_step(0)
        self.status_var.set("Conversion failed")
        self._log(f"Error: {message}")
        messagebox.showerror("Novelflow", message)

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


def _show_splash() -> tk.Tk:
    splash = tk.Tk()
    splash.title("Novelflow")
    splash.resizable(False, False)
    splash.configure(bg="#12101a")
    splash.geometry("400x160")
    splash.update_idletasks()
    x = (splash.winfo_screenwidth() - 400) // 2
    y = (splash.winfo_screenheight() - 160) // 2
    splash.geometry(f"400x160+{x}+{y}")
    tk.Label(
        splash, text="Novelflow", fg="#c4b5fd", bg="#12101a",
        font=("Segoe UI Semibold", 18),
    ).pack(pady=(40, 8))
    tk.Label(
        splash, text="Loading…", fg="#9b93b8", bg="#12101a",
        font=("Segoe UI", 10),
    ).pack()
    splash.update()
    return splash


def main() -> None:
    splash = _show_splash()
    app = NovelflowApp()
    splash.destroy()
    app.mainloop()


if __name__ == "__main__":
    main()
