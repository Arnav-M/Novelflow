"""Document tab for the Novelflow GUI.

Drop zone, source selection, markdown conversion, and the Advanced popup.
Mixed into NovelflowApp (see gui.py); shared helpers/state live on the shell.
"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, ttk

from novelflow.gui_jobs import JobCancelled
from novelflow.gui_theme import (
    make_accent_button,
    make_compact_dropdown,
    make_ghost_button,
    make_round_surface,
    make_secondary_button,
    space,
)


class DocumentTabMixin:
    """Document tab UI and conversion actions."""

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

        self._build_doc_drop_zone(content)
        self._build_doc_actions(action_row)

        self._doc_log_host = ttk.Frame(inner)
        self._doc_log_host.grid(row=1, column=0, sticky="nsew")

        self._sync_document_source_view()
        self._sync_drop_zone_height(force=True)
        self.after_idle(self._sync_work_tab_heights)

    def _build_doc_drop_zone(self, content: ttk.Frame) -> None:
        """Drop zone with its empty and file-selected views."""
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
            sel_content, textvariable=self._doc_filename_var, style="CardSectionHeading.TLabel", anchor="center",
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

    def _build_doc_actions(self, action_row: ttk.Frame) -> None:
        """Convert/open buttons and the Advanced popup trigger."""
        self._doc_adv_popup_open = False
        self.output_entry: tk.Entry | None = None

        gap = space(2, self._ui_scale)
        bar = ttk.Frame(action_row, style="Card.TFrame")
        bar.grid(row=0, column=0, sticky="w")
        self.convert_btn = make_accent_button(bar, "Convert to markdown", self._start_convert, self.colors)
        self.convert_btn.pack(side=tk.LEFT, padx=(0, gap))
        self.open_btn = make_secondary_button(bar, "Open folder", self._open_output_folder, self.colors)
        self.open_btn.pack(side=tk.LEFT, padx=(0, gap))
        self.open_file_btn = make_secondary_button(bar, "Open markdown", self._open_output_file, self.colors)
        self.open_file_btn.pack(side=tk.LEFT)
        self.open_btn.configure(state=tk.DISABLED)
        self.open_file_btn.configure(state=tk.DISABLED)
        self._doc_adv_btn = make_compact_dropdown(
            action_row, "Advanced", self._toggle_doc_advanced_popup, self.colors,
        )
        self._doc_adv_btn.grid(row=0, column=1, sticky="e", padx=(space(3, self._ui_scale), 0))
        # Root binding survives UI rebuilds (theme switch) — bind only once.
        if not getattr(self, "_doc_adv_dismiss_bound", False):
            self.bind("<Button-1>", self._on_doc_adv_dismiss, add="+")
            self._doc_adv_dismiss_bound = True

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

    def _start_convert(self) -> None:
        if self._busy:
            return
        src = self._validated_source(missing_msg="Choose a PDF or markdown file first.")
        if src is None:
            return
        source = str(src)
        if src.suffix.lower() == ".md":
            self._show_toast("That's already markdown — use the Audiobook tab to narrate it.", kind="info")
            return

        output_raw = self.output_var.get().strip()
        output = self._normalize_path(output_raw) if output_raw else None
        keep_raw = self.keep_raw_var.get()
        self._begin_run(make_audiobook=False, status="Converting to markdown…")

        def work(cancel: threading.Event) -> Path:
            from novelflow.convert import ConversionCancelled, convert_pdf

            try:
                return convert_pdf(
                    source, output, keep_raw=keep_raw,
                    progress=lambda msg: self._ui(self._log, msg),
                    on_progress=lambda pct: self._ui(self._set_progress, pct),
                    cancel_check=cancel.is_set,
                )
            except ConversionCancelled as exc:
                raise JobCancelled from exc

        self._jobs.run(
            work,
            on_done=lambda result: self._on_success(result, None),
            on_cancelled=self._on_cancelled,
            on_error=self._on_error,
        )
