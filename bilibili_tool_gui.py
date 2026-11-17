#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bilibili Downloader Tool — Graphical User Interface
====================================================
A Tkinter GUI wrapper around bilibili_tool.py that downloads Bilibili videos,
extracts instrumental BGM (vocals removed via Demucs), and converts subtitles
to SRT.

Requirements:
    - bilibili_tool.py (in the same folder)
    - yt-dlp, ffmpeg, Python + demucs (see bilibili_tool.py README)

Usage:
    python bilibili_tool_gui.py
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# Import the downloader class from the CLI tool
try:
    from bilibili_tool import BilibiliDownloader, normalize_bilibili_url
except ImportError as exc:
    raise SystemExit(
        "Could not import bilibili_tool.py. Make sure it is in the same folder.\n"
        f"Import error: {exc}"
    )


class LogRedirector:
    """Redirects print() output to a Tkinter ScrolledText widget safely."""

    def __init__(self, text_widget):
        self.text_widget = text_widget

    def write(self, message):
        if not message:
            return
        self.text_widget.after(0, self._insert, message)

    def _insert(self, message):
        self.text_widget.configure(state="normal")
        self.text_widget.insert(tk.END, message)
        self.text_widget.see(tk.END)
        self.text_widget.configure(state="disabled")

    def flush(self):
        pass
class BilibiliDownloaderGUI:
    """Main GUI application."""

    BROWSERS = ["edge", "chrome", "firefox", "brave", "opera", "safari"]

    def __init__(self, root):
        self.root = root
        self.root.title("Bilibili Downloader Tool")
        self.root.geometry("800x650")
        self.root.minsize(700, 550)

        self.downloader_thread = None
        self.is_running = False

        self._build_ui()
        self._center_window()

    def _center_window(self):
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        container = ttk.Frame(self.root, padding="12")
        container.pack(fill=tk.BOTH, expand=True)

        # --- URL section ---
        url_frame = ttk.LabelFrame(container, text="Video URL", padding="8")
        url_frame.pack(fill=tk.X, pady=(0, 8))

        self.url_var = tk.StringVar()
        url_entry = ttk.Entry(url_frame, textvariable=self.url_var, width=90)
        url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        url_entry.focus()

        paste_btn = ttk.Button(url_frame, text="Paste", command=self._paste_url, width=8)
        paste_btn.pack(side=tk.RIGHT)

        tip = ttk.Label(
            url_frame,
            text="Tip: paste a Bilibili video URL. Language prefixes and tracking params are stripped automatically.",
            foreground="#666666",
            font=("Segoe UI", 8),
        )
        tip.pack(anchor=tk.W, pady=(2, 0))

        # --- Options section ---
        opts_frame = ttk.LabelFrame(container, text="Options", padding="8")
        opts_frame.pack(fill=tk.X, pady=(0, 8))

        # Output directory
        out_row = ttk.Frame(opts_frame)
        out_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(out_row, text="Output folder:").pack(side=tk.LEFT)
        self.output_var = tk.StringVar(value="./bilibili_downloads")
        out_entry = ttk.Entry(out_row, textvariable=self.output_var, width=50)
        out_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
        browse_btn = ttk.Button(out_row, text="Browse…", command=self._browse_output, width=10)
        browse_btn.pack(side=tk.RIGHT)

        # Checkboxes row
        cb_row1 = ttk.Frame(opts_frame)
        cb_row1.pack(fill=tk.X, pady=(0, 4))
        self.skip_video_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(cb_row1, text="Skip video download (use existing file)", variable=self.skip_video_var).pack(side=tk.LEFT, padx=(0, 12))
        self.skip_bgm_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(cb_row1, text="Skip BGM extraction", variable=self.skip_bgm_var).pack(side=tk.LEFT, padx=(0, 12))
        self.skip_subs_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(cb_row1, text="Skip subtitles", variable=self.skip_subs_var).pack(side=tk.LEFT)

        cb_row2 = ttk.Frame(opts_frame)
        cb_row2.pack(fill=tk.X, pady=(0, 4))
        self.keep_temp_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(cb_row2, text="Keep temporary files", variable=self.keep_temp_var).pack(side=tk.LEFT, padx=(0, 12))

        # Cookies dropdown
        cookie_row = ttk.Frame(opts_frame)
        cookie_row.pack(fill=tk.X)
        ttk.Label(cookie_row, text="Cookies from browser:").pack(side=tk.LEFT)
        self.cookies_var = tk.StringVar(value="(none)")
        cookie_combo = ttk.Combobox(
            cookie_row,
            textvariable=self.cookies_var,
            values=["(none)"] + self.BROWSERS,
            state="readonly",
            width=14,
        )
        cookie_combo.pack(side=tk.LEFT, padx=(6, 0))
        cookie_tip = ttk.Label(
            cookie_row,
            text="  (use if video requires login)",
            foreground="#666666",
            font=("Segoe UI", 8),
        )
        cookie_tip.pack(side=tk.LEFT, padx=(6, 0))

        # --- Action buttons ---
        btn_frame = ttk.Frame(container)
        btn_frame.pack(fill=tk.X, pady=(0, 8))

        self.run_btn = ttk.Button(btn_frame, text="Start Download", command=self._start_download, width=20)
        self.run_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.open_folder_btn = ttk.Button(btn_frame, text="Open Output Folder", command=self._open_output_folder, width=20, state="disabled")
        self.open_folder_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.clear_btn = ttk.Button(btn_frame, text="Clear Log", command=self._clear_log, width=12)
        self.clear_btn.pack(side=tk.LEFT)

        # --- Log section ---
        log_frame = ttk.LabelFrame(container, text="Log / Progress", padding="8")
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            wrap=tk.WORD,
            state="disabled",
            font=("Consolas", 9),
            background="#fafafa",
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding="4")
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _paste_url(self):
        try:
            self.url_var.set(self.root.clipboard_get())
        except tk.TclError:
            pass

    def _browse_output(self):
        folder = filedialog.askdirectory(title="Select output folder", initialdir=self.output_var.get() or None)
        if folder:
            self.output_var.set(folder)

    def _open_output_folder(self):
        folder = self.output_var.get()
        if not folder:
            folder = "./bilibili_downloads"
        folder = os.path.abspath(folder)
        if os.path.isdir(folder):
            os.startfile(folder)

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def _start_download(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Please paste a Bilibili video URL.")
            return

        if self.is_running:
            messagebox.showinfo("Already running", "A download is already in progress.")
            return

        output = self.output_var.get().strip() or "./bilibili_downloads"

        cookies = self.cookies_var.get()
        cookies_arg = None if cookies == "(none)" else cookies

        self.is_running = True
        self.run_btn.configure(state="disabled")
        self.open_folder_btn.configure(state="disabled")
        self.status_var.set("Running…")
        self._clear_log()

        self.downloader_thread = threading.Thread(
            target=self._run_downloader,
            args=(url, output, cookies_arg),
            daemon=True,
        )
        self.downloader_thread.start()

        self.root.after(500, self._poll_thread)

    def _run_downloader(self, url, output, cookies):
        try:
            redirector = LogRedirector(self.log_text)
            old_stdout = sys.stdout
            sys.stdout = redirector

            try:
                downloader = BilibiliDownloader(
                    output_dir=output,
                    keep_temp=self.keep_temp_var.get(),
                    cookies_from_browser=cookies,
                )
                downloader.process(
                    url=url,
                    skip_video=self.skip_video_var.get(),
                    skip_bgm=self.skip_bgm_var.get(),
                    skip_subs=self.skip_subs_var.get(),
                )
            finally:
                sys.stdout = old_stdout

            self.root.after(0, self._download_finished, True, None)

        except Exception as exc:
            self.root.after(0, self._download_finished, False, exc)

    def _poll_thread(self):
        if self.downloader_thread and self.downloader_thread.is_alive():
            self.root.after(500, self._poll_thread)
        else:
            self._download_finished(True, None)

    def _download_finished(self, success, exc):
        self.is_running = False
        self.run_btn.configure(state="normal")
        self.open_folder_btn.configure(state="normal")

        if exc:
            self.status_var.set("Error")
            messagebox.showerror("Download failed", str(exc))
        else:
            self.status_var.set("Finished")
            messagebox.showinfo("Complete", "Download finished! Check the output folder and log above.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    root = tk.Tk()
    app = BilibiliDownloaderGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()

