"""Render the malugi 64-bar segment (the golden-mix malugi section) for DNA work.

Starts at the main drop entry (bar 103) and renders 64 bars as ONE continuous
WAV — this is the canvas for the producer DNA recipe.
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
SEG_BARS = 64

c = Canonicalizer(DEFAULT_CONFIG)
res = c.canonicalize(TRACK, c.default_private_root())
audio = read_wav(res.canonical_path)
a = AutomixAnalyzer(DEFAULT_CONFIG).analyze(audio, DEFAULT_CONFIG.phrase_bars)
sr = audio.sample_rate

bars = a.bars
s0 = bars[START_BAR]
e0 = bars[START_BAR + SEG_BARS] if START_BAR + SEG_BARS < len(bars) else audio.n_samples
seg = audio.samples[s0:e0]
peak = np.abs(seg).max()
if peak > 0.98:
    seg = seg * 0.98 / peak
dur = len(seg) / sr
out = OUTDIR / f'malugi.segment64.bar{START_BAR}.{dur:.0f}s.wav'
sf.write(str(out), seg.astype(np.float32), sr)
print('bpm=%.1f  bar %d -> %d  %d bars  %.1fs  -> %s'
      % (a.bpm, START_BAR, START_BAR + SEG_BARS, SEG_BARS, dur, out))
print('out abs:', out.resolve())
