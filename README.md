# 🎤 KTV — YouTube 卡拉 OK 字幕生成器

把任何 YouTube 音樂影片變成專業卡拉 OK 伴唱帶：自動下載、AI 去人聲、精準生成逐字字幕、燒錄輸出。

## ✨ 功能

- **AI 人聲分離** — 使用 Meta Demucs 分離人聲與伴奏，輸出純樂器版
- **強制對齊字幕** — 使用 stable-ts 將歌詞精準對齊到音軌時間軸，零錯字
- **逐字卡啦 OK 效果** — 輸出 `.ass` 字幕，支援逐字漸變高亮（KTV 風格）
- **雙軌道模式** — Track A 手動提供歌詞 / Track B 自動搜尋歌詞
- **三種執行模式** — 完整模式 / 純字幕模式（跳過去人聲）/ 純去人聲模式
- **圖形介面** — 內建 tkinter GUI，免打指令

## 🚀 快速開始

```bash
# Track A：你有歌詞檔
python KTV.py "https://www.youtube.com/watch?v=xxxxx" --lyrics 歌詞.txt

# Track B：自動抓歌詞
python KTV.py "https://www.youtube.com/watch?v=xxxxx"

# 純字幕模式（跳過 Demucs，快 3 倍）
python KTV.py "URL" --lyrics 歌詞.txt --mode lyrics_only

# 純去人聲模式（不生成字幕）
python KTV.py "URL" --mode vocal_only

# 使用不同 AI 模型
python KTV.py "URL" --lyrics 歌詞.txt -m tiny    # 最快
python KTV.py "URL" --lyrics 歌詞.txt -m medium  # 較準
```

## 📦 安裝

詳見 **[INSTALL.md](INSTALL.md)**（英文）或 **[INSTALL_zh.md](INSTALL_zh.md)**（中文）。

一行安裝所有依賴：

```bash
pip install stable-ts demucs soundfile yt-dlp torch torchaudio pypinyin duckduckgo-search youtube-transcript-api
```

需另外安裝 FFmpeg（`winget install ffmpeg` / `brew install ffmpeg`）。

## 🖥️ 圖形介面

```bash
python KTV_GUI.py
```

- 輸入 YouTube 網址
- 貼上歌詞或上傳 `.txt` 檔案
- 選擇模式、模型與升降 Key（-12 ~ +12）
- 點擊 RUN，即時顯示進度

## 📝 歌詞檔格式

- 純文字 `.txt`，UTF-8 編碼
- 一行一句歌詞
- 可用空行分隔段落
- **執行後會自動清空**，下次如需 Track A 請重新加入歌詞

範例：

```
從手中退去的溫度
到眼神失去了愛慕
曾衝動挽留什麼

分手那句話  當作祝福吧
也許曾經深愛他  才會有傷疤
```

## ⚙️ 模式說明

| 模式 | 指令 | 說明 |
|------|------|------|
| 完整 | `--mode full`（預設） | 下載 → 去人聲 → 生成字幕 → 輸出 |
| 純字幕 | `--mode lyrics_only` | 跳過 Demucs，保留原聲，生成字幕 |
| 純去人聲 | `--mode vocal_only` | 只做去人聲，不生成字幕 |

## 🎹 升降 Key（Pitch Shift）

支援將整首歌升/降 Key，保持原速度不變。使用 FFmpeg `rubberband` 濾波器。

```bash
# 女歌降 4 個半音（適合男聲）
python KTV.py "URL" --lyrics 歌詞.txt --mode lyrics_only --pitch -4

# 男歌升 3 個半音（適合女聲）
python KTV.py "URL" --pitch +3

# 降 8 個半音（低八度）
python KTV.py "URL" --pitch -8
```

| 參數 | 範圍 | 說明 |
|------|------|------|
| `--pitch N` | -12 ~ +12 | N 個半音，負=降，正=升，0=原調（預設） |

> **貼士：** 女歌手原調通常在 **A Major～C Major**（A-Lin、鄧紫棋等），男聲建議降 **2～6 個半音**。可用 `librosa` 偵測原 Key。

輸出檔名會自動標註升降數值，例如 `_pitch-4_instrumental_karaoke.mp4`。

## 🤖 AI 模型選擇

| 模型 | 速度 | 準確度 | 用途 |
|------|------|--------|------|
| tiny | 最快 | 較低 | 快速測試 |
| base | 預設 | 中等 | 日常使用 |
| medium | 較慢 | 高 | 追求品質 |
| turbo | 最慢 | 最高 | 專業輸出 |

## 🐛 常見問題

| 問題 | 解法 |
|------|------|
| yt-dlp 下載失敗 | `pip install --upgrade yt-dlp` |
| GUI 執行卡住 | 同一網址跑兩次會碰撞，已自動修正 |
| Chrome Cookie 錯誤 | 關閉 Chrome 後再執行 |
| 字幕時間不準 | 改用 `-m medium` 或更大模型 |
