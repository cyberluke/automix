"""Measure the vocal section length (in bars) of the malugi 64-bar segment.

Computes per-bar vocal_probability + role classification so the user can see
exactly where the vocal part ends (16 / 24 / 32 bars?).
"""
import sys
sys.path.insert(0, '.')
from pathlib import Path
import numpy as np

from src.hypermix.canonicalize import Canonicalizer
from src.hypermix.config import DEFAULT_CONFIG
from src.hypermix.audio_io import read_wav
from src.hypermix.analysis.automix_analyzer import AutomixAnalyzer
from src.hypermix.analysis.phrase_features import extract_phrase_features, classify_phrase

TRACK = Path('music/Malugi MCYL - Knees Break.mp4')
START_BAR = 103
SEG_BARS = 64

c = Canonicalizer(DEFAULT_CONFIG)
res = c.canonicalize(TRACK, c.default_private_root())
audio = read_wav(res.canonical_path)
a = AutomixAnalyzer(DEFAULT_CONFIG).analyze(audio, DEFAULT_CONFIG.phrase_bars)
sr = audio.sample_rate
bars = a.bars

print('bpm=%.1f' % a.bpm)
print('bar | vocal_prob | vocal_ratio | top roles')
print('----+------------+-------------+--------------------------')

vocal_end = None
for i in range(SEG_BARS):
    bi = START_BAR + i
    if bi + 1 >= len(bars):
        break
    s0, s1 = bars[bi], bars[bi + 1]
    f = extract_phrase_features(audio.samples[s0:s1], sr, a.bpm)
    co = f['content']
    roles = classify_phrase(f)
    top = ', '.join(f"{r['role']}:{r['confidence']:.2f}" for r in roles[:2])
    vp = co['vocal_probability']
    vr = co['vocal_energy_ratio']
    print(f'{i:3d} | {vp:10.2f} | {vr:11.2f} | {top}')
    # vocal section = consecutive bars from 0 with vocal_prob >= 0.4
    if vocal_end is None and vp < 0.4:
        vocal_end = i

print('\nVocal section (vocal_prob>=0.4 from bar 0): ~%d bars' % (vocal_end if vocal_end is not None else SEG_BARS))
