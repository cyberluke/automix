"""Render the DNA canvas: malugi 0-16 (vocal) DUPLICATED at bar 16 + 32-64.

Structure (80 bars total):
  bars 0-16   : vocal+melody (original, main drop entry bar 103)
  bars 16-32  : SAME vocal section duplicated (so energy doesn't drop)
  bars 32-64  : original middle/end (beat-only)
Gentle raised-cosine crossfade at the bar-16 join so the duplicate doesn't chop.
"""
import sys
sys.path.insert(0, '.')
from pathlib import Path
import numpy as np
import soundfile as sf

from src.hypermix.canonicalize import Canonicalizer
from src.hypermix.config import DEFAULT_CONFIG
from src.hypermix.audio_io import read_wav
from src.hypermix.analysis.automix_analyzer import AutomixAnalyzer

TRACK = Path('music/Malugi MCYL - Knees Break.mp4')
OUTDIR = Path('renders/malugi-phrases')
OUTDIR.mkdir(parents=True, exist_ok=True)

START_BAR = 103
# vocal block = bars 0-15 (bar 15 is the natural decay, rms 0.20). Duplicating
# 0-15 keeps the phrase whole; the beat (3rd part) then follows after the
# duplicate's natural decay instead of chopping it mid-phrase.
VOCAL_BARS = 16          # bars 0-16 (0-14 strong + 15 natural decay)
REST_START_BAR = 24      # 3rd part (beat) starts at original bar 24 -> continues
XFADE_MS = 60            # gentle join at the duplicate boundary

c = Canonicalizer(DEFAULT_CONFIG)
res = c.canonicalize(TRACK, c.default_private_root())
audio = read_wav(res.canonical_path)
a = AutomixAnalyzer(DEFAULT_CONFIG).analyze(audio, DEFAULT_CONFIG.phrase_bars)
sr = audio.sample_rate
bars = a.bars


def bar_range(b0, b1):
    s = bars[START_BAR + b0]
    e = bars[START_BAR + b1] if START_BAR + b1 < len(bars) else audio.n_samples
    return audio.samples[s:e]


vocal = bar_range(0, VOCAL_BARS)              # bars 0-16 (incl. bar-15 decay)
rest = bar_range(REST_START_BAR, 64)          # 3rd part: original bar 24-64


def xfade_join(a_seg, b_seg, ms):
    """Join b after a with a short equal-power raised-cosine crossfade."""
    n = int(sr * ms / 1000.0)
    n = min(n, len(a_seg), len(b_seg))
    t = np.linspace(0, np.pi, n, dtype=np.float32)
    fade_out = (0.5 * (1 + np.cos(t)))[:, None]
    fade_in = (0.5 * (1 - np.cos(t)))[:, None]
    overlap = a_seg[-n:] * fade_out + b_seg[:n] * fade_in
    return np.concatenate([a_seg[:-n], overlap, b_seg[n:]])


# canvas = vocal + vocal(duplicate) + rest, gentle joins
canvas = xfade_join(vocal, vocal.copy(), XFADE_MS)
canvas = xfade_join(canvas, rest, XFADE_MS)

peak = np.abs(canvas).max()
if peak > 0.98:
    canvas = canvas * 0.98 / peak
dur = len(canvas) / sr
out = OUTDIR / f'malugi.canvas.dup16.{dur:.0f}s.wav'
sf.write(str(out), canvas.astype(np.float32), sr)
print('bpm=%.1f  vocal 0-16 duplicated + 32-64  total %.1fs  peak %.2f'
      % (a.bpm, dur, np.abs(canvas).max()))
print('join at bar 16 = %.1fs, bar 32 = %.1fs' % (len(vocal) / sr, 2 * len(vocal) / sr))
print('out:', out.resolve())
