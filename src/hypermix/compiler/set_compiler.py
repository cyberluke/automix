"""Set compiler (§16). Runs the director to produce a deterministic set plan
from a compiled graph."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from ..director.deep_selector import DeepMixDirector
from ..director.graph import MixGraph
from ..director.selector import Director
from ..model import Segment, TransitionEdge


@dataclass
class SetStep:
    segment_id: str
    edge_id: Optional[str]        # edge used to arrive (None for entry)
    technique: Optional[str]
    start_sample: int             # position in rendered set (filled by renderer)
    length_samples: int

    def to_dict(self) -> dict:
        return {
            "segmentId": self.segment_id,
            "edgeId": self.edge_id,
            "technique": self.technique,
            "startSample": self.start_sample,
            "lengthSamples": self.length_samples,
        }


@dataclass
class SetPlan:
    seed: int
    steps: List[SetStep] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"seed": self.seed, "steps": [s.to_dict() for s in self.steps]}


class SetCompiler:
    def __init__(self, graph: MixGraph) -> None:
        self.graph = graph

    def compile(self, seed: int, length: int = 12,
                mode: str = "weighted-random",
                target_mood: Optional[Sequence[str]] = None,
                energy_min: float = 0.0, energy_max: float = 1.0,
                segment_bars: Optional[int] = None,
                sr: int = 48000,
                seg_keys: Optional[Dict[str, str]] = None,
                seg_energy: Optional[Dict[str, float]] = None,
                seg_level: Optional[Dict[str, float]] = None,
                seg_spec: Optional[Dict[str, Dict[str, float]]] = None,
                harmonic_arc: bool = False) -> SetPlan:
        deep = mode == "deep"
        if deep:
            target = max(1, int(segment_bars or 4))
            director = DeepMixDirector(self.graph, seed=seed,
                                       mode="deterministic",
                                       target_bars=target,
                                       energy_min=energy_min,
                                       energy_max=energy_max,
                                       seg_keys=seg_keys,
                                       seg_energy=seg_energy,
                                       seg_level=seg_level,
                                       seg_spec=seg_spec,
                                       harmonic_arc=harmonic_arc)
        else:
            director = Director(self.graph, seed=seed, mode=mode,
                                mood_tags=target_mood,
                                energy_min=energy_min, energy_max=energy_max)
        plan = SetPlan(seed=seed)
        current_id: Optional[str] = None
        for _ in range(max(1, length)):
            nxt = director.advance(current_id) if deep else director.advance(current_id, target_mood)
            if nxt is None:
                break
            edge = self.graph.edge_between(current_id, nxt.id) if current_id else None
            full_len = nxt.end_sample - nxt.start_sample
            if deep:
                # Deep/megamix: play only the head of the hook (target bars).
                # Quantize to the EXACT bar grid from the segment's BPM (not
                # full_len//bars, which drifts when the source segment isn't
                # an integer number of beats). Cuts then land on bar
                # boundaries instead of chopping a phrase mid-vocal.
                bar_beats = 4.0
                spb = sr * 60.0 / float(nxt.bpm) if nxt.bpm else (full_len / max(1, nxt.bars * bar_beats))
                want = int(round(max(1, int(segment_bars or 4)) * bar_beats * spb))
                step_len = min(full_len, want)
            else:
                step_len = full_len
            plan.steps.append(SetStep(
                segment_id=nxt.id,
                edge_id=edge.id if edge else None,
                technique=edge.technique if edge else None,
                start_sample=0,
                length_samples=step_len,
            ))
            current_id = nxt.id
        return plan
