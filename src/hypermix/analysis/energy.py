"""Energy derivations (§8)."""
from __future__ import annotations

from typing import List

import numpy as np


def phrase_energies(bar_energy: List[float], phrase_bars: int) -> List[float]:
    if not bar_energy:
        return []
    out = []
    for i in range(0, len(bar_energy), phrase_bars):
        window = bar_energy[i:i + phrase_bars]
        out.append(float(np.mean(window)) if window else 0.0)
    return out


def track_energy(bar_energy: List[float]) -> float:
    """Normalized 0..1 track energy from per-bar RMS (95th-percentile anchored)."""
    if not bar_energy:
        return 0.0
    arr = np.asarray(bar_energy, dtype=float)
    ref = float(np.percentile(arr, 95)) or 1e-9
    return float(np.clip(np.mean(arr) / ref, 0.0, 1.0))
