"""Cue resolution + stale handling (§10).

Manual cues are authoritative (§1.5). If the canonical source changes, cues are
marked stale rather than moved.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from ..errors import ErrorCode, HyperMixError
from ..model import Cue, Track
from .snapping import snap_sample


class CueResolver:
    def resolve_position(self, track: Track, cue: Cue) -> dict:
        """Return beat/bar/phrase indices for a cue sample."""
        a = track.analysis
        if a is None:
            raise HyperMixError(ErrorCode.HMX_ANALYSIS_FAILED,
                                f"track {track.id} has no analysis")
        beat = _index_of(a.beat_samples, cue.sample)
        bar = _index_of(a.bars, cue.sample)
        phrase = _index_of(a.phrases, cue.sample)
        return {"beat": beat, "bar": bar, "phrase": phrase}

    def add_cue(self, track: Track, cue_id: str, raw_sample: int,
                kind: str, snap: str = "nearestPhrase",
                locked: bool = True, rating: float = 5.0,
                tags: Optional[List[str]] = None) -> Cue:
        if track.audio and not (0 <= raw_sample <= track.audio.samples):
            raise HyperMixError(ErrorCode.HMX_CUE_OUT_OF_RANGE,
                                f"cue {cue_id} sample {raw_sample} outside track")
        sample = raw_sample
        if track.analysis is not None and snap != "none":
            sample = snap_sample(raw_sample, snap, track.analysis)
        cue = Cue(id=cue_id, sample=sample, kind=kind, locked=locked,
                  rating=rating, tags=list(tags or []))
        if track.analysis is not None:
            pos = self.resolve_position(track, cue)
            cue.beat, cue.bar, cue.phrase = pos["beat"], pos["bar"], pos["phrase"]
            cue.energy = _energy_at(track, cue.bar)
        track.cues.append(cue)
        return cue

    def resnap(self, track: Track, cue: Cue, snap: str) -> Cue:
        """Never silently resnap a locked cue (§10)."""
        if cue.locked:
            return cue
        if track.analysis is None:
            return cue
        cue.sample = snap_sample(cue.sample, snap, track.analysis)
        return cue

    def mark_stale_if_source_changed(self, track: Track, current_source_hash: Optional[str]) -> bool:
        """If canonical source changed, mark cues stale instead of moving them."""
        recorded = track.source.sha256 if track.source else None
        if recorded and current_source_hash and current_source_hash != recorded:
            for c in track.cues:
                c.stale = True
            return True
        return False

    def entry_cues(self, track: Track) -> List[Cue]:
        return [c for c in track.cues if c.allowed_entry and not c.stale]

    def exit_cues(self, track: Track) -> List[Cue]:
        return [c for c in track.cues if c.allowed_exit and not c.stale]


def _index_of(grid: List[int], sample: int) -> Optional[int]:
    if not grid:
        return None
    best_i, best_d = None, None
    for i, g in enumerate(grid):
        d = abs(g - sample)
        if best_d is None or d < best_d:
            best_i, best_d = i, d
    return best_i


def _energy_at(track: Track, bar: Optional[int]) -> float:
    a = track.analysis
    if a is None or bar is None or not a.bar_energy:
        return 0.0
    i = min(bar, len(a.bar_energy) - 1)
    return float(a.bar_energy[i])
