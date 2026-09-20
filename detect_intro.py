#!/usr/bin/env python3
"""Detect where vocals/singing starts in a WAV file by analyzing
frequency-band energy. Outputs: intro_seconds, suggested_padding_lines."""

import sys, json
import numpy as np
import librosa

WAV = r"C:\Users\user\Desktop\KTV_Master_v2\tmp\故事還有呢.wav"

print(f"📂 Loading {WAV} …", flush=True)
y, sr = librosa.load(WAV, sr=22050, mono=True)  # downsample for speed
duration = len(y) / sr
print(f"   Duration: {duration:.1f}s, SR: {sr}Hz", flush=True)

# --- Method 1: Spectral centroid + high-frequency energy ratio ---
# Vocals have strong energy in 300-3000Hz range
# Instruments often dominate lower freq or have different spectral profile

frame_length = int(0.05 * sr)  # 50ms frames
hop_length = frame_length // 2

# RMS energy per frame
rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)

# Spectral centroid
centroid = librosa.feature.spectral_centroid(y=y, sr=sr,
    n_fft=frame_length, hop_length=hop_length)[0]

# Detect vocal presence: 
# 1) Centroid above a threshold (vocals ~500-3000Hz)
# 2) Combined with significant RMS energy (not silence)
# 3) Sustained for multiple frames (not a transient)

vocal_frames = []
for i in range(len(rms)):
    if rms[i] > 0.002 and centroid[i] > 400 and centroid[i] < 4000:
        vocal_frames.append(i)

# Find first sustained vocal activity (at least 10 consecutive frames = ~0.5s)
min_consecutive = 10
first_sustained = None
for i in range(len(rms) - min_consecutive):
    if all(f in vocal_frames for f in range(i, i + min_consecutive)):
        first_sustained = times[i + min_consecutive // 2]
        break

# Fallback: first frame where RMS exceeds 2x the median (simple energy burst)
if first_sustained is None or first_sustained > duration * 0.8:
    median_rms = np.median(rms)
    threshold = max(median_rms * 3, 0.005)
    for i, (t, e) in enumerate(zip(times, rms)):
        if e > threshold and all(rms[max(0,i-2):i+3].mean() > threshold):
            first_sustained = t
            break

# --- Method 2: Mel-spectrogram vocal band energy ---
mel = librosa.feature.melspectrogram(y=y, sr=sr, n_fft=frame_length,
    hop_length=hop_length, n_mels=128)
mel_db = librosa.power_to_db(mel, ref=np.max)

# Vocal bands (mel bins ~300-3000Hz): roughly mel bands 15-70
vocal_band = mel_db[15:71, :].mean(axis=0)
full_band = mel_db.mean(axis=0)

# Ratio: vocal band vs full spectrum
ratio = np.where(full_band > -60, vocal_band - full_band, -60)

# First sustained (0.5s) time where vocal band ratio > threshold
ratio_vocal_start = None
thresh_ratio = 2.0  # dB
for i in range(len(ratio) - min_consecutive):
    window = ratio[i:i+min_consecutive]
    if window.mean() > thresh_ratio:
        ratio_vocal_start = times[i + min_consecutive // 2]
        break

print(f"\n📊 Results:")
print(f"   Spectral + RMS method: {first_sustained:.1f}s" if first_sustained else "   Spectral + RMS method: NOT FOUND")
print(f"   Mel vocal-band ratio:  {ratio_vocal_start:.1f}s" if ratio_vocal_start else "   Mel vocal-band ratio:   NOT FOUND")

# Use the most reliable method
vocal_start = None
if ratio_vocal_start and first_sustained:
    # Pick the earlier but stable detection
    vocal_start = min(ratio_vocal_start, first_sustained)
elif ratio_vocal_start:
    vocal_start = ratio_vocal_start
elif first_sustained:
    vocal_start = first_sustained

# Also check by looking at 12-sec intervals to verify
print(f"\n📈 Energy heatmap (10-frame blocks):")
step = 10
for i in range(0, len(rms), step):
    block = rms[i:i+step]
    block_t = times[i]
    if block_t > vocal_start - 3 and block_t < vocal_start + 3:
        marker = " ⬅️  VOCAL START"
    else:
        marker = ""
    bar_len = int(block.mean() * 5000)
    if bar_len > 0 or vocal_start is None:
        print(f"   {block_t:5.1f}s {'█' * min(bar_len, 60)} {marker}")

if vocal_start:
    padding_pairs = int(vocal_start / 1.5)  # each ♫ line ~1.5s at 2x playback
    padding_lines = max(3, padding_pairs)
    print(f"\n✅ INTRO: {vocal_start:.1f}s → suggested {padding_lines} padding lines (♫)")
    print(json.dumps({"intro_seconds": round(vocal_start, 1), "padding_lines": padding_lines}))
else:
    print(f"\n❌ Could not detect vocal start. Suggest manual: 8 lines for safety.")
    print(json.dumps({"intro_seconds": 0, "padding_lines": 8}))
