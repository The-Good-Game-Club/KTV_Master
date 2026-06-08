#!/usr/bin/env python3
"""
KTV Setup — 一鍵安裝 KTV Karaoke Generator

自動安裝：
  - Python 3.12（若未安裝）
  - FFmpeg（若未安裝，自動下載）
  - 所有 Python 套件（stable-ts, demucs, torch...）
  - 桌面捷徑

此安裝程式將於 2027-06-05 到期。
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
from tkinter import messagebox, ttk

# ── 單一實例鎖（防止雙重安裝）────────────────────────
_LOCK_FILE = Path(tempfile.gettempdir()) / ".ktv_setup_running.lock"
try:
    if _LOCK_FILE.exists():
        messagebox.showwarning(
            "安裝程式已在執行",
            "KTV Karaoke Generator 安裝程式正在執行中。\n"
            "請檢查系統 tray 或工作管理員。"
        )
        sys.exit(0)
    _LOCK_FILE.touch()
except Exception:
    pass  # 如果 lock file 失敗，繼續執行

# ── 到期日設定 ──────────────────────────────────────
EXPIRY_DATE = date(2027, 6, 5)

# ── 設定 ──────────────────────────────────────────
if getattr(sys, 'frozen', False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent
KTV_EXE = APP_DIR / "KTV.exe"
PYTHON_INSTALLER = APP_DIR / "python-installer.exe"
FFMPEG_ZIP = APP_DIR / "ffmpeg.zip"
REQUIREMENTS = APP_DIR / "requirements.txt"


class InstallerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        # ── 到期檢查 ──────────────────────────────────
        if date.today() > EXPIRY_DATE:
            messagebox.showerror(
                "安裝程式已到期",
                f"此安裝程式已於 {EXPIRY_DATE} 到期。\n"
                f"請向作者索取最新版本。"
            )
            sys.exit(1)

        self.title("KTV Karaoke Generator — 安裝程式")
        self.geometry("600x500")
        self.minsize(500, 400)
        self.resizable(False, False)

        self._running = False
        self._build_ui()
        self._center_window()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _center_window(self):
        self.update_idletasks()
        w, h = 600, 500
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        # ── 標題區 ──
        title_frame = ttk.Frame(self)
        title_frame.pack(fill="x", padx=20, pady=(20, 5))

        ttk.Label(
            title_frame,
            text="🎤 KTV Karaoke Generator",
            font=("Microsoft JhengHei", 18, "bold"),
        ).pack(anchor="center")

        ttk.Label(
            title_frame,
            text="一鍵安裝所有前置程式，自動建立桌面捷徑",
            font=("Microsoft JhengHei", 10),
            foreground="#666666",
        ).pack(anchor="center", pady=(2, 0))

        # ── 步驟清單 ──
        step_frame = ttk.LabelFrame(self, text="安裝步驟", padding=10)
        step_frame.pack(fill="x", padx=20, pady=10)

        self.steps = {
            "python": {"label": "✓ 檢查 Python", "status": "waiting"},
            "ffmpeg": {"label": "安裝 FFmpeg（音訊處理）", "status": "waiting"},
            "packages": {"label": "安裝 Python 套件（約 2-5 GB）", "status": "waiting"},
            "shortcut": {"label": "建立桌面捷徑", "status": "waiting"},
        }

        self.step_vars = {}
        for key, info in self.steps.items():
            var = tk.StringVar(value="⏳ 等待中")
            self.step_vars[key] = var
            row = ttk.Frame(step_frame)
            row.pack(fill="x", pady=2)
            ttk.Label(row, textvariable=var, width=4).pack(side="left")
            ttk.Label(row, text=info["label"]).pack(side="left", padx=(5, 0))

        # ── Log 輸出 ──
        log_frame = ttk.LabelFrame(self, text="詳細訊息", padding=5)
        log_frame.pack(fill="both", expand=True, padx=20, pady=5)

        self.log_text = tk.Text(
            log_frame, height=10, wrap="word",
            bg="#1e1e1e", fg="#00ff00", font=("Consolas", 9),
            state="disabled", relief="flat", borderwidth=0,
        )
        self.log_text.pack(fill="both", expand=True)

        # ── 進度條 ──
        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.pack(fill="x", padx=20, pady=(5, 5))

        # ── 按鈕區 ──
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=20, pady=(5, 15))

        self.install_btn = ttk.Button(
            btn_frame, text="🚀 開始安裝", command=self._start_install,
            style="Accent.TButton",
        )
        self.install_btn.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.launch_btn = ttk.Button(
            btn_frame, text="🎬 啟動 KTV",
            command=self._launch_ktv, state="disabled",
        )
        self.launch_btn.pack(side="right", fill="x", expand=True, padx=(5, 0))

        # ── Style ──
        style = ttk.Style()
        style.configure("Accent.TButton", font=("Microsoft JhengHei", 10, "bold"))

    # ── Log ────────────────────────────────────────

    def _log(self, text: str):
        self.log_text.config(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")
        self.update_idletasks()

    def _set_step(self, key: str, status: str, symbol: str = None):
        symbols = {"done": "✅", "fail": "❌", "running": "🔄", "waiting": "⏳"}
        sym = symbol or symbols.get(status, "⏳")
        self.step_vars[key].set(sym)
        self.update_idletasks()

    # ── 安裝流程 ────────────────────────────────────

    def _start_install(self):
        if self._running:
            return
        self._running = True
        self.install_btn.config(state="disabled", text="安裝中…")
        self.progress.start()
        threading.Thread(target=self._run_install, daemon=True).start()

    def _run_install(self):
        try:
            self._log("=" * 50)
            self._log("KTV Karaoke Generator 安裝程式")
            self._log("=" * 50)
            self._log("")

            # Step 1: Check / Install Python
            self._set_step("python", "running")
            self._log("[1/4] 檢查 Python…")

            # 用系統 python，唔係 PyInstaller bundle 自身
            _py_cmd = shutil.which('python3') or shutil.which('python') or 'python'
            try:
                ver = subprocess.run(
                    [_py_cmd, "--version"],
                    capture_output=True, text=True, timeout=10,
                ).stdout.strip()
                self._log(f"    ✓ 已安裝: {ver}")
                self._python_exe = _py_cmd
                self._set_step("python", "done", "✅")
            except Exception:
                self._log("    ⚠ Python 未安裝，正在安裝內建 Python 3.12…")
                if PYTHON_INSTALLER.exists():
                    self._log(f"    執行 {PYTHON_INSTALLER.name}（靜默安裝）…")
                    ret = subprocess.run(
                        [str(PYTHON_INSTALLER), "/quiet",
                         "InstallAllUsers=0", "PrependPath=1",
                         "Include_pip=1", "Include_test=0"],
                        timeout=120,
                    )
                    if ret.returncode == 0:
                        self._log("    ✓ Python 3.12 安裝成功！")
                        # 安裝後重新查找 python 路徑
                        import time
                        time.sleep(2)  # 等 PATH 更新
                        _py_cmd = shutil.which('python3') or shutil.which('python') or 'python'
                        self._python_exe = _py_cmd
                        self._set_step("python", "done", "✅")
                    else:
                        self._log(f"    ❌ Python 安裝失敗（返回碼 {ret.returncode}）")
                        self._set_step("python", "fail", "❌")
                        raise RuntimeError("Python 安裝失敗")
                else:
                    self._log("    ❌ 找不到內建 python-installer.exe")
                    self._set_step("python", "fail", "❌")
                    raise RuntimeError("Python 安裝檔缺失")

            # Step 2: Download FFmpeg
            self._set_step("ffmpeg", "running")
            self._log("[2/4] 下載 FFmpeg…")

            # 檢查 FFmpeg 是否已存在
            ffmpeg_dest = APP_DIR / "ffmpeg.exe"
            if ffmpeg_dest.exists():
                self._log(f"    ✓ FFmpeg 已存在")
                self._set_step("ffmpeg", "done", "✅")
            else:
                self._log("    正在從 gyan.dev 下載 FFmpeg essentials…")
                self._log("    （約 100 MB，視網路速度可能需要 1-5 分鐘）")
                self._log("")
                zip_path = APP_DIR / "ffmpeg.zip"
                ffmpeg_url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
                try:
                    # 用 PowerShell 下載
                    ps_cmd = (
                        f'Invoke-WebRequest -Uri "{ffmpeg_url}" '
                        f'-OutFile "{zip_path}" -UseBasicParsing'
                    )
                    ret = subprocess.run(
                        ["powershell", "-NoProfile", "-Command", ps_cmd],
                        timeout=600,
                    )
                    if ret.returncode != 0 or not zip_path.exists():
                        raise RuntimeError("下載失敗")

                    self._log("    下載完成，解壓縮 ffmpeg.exe…")

                    # 用 PowerShell 解壓（只抽出 ffmpeg.exe）
                    extract_cmd = (
                        f'Expand-Archive -Path "{zip_path}" '
                        f'-DestinationPath "{APP_DIR}" -Force; '
                        f'# Find and move ffmpeg.exe: '
                        f'$ffd = Get-ChildItem -Path "{APP_DIR}" -Recurse -Filter "ffmpeg.exe" | '
                        f'Select-Object -First 1; '
                        f'if ($ffd) {{ '
                        f'  Move-Item -Path $ffd.FullName -Destination "{ffmpeg_dest}" -Force; '
                        f'  # Clean up extracted folders '
                        f'  Get-ChildItem "{APP_DIR}" -Directory | '
                        f'  Where-Object {{ $_.Name -like "ffmpeg*" }} | '
                        f'  Remove-Item -Recurse -Force; '
                        f'}}'
                    )
                    ret2 = subprocess.run(
                        ["powershell", "-NoProfile", "-Command", extract_cmd],
                        timeout=120,
                    )

                    # Clean up zip
                    if zip_path.exists():
                        zip_path.unlink()

                    if ffmpeg_dest.exists():
                        self._log(f"    ✓ FFmpeg 下載完成 ({ffmpeg_dest.name})")
                        self._set_step("ffmpeg", "done", "✅")
                    else:
                        self._log("    ⚠ 解壓縮後找不到 ffmpeg.exe")
                        self._set_step("ffmpeg", "done", "⚠")
                except Exception as e:
                    self._log(f"    ⚠ FFmpeg 下載失敗: {e}")
                    self._log("    可稍後手動下載：https://ffmpeg.org/download.html")
                    self._set_step("ffmpeg", "done", "⚠")

            # Step 3: Install Python packages
            self._set_step("packages", "running")
            self._log("[3/4] 安裝 Python 套件…")

            req_file = str(REQUIREMENTS) if REQUIREMENTS.exists() else ""
            if req_file:
                # 先檢查是否已安裝主要套件
                _check_pkg = subprocess.run(
                    [self._python_exe, "-c", "import torch, demucs, stable_whisper; print('OK')"],
                    capture_output=True, text=True, timeout=15,
                )
                if _check_pkg.returncode == 0 and "OK" in _check_pkg.stdout:
                    self._log("    ✓ 主要套件已安裝，跳過")
                    self._set_step("packages", "done", "✅")
                else:
                    self._log("    這可能需要 10-30 分鐘（取決於網路速度）")
                    self._log("    需下載約 2-5 GB 的 AI 模型…")
                    self._log("")
                    self._log(f"    使用 {REQUIREMENTS.name}…")
                    proc = subprocess.Popen(
                        [self._python_exe, "-m", "pip", "install", "-r", req_file],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding="utf-8", errors="replace",
                        bufsize=1,
                    )
                    for line in proc.stdout:
                        self._log(f"    {line.rstrip()}")
                    proc.wait()
                    if proc.returncode == 0:
                        self._log("")
                        self._log("    ✓ 所有 Python 套件安裝完成！")
                        self._set_step("packages", "done", "✅")
                    else:
                        self._log(f"    ⚠ pip 返回代碼 {proc.returncode}")
                        self._log("    有些套件可能安裝失敗，但基本功能應可運作")
                        self._set_step("packages", "done", "⚠")
            else:
                self._log("    未找到 requirements.txt，跳過")
                self._set_step("packages", "done", "⚠")

            # Step 4: Create shortcut
            self._set_step("shortcut", "running")
            self._log("[4/4] 建立桌面捷徑…")

            target = str(KTV_EXE) if KTV_EXE.exists() else str(APP_DIR / "KTV_GUI.py")
            working_dir = str(APP_DIR)

            ps_script = f'''
$WS = New-Object -ComObject WScript.Shell
$SC = $WS.CreateShortcut([Environment]::GetFolderPath("Desktop") + "\\KTV Karaoke.lnk")
$SC.TargetPath = "{target}"
$SC.WorkingDirectory = "{working_dir}"
$SC.Description = "KTV Karaoke Generator - YouTube 卡拉 OK"
$SC.Save()
'''
            ret = subprocess.run(
                ["powershell", "-Command", ps_script],
                capture_output=True, text=True, timeout=15,
            )
            if ret.returncode == 0:
                self._log("    ✓ 桌面捷徑已建立！")
                self._set_step("shortcut", "done", "✅")
            else:
                self._log(f"    ⚠ 捷徑建立失敗: {ret.stderr.strip()}")
                self._set_step("shortcut", "done", "⚠")

            # Done
            self._log("")
            self._log("=" * 50)
            self._log("🎉 安裝完成！")
            self._log("=" * 50)
            self._log("")

            self.after(0, self._on_install_done)

        except Exception as e:
            self._log(f"\n❌ 安裝中斷：{e}")
            self.after(0, self._on_install_fail)

    def _on_install_done(self):
        self.progress.stop()
        self.install_btn.config(text="✅ 安裝完成", state="disabled")
        self.launch_btn.config(state="normal")
        self._running = False
        # Auto-launch after 1 second
        self.after(1000, self._launch_ktv)

    def _on_install_fail(self):
        self.progress.stop()
        self.install_btn.config(text="❌ 安裝失敗", state="normal")
        self._running = False
        messagebox.showerror(
            "安裝失敗",
            "安裝過程中出現錯誤，請檢查上方 Log 資訊。\n"
            "亦可手動參考 INSTALL.md 進行安裝。"
        )

    def _launch_ktv(self):
        exe = str(KTV_EXE) if KTV_EXE.exists() else str(APP_DIR / "KTV_GUI.py")
        if os.path.exists(exe):
            self._log(f"🎬 啟動 {os.path.basename(exe)}…")
            subprocess.Popen([exe], cwd=str(APP_DIR))
        else:
            messagebox.showerror("錯誤", f"找不到 KTV 執行檔：\n{exe}")

    def _on_close(self):
        if self._running:
            if not messagebox.askyesno("確認", "安裝進行中，確定要關閉嗎？"):
                return
        self._cleanup_lock()
        self.destroy()

    @staticmethod
    def _cleanup_lock():
        try:
            if _LOCK_FILE.exists():
                _LOCK_FILE.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        app = InstallerApp()
        app.mainloop()
    finally:
        try:
            if _LOCK_FILE.exists():
                _LOCK_FILE.unlink()
        except Exception:
            pass
