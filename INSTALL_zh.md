# KTV 卡拉 OK 字幕生成器 — 安裝指南

## 系統需求
- Python 3.11 以上（含 pip）
- FFmpeg（已安裝並加入 PATH）
- 網路連線（下載 YouTube 影片及 AI 模型）

## 第一步 — 安裝 Python

前往 https://www.python.org/downloads/ 下載安裝。

安裝時勾選「Add Python to PATH」。

確認安裝成功：

```bash
python --version   # 需顯示 3.11 或以上
pip --version
```

## 第二步 — 安裝 FFmpeg

### Windows
```bash
winget install ffmpeg
```
或從 https://ffmpeg.org/download.html 手動下載並加入 PATH。

### macOS
```bash
brew install ffmpeg
```

### Linux
```bash
sudo apt install ffmpeg   # Debian / Ubuntu
```

確認安裝成功：

```bash
ffmpeg -version
```

## 第三步 — 安裝 Python 套件

一行指令安裝所有依賴：

```bash
pip install stable-ts demucs soundfile yt-dlp torch torchaudio pypinyin duckduckgo-search youtube-transcript-api
```

> **可選套件：** `pip install librosa` — 用於偵測歌曲原 Key（升降 Key 功能輔助工具）。

首次執行時會自動下載 Whisper AI 模型（base 約 1 GB、medium 約 3 GB），請保持網路暢通。

## 第四步 — 驗證

```bash
cd ~/你的專案資料夾
python KTV.py --help
```

若看到說明訊息即安裝成功。若出現 `ModuleNotFoundError`，請用 `pip install` 補裝缺少的套件。

## 可選 — 圖形介面（GUI）

無需額外安裝套件，tkinter 已內建於 Python：

```bash
python KTV_GUI.py
```

雙擊 `KTV_GUI.py` 檔案也可直接啟動。

## 檔案結構

```
你的資料夾/
├── KTV.py           # 主程式（指令列）
├── KTV_GUI.py       # 圖形介面（可選）
├── lyrics_input.txt # Track A 歌詞檔（執行後會自動清空）
└── test_lyrics.txt  # 範例歌詞（改名為 lyrics_input.txt 或使用 --lyrics）
```

## 常見問題

| 症狀 | 解法 |
|------|------|
| `ModuleNotFoundError: No module named 'xxx'` | `pip install xxx` |
| yt-dlp 下載失敗（反機器人阻擋） | 更新 yt-dlp：`pip install --upgrade yt-dlp` |
| GUI 執行時卡住不動 | 關掉重開。FFmpeg 碰撞問題已在最新版 KTV.py 修復 |
| 同一網址跑兩次 — 檔案已存在錯誤 | 已自動修正：檔名會自動加上 `_1`、`_2` |
| Chrome Cookie 無法讀取 | 關閉 Chrome 瀏覽器後再執行 |
| stable-ts 無法使用 | 先裝 openai-whisper：`pip install openai-whisper` |
