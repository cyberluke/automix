"""Render Variant A (cyber bass reinforcement) + Variant B (bass-solo loop).

Runs in .venv-hypermix. Reads the already-separated spr.bass.wav + the full
crop mix, detects bass character, and writes both variants for listening.
"""
import sys
sys.path.insert(0, '.')
import numpy as np
import soundfile as sf

from src.hypermix.spr.bass_character import analyze_bass, apply_cyber_bass, BassRole

BPM = 144.2
DIR = 'renders/spr-malugi-v15/'
BASS = DIR + 'spr.bass.wav'
VOCALS = DIR + 'spr.vocals.wav'
CROP = DIR + 'spr.crop.wav'
OUTA = DIR + 'spr.variantA_cyberbass.wav'
OUTB = DIR + 'spr.variantB_basssolo.wav'
OUTCH = DIR + 'spr.bass_character.txt'

bass, sr = sf.read(BASS, dtype='float32', always_2d=True)
vocals, _ = sf.read(VOCALS, dtype='float32', always_2d=True)
crop, _ = sf.read(CROP, dtype='float32', always_2d=True)

char = analyze_bass(bass, sr)
lines = [f'role={char.role.value}  filter_open_prob={char.filter_open_prob:.2f}',
         f'frames={len(char.frames)} hop={char.frame_hop_s}s', '']
for f in char.frames:
    lines.append('%5.2fs sub=%.2f low=%.2f mid=%.2f open=%.2f cent=%5.0f'
                 % (f.t_s, f.sub_ratio, f.low_ratio, f.mid_ratio,
                    char.openness_at(f.t_s), f.centroid_hz))
open(OUTCH, 'w').write('\n'.join(lines))
print('\n'.join(lines[:6]))

# ---------------- VARIANT A: cyber reinforcement over the full mix ----------
# cyber layer only where the reese opens; sub preserved. Mix over the crop.
# VARIANT A: ADD the cyber mid-bass layer ON TOP of the full mix (parallel).
# Do NOT reconstruct via 'crop - bass + newbass' (phase cancellation kills the
# mid). Just add the isolated cyber layer — the sub stays untouched in crop.
from src.hypermix.spr.bass_character import cyber_bass_layer
layer = cyber_bass_layer(bass, char, sr=sr, bpm=BPM, drive=0.8, max_wet=1.0,
                         overshoot=0.5, chorus_ms=18.0, seed=1)
# ADD the layer ON TOP of the mix. The layer is small vs the mix (~7%), so a
# strong parallel gain is needed to actually hear the cyber growl. Clip-guard
# only on true peaks (no global re-level, no limiter — those hid the tweak).
# The crop is ALREADY normalized (peak ~1.0) and demucs stems DON'T sum exactly
# (crop-bass≠crop), so stem substitution breaks phase. SIMPLEST working path:
# add the layer DIRECTLY on the crop and hard-clip only true peaks. The layer
# is small so a few clipped samples are inaudible; global re-level hid the tweak.
gain = 2.0
mixA = crop + gain * layer
mixA = np.clip(mixA, -0.98, 0.98).astype(np.float32)  # hard clip guard only
sf.write(OUTA, mixA, sr)
print('   layer_peak=%.2f added_mid~%.0f' % (float(np.abs(layer).max()),
      float(np.abs(gain * layer).mean())))
print('wrote', OUTA, 'role=', char.role.value, 'layer_peak=%.2f' % np.abs(layer).max())

# ---------------- VARIANT B: bass-solo breakdown loop -----------------------
# 'happy accident': when the mid bass opens, drop EVERYTHING else and let ONLY
# the boosted bass play (no beat/synth), then resume the normal loop.
# We take the 2nd half (where the filter opens ~t>=4.5s) as the solo window.
bar_s = 4.0 * 60.0 / BPM
# Place the solo where the MID-RANGE actually opens (mid_ratio peak) in the
# SECOND HALF — the user: 'v prvni polovine sub, az v druhe se otevira. ten
# midrange je az potom'. Use the per-frame mid_ratio, not the normalized
# openness (which can be fooled by transients).
mids = np.array([f.mid_ratio for f in char.frames])
sub = np.array([f.sub_ratio for f in char.frames])
# reese character = mid is present AND there's still low/sub body (not a drum hit)
reese_score = mids * np.clip(sub * 3.0, 0.0, 1.0)
half = len(mids) // 2
peak_idx = half + int(np.argmax(reese_score[half:]))
open_t = char.frame_hop_s * float(peak_idx)
solo_len = 0.5 * bar_s  # HALF bar solo — user: 'basa hraje solo moc dlouho'
# start the solo just BEFORE the mid-range peak so the filter opens into it
start = max(0.0, min(open_t - 0.3, (len(bass) / sr) - solo_len))
i0, i1 = int(start * sr), int((start + solo_len) * sr)
# CRANK the bass ABOVE 300 Hz — user: 'pritlacit basu nad 300 hz'. Split the
# bass with a Linkwitz-Riley crossover (LP4+HP4 sum back phase-coherently, the
# linear-phase equivalent for multiband work), boost ONLY the >300 Hz band.
from scipy.signal import butter, sosfiltfilt
XOVER = 300.0
sos_lp = butter(4, XOVER / (sr / 2), 'lowpass', output='sos')
sos_hp = butter(4, XOVER / (sr / 2), 'highpass', output='sos')
b_lo = sosfiltfilt(sos_lp, bass, axis=0)   # sub/low stays as-is
b_hi = sosfiltfilt(sos_hp, bass, axis=0)   # mid/upper bass -> CRANK this
boost = b_lo + 4.0 * b_hi                  # heavy push above 300 Hz
peak = np.abs(boost).max()
if peak > 0.88:
    boost *= 0.88 / peak
# keep VOCALS in the solo (the REAL vocal stem, not 'other' which is melody
# without vocals). user: 'bass solo paradoxne neobsahuje vokaly ale melodii
# bez vokalu'. Gain vocals up to sit with the boosted bass.
solo = np.clip(boost + 1.5 * vocals, -0.97, 0.97)   # bass + vocals
# build variant B: original crop, but during [i0:i1] replace with bass-solo
# (crossfade edges to avoid clicks)
mixB = crop.copy()
xf = int(0.03 * sr)  # 30ms crossfade in
# LONGER fade back so the beat RESUMES sooner — user: 'beat do toho pust drive'
xf_out = int(0.35 * sr)  # 350ms fade-resume of the full mix
env_out = np.linspace(1, 0, xf)[:, None]
env_in = np.linspace(0, 1, xf)[:, None]
env_res = np.linspace(0, 1, xf_out)[:, None]
# fade the mix down into the solo
mixB[i0:i0 + xf] = crop[i0:i0 + xf] * env_out + solo[i0:i0 + xf] * env_in
mixB[i0 + xf:i1] = solo[i0 + xf:i1]
# long fade back to the full mix so the beat creeps in before the solo ends
mixB[i1:i1 + xf_out] = solo[i1:i1 + xf_out] * (1 - env_res) + crop[i1:i1 + xf_out] * env_res
peak = np.abs(mixB).max()
if peak > 0.98:
    mixB *= 0.98 / peak
sf.write(OUTB, mixB, sr)
print('wrote', OUTB, 'solo at %.2fs (openness peak %.2f)' % (start, open_t))
