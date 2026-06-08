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

  Use a specific Whisper model (default: base):
      python KTV.py "URL" --lyrics my_lyrics.txt -m tiny   (fast)
      python KTV.py "URL" --lyrics my_lyrics.txt -m medium (accurate)

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
  base   (default, good balance)
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
    "fontsize": 96,
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
                   cookies_from_browser: str | None = None) -> tuple[Path, Path]:
    log.info("Downloading video from %s …", url)
    video_out = workdir / "%(title)s.%(ext)s"
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/mp4",
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
        "-f", "bestaudio/best",
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
    """Prepare lyrics for stable-ts forced alignment. Preserves line breaks."""
    text = _clean_metadata(text)
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    return "\n".join(lines)


def _split_segments(result) -> None:
    """Break oversized segments into KTV-friendly lines using stable-ts utilities."""
    if hasattr(result, "split_by_gap"):
        result.split_by_gap(0.5)
    if hasattr(result, "split_by_length"):
        result.split_by_length(max_chars=LINE_MAX_CHARS)


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
                for char in line:
                    if char.isspace():
                        # Keep original layout whitespace intact without breaking ASS tags
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
                                dur_cs = max(1, int(round((cs_end - cs_start) * 100)))
                            
                            parts.append(f"{{\\k{dur_cs}}}{char}")
                            ct_idx += 1
                        else:
                            parts.append(f"{{\\k1}}{char}")
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
                            parts.append(f"{{\\k{dur_cs}}}{c}")
                else:
                    text = seg.text.strip() if hasattr(seg, "text") else str(seg.get("text", "")).strip()
                    if not text:
                        continue
                    dur = max(e - s, 0.01)
                    cs = max(1, int(round(dur * 100 / len(text))))
                    parts.extend(f"{{\\k{cs}}}{c}" for c in text)

            prev_end = e
            f.write(
                f"Dialogue: 0,{_secs_to_ass(display_start)},{_secs_to_ass(e)},"
                f"{ASS_STYLE['name']},,0,0,0,,{' '.join(parts)}\n"
            )


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

    clean_text = _clean_for_alignment(ref)
    log.info("Cleaned lyrics: %d chars for forced alignment", len(clean_text))

    if not hasattr(model, "align"):
        log.warning("stable-ts align() not available; falling back to transcribe")
        result = model.transcribe(str(vocals_path))
        _split_segments(result)
        _write_ass_from_alignment(ass_path, result)
        log.info("Karaoke subtitles written to %s (transcribe fallback)",
                 ass_path.name)
        return ass_path

    try:
        log.info("Running forced alignment (stable-ts align) …")
        result = model.align(str(vocals_path), clean_text, language="zh")
        if result is None:
            raise RuntimeError("align() returned None")
        
        # Core Improvement: Map AI outputs strictly back to the original text layout structures
        log.info("Re-segmenting alignment results to perfectly match original lines...")
        all_words = []
        for seg in result.segments:
            if hasattr(seg, "words") and seg.words:
                all_words.extend(seg.words)
        
        lines = [l.strip() for l in clean_text.split("\n") if l.strip()]
        new_segments = []
        w_idx = 0
        
        for line in lines:
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
                class LineSegment:
                    def __init__(self, text, words):
                        self.text = text
                        self.words = words
                        self.start = words[0].start if hasattr(words[0], "start") else words[0].get("start", 0)
                        self.end = words[-1].end if hasattr(words[-1], "end") else words[-1].get("end", 0)
                new_segments.append(LineSegment(line, line_words))
        
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

def remux(video_path: Path, accomp_path: Path, output_dir: Path,
          subtitle_path: Path | None = None, pitch: int = 0) -> Path:
    stem = video_path.stem
    pitch_tag = ""
    if pitch != 0:
        pitch_tag = f"_pitch{pitch:+d}"
    if subtitle_path:
        out_name = stem + pitch_tag + "_instrumental_karaoke.mp4"
    else:
        out_name = stem + pitch_tag + "_instrumental.mp4"
    out_path = output_dir / out_name

    # Avoid collision when same song is processed concurrently
    counter = 1
    while out_path.exists():
        suffix = f"_{counter}"
        if subtitle_path:
            out_name = stem + pitch_tag + suffix + "_instrumental_karaoke.mp4"
        else:
            out_name = stem + pitch_tag + suffix + "_instrumental.mp4"
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


# ---------------------------------------------------------------------------
# Entry point
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
        default="base",
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
        "--cookies-from-browser",
        default=None,
        metavar="BROWSER",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    mode = args.mode
    check_dependencies(mode)

    url = args.url
    if not url:
        url = input("YouTube video URL: ").strip()
    if not url:
        log.error("No URL provided.")
        sys.exit(1)

    need_karaoke = mode in ("full", "lyrics_only")
    need_demucs = mode in ("full", "vocal_only")

    lyrics_text: str | None = None
    lyrics_path = args.lyrics
    if need_karaoke and lyrics_path.exists():
        raw = lyrics_path.read_text(encoding="utf-8").strip()
        if raw:
            raw = _clean_lyrics_local(raw)
            lines = raw.split("\n")
            lyrics_text = raw
            log.info("Track A: loaded %d lines from %s", len(lines), lyrics_path.name)
        else:
            log.info("Track B: %s is empty → will auto-fetch lyrics",
                     lyrics_path.name)
    elif need_karaoke:
        log.info("Track B: no lyrics file → will auto-fetch lyrics")

    if mode == "lyrics_only" and not lyrics_text:
        log.error("lyrics_only mode requires --lyrics with a non-empty file.")
        sys.exit(1)

    video_info = _get_video_info(url) if need_karaoke and not lyrics_text else None

    tmpdir = tempfile.mkdtemp(prefix="yt_karaoke_")
    workdir = Path(tmpdir)
    log.info("Working in temporary directory: %s", workdir)

    try:
        video_path, audio_path = download_video(
            url, workdir,
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

        final_path = remux(video_path, accomp_path, args.output.resolve(),
                           subtitle_path=subtitle_path, pitch=args.pitch)

        if args.keep_vocals and need_demucs:
            dest = args.output.resolve() / f"{video_path.stem}_vocals.wav"
            shutil.copy2(vocals_path, dest)

        if need_karaoke and lyrics_text and lyrics_path and lyrics_path.exists():
            lyrics_path.write_text("", encoding="utf-8")
            log.info("Cleared lyrics file: %s", lyrics_path.name)

        log.info("Done!  File created: %s", final_path)

    finally:
        if not args.keep_temp:
            cleanup(workdir)


if __name__ == "__main__":
    main()