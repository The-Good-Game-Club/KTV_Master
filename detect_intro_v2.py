#!/usr/bin/env python3
"""Better vocal start detection using high-frequency band + onset patterns."""
import json
import numpy as np
import librosa

WAV = r"C:\Users\user\Desktop\KTV_Master_v2\tmp\故事還有呢.wav"
y, sr = librosa.load(WAV, sr=16000, mono=True)

frame_len = int(0.05 * sr)
hop = frame_len // 2

# STFT
D = librosa.stft(y, n_fft=frame_len, hop_length=hop)
mag = np.abs(D)
freqs = librosa.fft_frequencies(sr=sr, n_fft=frame_len)
times = librosa.frames_to_time(np.arange(mag.shape[1]), sr=sr, hop_length=hop)

# High-frequency energy bands
# Vocal formants: ~500-3000Hz
vocal_mask = (freqs >= 500) & (freqs <= 3000)
# Low/mid instruments: <500Hz
bass_mask = freqs < 500
# High hiss/cymbals: >3000Hz
high_mask = freqs > 3000

vocal_energy = np.sqrt((mag[vocal_mask]**2).mean(axis=0))
bass_energy = np.sqrt((mag[bass_mask]**2).mean(axis=0))
high_energy = np.sqrt((mag[high_mask]**2).mean(axis=0))

# Ratio: vocal vs bass (goes up when singing starts)
vocal_ratio = np.where(bass_energy > 0.001, vocal_energy / (bass_energy + 1e-10), 0)

# Smooth
window = 5  # ~0.5s
vocal_ratio_smooth = np.convolve(vocal_ratio, np.ones(window)/window, mode='same')

# Find when vocal_ratio crosses threshold AND stays high
vocal_start = None
for i in range(20, len(vocal_ratio_smooth) - 20):
    window_after = vocal_ratio_smooth[i:i+20]
    window_before = vocal_ratio_smooth[i-20:i]
    
    # Mean vocal ratio before vs after
    after_mean = window_after.mean()
    before_mean = window_before.mean()
    
    # Also check absolute vocal energy
    if (after_mean > before_mean * 2.5 and 
        after_mean > 0.3 and
        vocal_energy[i] > 0.01):
        vocal_start = times[i]
        break

# Fallback: just find where high freq energy jumps by 2x
if vocal_start is None or vocal_start > 30:
    for i in range(10, len(vocal_energy) - 10):
        if vocal_energy[i] > 0.005 and vocal_energy[i] > vocal_energy[i-10] * 2.0:
            vocal_start = times[i]
            break

if vocal_start is None:
    vocal_start = 0

# Print analysis
print(f"Detected vocal start: {vocal_start:.1f}s")
print(f"Song duration: {len(y)/sr:.1f}s")

# Detail of first 35s
print(f"\nFirst 35s vocal/bass ratio heatmap:")
for i, t in enumerate(times):
    if t > 35: break
    if i % 5 == 0:
        bar = "█" * min(int(vocal_ratio_smooth[i] * 20), 60)
        marker = "  ⬅️ VOCAL START" if abs(t - vocal_start) < 0.3 else ""
        if bar.strip():
            print(f"  {t:5.1f}s {bar} (voc:{vocal_energy[i]:.3f} bass:{bass_energy[i]:.3f}){marker}")

padding = max(3, int(vocal_start / 1.8))
print(f"\n✅ Intro: {vocal_start:.1f}s → {padding} padding lines (♫)")
print(json.dumps({"intro_seconds": round(vocal_start, 1), "padding_lines": padding}))
