"""Transition-internal model + technique protocol (§11).

Universal t1/t2/t3 semantics are kept: t1 transition begins, t2 musical switch
point, t3 transition completes. All stored as integer samples.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

import numpy as np

from ..audio_io import CanonicalAudio
from ..model import TransitionCapabilities, TransitionTimeline, PackEvent


@dataclass
class SegmentContext:
    """Everything a technique needs to plan/render an edge between two segments."""
    outgoing_audio: CanonicalAudio
    incoming_audio: CanonicalAudio
    outgoing_start: int            # absolute sample in outgoing track
    outgoing_end: int
    incoming_start: int            # absolute sample in incoming track (entry cue)
    incoming_end: int
    outgoing_bpm: float
    incoming_bpm: float
    sample_rate: int
    beat_samples_out: List[int] = field(default_factory=list)
    beat_samples_in: List[int] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)

    @property
    def beat_sec_out(self) -> float:
        return 60.0 / self.outgoing_bpm if self.outgoing_bpm else 0.5

    @property
    def beat_sec_in(self) -> float:
        return 60.0 / self.incoming_bpm if self.incoming_bpm else 0.5


@dataclass
class PlannedTransition:
    technique: str
    timeline: TransitionTimeline
    tempo_continuity_required: bool
    phrase_safe: bool
    quality: float = 1.0
    params: Dict[str, Any] = field(default_factory=dict)
    events: List[PackEvent] = field(default_factory=list)
    # Length of the rendered transition asset (samples) and where, within it,
    # the musical switch t2 occurs.
    render_length: int = 0
    switch_offset: int = 0


@dataclass
class RenderedTransition:
    samples: np.ndarray           # float32 stereo
    sample_rate: int
    timeline: TransitionTimeline  # relative to start of `samples`
    switch_offset: int            # sample index of t2 inside `samples`
    events: List[PackEvent] = field(default_factory=list)


class CapabilityMiss(Exception):
    """Raised when a technique lacks required capabilities (§12). Deterministic
    fallback is chosen by the caller."""

    def __init__(self, technique: str, missing: List[str]) -> None:
        super().__init__(f"{technique} missing capabilities: {', '.join(missing)}")
        self.technique = technique
        self.missing = missing


@runtime_checkable
class TransitionTechnique(Protocol):
    id: str
    capabilities: TransitionCapabilities

    def plan(self, ctx: SegmentContext) -> PlannedTransition:
        ...

    def render(self, plan: PlannedTransition, ctx: SegmentContext) -> RenderedTransition:
        ...
