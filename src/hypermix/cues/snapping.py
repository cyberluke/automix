"""Cue snapping modes (§10). Locked cues are never silently resnapped (§1.5)."""
from __future__ import annotations

from typing import List, Optional

from ..model import TrackAnalysis


def _nearest(grid: List[int], sample: int) -> int:
    if not grid:
        return sample
    return min(grid, key=lambda g: abs(g - sample))


def _previous(grid: List[int], sample: int) -> int:
    prev = [g for g in grid if g <= sample]
    return prev[-1] if prev else (grid[0] if grid else sample)


def _next(grid: List[int], sample: int) -> int:
    nxt = [g for g in grid if g >= sample]
    return nxt[0] if nxt else (grid[-1] if grid else sample)


def snap_sample(sample: int, mode: str, analysis: TrackAnalysis) -> int:
    """Snap `sample` per `mode` against the analysis grids. Returns snapped sample."""
    beats = analysis.beat_samples
    downbeats = analysis.downbeats
    bars = analysis.bars
    phrases = analysis.phrases

    if mode == "none":
        return sample
    if mode == "nearestBeat":
        return _nearest(beats, sample)
    if mode == "nearestDownbeat":
        return _nearest(downbeats, sample)
    if mode == "nearestBar":
        return _nearest(bars, sample)
    if mode == "nearestPhrase":
        return _nearest(phrases, sample)
    if mode == "previousBeat":
        return _previous(beats, sample)
    if mode == "previousBar":
        return _previous(bars, sample)
    if mode == "previousPhrase":
        return _previous(phrases, sample)
    if mode == "nextBeat":
        return _next(beats, sample)
    if mode == "nextBar":
        return _next(bars, sample)
    if mode == "nextPhrase":
        return _next(phrases, sample)
    raise ValueError(f"unknown snap mode {mode!r}")


def snap_delta_ms(raw: int, snapped: int, sample_rate: int) -> float:
    return (snapped - raw) * 1000.0 / sample_rate
