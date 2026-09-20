#!/usr/bin/env python3
"""
KTV — YouTube Karaoke Generator
================================
Download any YouTube music video, remove vocals (Demucs), generate perfectly-
timed karaoke subtitles (stable-ts forced alignment), and burn them into a
new instrumental video.

USER MANUAL — Quick Start
-------------------------
  Track A (you have lyrics):
      python KTV.py "URL" --lyrics my_lyrics.txt

  Track B (auto-fetch lyrics):
      python KTV.py "URL"
      (searches CC → description → web for lyrics)

  Karaoke only (skip vocal removal, faster):
      python KTV.py "URL" --lyrics my_lyrics.txt --mode lyrics_only

  Vocal removal only (no subtitles):
      python KTV.py "URL" --mode vocal_only

  Use a specific Whisper model (default: turbo):
      python KTV.py "URL" --lyrics my_lyrics.txt -m tiny   (fastest)
      python KTV.py "URL" --lyrics my_lyrics.txt -m turbo  (default)

  Bypass YouTube anti-bot (close browser first):
      python KTV.py "URL" --cookies-from-browser chrome

  GUI launcher (no CLI needed):
      python KTV_GUI.py

Lyrics File Format
------------------
  Plain .txt file, UTF-8 encoded. One line per karaoke line.
  Empty lines are OK — they separate verses/choruses.
  The file is CLEARED after each successful Track A run.
  Re-add lyrics before running again for Track A.

Output
------
  The generated video is saved to the current directory as:
      <video_title>_instrumental_karaoke.mp4 (with subtitles)
      <video_title>_instrumental.mp4          (vocal removal only)

Modes
-----
  --mode full          Download + Demucs + align + burn subs (default)
  --mode lyrics_only    Skip Demucs (use original audio, ~3x faster)
  --mode vocal_only     Skip karaoke (just vocal removal, output instrumental)

Models
------
  tiny   (fastest, less accurate)
  turbo  (default, best accuracy/speed balance)
  small
  medium
  large
  turbo  (slowest, most accurate)

Dependencies
------------
  pip install stable-ts demucs soundfile yt-dlp torch torchaudio pypinyin

  FFmpeg must be installed separately and available on PATH.
  See INSTALL.md for full setup instructions.
"""

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("youtube_karaoke_txt")

# ---------------------------------------------------------------------------
#  Karaoke style settings
# ---------------------------------------------------------------------------

ASS_PLAYRES_X = 1920
ASS_PLAYRES_Y = 1080
PRE_DISPLAY_SECONDS = 2.0
ASS_STYLE = {
    "name": "Karaoke",
    "fontname": "Microsoft JhengHei",
    "fontsize": 120,
    "primary": "&H00FFFFFF",
    "secondary": "&H0000CCFF",
    "outline": "&H00000000",
    "back": "&H80000000",
    "bold": 0,
    "italic": 0,
    "underline": 0,
    "strikeout": 0,
    "scalex": 100,
    "scaley": 100,
    "spacing": 0,
    "angle": 0,
    "borderstyle": 1,
    "outline": 1.5,
    "shadow": 0.5,
    "alignment": 2,
    "marginl": 30,
    "marginr": 30,
    "marginv": 60,
    "encoding": 1,
}

LINE_MAX_DURATION = 6.0
LINE_MAX_CHARS = 20
SIMILARITY_THRESHOLD = 0.40

_PUNCT_STRIP_RE = re.compile(
    r"[\s,\.!?\-:;'\"\(\)\[\]\u3000\u3001\u3002\uff0c\uff0e\uff01\uff1f"
    r"\uff08\uff09\u300a\u300b\u300c\u300d\uff1a\uff1b\u201c\u201d\u2018\u2019"
    r"\uff1f\u3000]"
)


# ---------------------------------------------------------------------------
#  Dependency helpers
# ---------------------------------------------------------------------------

def _which(name: str) -> Path | None:
    path = shutil.which(name)
    return Path(path) if path else None


def check_dependencies(mode: str = "full") -> None:
    try:
        subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--version"],
            capture_output=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        log.error("yt-dlp not found.  Install with:  pip install yt-dlp")
        sys.exit(1)

    if not _which("ffmpeg"):
        log.error(
            "ffmpeg not found.  Install from https://ffmpeg.org/download.html "
            "or run:  winget install ffmpeg"
        )
        sys.exit(1)

    if mode != "vocal_only":
        try:
            import demucs  # noqa: F401
        except ImportError:
            log.error("demucs not installed.  Run:  pip install demucs")
            sys.exit(1)

        try:
            import soundfile  # noqa: F401
        except ImportError:
            log.error("soundfile not installed.  Run:  pip install soundfile")
            sys.exit(1)

        try:
            import stable_whisper  # noqa: F401
        except ImportError:
            log.error(
                "stable-ts not installed.  Run:  pip install stable-ts"
            )
            sys.exit(1)

        try:
            import pypinyin  # noqa: F401
        except ImportError:
            log.warning("pypinyin not installed. Pinyin matching disabled. "
                        "Run: pip install pypinyin")

    log.info("All dependencies satisfied.")


# ---------------------------------------------------------------------------
# Step 1 – Download
# ---------------------------------------------------------------------------

def download_video(url: str, workdir: Path,
                   max_height: int = 1080,
                   cookies_from_browser: str | None = None) -> tuple[Path, Path]:
    log.info("Downloading video from %s …", url)
    video_out = workdir / "%(title)s.%(ext)s"
    fmt = f"bestvideo[height<={max_height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={max_height}][ext=mp4]/mp4"
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", fmt,
        "--merge-output-format", "mp4",
        "-o", str(video_out),
        "--embed-metadata",
        "--no-playlist",
    ]
    if cookies_from_browser:
        cmd += ["--cookies-from-browser", cookies_from_browser]
    cmd.append(url)
    subprocess.run(cmd, check=True)
    candidates = sorted(workdir.glob("*.mp4"), key=os.path.getmtime, reverse=True)
    if not candidates:
        log.error("No MP4 video file was downloaded.")
        sys.exit(1)
    video_path = candidates[0]

    audio_out = workdir / "%(title)s.%(ext)s"
    audio_cmd = [
        sys.executable, "-m", "yt_dlp",
        # Prefer m4a (AAC) audio: YouTube intermittently 403s the opus DASH
        # format (251). m4a 140 (129k) is equal-or-better for Demucs + final AAC.
        "-f", "bestaudio[ext=m4a]/bestaudio/best",
        "--extract-audio",
        "--audio-format", "wav",
        "--audio-quality", "0",
        "-o", str(audio_out),
        "--no-playlist",
    ]
    if cookies_from_browser:
        audio_cmd += ["--cookies-from-browser", cookies_from_browser]
    audio_cmd.append(url)
    subprocess.run(audio_cmd, check=True)
    candidates = sorted(workdir.glob("*.wav"), key=os.path.getmtime, reverse=True)
    if not candidates:
        log.error("No WAV audio file was downloaded.")
        sys.exit(1)
    audio_path = candidates[0]

    log.info("Downloaded video : %s", video_path.name)
    log.info("Downloaded audio : %s", audio_path.name)
    return video_path, audio_path


# ---------------------------------------------------------------------------
# Step 2 – Vocal separation
# ---------------------------------------------------------------------------

def separate_audio(audio_path: Path, workdir: Path) -> tuple[Path, Path]:
    import torch
    from demucs import pretrained
    from demucs.apply import apply_model
    import soundfile as sf

    device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info("Loading Demucs model (htdemucs) on %s …", device)
    model = pretrained.get_model("htdemucs")
    model.to(device)
    model.eval()

    log.info("Loading audio …")
    raw, orig_sr = sf.read(str(audio_path))
    wav = torch.from_numpy(raw.T).to(device).float()

    if wav.dim() == 1:
        wav = wav.unsqueeze(0)
    if wav.size(0) > 2:
        wav = wav[:2]

    from demucs.audio import convert_audio
    wav = convert_audio(wav, orig_sr, model.samplerate, model.audio_channels)
    wav = wav.unsqueeze(0)

    log.info("Separating (this may take a while) …")
    with torch.no_grad():
        sources = apply_model(model, wav, split=True, overlap=0.25, progress=True)[0]

    stem_name = audio_path.stem

    accomp = torch.zeros_like(sources[0])
    for i, name in enumerate(model.sources):
        if name != "vocals":
            accomp += sources[i]

    accomp_dir = workdir / "htdemucs" / "accompaniment"
    accomp_dir.mkdir(parents=True, exist_ok=True)
    accomp_path = accomp_dir / f"{stem_name}.wav"
    sf.write(str(accomp_path), accomp.cpu().numpy().T, model.samplerate)

    voc_dir = workdir / "htdemucs" / "vocals"
    voc_dir.mkdir(parents=True, exist_ok=True)
    voc_idx = model.sources.index("vocals")
    vocals_path = voc_dir / f"{stem_name}.wav"
    sf.write(str(vocals_path), sources[voc_idx].cpu().numpy().T, model.samplerate)

    log.info("Accompaniment written to %s", accomp_path.name)
    log.info("Vocals written to %s", vocals_path.name)
    return accomp_path, vocals_path


# ---------------------------------------------------------------------------
# Step 3 – Karaoke subtitle generation
# ---------------------------------------------------------------------------

def _strip_punct(s: str) -> str:
    return _PUNCT_STRIP_RE.sub("", s)


_CREDIT_RE = re.compile(
    r"(作詞|作曲|編曲|監製|製作人|混音|母帶|錄音|和聲|吉他|貝斯|鼓|鍵盤|弦樂|"
    r"Producer|Composer|Lyricist|Arranger|Mixed|Mastered|Recorded|"
    r"Engineer|Guitar|Bass|Drum|Keyboard|Strings|Orchestra|Vocal|"
    r"Director|Label|Release|Copyright|℗|©|OP|SP)",
    re.IGNORECASE,
)


def _clean_metadata(text: str) -> str:
    """Strip credit lines and non-lyric metadata. Keep only sung lines."""
    lines = text.split("\n")
    cleaned = []
    for s in lines:
        s = s.strip()
        if not s:
            continue
        if len(s) > 100:
            continue
        if _CREDIT_RE.search(s):
            continue
        if re.match(r"^[\w\s\-–—,]+(?:Lyrics|歌詞)\s*$", s, re.IGNORECASE):
            continue
        s = re.sub(r"^\[.*?\]\s*", "", s).strip()
        if not s:
            continue
        if not cleaned or s.lower() != cleaned[-1].lower():
            cleaned.append(s)
    return "\n".join(cleaned)


def _clean_for_alignment(text: str) -> str:
    """Prepare lyrics for stable-ts forced alignment. Preserves line breaks.

    Dual-line lyrics (A||B): only the PRIMARY line (before ||) is aligned.
    The translation line is static display text and must NOT enter the
    alignment — non-matching chars get zero/interpolated timestamps that
    drift the char-count line mapping, especially across silence gaps.
    """
    text = _clean_metadata(text)
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    # Keep only the primary (karaoke) line; drop the || translation
    lines = [l.split("||", 1)[0].strip() for l in lines]
    return "\n".join(lines)


def _split_segments(result) -> None:
    """Break oversized segments into KTV-friendly lines using stable-ts utilities."""
    if hasattr(result, "split_by_gap"):
        result.split_by_gap(0.5)
    if hasattr(result, "split_by_length"):
        result.split_by_length(max_chars=LINE_MAX_CHARS)


def _secs_to_srt(t: float) -> str:
    """Convert seconds to SRT timestamp HH:MM:SS,mmm."""
    ms = int(round(t * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem2 = divmod(rem, 60000)
    s, ms3 = divmod(rem2, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms3:03d}"


def _write_srt_from_segments(srt_path: Path, segments) -> None:
    """Write a plain SRT from alignment segments for pre-burn verification.

    Dual-line lyrics (||) are rendered as two SRT subtitle lines.
    """
    blocks = []
    idx = 0
    for seg in segments:
        s = float(getattr(seg, "start", 0) or 0)
        e = float(getattr(seg, "end", 0) or 0)
        text = (getattr(seg, "text", "") or "").replace("||", "\n").strip()
        if not text:
            continue
        idx += 1
        blocks.append(f"{idx}\n{_secs_to_srt(s)} --> {_secs_to_srt(e)}\n{text}")
    srt_path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def _write_timing_summary(summary_path: Path, segments) -> None:
    """Write a compact per-line timing table for quick agent/human checks."""
    lines = []
    for seg in segments:
        s = float(getattr(seg, "start", 0) or 0)
        e = float(getattr(seg, "end", 0) or 0)
        text = (getattr(seg, "text", "") or "").replace("||", " | ").strip()
        lines.append(f"{s:7.2f} -> {e:7.2f}  {text}")
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_ass_from_alignment(
    ass_path: Path,
    result,
) -> None:
    """Write .ass from stable-ts alignment result, preserving per-word timing and original spaces."""
    segments = list(result.segments) if result and hasattr(result, "segments") else []
    if not segments:
        log.warning("No segments in alignment result; writing empty .ass")
        return

    with open(ass_path, "w", encoding="utf-8") as f:
        _write_ass_header(f)
        prev_end = 0.0
        for seg in segments:
            s = float(seg.start if hasattr(seg, "start") else seg.get("start", 0))
            e = float(seg.end if hasattr(seg, "end") else seg.get("end", 0))
            if e - s < 0.1:
                continue

            display_start = max(prev_end, s - PRE_DISPLAY_SECONDS)
            lead_in = max(0.0, s - display_start)

            # Check if this segment uses our custom line-structure reconstruction
            if hasattr(seg, "text") and hasattr(seg, "words") and seg.words:
                line = seg.text
                
                # Flatten word/token list down to character-level precise timestamps
                char_timestamps = []
                for w in seg.words:
                    w_text = w.word if hasattr(w, "word") else w.get("word", "")
                    w_start = float(w.start if hasattr(w, "start") else w.get("start", 0))
                    w_end = float(w.end if hasattr(w, "end") else w.get("end", 0))
                    
                    w_chars = [c for c in w_text if not c.isspace()]
                    if not w_chars:
                        continue
                    
                    total_dur = w_end - w_start
                    char_dur = total_dur / len(w_chars)
                    for idx, c in enumerate(w_chars):
                        c_start = w_start + idx * char_dur
                        c_end = c_start + char_dur
                        char_timestamps.append({"char": c, "start": c_start, "end": c_end})
                
                # KTV countdown dots prepended — same dialogue line, NOT in alignment text
                if lead_in >= 0.3:
                    lead_cs = max(1, int(round(lead_in * 100)))
                    third = max(1, lead_cs // 3)
                    last = lead_cs - third * 2
                    # Big dots with \fs128, then reset to lyric font size
                    fontsize = ASS_STYLE['fontsize']
                    parts = [f"{{\\fs128}}{{\\k{third}}}●{{\\k{third}}}●{{\\k{last}}}●{{\\fs{fontsize}}} "]
                else:
                    parts = [f"{{\\k{max(1, int(round(lead_in * 100)))}}}"]
                
                ct_idx = 0
                total_singing_cs = 0
                
                # Dual-line support: split on || and insert \N between segments
                if "||" in line:
                    line1, line2 = line.split("||", 1)
                    display_lines = [line1, line2]
                else:
                    display_lines = [line]
                
                for dl_idx, dl in enumerate(display_lines):
                    if dl_idx > 0:
                        parts.append("\\N")  # ASS newline between dual lines
                    for char in dl:
                        if char.isspace():
                            # Keep original layout whitespace intact without breaking ASS tags
                            parts.append(char)
                        else:
                            if dl_idx > 0:
                                # Translation line: plain static text, NO karaoke tags
                                # Don't consume timestamps or inflate total_singing_cs
                                parts.append(char)
                            else:
                                    if ct_idx < len(char_timestamps):
                                        ct = char_timestamps[ct_idx]
                                        cs_start = ct["start"]
                                        cs_end = ct["end"]

                                        if ct_idx < len(char_timestamps) - 1:
                                            next_ct = char_timestamps[ct_idx + 1]
                                            nws = next_ct["start"]
                                            dur_cs = max(1, int(round((nws - cs_start) * 100)))
                                        else:
                                            # Last character: leave 8cs grace before e so it fills EARLY
                                            dur_cs = max(1, int(round((cs_end - cs_start) * 100)))
                                            dur_cs = max(1, min(dur_cs, max(1, int(round((e - cs_start) * 100))) - 8))

                                        total_singing_cs += dur_cs
                                        parts.append(f"{{\\\\K{dur_cs}}}{char}")
                                        ct_idx += 1
                                    else:
                                        parts.append(f"{{\\\\K1}}{char}")
                                        total_singing_cs += 1
            else:
                # Fallback / Blind transcription standard mode
                # Prepend KTV countdown dots in the same dialogue line
                if lead_in >= 0.3:
                    lead_cs = max(1, int(round(lead_in * 100)))
                    third = max(1, lead_cs // 3)
                    last = lead_cs - third * 2
                    fontsize = ASS_STYLE['fontsize']
                    parts = [f"{{\\fs128}}{{\\k{third}}}●{{\\k{third}}}●{{\\k{last}}}●{{\\fs{fontsize}}} "]
                else:
                    parts = [f"{{\\k{max(1, int(round(lead_in * 100)))}}}"]
                words = getattr(seg, "words", None)
                if words and len(words) > 0:
                    total_singing_cs = 0
                    for i, w in enumerate(words):
                        wt = w.word.strip() if hasattr(w, "word") else str(w.get("word", "")).strip()
                        ws = float(w.start if hasattr(w, "start") else w.get("start", 0))
                        we = float(w.end if hasattr(w, "end") else w.get("end", 0))
                        if not wt:
                            continue
                        if i < len(words) - 1:
                            nws = float(words[i + 1].start if hasattr(words[i + 1], "start")
                                       else words[i + 1].get("start", we))
                            wdur_cs = max(1, int(round((nws - ws) * 100)))
                        else:
                            wdur_cs = max(1, int(round((we - ws) * 100)))
                        nc = len(wt)
                        wcs = max(1, wdur_cs // nc) if nc > 1 else wdur_cs
                        remainder = wdur_cs - wcs * (nc - 1) if nc > 1 else 0
                        for j, c in enumerate(wt):
                            dur_cs = wcs + remainder if j == nc - 1 and remainder > 0 else wcs
                            # Last character of LAST word: leave 8cs grace
                            if i == len(words) - 1 and j == nc - 1:
                                dur_cs = max(1, dur_cs - 8) if dur_cs > 8 else dur_cs
                            total_singing_cs += dur_cs
                            parts.append(f"{{\\K{dur_cs}}}{c}")
                else:
                    text = seg.text.strip() if hasattr(seg, "text") else str(seg.get("text", "")).strip()
                    if not text:
                        continue
                    dur = max(e - s, 0.01)
                    cs = max(1, int(round(dur * 100 / len(text))))
                    parts.extend(f"{{\\K{cs}}}{c}" for c in text)
                    total_singing_cs = len(text) * cs

            GRACE_CS = 8  # centiseconds of grace after last char fills before line ends
            last_fill_time = s + total_singing_cs / 100.0
            new_e = min(e, last_fill_time + GRACE_CS / 100.0)
            prev_end = new_e
            f.write(
                f"Dialogue: 0,{_secs_to_ass(display_start)},{_secs_to_ass(new_e)},"
                f"{ASS_STYLE['name']},,0,0,0,,{' '.join(parts)}\n"
            )

    # Pre-burn verification artifacts: plain SRT + per-line timing summary
    _write_srt_from_segments(ass_path.with_suffix(".srt"), segments)
    _write_timing_summary(ass_path.with_name(ass_path.stem + "_summary.txt"), segments)


def generate_karaoke(
    vocals_path: Path,
    workdir: Path,
    lyrics_text: str | None = None,
    model_name: str = "base",
    video_info: dict | None = None,
) -> Path:
    """
    Forced-alignment karaoke paradigm:
      - Maps clean lyric lines directly to the audio timeline.
      - Enforces strict line-by-line formatting matching the original layout structure.
    """
    import stable_whisper

    model = stable_whisper.load_model(model_name)
    ass_path = workdir / "karaoke.ass"

    ref = lyrics_text
    if not ref and video_info:
        log.info("Track B: auto-fetching reference lyrics …")
        ref = _fetch_reference_lyrics(video_info)

    if not ref or not ref.strip():
        log.warning("No lyrics available; using blind transcription fallback")
        result = model.transcribe(str(vocals_path))
        _split_segments(result)
        _write_ass_from_alignment(ass_path, result)
        log.info("Karaoke subtitles written to %s (blind mode)", ass_path.name)
        return ass_path

    # Parse inline #SILENCE directives into per-block alignment slices
    import soundfile as sf
    track_duration = sf.info(str(vocals_path)).duration
    chunks, blocks, silence_ranges = _parse_lyrics_blocks(ref, track_duration)
    ref_display = "\n".join(chunks)
    clean_text = _clean_for_alignment(ref_display)
    log.info("Cleaned lyrics: %d chars for forced alignment", len(clean_text))
    if blocks:
        log.info("Alignment blocks: %s",
                 [(round(s, 1), round(e, 1)) for _, s, e in blocks])

    if not hasattr(model, "align"):
        log.warning("stable-ts align() not available; falling back to transcribe")
        result = model.transcribe(str(vocals_path))
        _split_segments(result)
        _write_ass_from_alignment(ass_path, result)
        log.info("Karaoke subtitles written to %s (transcribe fallback)",
                 ass_path.name)
        return ass_path

    try:
        if silence_ranges or len(blocks) > 1:
            log.info("Running per-block forced alignment (%d blocks) …",
                     len(blocks))
            all_words = _align_blocks(model, vocals_path, workdir, blocks)
            if not all_words:
                raise RuntimeError("block alignment produced no words")
        else:
            log.info("Running forced alignment (stable-ts align) …")
            result = model.align(str(vocals_path), clean_text, language="zh")
            if result is None:
                raise RuntimeError("align() returned None")
            all_words = []
            for seg in result.segments:
                if hasattr(seg, "words") and seg.words:
                    all_words.extend(seg.words)
        
        # Core Improvement: Map AI outputs strictly back to the original text layout structures
        log.info("Re-segmenting alignment results to perfectly match original lines...")
        lines = [l.strip() for l in clean_text.split("\n") if l.strip()]
        # Preserve original display lines (with || separators) before strip
        orig_lines = [l.strip() for l in ref_display.split("\n") if l.strip()]
        new_segments = []
        w_idx = 0

        for i, line in enumerate(lines):
            line_clean = "".join([c for c in line if not c.isspace()])
            if not line_clean:
                continue
            
            line_words = []
            target_chars = len(line_clean)
            matched_chars = 0
            
            while w_idx < len(all_words) and matched_chars < target_chars:
                w = all_words[w_idx]
                w_text = w.word if hasattr(w, "word") else w.get("word", "")
                w_clean = "".join([c for c in w_text if not c.isspace()])
                matched_chars += len(w_clean)
                line_words.append(w)
                w_idx += 1
            
            if line_words:
                display_line = orig_lines[i] if i < len(orig_lines) else line
                class LineSegment:
                    def __init__(self, text, words):
                        self.text = text
                        self.words = words
                        self.start = words[0].start if hasattr(words[0], "start") else words[0].get("start", 0)
                        self.end = words[-1].end if hasattr(words[-1], "end") else words[-1].get("end", 0)
                new_segments.append(LineSegment(display_line, line_words))
        
        class CustomResult:
            def __init__(self, segments):
                self.segments = segments
        
        result = CustomResult(new_segments)
        seg_count = len(result.segments)
        log.info("Forced alignment mapped perfectly to original lines: %d lines", seg_count)
        _write_ass_from_alignment(ass_path, result)
        
    except Exception as exc:
        log.warning("Forced alignment failed: %s", exc)
        log.info("Falling back to blind transcription …")
        try:
            result = model.transcribe(str(vocals_path))
            _split_segments(result)
            _write_ass_from_alignment(ass_path, result)
            log.info("Karaoke subtitles written to %s (fallback mode)",
                     ass_path.name)
        except Exception as exc2:
            log.error("Blind transcription also failed: %s", exc2)
            sys.exit(1)

    log.info("Karaoke subtitles written to %s", ass_path.name)
    return ass_path


def _download_captions_standalone(url: str) -> str | None:
    """Download YouTube CC subtitles via youtube-transcript-api."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        import re as _re
        vid = _re.search(r"(?:v=|/)([\w\-]{11})", url)
        if not vid:
            return None
        video_id = vid.group(1)
        transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
        lang_priority = ["yue-HK", "yue", "zh-TW", "zh-Hant", "zh-CN", "zh-Hans", "zh", "chi"]
        chosen = None
        for t in transcripts:
            code = t.language_code
            if code in lang_priority:
                chosen = t
                break
        if not chosen:
            try:
                chosen = transcripts.find_transcript(lang_priority)
            except Exception:
                try:
                    chosen = next(iter(transcripts))
                except StopIteration:
                    return None
        if not chosen:
            return None
        lines = [entry["text"] for entry in chosen.fetch()]
        return "\n".join(lines)
    except ImportError:
        return None
    except Exception:
        return None


def _parse_description_standalone(url: str) -> str | None:
    """Extract lyrics from YouTube video description via yt-dlp."""
    try:
        out = subprocess.run(
            [sys.executable, "-m", "yt_dlp",
             "--print", "%(description)s", "--skip-download", "--no-playlist", url],
            capture_output=True, text=True, timeout=30,
        ).stdout
        if not out.strip():
            return None
        lines = out.split("\n")
        lyrics_lines = []
        in_lyrics = False
        keyword_re = re.compile(r"(歌詞|lyrics|Lyrics)", re.IGNORECASE)
        for line in lines:
            s = line.strip()
            if not s:
                if in_lyrics:
                    lyrics_lines.append("")
                continue
            if not in_lyrics:
                if keyword_re.search(s):
                    in_lyrics = True
                continue
            if s.startswith(("http", "Auto-generated", "Provided to")):
                continue
            if len(s) > 100:
                continue
            lyrics_lines.append(s)
        result = "\n".join(lyrics_lines).strip()
        return result if len(result.split("\n")) >= 2 else None
    except Exception:
        return None


def _scrape_lyrics_standalone(url: str) -> str | None:
    """Search the web for lyrics using ddgs."""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return None
    try:
        out = subprocess.run(
            [sys.executable, "-m", "yt_dlp",
             "--print", "%(title)s", "--skip-download", "--no-playlist", url],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        query = f"{out} lyrics" if out else "lyrics"
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        for r in results:
            link = r.get("href", "")
            if not link:
                continue
            try:
                import requests
                resp = requests.get(link, timeout=10, headers={
                    "User-Agent": "Mozilla/5.0"})
                if resp.status_code != 200:
                    continue
                text = resp.text
                lines = [l.strip() for l in text.split("\n")
                         if 2 < len(l.strip()) < 200 and not l.startswith("<")]
                if len(lines) < 3:
                    continue
                return "\n".join(lines[:60])
            except Exception:
                continue
    except Exception:
        pass
    return None


def _fetch_reference_lyrics(video_info: dict) -> str | None:
    """Attempt to fetch reference lyrics: CC captions → description → web scrape."""
    url = video_info.get("url", "")

    log.info("Track B: trying YouTube CC subtitles …")
    captions = _download_captions_standalone(url)
    if captions and captions.strip():
        cleaned = _clean_lyrics_local(captions)
        if len(cleaned.strip().split("\n")) >= 2:
            log.info("Track B: lyrics from YouTube CC (%d lines)",
                     len(cleaned.strip().split("\n")))
            return cleaned

    log.info("Track B: trying video description …")
    desc = _parse_description_standalone(url)
    if desc and desc.strip():
        cleaned = _clean_lyrics_local(desc)
        if len(cleaned.strip().split("\n")) >= 2:
            log.info("Track B: lyrics from video description (%d lines)",
                     len(cleaned.strip().split("\n")))
            return cleaned

    log.info("Track B: searching web for lyrics …")
    scraped = _scrape_lyrics_standalone(url)
    if scraped and scraped.strip():
        cleaned = _clean_lyrics_local(scraped)
        if len(cleaned.strip().split("\n")) >= 2:
            log.info("Track B: lyrics from web scrape (%d lines)",
                     len(cleaned.strip().split("\n")))
            return cleaned

    return None


def _secs_to_ass(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    cs = int(round((t - int(t)) * 100))
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_style_block() -> str:
    s = ASS_STYLE
    return (
        f"Style: {s['name']},{s['fontname']},{s['fontsize']},"
        f"{s['primary']},{s['secondary']},{s['outline']},{s['back']},"
        f"{s['bold']},{s['italic']},{s['underline']},{s['strikeout']},"
        f"{s['scalex']},{s['scaley']},{s['spacing']},{s['angle']},"
        f"{s['borderstyle']},{s['outline']},{s['shadow']},"
        f"{s['alignment']},{s['marginl']},{s['marginr']},{s['marginv']},"
        f"{s['encoding']}"
    )


def _write_ass_header(f) -> None:
    f.write("[Script Info]\n")
    f.write("; Generated by youtube_karaoke_txt.py\n")
    f.write("ScriptType: v4.00+\n")
    f.write("Collisions: Normal\n")
    f.write(f"PlayResX: {ASS_PLAYRES_X}\n")
    f.write(f"PlayResY: {ASS_PLAYRES_Y}\n")
    f.write("Timer: 100.0000\n\n")
    f.write("[V4+ Styles]\n")
    f.write("Format: Name, Fontname, Fontsize, PrimaryColour, "
            "SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, "
            "BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n")
    f.write(_ass_style_block() + "\n\n")
    f.write("[Events]\n")
    f.write("Format: Layer, Start, End, Style, Name, "
            "MarginL, MarginR, MarginV, Effect, Text\n")


# ---------------------------------------------------------------------------
# Helpers – video info
# ---------------------------------------------------------------------------

def _get_video_resolution(video_path: Path) -> tuple[int, int]:
    ffprobe = _which("ffprobe")
    if not ffprobe:
        log.warning("ffprobe not found; falling back to 1920x1080")
        return 1920, 1080
    try:
        out = subprocess.run(
            [str(ffprobe), "-v", "error",
             "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0",
             str(video_path)],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        w_str, h_str = out.split(",")
        return int(w_str), int(h_str)
    except Exception:
        log.warning("Could not detect video resolution; falling back to 1920x1080")
        return 1920, 1080


def _get_video_info(url: str) -> dict:
    info = {"url": url, "title": "", "channel": ""}
    try:
        out = subprocess.run(
            [
                sys.executable, "-m", "yt_dlp",
                "--print", "%(title)s|||%(channel)s",
                "--no-playlist", "--skip-download",
                url,
            ],
            capture_output=True, text=True, check=True,
            timeout=30,
        ).stdout.strip()
        parts = out.split("|||", 1)
        if len(parts) >= 1:
            info["title"] = parts[0].strip()
        if len(parts) >= 2:
            info["channel"] = parts[1].strip()
    except Exception as e:
        log.warning("Could not fetch video info: %s", e)
    return info


# ---------------------------------------------------------------------------
# Step 4 – Remux + subtitle burn-in
# ---------------------------------------------------------------------------


def _resolution_tag(max_height: int) -> str:
    """Return short tag for non-1080p resolutions, e.g. '_4K', '_2K'."""
    if max_height <= 1080:
        return ""
    tag = RESOLUTION_LABEL.get(max_height, f"{max_height}p")
    # Shorten labels like '2160p(4K)' → '_4K', '1440p(2K)' → '_2K'
    short = tag.replace("2160p(4K)", "4K").replace("1440p(2K)", "2K")
    return f"_{short}"


def remux(video_path: Path, accomp_path: Path, output_dir: Path,
          subtitle_path: Path | None = None, pitch: int = 0,
          max_height: int = 1080) -> Path:
    stem = video_path.stem
    pitch_tag = ""
    if pitch != 0:
        pitch_tag = f"_pitch{pitch:+d}"
    res_tag = _resolution_tag(max_height)
    if subtitle_path:
        out_name = stem + pitch_tag + res_tag + "_instrumental_karaoke.mp4"
    else:
        out_name = stem + pitch_tag + res_tag + "_instrumental.mp4"
    out_path = output_dir / out_name

    # Avoid collision when same song is processed concurrently
    counter = 1
    while out_path.exists():
        suffix = f"_{counter}"
        if subtitle_path:
            out_name = stem + pitch_tag + res_tag + suffix + "_instrumental_karaoke.mp4"
        else:
            out_name = stem + pitch_tag + res_tag + suffix + "_instrumental.mp4"
        out_path = output_dir / out_name
        counter += 1

    log.info("Building final video → %s", out_name)

    cmd: list[str] = [
        "ffmpeg", "-y", "-nostdin",
        "-i", str(video_path),
        "-i", str(accomp_path),
        "-map", "0:v:0",
        "-map", "1:a:0",
    ]

    # Pitch shift via FFmpeg rubberband (preserves timing, changes pitch only)
    if pitch != 0:
        factor = 2 ** (pitch / 12)
        cmd += ["-af", f"rubberband=tempo=1.0:pitch={factor:.6f}"]
        log.info("Pitch shift: %+d semitones (factor=%.4f)", pitch, factor)

    if subtitle_path:
        res_w, res_h = _get_video_resolution(video_path)
        tmp_ass = Path("_yt_karaoke_subs_temp.ass")
        shutil.copy2(subtitle_path, str(tmp_ass))
        cmd += ["-vf", f"subtitles={tmp_ass.name}:original_size={res_w}x{res_h}:charenc=UTF-8"]
        cmd += ["-c:v", "libx264", "-crf", "20", "-preset", "veryfast"]
    else:
        cmd += ["-c:v", "copy"]

    cmd += ["-c:a", "aac", "-q:a", "2", "-shortest", str(out_path)]

    subprocess.run(cmd, check=True)

    if subtitle_path:
        tmp_ass = Path("_yt_karaoke_subs_temp.ass")
        if tmp_ass.exists():
            tmp_ass.unlink()

    log.info("Final video created: %s", out_path)
    return out_path


# ---------------------------------------------------------------------------
# Step 5 – Cleanup
# ---------------------------------------------------------------------------

def cleanup(*paths: Path) -> None:
    for p in paths:
        if not p.exists():
            continue
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            log.info("Removed: %s", p)
        except OSError as exc:
            log.warning("Could not remove %s: %s", p, exc)


def _clean_lyrics_local(text: str) -> str:
    lines = text.split("\n")
    cleaned = []
    for l in lines:
        s = l.strip()
        if not s:
            continue
        if len(s) > 100:
            continue
        if re.match(r"^\d+\s+Contributors?", s, re.IGNORECASE):
            continue
        if re.match(
            r"^[\w\s\-–—'´`()《》\[\]【】<>「」]+(?:Lyrics|歌詞)\s*$",
            s, re.IGNORECASE,
        ) and len(s) < 60:
            continue
        s = re.sub(r"^\[.*?\]\s*", "", s).strip()
        if not s:
            continue
        if not cleaned or s.lower() != cleaned[-1].lower():
            cleaned.append(s)
    return "\n".join(cleaned)


# ── Resolution lookup ──────────────────────────────────────────

RESOLUTION_MAP: dict[str, int] = {
    "1080p": 1080,
    "1440p(2K)": 1440,
    "2160p(4K)": 2160,
}

RESOLUTION_LABEL: dict[int, str] = {v: k for k, v in RESOLUTION_MAP.items()}


# ---------------------------------------------------------------------------
#  Two-stage checkpoint (align-only → verify → burn-only)
# ---------------------------------------------------------------------------

def _checkpoint_base(output_dir: Path) -> Path:
    return output_dir / "checkpoints"


def _save_checkpoint(output_dir: Path, video_path: Path, accomp_path: Path,
                     vocals_path: Path, subtitle_path: Path | None,
                     meta: dict) -> Path:
    """Copy Stage-1 artifacts into checkpoints/<video_stem>/ for Stage 2."""
    base = _checkpoint_base(output_dir)
    ckpt_dir = base / video_path.stem
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    for old in ckpt_dir.iterdir():
        if old.is_file():
            old.unlink()
    shutil.copy2(video_path, ckpt_dir / video_path.name)
    shutil.copy2(accomp_path, ckpt_dir / "accompaniment.wav")
    shutil.copy2(vocals_path, ckpt_dir / "vocals.wav")
    if subtitle_path and subtitle_path.exists():
        shutil.copy2(subtitle_path, ckpt_dir / "karaoke.ass")
        srt = subtitle_path.with_suffix(".srt")
        if srt.exists():
            shutil.copy2(srt, ckpt_dir / "karaoke.srt")
        summary = subtitle_path.with_name(subtitle_path.stem + "_summary.txt")
        if summary.exists():
            shutil.copy2(summary, ckpt_dir / "karaoke_summary.txt")
    meta.update({
        "video_name": video_path.name,
        "accomp_name": "accompaniment.wav",
        "vocals_name": "vocals.wav",
    })
    (ckpt_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return ckpt_dir


def _find_latest_checkpoint(output_dir: Path) -> Path | None:
    base = _checkpoint_base(output_dir)
    if not base.exists():
        return None
    dirs = [d for d in base.iterdir()
            if d.is_dir() and (d / "meta.json").exists()]
    if not dirs:
        return None
    return max(dirs, key=lambda d: d.stat().st_mtime)


def _time_str_to_sec(t: str) -> float:
    parts = t.strip().split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(t)


def _parse_lyrics_blocks(text: str, track_duration: float):
    """Parse inline #SILENCE directives into alignment blocks.

    Inline format: a #SILENCE line between lyric lines marks an audio gap.
        #SILENCE 0:00-0:34          <- gap before the first block
        <line1>||<translation>
        ...
        <lineN>||<translation>
        #SILENCE 4:25-4:54          <- gap between blocks
        <lineN+1>||<translation>

    Returns (chunks, blocks, ranges):
      chunks — list of raw text per block (directives removed, || kept)
      blocks — list of (chunk_text, audio_start, audio_end) per block
      ranges — list of (start_sec, end_sec) silence gaps
    """
    blocks: list[tuple[str, float, float]] = []
    ranges: list[tuple[float, float]] = []
    cur: list[str] = []
    pending_start = 0.0
    for line in text.split("\n"):
        s = line.strip()
        if s.upper().startswith("#SILENCE"):
            spec = s.split(None, 1)
            gap = (0.0, 0.0)
            if len(spec) > 1:
                pairs = [p for p in spec[1].split(",") if p.strip()]
                if pairs and "-" in pairs[0]:
                    a, b = pairs[0].split("-", 1)
                    gap = (_time_str_to_sec(a), _time_str_to_sec(b))
                    ranges.append(gap)
            if cur:
                blocks.append(("\n".join(cur), pending_start, gap[0]))
                cur = []
            pending_start = max(gap[1], pending_start)
        else:
            cur.append(line)
    if cur:
        blocks.append(("\n".join(cur), pending_start, track_duration))
    chunks = [b[0] for b in blocks]
    return chunks, blocks, ranges


def _align_blocks(model, vocals_path: Path, workdir: Path,
                  blocks: list[tuple[str, float, float]]) -> list[dict]:
    """Align each lyrics block against its own audio slice, offset-merged.

    Long audio gaps (harmony/interludes marked with #SILENCE) are CUT out of
    the alignment input entirely, so whisper transcribes short contiguous
    audio chunks and cannot drift or collapse across the gap.
    """
    import soundfile as sf

    y, sr = sf.read(str(vocals_path), dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    all_words: list[dict] = []
    for bi, (chunk, s0, s1) in enumerate(blocks):
        if not chunk.strip():
            continue
        i0, i1 = max(0, int(s0 * sr)), min(len(y), int(s1 * sr))
        if i1 - i0 < sr:  # block shorter than 1s — skip
            continue
        tmp = workdir / f"_block{bi}.wav"
        sf.write(str(tmp), y[i0:i1], sr)
        res = model.align(str(tmp), _clean_for_alignment(chunk), language="zh")
        if res is None:
            log.warning("Block %d align returned None — skipping", bi)
            continue
        for sgm in res.segments:
            for w in (sgm.words or []):
                wt = w.word if hasattr(w, "word") else w.get("word", "")
                ws = float(w.start if hasattr(w, "start") else w.get("start", 0))
                we = float(w.end if hasattr(w, "end") else w.get("end", 0))
                all_words.append({"word": wt, "start": ws + s0, "end": we + s0})
        log.info("Block %d aligned: [%6.1f -> %6.1f] %d words",
                 bi, s0, s1, len(all_words))
    return all_words


# ---------------------------------------------------------------------------
#  Entry point
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download a YouTube video, remove vocals, and produce "
                    "a karaoke video (manual or auto-fetch lyrics).",
    )
    parser.add_argument("url", nargs="?", help="YouTube video URL")
    parser.add_argument(
        "--lyrics", "-l",
        default=Path("lyrics_input.txt"),
        type=Path,
        help="Path to lyrics file (default: lyrics_input.txt).",
    )
    parser.add_argument(
        "--output", "-o",
        default=Path.cwd(),
        type=Path,
    )
    parser.add_argument(
        "--whisper-model", "-m",
        default="turbo",
        choices=("tiny", "base", "small", "medium", "large", "turbo"),
    )
    parser.add_argument(
        "--mode",
        default="full",
        choices=("full", "lyrics_only", "vocal_only"),
    )
    parser.add_argument(
        "--pitch",
        type=int,
        default=0,
        help="Pitch shift in semitones (-12 to +12). Negative=lower, positive=raise. "
             "Uses FFmpeg rubberband filter.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
    )
    parser.add_argument(
        "--keep-vocals",
        action="store_true",
    )
    parser.add_argument(
        "--align-only",
        action="store_true",
        help="Stage 1: stop after forced alignment. Saves a checkpoint "
             "(karaoke.ass/.srt, video, accompaniment, vocals) under "
             "checkpoints/<title>/ WITHOUT burning subtitles. "
             "Verify karaoke.srt, then run --burn-only.",
    )
    parser.add_argument(
        "--burn-only",
        action="store_true",
        help="Stage 2: resume from the latest checkpoint and burn subtitles "
             "+ analyze + Music Bank. Skips download/Demucs/alignment. "
             "Pitch/artist/analyze/resolution are restored from meta.json.",
    )
    parser.add_argument(
        "--cookies-from-browser",
        default=None,
        metavar="BROWSER",
    )
    parser.add_argument(
        "--resolution", "-r",
        default="1080p",
        choices=list(RESOLUTION_MAP.keys()),
        help="Output video resolution (default: 1080p). Falls back to highest available if source is lower.",
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Analyze vocal range after separation, rename file to include range info.",
    )
    parser.add_argument(
        "--music-bank",
        type=Path,
        default=Path(r"C:\Users\user\iCloudDrive\iCloud~md~obsidian\HappyUltimate\Music_Bank\generate_bank.py"),
        help="Path to generate_bank.py for auto-adding analyzed songs.",
    )
    parser.add_argument(
        "--artist", "-a",
        default="",
        help="Artist name for filename & Music Bank (e.g. 'IU', '林志炫').",
    )
    return parser.parse_args(argv)


def _analyze_and_rename(vocals_path: Path, final_path: Path, pitch: int,
                         music_bank: Path | None, song_name: str,
                         artist: str = "") -> Path:
    """
    Analyze vocals for key + vocal range using librosa.
    Rename final_path to include range info.
    Optionally append to generate_bank.py's SONGS list.
    Returns the new (renamed) path.
    """
    import librosa
    import numpy as np
    import re as _re
    import sys as _sys
    # Fix Hermes venv contamination for scipy/librosa
    _sys.path = [p for p in _sys.path if 'hermes' not in p.lower()]
    import site as _site
    _site.addsitedir(_site.getusersitepackages())

    if not vocals_path or not vocals_path.exists():
        log.warning("Vocals not available for analysis")
        return final_path

    try:
        log.info("🔬 Analyzing vocal range …")
        y, sr = librosa.load(str(vocals_path), sr=22050)

        # ── Key detection (Krumhansl-Schmuckler) ──
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        chroma_mean = np.mean(chroma, axis=1)
        major_t = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                            2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
        minor_t = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                            2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
        notes = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        best = (-999, '', '')
        for i in range(12):
            for mode, tmpl in [('Maj', major_t), ('min', minor_t)]:
                s = np.corrcoef(chroma_mean, np.roll(tmpl, i))[0, 1]
                if s > best[0]:
                    best = (s, notes[i], mode)

        # ── Vocal range (pYIN) ──
        f0, voiced, _ = librosa.pyin(y, fmin=65, fmax=1046, sr=sr, fill_na=np.nan)
        f0_clean = f0[~np.isnan(f0)]

        if len(f0_clean) < 100:
            log.warning("Not enough vocal data for range detection")
            return final_path

        low_hz = np.percentile(f0_clean, 2)
        high_hz = np.percentile(f0_clean, 98)
        low_note = librosa.hz_to_note(low_hz).replace('♯', '#')
        high_note = librosa.hz_to_note(high_hz).replace('♯', '#')
        semitones = librosa.hz_to_midi(high_hz) - librosa.hz_to_midi(low_hz)

        range_tag = f"{low_note}-{high_note}"
        key_tag = f"{best[1]}{best[2]}"

        log.info(f"📊  Key: {key_tag}  |  Range: {range_tag} ({semitones:.0f} semitones)")

        # ── Rename final file: Artist_Song_pitch_Range.mp4 ──
        parent = final_path.parent

        # Clean song name for filename (remove special chars)
        clean_song = _re.sub(r'[^\w\s-]', '', song_name).strip()
        clean_song = _re.sub(r'\s+', '_', clean_song)[:50]

        pitch_str = f"{pitch:+d}" if pitch != 0 else "0"
        range_tag = f"{low_note}-{high_note}"

        if artist:
            new_name = f"{artist}_{clean_song}_{pitch_str}_{range_tag}.mp4"
        else:
            new_name = f"{clean_song}_{pitch_str}_{range_tag}.mp4"

        new_path = parent / new_name

        # Avoid collision
        counter = 1
        while new_path.exists():
            stem_base = new_name.rsplit('.', 1)[0]
            if artist:
                new_name = f"{artist}_{clean_song}_{counter}_{pitch_str}_{range_tag}.mp4"
            else:
                new_name = f"{clean_song}_{counter}_{pitch_str}_{range_tag}.mp4"
            new_path = parent / new_name
            counter += 1

        try:
            final_path.rename(new_path)
            log.info(f"📁 {new_path.name}")
        except Exception:
            log.warning(f"Could not rename to {new_name}, keeping original")

        # ── Update Music Bank ──
        if music_bank and music_bank.exists():
            _add_to_music_bank(music_bank, song_name, low_note, high_note, pitch, artist)

        return new_path

    except Exception as e:
        log.warning(f"Analysis failed: {e}")
        return final_path


def _add_to_music_bank(music_bank: Path, song_name: str,
                        low_note: str, high_note: str, pitch: int,
                        artist: str = "") -> None:
    """Append a new song entry to generate_bank.py's SONGS list."""
    import re as _re

    try:
        content = music_bank.read_text(encoding='utf-8')
        pitch_str = f"{pitch:+d}" if pitch != 0 else "±0"
        artist_clean = artist if artist else "—"
        new_entry = f'    ("{song_name}", "{low_note}", "{high_note}", "{pitch_str}", 2, "4", "{artist_clean}"),'

        # Insert before the last ']' in the SONGS list
        lines = content.split('\n')
        # Find the SONGS list section and add
        in_songs = False
        inserted = False
        new_lines = []
        for line in lines:
            if '# === SONGS ===' in line:
                in_songs = True
            if in_songs and line.strip().startswith(']') and not inserted:
                new_lines.append(new_entry)
                inserted = True
            new_lines.append(line)

        if inserted:
            music_bank.write_text('\n'.join(new_lines), encoding='utf-8')
            log.info(f"📝 Added to Music Bank: {song_name} {low_note}-{high_note}")
    except Exception as e:
        log.warning(f"Music Bank update failed: {e}")


def main() -> None:
    args = parse_args()
    mode = args.mode
    check_dependencies(mode)

    if args.align_only and args.burn_only:
        log.error("--align-only and --burn-only are mutually exclusive.")
        sys.exit(1)

    url = args.url
    if not url and not args.burn_only:
        url = input("YouTube video URL: ").strip()
    if not url and not args.burn_only:
        log.error("No URL provided.")
        sys.exit(1)

    need_karaoke = mode in ("full", "lyrics_only")
    need_demucs = mode in ("full", "vocal_only")

    lyrics_text: str | None = None
    lyrics_path = args.lyrics
    if not args.burn_only and need_karaoke and lyrics_path.exists():
        raw = lyrics_path.read_text(encoding="utf-8").strip()
        if raw:
            raw = _clean_lyrics_local(raw)
            lines = raw.split("\n")
            lyrics_text = raw
            log.info("Track A: loaded %d lines from %s", len(lines), lyrics_path.name)
        else:
            log.info("Track B: %s is empty → will auto-fetch lyrics",
                     lyrics_path.name)
    elif not args.burn_only and need_karaoke:
        log.info("Track B: no lyrics file → will auto-fetch lyrics")

    if mode == "lyrics_only" and not lyrics_text and not args.burn_only:
        log.error("lyrics_only mode requires --lyrics with a non-empty file.")
        sys.exit(1)

    video_info = None
    if not args.burn_only and need_karaoke and not lyrics_text:
        video_info = _get_video_info(url)

    # Resolve resolution to max height
    res_key = args.resolution
    max_height = RESOLUTION_MAP.get(res_key, 1080)
    log.info("Target resolution: %s (max height=%d)", res_key, max_height)

    _from_checkpoint = False
    if args.burn_only:
        ckpt_dir = _find_latest_checkpoint(args.output.resolve())
        if ckpt_dir is None:
            log.error("No checkpoint found under %s — run --align-only first.",
                      _checkpoint_base(args.output.resolve()))
            sys.exit(1)
        meta = json.loads((ckpt_dir / "meta.json").read_text(encoding="utf-8"))
        video_path = ckpt_dir / meta["video_name"]
        accomp_path = ckpt_dir / meta["accomp_name"]
        vocals_path = ckpt_dir / meta["vocals_name"]
        subtitle_path = ckpt_dir / "karaoke.ass"
        if not subtitle_path.exists():
            log.error("Checkpoint missing karaoke.ass: %s", ckpt_dir)
            sys.exit(1)
        # Restore Stage-1 settings from meta.json
        args.pitch = int(meta.get("pitch", 0))
        if meta.get("artist"):
            args.artist = meta["artist"]
        args.analyze = bool(meta.get("analyze", args.analyze))
        max_height = int(meta.get("max_height", max_height))
        need_demucs = True  # separation already happened in Stage 1
        _from_checkpoint = True
        workdir = ckpt_dir
        log.info("🔥 Burn-only: resuming from checkpoint %s (pitch=%+d, artist=%s, analyze=%s)",
                 ckpt_dir.name, args.pitch, args.artist or "(none)", args.analyze)
    else:
        tmpdir = tempfile.mkdtemp(prefix="yt_karaoke_")
        workdir = Path(tmpdir)
        log.info("Working in temporary directory: %s", workdir)

    try:
        if not _from_checkpoint:
            video_path, audio_path = download_video(
                url, workdir,
                max_height=max_height,
                cookies_from_browser=args.cookies_from_browser,
            )

            if need_demucs:
                accomp_path, vocals_path = separate_audio(audio_path, workdir)
            else:
                accomp_path = audio_path
                vocals_path = audio_path

            subtitle_path: Path | None = None
            if need_karaoke:
                subtitle_path = generate_karaoke(
                    vocals_path, workdir,
                    lyrics_text=lyrics_text,
                    model_name=args.whisper_model,
                    video_info=video_info,
                )

            if args.align_only:
                meta = {
                    "pitch": args.pitch,
                    "artist": args.artist,
                    "analyze": args.analyze,
                    "max_height": max_height,
                }
                ckpt = _save_checkpoint(args.output.resolve(), video_path,
                                        accomp_path, vocals_path, subtitle_path, meta)
                log.info("✅ Checkpoint saved: %s", ckpt)
                log.info("   Verify karaoke.srt + karaoke_summary.txt, then run --burn-only")
                return

        final_path = remux(video_path, accomp_path, args.output.resolve(),
                           subtitle_path=subtitle_path, pitch=args.pitch,
                           max_height=max_height)

        if args.keep_vocals and need_demucs:
            dest = args.output.resolve() / f"{video_path.stem}_vocals.wav"
            shutil.copy2(vocals_path, dest)

        # ── Analyze vocal range + rename + Music Bank ──
        if args.analyze and need_demucs:
            # Extract clean song name from video title
            import re as _re2
            vid_title = video_path.stem
            
            # Step 1: Remove all bracketed content 【】, [], ()
            clean = _re2.sub(r'[【\[\(][^】\]\)]*[】\]\)]', '', vid_title)
            # Step 2: Remove artist prefix if specified (case-insensitive)
            if args.artist:
                clean = _re2.sub(_re2.escape(args.artist), '', clean, flags=_re2.IGNORECASE)
            # Step 3: Remove Korean artist name in parentheses (아이유)
            clean = _re2.sub(r'\([^)]*\)', '', clean)
            # Step 4: Split on common separators and take the main title
            # Look for English title segment (most reliable)
            parts = _re2.split(r'[-–—|｜]', clean)
            # Pick the longest segment that has meaningful content
            if len(parts) > 1:
                # Prefer segment with English letters that isn't OST/cover info
                best = ''
                for p in parts:
                    p = p.strip()
                    if _re2.search(r'[A-Za-z]{3,}', p) and not _re2.search(r'(OST|Cover|Live|M[Vv]|Official)', p, _re2.IGNORECASE):
                        best = p
                        break
                if not best:
                    best = parts[0].strip()
                clean = best
            
            # Step 5: Remove common noise words at end
            clean = _re2.sub(r'\s*(OST|M[Vv]|Official|Music|Video|Live|Concert|Lyrics|歌詞|中字|繁中|字幕|Part\d*)\s*', '', clean, flags=_re2.IGNORECASE)
            # Step 6: Clean up whitespace and trim
            clean = _re2.sub(r'\s+', ' ', clean).strip()
            clean = clean.strip('-_ \t.')
            
            # Fallback if too short
            if len(clean) < 3:
                clean = vid_title.split('-')[0].split('|')[0].split('—')[0].strip()[:40]
            
            song_name = clean[:40]
            log.info(f"🎵 Detected song: {song_name}")
            final_path = _analyze_and_rename(
                vocals_path, final_path, args.pitch,
                args.music_bank, song_name, args.artist
            )

        if need_karaoke and lyrics_text and lyrics_path and lyrics_path.exists():
            lyrics_path.write_text("", encoding="utf-8")
            log.info("Cleared lyrics file: %s", lyrics_path.name)

        log.info("Done!  File created: %s", final_path)

    finally:
        if not args.keep_temp:
            cleanup(workdir)


if __name__ == "__main__":
    main()