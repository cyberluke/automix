"""Advisory HERO candidate ranking (§8).

V1 DeepDance rework: a HERO cue is a DROP/HOOK *entry* — the musically
intentional moment where the producer slams kick+bass back in after a build or
breakdown. The old scorer ranked by raw bar energy (loud == good), which picked
mid-groove bars. The empirical signature mined from CyberLuke's annotations
across 7 tracks is clean and separable:

    DROP/HOOK entry :  bass_rms_delta  >= ~+0.10   (kick+bass slam IN)
                       rms_delta       >  ~+0.05
    BREAKDOWN/exit  :  bass_rms_delta  <= ~-0.05   (kick+bass drop OUT)
    BUILD/mini-hook :  |bass_rms_delta| small      (no full kick yet)

So the V1 scorer is dominated by the *before -> after* low-end delta at each bar
boundary, with absolute loudness, onset density and tonal novelty as tiebreakers.
Advisory only — manual cues always win (§1.5).
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np

from ..audio_io import CanonicalAudio

# Empirical thresholds from renders/anchor_analysis.json (7 annotated tracks).
_DROP_BASS_DELTA = 0.07    # kick+bass entry gate (soft trance drops ~+0.07)
_DROP_RMS_DELTA = 0.03     # full-band energy rise gate


def _lowpass(x: np.ndarray, sr: int, cutoff: float) -> np.ndarray:
    from scipy.signal import butter, sosfiltfilt
    sos = butter(2, cutoff, "lowpass", fs=sr, output="sos")
    return sosfiltfilt(sos, x)


def _frame_rms(x: np.ndarray, hop: int = 512) -> np.ndarray:
    m = len(x) // hop
    if m == 0:
        return np.zeros(1, dtype=np.float32)
    return np.sqrt(x[: m * hop].reshape(m, hop).mean(axis=1) ** 2 + 1e-12)


def hero_candidates(audio: CanonicalAudio, bars: List[int],
                    bar_energy: List[float], bpm: float,
                    phrase_bars: int = 8, top_k: int = 12) -> List[Dict]:
    if len(bars) < 2 or not bar_energy:
        return []
    sr = audio.sample_rate
    mono = audio.mono()
    hop = 512

    # Per-frame low-band (kick+bass <160 Hz) and full-band RMS.
    bass = _lowpass(mono, sr, 160.0)
    bass_rms = _frame_rms(bass, hop)
    full_rms = _frame_rms(mono, hop)

    # Onset density per bar (advisory accent strength).
    try:
        import librosa
        onset_env = librosa.onset.onset_strength(y=mono, sr=sr, hop_length=hop)
    except Exception:
        onset_env = np.zeros(len(full_rms), dtype=np.float32)

    med = float(np.median(bar_energy)) or 1e-9
    beat_s = 60.0 / max(bpm, 1.0)
    win_f = max(1, int(4 * beat_s * sr / hop))    # 1 bar of frames
    tol_f = max(1, int(beat_s * sr / hop))        # +-1 beat grid-phase tolerance

    def band_delta(env: np.ndarray, sample: int) -> float:
        """before->after band-energy rise; max over +-1 beat so a bar grid that
        is phase-offset from the true downbeat still catches the impact."""
        f = int(sample / hop)
        best = 0.0
        for off in range(-tol_f, tol_f + 1, max(1, tol_f // 2)):
            g = f + off
            before = float(env[max(0, g - win_f):g].mean()) if g > 0 else 0.0
            after = float(env[g:g + win_f].mean()) if g + win_f <= len(env) else 0.0
            best = max(best, after - before)
        return best

    cands: List[Dict] = []
    n_bars = min(len(bar_energy), len(bars) - 1)
    for i in range(n_bars):
        s, e = bars[i], bars[i + 1]
        if e <= s:
            continue
        f0 = int(s / hop)
        f1 = max(f0 + 1, int(e / hop))
        onset = float(np.mean(onset_env[f0:f1])) if f1 <= len(onset_env) else 0.0

        bass_d = band_delta(bass_rms, s)      # kick+bass entry strength
        rms_d = band_delta(full_rms, s)       # full-band energy rise
        energy_rel = float(bar_energy[i] / med)

        # Tonal / spectral novelty vs the 4-bar neighbourhood (hook content).
        lo, hi = max(0, i - 2), min(n_bars, i + 2)
        local = float(np.mean(bar_energy[lo:hi])) or 1e-9
        novelty = float(max(0.0, bar_energy[i] - local) / med)

        # DROP/HOOK entry gate + scoring. The bass-entry delta dominates.
        is_drop_entry = bass_d >= _DROP_BASS_DELTA and rms_d >= _DROP_RMS_DELTA
        score = (0.50 * min(max(bass_d, 0.0) / 0.30, 1.0)      # kick+bass slam-in
                 + 0.15 * min(max(rms_d, 0.0) / 0.25, 1.0)     # full-band rise
                 + 0.15 * min(energy_rel, 2.0) / 2.0           # absolute loudness
                 + 0.10 * min(onset, 1.0)                       # accent density
                 + 0.10 * min(novelty, 1.0))                    # tonal surprise
        cands.append({
            "sample": int(s),
            "bar": int(i),
            "score": round(score, 4),
            "bassDelta": round(bass_d, 4),
            "rmsDelta": round(rms_d, 4),
            "isDropEntry": bool(is_drop_entry),
        })

    # Drop/hook entries first (they are the hero cues); the rest ranked by score.
    entries = [c for c in cands if c["isDropEntry"]]
    others = [c for c in cands if not c["isDropEntry"]]
    entries.sort(key=lambda c: c["score"], reverse=True)
    others.sort(key=lambda c: c["score"], reverse=True)
    return (entries + others)[:top_k]
