"""Structural derivations on integer sample indices (§8)."""
from __future__ import annotations

from typing import List


def derive_bars_from_downbeats(downbeats: List[int], n_samples: int) -> List[int]:
    """Bar boundaries = downbeats plus final end boundary."""
    bars = list(downbeats)
    if not bars or bars[-1] != n_samples:
        bars.append(n_samples)
    return bars


def derive_phrases(downbeats: List[int], phrase_bars: int,
                   n_samples: int, phase_offset_bars: int = 0) -> List[int]:
    """Phrase boundaries every `phrase_bars` downbeats, honouring a manual
    phrasePhaseOffsetBars when automatic phrase phase is wrong (§8)."""
    if not downbeats:
        return [0, n_samples]
    start = min(max(0, phase_offset_bars), len(downbeats) - 1)
    phrases = [downbeats[i] for i in range(start, len(downbeats), phrase_bars)]
    if phrases[0] != 0:
        phrases.insert(0, 0)
    if phrases[-1] != n_samples:
        phrases.append(n_samples)
    return phrases
