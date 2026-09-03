"""Render the engine's recommended phrases on the REAL malugi track for listening.

Runs AutomixAnalyzer (phrase grid + hero/drop-entry detection) on the full
malugi track, then renders each recommended phrase (entry/exit candidates) as a
WAV so the user can HEAR which phrase the engine picks — before we build the
producer DNA recipe on top.

Run in .venv-hypermix.
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

PHRASE_BARS = DEFAULT_CONFIG.phrase_bars

# 1) canonicalize (decode mp4 -> 48k stereo wav cache)
c = Canonicalizer(DEFAULT_CONFIG)
res = c.canonicalize(TRACK, c.default_private_root())
print('canonical:', res.canonical_path, 'dur=%.1fs' % res.duration_sec)

# 2) analyze
audio = read_wav(res.canonical_path)
a = AutomixAnalyzer(DEFAULT_CONFIG).analyze(audio, DEFAULT_CONFIG.phrase_bars)
sr = audio.sample_rate
print('bpm=%.1f  bars=%d  phrases=%d  confidence=%.2f'
      % (a.bpm, len(a.bars), len(a.phrases), a.confidence))
print('hero candidates:', len(a.hero_candidates),
      ' entry:', len(a.entry_candidates), ' exit:', len(a.exit_candidates))

# save the full analysis for inspection
import json
json.dump(a.to_dict(), open(OUTDIR / 'analysis.json', 'w'), indent=2, default=str)


def render_phrase(start_sample, tag):
    """Render phrase_bars bars starting at the bar containing start_sample."""
    bars = a.bars
    # find the bar index containing this sample
    bi = 0
    for i in range(len(bars) - 1):
        if bars[i] <= start_sample < bars[i + 1]:
            bi = i
            break
    s0 = bars[bi]
    e0 = bars[bi + PHRASE_BARS] if bi + PHRASE_BARS < len(bars) else audio.n_samples
    seg = audio.samples[s0:e0]
    if len(seg) == 0:
        return None
    peak = np.abs(seg).max()
    if peak > 0.98:
        seg = seg * 0.98 / peak
    dur = len(seg) / sr
    out = OUTDIR / f'phrase.{tag}.bar{bi:03d}.{dur:.1f}s.wav'
    sf.write(str(out), seg.astype(np.float32), sr)
    return out, bi, dur


print('\n--- ENTRY candidates (drop/hook entries, kick+bass slam IN) ---')
seen = set()
for i, s in enumerate(a.entry_candidates):
    r = render_phrase(int(s), f'entry{i+1}')
    if r:
        out, bi, dur = r
        if bi in seen:
            continue
        seen.add(bi)
        print(f'  [{i+1}] bar {bi}  {dur:.1f}s  -> {out.name}')

print('\n--- EXIT candidates (breakdown/exit) ---')
for i, s in enumerate(a.exit_candidates):
    r = render_phrase(int(s), f'exit{i+1}')
    if r:
        out, bi, dur = r
        if bi in seen:
            continue
        seen.add(bi)
        print(f'  [{i+1}] bar {bi}  {dur:.1f}s  -> {out.name}')

print('\nwrote previews to', OUTDIR)
