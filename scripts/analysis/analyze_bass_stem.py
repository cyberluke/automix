"""One-off: demucs-separate the BASS stem from spr.crop.wav + spectral analysis.

Runs in .venv-stems (torch/demucs). Saves bass.wav + prints per-frame band
ratios so we can find where the mid-range reese opens up.
"""
import sys
sys.path.insert(0, '.')
import numpy as np
import soundfile as sf
import librosa

from src.hypermix.spr.isolate import demucs_all_stems

CROP = 'renders/spr-malugi-v15/spr.crop.wav'
OUT = 'renders/spr-malugi-v15/spr.bass.wav'
OUTV = 'renders/spr-malugi-v15/spr.vocals.wav'

y, sr = librosa.load(CROP, sr=44100, mono=False)
y = np.asarray(y).T.astype(np.float32)  # (n,2)
stems = demucs_all_stems(y, sr)
bass = stems['bass']
sf.write(OUT, bass, sr)
sf.write(OUTV, stems['vocals'], sr)
print('wrote', OUT, 'shape', bass.shape, '| vocals rms=%.4f' %
      float(np.sqrt((stems['vocals'] ** 2).mean())))

# ---- spectral analysis per 0.5s window -------------------------------
mono = bass.mean(1)
win = int(0.5 * sr)
hop = int(0.25 * sr)
freqs = np.fft.rfftfreq(win, 1 / sr)


def bands(sp):
    tot = sp.sum() + 1e-12
    def e(lo, hi): return float(sp[(freqs >= lo) & (freqs < hi)].sum())
    return dict(sub=e(20, 120) / tot, low=e(120, 250) / tot,
                mid=e(250, 2500) / tot, hi=e(2500, 8000) / tot)


print('\n t(s)  sub%%   low%%   mid%%   hi%%   centroid(Hz)')
for s in range(0, len(mono) - win, hop):
    seg = mono[s:s + win] * np.hanning(win)
    sp = np.abs(np.fft.rfft(seg))
    b = bands(sp)
    centroid = float((sp * freqs).sum() / (sp.sum() + 1e-12))
    t = s / sr
    bar = '#' * int(b['mid'] * 60)
    print('%5.2f  %5.1f  %5.1f  %5.1f  %5.1f  %7.0f  %s'
          % (t, 100 * b['sub'], 100 * b['low'], 100 * b['mid'],
             100 * b['hi'], centroid, bar))
