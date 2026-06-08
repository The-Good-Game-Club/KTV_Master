# 🎤 KTV — YouTube Karaoke Subtitle Generator / YouTube 卡拉 OK 字幕生成器

Turn any YouTube music video into a professional karaoke track: auto-download, AI vocal isolation, precise word-level subtitles, and video output.
把任何 YouTube 音樂影片變成專業卡拉 OK 伴唱帶：自動下載、AI 去人聲、精準生成逐字字幕、燒錄輸出。

---

## ✨ Features / 功能

- **AI Vocal Separation / AI 人聲分離** — Uses Meta Demucs to separate vocals from accompaniment, outputs pure instrumental version
  使用 Meta Demucs 分離人聲與伴奏，輸出純樂器版
- **Forced Alignment / 強制對齊字幕** — Uses stable-ts to precisely align lyrics to the audio timeline, zero typos
  使用 stable-ts 將歌詞精準對齊到音軌時間軸，零錯字
- **Word-by-Word Karaoke Effect / 逐字卡啦 OK 效果** — Outputs `.ass` subtitles with per-character gradient highlighting (KTV style)
  輸出 `.ass` 字幕，支援逐字漸變高亮（KTV 風格）
- **Dual Track Mode / 雙軌道模式** — Track A: manual lyrics input / Track B: auto-fetch lyrics online
  Track A 手動提供歌詞 / Track B 自動搜尋歌詞
- **Three Execution Modes / 三種執行模式** — Full mode / Lyrics-only mode (skip vocal separation) / Vocal-only mode
  完整模式 / 純字幕模式（跳過去人聲）/ 純去人聲模式
- **Graphical Interface / 圖形介面** — Built-in tkinter GUI, no command line needed
  內建 tkinter GUI，免打指令

---

## 🚀 Quick Start / 快速開始

```bash
# Track A: You have a lyrics file / 你有歌詞檔
python KTV.py "https://www.youtube.com/watch?v=xxxxx" --lyrics lyrics.txt

# Track B: Auto-fetch lyrics / 自動抓歌詞
python KTV.py "https://www.youtube.com/watch?v=xxxxx"

# Lyrics-only mode (skip Demucs, 3x faster) / 純字幕模式（跳過 Demucs，快 3 倍）
python KTV.py "URL" --lyrics lyrics.txt --mode lyrics_only

# Vocal-only mode (no subtitles) / 純去人聲模式（不生成字幕）
python KTV.py "URL" --mode vocal_only

# Use different AI models / 使用不同 AI 模型
python KTV.py "URL" --lyrics lyrics.txt -m tiny    # Fastest / 最快
python KTV.py "URL" --lyrics lyrics.txt -m medium  # More accurate / 較準
```

---

## 📦 Installation / 安裝

See **[INSTALL.md](INSTALL.md)** (English) or **[INSTALL_zh.md](INSTALL_zh.md)** (Chinese) for details.
詳見 **[INSTALL.md](INSTALL.md)**（英文）或 **[INSTALL_zh.md](INSTALL_zh.md)**（中文）。

One-line install of all dependencies / 一行安裝所有依賴：

```bash
pip install stable-ts demucs soundfile yt-dlp torch torchaudio pypinyin duckduckgo-search youtube-transcript-api
```

FFmpeg is also required (`winget install ffmpeg` on Windows / `brew install ffmpeg` on macOS).
需另外安裝 FFmpeg（Windows 用 `winget install ffmpeg` / macOS 用 `brew install ffmpeg`）。

---

## 🖥️ Graphical Interface / 圖形介面

```bash
python KTV_GUI.py
```

- Enter a YouTube URL / 輸入 YouTube 網址
- Paste lyrics or upload a `.txt` file / 貼上歌詞或上傳 `.txt` 檔案
- Select mode, model, and pitch shift (-12 ~ +12) / 選擇模式、模型與升降 Key（-12 ~ +12）
- Click RUN, real-time progress display / 點擊 RUN，即時顯示進度

---

## 📝 Lyrics File Format / 歌詞檔格式

- Plain text `.txt`, UTF-8 encoded / 純文字 `.txt`，UTF-8 編碼
- One line per lyric / 一行一句歌詞
- Blank lines separate verses / 可用空行分隔段落
- **Auto-cleared after execution** — add lyrics again next time if using Track A
  **執行後會自動清空**，下次如需 Track A 請重新加入歌詞

Example / 範例：

```
從手中退去的溫度
到眼神失去了愛慕
曾衝動挽留什麼

分手那句話  當作祝福吧
也許曾經深愛他  才會有傷疤
```

---

## ⚙️ Mode Reference / 模式說明

| Mode / 模式 | Command / 指令 | Description / 說明 |
|---|---:|---|
| Full / 完整 | `--mode full` (default) | Download → Vocal removal → Subtitle gen → Output<br>下載 → 去人聲 → 生成字幕 → 輸出 |
| Lyrics Only / 純字幕 | `--mode lyrics_only` | Skip Demucs, keep original audio, gen subtitles<br>跳過 Demucs，保留原聲，生成字幕 |
| Vocal Only / 純去人聲 | `--mode vocal_only` | Vocal removal only, no subtitle output<br>只做去人聲，不生成字幕 |

---

## 🎹 Pitch Shift / 升降 Key

Pitch up/down the entire song while keeping the original tempo. Uses FFmpeg `rubberband` filter.
支援將整首歌升/降 Key，保持原速度不變。使用 FFmpeg `rubberband` 濾波器。

```bash
# Lower by 4 semitones (suitable for male vocals) / 女歌降 4 個半音（適合男聲）
python KTV.py "URL" --lyrics lyrics.txt --mode lyrics_only --pitch -4

# Raise by 3 semitones (suitable for female vocals) / 男歌升 3 個半音（適合女聲）
python KTV.py "URL" --pitch +3

# Lower by 8 semitones (one octave down) / 降 8 個半音（低八度）
python KTV.py "URL" --pitch -8
```

| Parameter / 參數 | Range / 範圍 | Description / 說明 |
|---|---:|---|
| `--pitch N` | -12 ~ +12 | N semitones, negative=down, positive=up, 0=original (default)<br>N 個半音，負=降，正=升，0=原調（預設） |

> **Tip / 貼士：** Female vocalists are typically in **A Major～C Major** (A-Lin, G.E.M., etc.). Male vocals should lower by **2～6 semitones**. Use `librosa` to detect the original key.
> 女歌手原調通常在 **A Major～C Major**（A-Lin、鄧紫棋等），男聲建議降 **2～6 個半音**。可用 `librosa` 偵測原 Key。

Output filenames are auto-tagged with the pitch value, e.g. `_pitch-4_instrumental_karaoke.mp4`.
輸出檔名會自動標註升降數值，例如 `_pitch-4_instrumental_karaoke.mp4`。

---

## 🤖 AI Model Selection / AI 模型選擇

| Model / 模型 | Speed / 速度 | Accuracy / 準確度 | Use Case / 用途 |
|---|---:|---:|---|
| tiny | Fastest / 最快 | Lower / 較低 | Quick testing / 快速測試 |
| base | Default / 預設 | Medium / 中等 | Daily use / 日常使用 |
| medium | Slower / 較慢 | High / 高 | Quality focused / 追求品質 |
| turbo | Slowest / 最慢 | Highest / 最高 | Professional output / 專業輸出 |

---

## 🐛 Common Issues / 常見問題

| Issue / 問題 | Solution / 解法 |
|---|---:|---|
| yt-dlp download fails / yt-dlp 下載失敗 | `pip install --upgrade yt-dlp` |
| GUI hangs on run / GUI 執行卡住 | Auto-handled — running the same URL twice is now prevented<br>已自動修正 — 同一網址跑兩次會碰撞 |
| Chrome cookie error / Chrome Cookie 錯誤 | Close Chrome first, then retry / 關閉 Chrome 後再執行 |
| Subtitle timing is off / 字幕時間不準 | Use `-m medium` or larger model / 改用 `-m medium` 或更大模型 |
