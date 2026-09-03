"""Bass character detection + CyberLuke bass reinforcement.

Idea (user, 2026-08-11):
  - Sub-only / low bass (energy mostly < ~120-250 Hz) → LEAVE ALONE.
  - Mid-bass / reese (harmonics extend upward, spectral centroid/rolloff move,
    mid/low ratio opens on a filter sweep) → eligible for CyberLuke parallel
    reinforcement that FOLLOWS the source filter gesture, but exaggerated.

Detection works per-frame over the Demucs BASS stem and returns a continuous
feature track + discrete role labels, so the remix section can AUTOMATE wet
amount from the source's own spectral motion (audio-following producer
automation), with a humanizer lag/overshoot so it doesn't sound like a copy.

Runs entirely in .venv-hypermix (numpy/scipy/librosa only — no torch).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import List

import numpy as np


class BassRole(str, enum.Enum):
    SUB_ONLY = "SUB_ONLY"          # energy locked in sub — preserve, no FX
    LOW_BASS = "LOW_BASS"          # low + some body — mostly preserve
    MID_BASS = "MID_BASS"          # audible mid harmonics — eligible
    REESE = "REESE"                # strong moving mid character — cyber target
    ACIDIC = "ACIDIC"              # resonant swept mid (squawk)
    DISTORTED_GROWL = "DISTORTED_GROWL"  # already saturated — reduce added FX


@dataclass
class BassFrame:
    """Per-frame spectral features of the bass stem."""
    t_s: float
    sub_ratio: float       # 20-120 Hz share
    low_ratio: float       # 120-250 Hz share
    mid_ratio: float       # 250-2500 Hz share
    hi_ratio: float        # 2500-8000 Hz share
    centroid_hz: float
    rolloff_hz: float
    bandwidth_hz: float
    rms: float


@dataclass
class BassCharacter:
    """Result of analyzing a bass stem."""
    frames: List[BassFrame]
    role: BassRole                     # overall dominant role
    openness: np.ndarray               # 0..1 per-frame 'filter open' track
    filter_open_prob: float            # global probability a filter is moving
    frame_hop_s: float
    sr: int

    def openness_at(self, t_s: float) -> float:
        i = int(round(t_s / self.frame_hop_s))
        i = int(np.clip(i, 0, len(self.openness) - 1))
        return float(self.openness[i])


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def analyze_bass(bass: np.ndarray, sr: int = 44100,
                 win_s: float = 0.25, hop_s: float = 0.125) -> BassCharacter:
    """Per-frame spectral analysis of the Demucs BASS stem.

    Returns BassCharacter with an `openness` track (0..1) = how open the
    mid-range / filter is at each frame (drives Cyber wet automation).
    """
    from scipy.signal import butter, sosfilt

    mono = bass.mean(axis=1) if bass.ndim > 1 else np.asarray(bass)
    mono = np.nan_to_num(mono)
    win = max(64, int(win_s * sr))
    hop = max(32, int(hop_s * sr))
    window = np.hanning(win)
    freqs = np.fft.rfftfreq(win, 1.0 / sr)

    def bandmask(lo, hi):
        return (freqs >= lo) & (freqs < hi)

    m_sub, m_low, m_mid, m_hi = (bandmask(20, 120), bandmask(120, 250),
                                 bandmask(250, 2500), bandmask(2500, 8000))

    frames: List[BassFrame] = []
    mids, lows, cents, rolls, bws = [], [], [], [], []
    for s in range(0, max(1, len(mono) - win + 1), hop):
        seg = mono[s:s + win]
        if len(seg) < win:
            seg = np.pad(seg, (0, win - len(seg)))
        sp = np.abs(np.fft.rfft(seg * window)) + 1e-12
        tot = sp.sum()
        sub = float(sp[m_sub].sum() / tot)
        low = float(sp[m_low].sum() / tot)
        mid = float(sp[m_mid].sum() / tot)
        hi = float(sp[m_hi].sum() / tot)
        centroid = float((sp * freqs).sum() / tot)
        # rolloff 85%
        cumsum = np.cumsum(sp)
        roll = float(freqs[np.searchsorted(cumsum, 0.85 * tot)]) if tot > 0 else 0.0
        bw = float(np.sqrt((((freqs - centroid) ** 2) * sp).sum() / tot))
        rms = float(np.sqrt(np.mean(seg ** 2)) + 1e-12)
        frames.append(BassFrame(t_s=s / sr, sub_ratio=sub, low_ratio=low,
                                mid_ratio=mid, hi_ratio=hi,
                                centroid_hz=centroid, rolloff_hz=roll,
                                bandwidth_hz=bw, rms=rms))
        mids.append(mid); lows.append(low); cents.append(centroid)
        rolls.append(roll); bws.append(bw)

    mids = np.asarray(mids); cents = np.asarray(cents)
    rolls = np.asarray(rolls); bws = np.asarray(bws)

    # --- continuous 'openness' track ---------------------------------------
    # Use ABSOLUTE mid_ratio (not normalized) so a percussive transient at t=0
    # doesn't squash the real reese opening later. Openness = how 'open' the
    # mid character is vs its own quiet baseline. The mid_ratio band (250-2500)
    # is the dominant term; a mild centroid/rolloff term catches the sweep.
    base = float(np.percentile(mids, 25)) if len(mids) else 0.0  # quiet baseline
    span = max(0.08, float(mids.max()) - base) if len(mids) else 0.08
    mid_open = np.clip((mids - base) / span, 0.0, 1.0)  # 0 at baseline, 1 at peak
    # suppress transient-y frames (very high centroid + very low sub = drum hit,
    # not a reese opening) — a reese keeps energy in low/sub while mids rise.
    sub_arr = np.asarray([f.sub_ratio for f in frames])
    reese_guard = np.clip(sub_arr * 4.0, 0.0, 1.0)  # ~0 when sub vanishes (hit)
    def norm(x):
        lo, hi = float(x.min()), float(x.max())
        return (x - lo) / (hi - lo + 1e-9)
    cent_n = norm(cents)
    openness = np.clip(mid_open * (0.5 + 0.5 * reese_guard)
                       + 0.15 * cent_n * reese_guard, 0.0, 1.0)

    # --- global filter-open probability ------------------------------------
    # How much the mid content MOVES (positive slope / variance), not just its
    # absolute level — a moving filter is the cyber trigger. Use mid_open (the
    # absolute reese-open track) so the probability reflects real openings.
    mid_slope = float(np.mean(np.maximum(0.0, np.diff(mid_open)))) if len(mid_open) > 1 else 0.0
    mid_var = float(np.std(mid_open))
    filter_open_prob = float(np.clip(2.2 * mid_var + 2.5 * mid_slope, 0.0, 1.0))

    # --- dominant role -------------------------------------------------------
    mean_mid = float(mids.mean()) if len(mids) else 0.0
    mean_sub = float(np.mean([f.sub_ratio for f in frames])) if frames else 1.0
    mean_cent = float(cents.mean()) if len(cents) else 0.0
    if mean_sub > 0.62 and mean_mid < 0.12:
        role = BassRole.SUB_ONLY
    elif mean_mid < 0.16:
        role = BassRole.LOW_BASS
    elif mean_mid < 0.30 or filter_open_prob > 0.45:
        role = BassRole.MID_BASS if mean_cent < 900 else BassRole.REESE
    else:
        role = BassRole.REESE

    return BassCharacter(frames=frames, role=role, openness=openness,
                         filter_open_prob=filter_open_prob,
                         frame_hop_s=hop_s, sr=sr)


# ---------------------------------------------------------------------------
# CyberLuke parallel reinforcement (VARIANT A)
# ---------------------------------------------------------------------------

def cyber_bass_layer(bass: np.ndarray, char: BassCharacter, sr: int = 44100,
                     bpm: float = 174.0, lag_beats: float = 0.125,
                     overshoot: float = 0.35, max_wet: float = 0.6,
                     drive: float = 0.5, chorus_ms: float = 18.0,
                     chorus_depth: float = 0.35, add_octave: bool = True,
                     seed: int = 0) -> np.ndarray:
    """Build the CyberLuke parallel mid-bass layer.

    Signal path (from user's spec):
      bass → HP 150 Hz (leave sub out) → extract reese/mid character →
      parallel FX (JP chorus, MS-20-style filter movement, mild harmonics,
      optional +12 layer) → wet automation FOLLOWING char.openness (with a
      humanizer lag + overshoot so it doesn't sound like a copy) → output wet
      layer to be mixed over the untouched original.
    """
    from scipy.signal import butter, sosfilt, lfilter

    rng = np.random.default_rng(seed)
    x = bass.mean(axis=1) if bass.ndim > 1 else np.asarray(bass, dtype=np.float32)
    x = np.nan_to_num(x).astype(np.float32)
    n = len(x)
    if n == 0:
        return np.zeros_like(bass)

    # 1) HP 150 Hz — never effect the sub itself
    sos_hp = butter(4, 150.0, btype="high", fs=sr, output="sos")
    mid = sosfilt(sos_hp, x)

    # 2) mild nonlinear harmonics (tanh drive) — pull the reese 'teeth' up
    driven = np.tanh(mid * (1.0 + 6.0 * drive))

    # 3) optional +12 semitone layer (resample up, quiet)
    layer = driven
    if add_octave:
        up = driven[::2]  # naive 2x (≈+12st)
        up = np.repeat(up, 2)[:n]
        layer = 0.75 * driven + 0.25 * up

    # 4) JP-style chorus (short modulated delay, stereo spread) above bass.
    # Keep the DRY signal dominant and add only a QUIET modulated tap — a heavy
    # 0.6/0.4 mix creates a comb filter that CANCELS the mid band in the mix.
    d_base = int(chorus_ms * sr / 1000.0)
    lfo = chorus_depth * d_base * np.sin(2 * np.pi * 0.8 * np.arange(n) / sr)
    idx = np.clip(np.arange(n) - (d_base + lfo).astype(int), 0, n - 1)
    chor = 0.9 * layer + 0.15 * layer[idx]   # mostly dry, subtle movement
    # normalize the layer up so the cyber character is audible (mid after HP-150
    # is quiet vs the sub) — but keep headroom so it adds instead of fighting.
    chor = chor / (np.abs(chor).max() + 1e-9) * 0.7

    # 5) wet automation FOLLOWING the source openness, with humanizer lag +
    # overshoot so it reads as a SECOND hand turning another filter knob.
    hop_s = char.frame_hop_s
    wet = np.interp(np.arange(n) / sr, np.arange(len(char.openness)) * hop_s,
                    char.openness)
    # lag: delay the follow by lag_beats
    lag_n = int(lag_beats * (60.0 / bpm) * sr)
    if lag_n > 0:
        wet = np.concatenate([np.full(lag_n, wet[0]), wet[:-lag_n]])
    # overshoot: push past the target then settle (simple 1-pole + bump)
    wet = np.clip(wet + overshoot * np.gradient(wet), 0.0, 1.0)
    wet = np.clip(wet * max_wet, 0.0, 1.0)
    # smooth wet so it doesn't zipper
    k = int(0.01 * sr)
    if k > 1:
        kern = np.ones(k) / k
        wet = np.convolve(wet, kern, mode="same")

    out = chor * wet[:, None] if chor.ndim > 1 else (chor * wet)
    # return stereo
    if bass.ndim > 1 and out.ndim == 1:
        out = np.column_stack([out, out])
    # tiny deterministic level variance so it breathes
    out = out * (1.0 + 0.02 * rng.standard_normal((len(out), 1))).astype(np.float32)
    return out.astype(np.float32)


def apply_cyber_bass(bass: np.ndarray, char: BassCharacter, sr: int = 44100,
                     bpm: float = 174.0, strength: float = 1.0, **kw) -> np.ndarray:
    """Mix the cyber layer over the ORIGINAL (sub preserved). strength 0..1."""
    role = char.role
    if role in (BassRole.SUB_ONLY, BassRole.LOW_BASS):
        return bass  # leave it alone
    layer = cyber_bass_layer(bass, char, sr=sr, bpm=bpm, **kw)
    if bass.ndim > 1 and layer.ndim == 1:
        layer = np.column_stack([layer, layer])
    mixed = bass + strength * layer
    peak = np.abs(mixed).max()
    if peak > 0.98:
        mixed *= 0.98 / peak
    return mixed.astype(np.float32)


# ---------------------------------------------------------------------------
# Bass-solo / cyber profiles (the approved 'recipes' — locked by ear)
# ---------------------------------------------------------------------------

@dataclass
class BassProfile:
    """A saved bass-treatment recipe (the parameters the user locked by ear).

    variant: 'cyber'  = parallel cyber reinforcement over the mix (Variant A)
             'solo'   = bass-solo breakdown loop (Variant B)
    """
    name: str
    variant: str
    # solo placement / length
    solo_bars: float = 0.5          # solo length in bars
    solo_pre_s: float = 0.3         # start this many s BEFORE the mid peak
    fade_in_ms: float = 30.0
    fade_resume_ms: float = 350.0   # beat fade-resume length
    # bass boost (multiband)
    xover_hz: float = 300.0         # Linkwitz-Riley crossover
    hi_gain: float = 4.0            # boost ABOVE xover
    norm_peak: float = 0.88         # bass-alone peak target (room for vocals)
    vocal_gain: float = 1.5         # keep vocal stem in the solo
    # cyber layer params (variant 'cyber')
    cyber_gain: float = 2.0
    cyber_drive: float = 0.8
    cyber_max_wet: float = 1.0
    cyber_overshoot: float = 0.5
    cyber_chorus_ms: float = 18.0
    note: str = ""


BASS_PROFILES: dict[str, BassProfile] = {}


def _reg(p: BassProfile) -> BassProfile:
    BASS_PROFILES[p.name] = p
    return p


# The approved recipes (locked by ear, 2026-08-12, spr.crop.wav):
CYBER_MALUGI = _reg(BassProfile(
    name="cyber_malugi", variant="cyber",
    cyber_gain=2.0, cyber_drive=0.8, cyber_max_wet=1.0, cyber_overshoot=0.5,
    cyber_chorus_ms=18.0,
    note="parallel cyber layer ADDED on crop, hard-clip guard only (crop is "
         "pre-normalized, no headroom — global re-level/limiter hides the tweak)"))

BASS_SOLO_MALUGI = _reg(BassProfile(
    name="bass_solo_malugi", variant="solo",
    solo_bars=0.5, solo_pre_s=0.3, fade_in_ms=30.0, fade_resume_ms=350.0,
    xover_hz=300.0, hi_gain=4.0, norm_peak=0.88, vocal_gain=1.5,
    note="0.5-bar bass-solo where mid_ratio*sub-guard peaks in the 2nd half; "
         "bass CRANKED above 300 Hz (LR crossover), vocals kept (real stem)"))


def get_bass_profile(name: str) -> BassProfile:
    if name not in BASS_PROFILES:
        raise KeyError(f"unknown bass profile {name!r}; "
                       f"available: {sorted(BASS_PROFILES)}")
    return BASS_PROFILES[name]
