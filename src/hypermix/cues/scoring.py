"""Cue/segment candidate scoring (§8, §16). Advisory ranking only."""
from __future__ import annotations

from typing import Iterable, Optional

from ..model import Cue, Track


def score_cue(track: Track, cue: Cue,
              mood_tags: Optional[Iterable[str]] = None,
              energy_min: float = 0.0, energy_max: float = 1.0) -> float:
    """Score = rating + mood match + energy match (advisory; curator wins)."""
    score = cue.rating / 10.0
    tags = set(mood_tags or [])
    if tags:
        overlap = len(tags.intersection(cue.tags) | tags.intersection(track.tags))
        score += min(0.5, 0.1 * overlap)
    if energy_min <= cue.energy <= energy_max:
        score += 0.25
    if cue.kind in ("hero", "drop", "hook"):
        score += 0.15
    if cue.stale:
        score -= 1.0
    return round(score, 4)
