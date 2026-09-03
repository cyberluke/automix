"""Phrase-level musical key detection (§-identity). Detects the key of the
exact phrase that goes into the mix — not the whole track.

Uses librosa chroma_cqt + Krumhansl-Schmuckler major/minor template matching
(the legacy `src/harmonic_analyzer.detect_key_camelot` algorithm), run on the
segment audio slice. Deterministic (mean chroma over the slice).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np

CAMELOT_WHEEL = {
    'C': (8, 'B'), 'Am': (8, 'A'), 'C#': (3, 'B'), 'A#m': (3, 'A'),
    'D': (10, 'B'), 'Bm': (10, 'A'), 'D#': (5, 'B'), 'Cm': (5, 'A'),
    'E': (12, 'B'), 'C#m': (12, 'A'), 'F': (7, 'B'), 'Dm': (7, 'A'),
    'F#': (2, 'B'), 'D#m': (2, 'A'), 'G': (9, 'B'), 'Em': (9, 'A'),
    'G#': (4, 'B'), 'Fm': (4, 'A'), 'A': (11, 'B'), 'F#m': (11, 'A'),
    'A#': (6, 'B'), 'Gm': (6, 'A'), 'B': (1, 'B'), 'G#m': (1, 'A'),
}

_KEYS_MAJOR = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
_KEYS_MINOR = ['Cm', 'C#m', 'Dm', 'D#m', 'Em', 'Fm', 'F#m', 'Gm', 'G#m',
               'Am', 'A#m', 'Bm']

# Krumhansl-Schmuckler tonal profiles (more musical than plain diatonic masks).
_MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                           2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                           2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    d = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / d) if d > 0 else 0.0


def detect_key(samples: np.ndarray, sr: int) -> Dict[str, Any]:
    """Detect key + Camelot of an audio slice (mono-mixed). Deterministic."""
    import librosa
    y = samples.mean(axis=1) if samples.ndim > 1 else samples
    y = np.ascontiguousarray(y, dtype=np.float32)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    cm = chroma.mean(axis=1)
    cm = cm / (cm.sum() + 1e-10)

    best_maj, key_maj = -2.0, 'C'
    for i, k in enumerate(_KEYS_MAJOR):
        s = _corr(cm, np.roll(_MAJOR_PROFILE, i))
        if s > best_maj:
            best_maj, key_maj = s, k
    best_min, key_min = -2.0, 'Am'
    for i, k in enumerate(_KEYS_MINOR):
        s = _corr(cm, np.roll(_MINOR_PROFILE, i))
        if s > best_min:
            best_min, key_min = s, k

    if best_maj >= best_min:
        key, mode, conf = key_maj, 'major', best_maj
    else:
        key, mode, conf = key_min, 'minor', best_min
    num, letter = CAMELOT_WHEEL.get(key, (8, 'B'))
    return {
        'key': key, 'mode': mode, 'camelot': f"{num}{letter}",
        'camelotNumber': num, 'camelotLetter': letter,
        'confidence': round(float(conf), 4),
        'chroma': [round(float(v), 5) for v in cm],
    }


def key_of_slice(samples: np.ndarray, sr: int, start: int, end: int) -> Dict[str, Any]:
    """Detect key for a sample-index slice [start:end] of a track/segment."""
    n = samples.shape[0]
    s = max(0, min(int(start), n - 1))
    e = max(s + 1, min(int(end), n))
    return detect_key(samples[s:e], sr)


def camelot_compatible(a: str, b: str) -> bool:
    """Camelot mixing rule: same code, +-1 same letter, or same number
    opposite letter (relative major<->minor)."""
    if not a or not b or a == b:
        return True
    try:
        na, la = int(a[:-1]), a[-1]
        nb, lb = int(b[:-1]), b[-1]
    except Exception:
        return False
    if la == lb and abs(na - nb) in (0, 1, 11):
        return True
    if na == nb and la != lb:
        return True
    return False
