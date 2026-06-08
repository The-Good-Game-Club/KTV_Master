# KTV Karaoke Generator — Installation Guide

## Requirements
- Python 3.11+ (with pip)
- FFmpeg (system-installed, on PATH)
- Internet connection (for YouTube downloads + model cache)

## Step 1 — Install Python

Download from https://www.python.org/downloads/

Check "Add Python to PATH" during installation.

Verify:

```bash
python --version   # 3.11 or newer
pip --version
```

## Step 2 — Install FFmpeg

### Windows
```bash
winget install ffmpeg
```
Or download from https://ffmpeg.org/download.html and add to PATH.

### macOS
```bash
brew install ffmpeg
```

### Linux
```bash
sudo apt install ffmpeg   # Debian/Ubuntu
```
Or your package manager equivalent.

Verify:

```bash
ffmpeg -version
```

## Step 3 — Install Python Dependencies

```bash
pip install stable-ts demucs soundfile yt-dlp torch torchaudio pypinyin duckduckgo-search youtube-transcript-api
```

> **Optional:** `pip install librosa` — for song key detection (pitch shift helper).

Or use requirements.txt (create it, paste the above):

```bash
pip install -r requirements.txt
```

First run will download Whisper model (~1 GB for base, ~3 GB for medium).

## Step 4 — Verify

```bash
cd ~/your_project_folder
python KTV.py --help
```

Should show the help message. If you see import errors, install the missing package with `pip`.

## Optional — GUI

Launch the GUI without extra dependencies:

```bash
python KTV_GUI.py
```

tkinter is built into Python — no extra install needed.

## File Layout

```
your_folder/
├── KTV.py           # Main script (CLI)
├── KTV_GUI.py       # GUI launcher (optional)
├── lyrics_input.txt # Lyrics file for Track A (auto-cleared after run)
└── test_lyrics.txt  # Example lyrics (rename to lyrics_input.txt or use --lyrics)
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ModuleNotFoundError: No module named 'xxx'` | `pip install xxx` |
| `yt-dlp` YouTube anti-bot error | Update yt-dlp: `pip install --upgrade yt-dlp` |
| GUI freezes on FFmpeg step | Close and re-open. FFmpeg collision fixed in latest KTV.py |
| Same URL twice — file exists error | Fixed: auto-appends `_1`, `_2` to filename |
| `stable-ts` doesn't work | Install openai-whisper first: `pip install openai-whisper` |
