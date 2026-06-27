"""
analyze_song.py — YouTube 歌曲 Key + 音域分析

用法:
  python3 analyze_song.py https://youtu.be/xxxxx
  
Output:
  🎵 Key: B♭ Major (confidence: 0.842)
  🎤 Vocal Range: G3 — D5 (21 semitones)

整合 KTV pipeline:
  KTV.py 完成 Demucs 後 → 保留 vocals.wav → 行呢個 script → 結果寫入 generate_bank.py
"""

import argparse, json, os, sys, tempfile, shutil

# ---- Fix Hermes venv contamination ----
sys.path = [p for p in sys.path if 'hermes' not in p.lower()]
import site
site.addsitedir(site.getusersitepackages())

import librosa
import numpy as np


def extract_audio(youtube_url: str, workdir: str) -> str:
    """Download audio from YouTube using yt-dlp. Returns path to WAV."""
    import subprocess, shutil as sh
    
    py = r'C:\ProgramData\chocolatey\bin\python3.14.exe'  # has yt_dlp installed
    out_template = os.path.join(workdir, 'input.%(ext)s')
    
    result = subprocess.run([py, '-m', 'yt_dlp', '-f', 'bestaudio', '-x',
                              '--audio-format', 'wav',
                              '-o', out_template,
                              youtube_url],
                             capture_output=True, text=True, timeout=120)
    
    if result.returncode != 0:
        print(f"yt-dlp error: {result.stderr[:200]}")
        # Fallback: try without audio format conversion
        result = subprocess.run([py, '-m', 'yt_dlp', '-f', 'bestaudio',
                                  '-o', out_template,
                                  youtube_url],
                                 capture_output=True, text=True, timeout=120)
    
    # Find resulting file
    for f in os.listdir(workdir):
        fp = os.path.join(workdir, f)
        if os.path.isfile(fp) and not f.endswith('.part'):
            return fp
    
    # If we got here, try converting manually
    for f in os.listdir(workdir):
        if os.path.isfile(os.path.join(workdir, f)) and not f.endswith('.part'):
            fp = os.path.join(workdir, f)
            wav_path = fp.rsplit('.', 1)[0] + '.wav'
            if fp != wav_path:
                subprocess.run(['ffmpeg', '-i', fp, '-ac', '1', '-ar', '22050',
                                wav_path, '-y'],
                               capture_output=True, timeout=60)
                return wav_path
            return fp
    return ''


def detect_key(y, sr) -> tuple:
    """Detect musical key using Krumhansl-Schmuckler algorithm."""
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    chroma_mean = np.mean(chroma, axis=1)
    
    major_template = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 
                               2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor_template = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 
                               2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
    note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    note_names_unicode = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    
    best_score = -999
    best_key = ''
    best_mode = ''
    
    for i in range(12):
        for mode, tmpl in [('Major', major_template), ('Minor', minor_template)]:
            score = np.corrcoef(chroma_mean, np.roll(tmpl, i))[0, 1]
            if score > best_score:
                best_score = score
                best_key = note_names_unicode[i]
                best_mode = mode
    
    return best_key, best_mode, best_score


def detect_vocal_range(y, sr) -> dict:
    """Detect vocal range using pYIN pitch tracking."""
    fmin = librosa.note_to_hz('C2')
    fmax = librosa.note_to_hz('C6')
    
    f0, voiced_flag, _ = librosa.pyin(y, fmin=fmin, fmax=fmax, sr=sr, fill_na=np.nan)
    f0_clean = f0[~np.isnan(f0)]
    
    if len(f0_clean) < 100:
        return {"error": "Not enough voiced segments"}
    
    # Use percentiles to filter noise
    min_hz = np.percentile(f0_clean, 2)
    max_hz = np.percentile(f0_clean, 98)
    
    min_note = librosa.hz_to_note(min_hz)
    max_note = librosa.hz_to_note(max_hz)
    
    min_midi = librosa.hz_to_midi(min_hz)
    max_midi = librosa.hz_to_midi(max_hz)
    semitone_range = max_midi - min_midi
    
    return {
        "lowest_note": min_note,
        "highest_note": max_note,
        "lowest_hz": round(min_hz, 1),
        "highest_hz": round(max_hz, 1),
        "semitone_range": round(semitone_range, 1),
        "octave_range": round(semitone_range / 12, 2)
    }


def analyze(audio_path: str) -> dict:
    """Full analysis of a WAV file."""
    print(f"📂 載入: {os.path.basename(audio_path)}")
    y, sr = librosa.load(audio_path, sr=None)
    duration = len(y) / sr
    print(f"⏱️  時長: {duration:.1f}s | 採樣率: {sr}Hz")
    
    # Key detection
    print("🎵 分析 Key...")
    key, mode, conf = detect_key(y, sr)
    
    # Vocal range
    print("🎤 分析音域...")
    range_info = detect_vocal_range(y, sr)
    
    result = {
        "key": f"{key} {mode}",
        "key_confidence": round(conf, 3),
        **range_info
    }
    return result


def format_result(r: dict) -> str:
    """Format analysis result for display."""
    lines = []
    lines.append("\n📊 === 歌曲分析報告 ===")
    lines.append(f"🎵  Key: {r['key']} (confidence: {r.get('key_confidence', '?')})")
    
    if 'error' not in r:
        lines.append(f"🎤  音域: {r['lowest_note']} — {r['highest_note']}")
        lines.append(f"📐  跨度: {r['semitone_range']} 半音 ({r['octave_range']} 八度)")
        lines.append(f"📝  建議格式:  (\"歌名\", \"{r['lowest_note']}\", \"{r['highest_note']}\", \"-3\", 難度, \"顏色\", \"歌手\"),")
    else:
        lines.append(f"❌  {r['error']}")
    
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze song key and vocal range")
    parser.add_argument("url", nargs="?", help="YouTube URL")
    parser.add_argument("--file", "-f", help="Local WAV file (skip download)")
    parser.add_argument("--keep", action="store_true", help="Keep temp files")
    args = parser.parse_args()
    
    workdir = tempfile.mkdtemp(prefix="analyze_")
    
    try:
        if args.file:
            audio_path = args.file
        elif args.url:
            print("⬇️  下載音訊...")
            audio_path = extract_audio(args.url, workdir)
            print(f"✅ 下載完成: {os.path.basename(audio_path)}")
        else:
            print("用法: python3 analyze_song.py <YouTube_URL>")
            print("  或: python3 analyze_song.py --file <path/to/vocals.wav>")
            sys.exit(1)
        
        result = analyze(audio_path)
        print(format_result(result))
        
    finally:
        if not args.keep:
            shutil.rmtree(workdir, ignore_errors=True)
