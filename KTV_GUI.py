#!/usr/bin/env python3
"""
KTV_GUI.py — Simple tkinter GUI for KTV.py.
Enter YouTube URL + lyrics, pick mode/model, click RUN.

Requires: KTV.py in the same directory.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

# ── 到期日設定 ──────────────────────────────────────
EXPIRY_DATE = date(2027, 6, 5)

# ── 驗證到期 ──────────────────────────────────────
if date.today() > EXPIRY_DATE:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "KTV Karaoke Generator 已到期",
        f"此版本已於 {EXPIRY_DATE} 到期。\n"
        f"請向作者索取最新版本。"
    )
    sys.exit(1)

# ── 重點修正：動態獲取當前 GUI 腳本所在的絕對路徑 ──────────────────
if getattr(sys, 'frozen', False):
    # Running as PyInstaller bundle
    SCRIPT_DIR = Path(sys._MEIPASS)
    # Find system Python (sys.executable points to KTV.exe itself)
    import shutil as _shutil
    _py = _shutil.which('python3') or _shutil.which('python')
    PYTHON_EXE = _py or 'python'
else:
    # Running as plain .py script
    SCRIPT_DIR = Path(__file__).resolve().parent
    PYTHON_EXE = sys.executable

# KTV.py lives alongside KTV.exe (in install dir) or in _MEIPASS bundle
KTV_SCRIPT = SCRIPT_DIR / "KTV.py"
# If running frozen, also check the install folder (next to the .exe)
if getattr(sys, 'frozen', False):
    _exe_dir = Path(sys.executable).resolve().parent
    _alt = _exe_dir / "KTV.py"
    if _alt.exists():
        KTV_SCRIPT = _alt

MODES = ("full", "lyrics_only", "vocal_only")
MODELS = ("tiny", "base", "small", "medium", "large", "turbo")
PITCH_RANGE = list(range(-12, 13))  # -12 to +12


class KTVApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("KTV Karaoke Generator")
        self.geometry("720x750")
        self.minsize(540, 500)
        self._process: subprocess.Popen | None = None
        self._lyrics_file: str | None = None
        self._build_ui()

    # ── UI layout ──────────────────────────────────────────

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # URL
        ttk.Label(self, text="YouTube URL:").pack(anchor="w", **pad)
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(self, textvariable=self.url_var)
        self.url_entry.pack(fill="x", **pad)

        # Mode
        ttk.Label(self, text="Mode:").pack(anchor="w", **pad)
        self.mode_var = tk.StringVar(value=MODES[0])
        self.mode_combo = ttk.Combobox(self, textvariable=self.mode_var, values=MODES, state="readonly")
        self.mode_combo.pack(fill="x", **pad)

        # Whisper Model
        ttk.Label(self, text="Whisper Model:").pack(anchor="w", **pad)
        self.model_var = tk.StringVar(value=MODELS[1])  # default base
        self.model_combo = ttk.Combobox(self, textvariable=self.model_var, values=MODELS, state="readonly")
        self.model_combo.pack(fill="x", **pad)

        # Pitch Shift
        ttk.Label(self, text="Pitch Shift (半音):").pack(anchor="w", **pad)
        pitch_frame = ttk.Frame(self)
        pitch_frame.pack(fill="x", **pad)
        self.pitch_var = tk.IntVar(value=0)
        self.pitch_spinbox = ttk.Spinbox(
            pitch_frame, from_=-12, to=12,
            textvariable=self.pitch_var, width=6, state="readonly",
        )
        self.pitch_spinbox.pack(side="left")
        self.pitch_label = ttk.Label(pitch_frame, text="→ 原調")
        self.pitch_label.pack(side="left", padx=(10, 0))

        def _on_pitch_change(*_):
            v = self.pitch_var.get()
            if v == 0:
                self.pitch_label.config(text="→ 原調")
            elif v < 0:
                self.pitch_label.config(text=f"→ 降 {abs(v)} 個半音")
            else:
                self.pitch_label.config(text=f"→ 升 {v} 個半音")

        self.pitch_var.trace_add("write", _on_pitch_change)

        # Output Folder
        ttk.Label(self, text="Output Folder:").pack(anchor="w", **pad)
        out_frame = ttk.Frame(self)
        out_frame.pack(fill="x", **pad)
        self.out_var = tk.StringVar(value=str(SCRIPT_DIR))
        self.out_entry = ttk.Entry(out_frame, textvariable=self.out_var)
        self.out_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(out_frame, text="Browse…", command=self._browse_output).pack(side="right", padx=(4, 0))

        # Lyrics (Text Area)
        ttk.Label(self, text="Lyrics (Optional / Leave empty for auto-fetch):").pack(anchor="w", **pad)
        self.lyrics_text = tk.Text(self, height=8, wrap="word")
        self.lyrics_text.pack(fill="both", expand=True, **pad)

        # Run Button
        self.run_btn = ttk.Button(self, text="RUN", command=self._on_run)
        self.run_btn.pack(fill="x", **pad)

        # Log Output
        ttk.Label(self, text="Log Output:").pack(anchor="w", **pad)
        log_frame = ttk.Frame(self)
        log_frame.pack(fill="both", expand=True, **pad)
        
        self.log_text = tk.Text(log_frame, state="disabled", wrap="none", height=10, bg="#1e1e1e", fg="#ffffff")
        self.log_text.pack(side="left", fill="both", expand=True)
        
        sbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        sbar.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=sbar.set)

    def _browse_output(self):
        d = filedialog.askdirectory(initialdir=self.out_var.get())
        if d:
            self.out_var.set(d)

    def _on_run(self):
        if self._process is not None:
            return

        url = self.url_var.get().strip()
        if not url:
            messagebox.showerror("Error", "Please enter a YouTube URL.")
            return

        # 確保在執行前，KTV.py 真的存在於該路徑
        if not KTV_SCRIPT.exists():
            messagebox.showerror("Error", f"Could not find KTV.py at:\n{KTV_SCRIPT}")
            return

        # 處理歌詞暫存檔
        lyrics = self.lyrics_text.get("1.0", "end-1c").strip()
        self._lyrics_file = None
        if lyrics:
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8")
            tmp.write(lyrics)
            tmp.close()
            self._lyrics_file = tmp.name

        cmd = [
            PYTHON_EXE,
            str(KTV_SCRIPT),
            url,
            "--mode", self.mode_var.get(),
            "--whisper-model", self.model_var.get(),
            "--output", self.out_var.get(),
        ]
        pitch_val = self.pitch_var.get()
        if pitch_val != 0:
            cmd.extend(["--pitch", str(pitch_val)])

        if self._lyrics_file:
            cmd.extend(["--lyrics", self._lyrics_file])

        self._log_clear()
        self._log(f"Starting command: {' '.join(cmd)}\n\n")

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        self.run_btn.config(state="disabled", text="Running…")

        # cwd=str(SCRIPT_DIR) 確保後台程序在 KTV.py 的資料夾下執行
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=str(SCRIPT_DIR),
            env=env,
        )
        threading.Thread(target=self._read_output, daemon=True).start()

    def _read_output(self):
        for line in self._process.stdout:
            self.after(0, self._log, line)
        self._process.wait()
        rc = self._process.returncode
        self.after(0, self._on_finish, rc)

    def _on_finish(self, returncode: int):
        # 清理暫存歌詞檔
        if self._lyrics_file and os.path.exists(self._lyrics_file):
            try:
                os.remove(self._lyrics_file)
            except Exception:
                pass
            self._lyrics_file = None

        # ── 新增功能：運行成功後自動關閉 ──────────────────
        if returncode == 0:
            self._log("\n✓ Done!\n")
            self._log("Closing window in 2 seconds...")
            self.after(2000, self.destroy)  # 2秒後自動關閉視窗
        else:
            self._log(f"\n✗ Failed (exit code {returncode})\n")
            self.run_btn.config(state="normal", text="RUN")
            self._process = None

    # ── Log helpers ────────────────────────────────────────

    def _log_clear(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    def _log(self, text: str):
        self.log_text.config(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.config(state="disabled")


if __name__ == "__main__":
    app = KTVApp()
    app.mainloop()