"""Director / sequencing engine (§16). Lightweight deterministic selection.
Scoring combines segment rating, mood match, energy match, transition quality,
novelty bonus and repetition penalty. Modes: deterministic | weighted-random | manual."""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from ..model import Segment
from .graph import MixGraph
from .seeded_rng import SeededRNG


class Director:
    def __init__(self, graph: MixGraph, seed: int = 0,
                 mode: str = "weighted-random",
                 mood_tags: Optional[Sequence[str]] = None,
                 energy_min: float = 0.0, energy_max: float = 1.0) -> None:
        self.graph = graph
        self.rng = SeededRNG(seed)
        self.mode = mode
        self.mood_tags = set(mood_tags or [])
        self.energy_min = energy_min
        self.energy_max = energy_max
        self.history: List[str] = []

    def _score(self, from_id: Optional[str], seg: Segment) -> float:
        score = seg.rating / 10.0
        if self.mood_tags:
            score += min(0.5, 0.1 * len(self.mood_tags.intersection(seg.mood_tags)))
        if self.energy_min <= seg.energy_start <= self.energy_max:
            score += 0.25
        # Transition quality of the edge used to arrive here.
        if from_id is not None:
            edge = self.graph.edge_between(from_id, seg.id)
            if edge:
                score += 0.5 * edge.quality
        # Novelty bonus / repetition penalty.
        if seg.id not in self.history:
            score += 0.2
        else:
            score -= 0.6 * self.history.count(seg.id)
        # Artist repetition penalty: strongly prefer tracks not played yet, and
        # especially avoid the immediately-recent ones (DJ-style crate digging).
        played_tracks = [self.graph.segments[h].track_id for h in self.history
                         if h in self.graph.segments]
        plays = played_tracks.count(seg.track_id)
        if plays == 0:
            score += 1.0                      # never-heard track: dig it hard
        else:
            score -= 2.5 * plays              # each repeat pushes it far down
        recent_tracks = [self.graph.segments[h].track_id for h in self.history[-3:]
                         if h in self.graph.segments]
        score -= 3.0 * recent_tracks.count(seg.track_id)  # just played: hard avoid
        return score

    def choose_entry(self) -> Segment:
        entries = [self.graph.segments[i] for i in self.graph.entry_segments
                   if i in self.graph.segments]
        if not entries:
            entries = list(self.graph.segments.values())
        if not entries:
            raise ValueError("mix graph has no segments")
        if self.mode == "deterministic":
            return max(entries, key=lambda s: self._score(None, s))
        weights = [max(1e-3, self._score(None, s)) for s in entries]
        return self.rng.weighted_choice(entries, weights)

    def choose_next(self, current_id: str,
                    target_mood: Optional[Sequence[str]] = None) -> Optional[Segment]:
        options = self.graph.outgoing(current_id)
        if not options:
            return None
        saved_tags = self.mood_tags
        if target_mood:
            self.mood_tags = set(target_mood)
        candidates = [self.graph.segments[o] for o in options if o in self.graph.segments]
        if not candidates:
            self.mood_tags = saved_tags
            return None
        # DJ-style crate digging: strongly prefer tracks not played yet. Only
        # revisit an already-played track once every reachable track is spent.
        played = {self.graph.segments[h].track_id for h in self.history
                  if h in self.graph.segments}
        fresh = [c for c in candidates if c.track_id not in played]
        pool = fresh if fresh else candidates
        if self.mode == "deterministic":
            pick = max(pool, key=lambda s: self._score(current_id, s))
        else:
            weights = [max(1e-3, self._score(current_id, s)) for s in pool]
            pick = self.rng.weighted_choice(pool, weights)
        self.mood_tags = saved_tags
        return pick

    def advance(self, current_id: Optional[str],
                target_mood: Optional[Sequence[str]] = None) -> Optional[Segment]:
        nxt = self.choose_entry() if current_id is None else self.choose_next(current_id, target_mood)
        if nxt is not None:
            self.history.append(nxt.id)
        return nxt
