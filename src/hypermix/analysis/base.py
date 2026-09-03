"""Analyzer protocol (§8). Analysis is advisory; manual cues are authoritative (§1.5)."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..audio_io import CanonicalAudio
from ..model import TrackAnalysis


@runtime_checkable
class HyperMixAnalyzer(Protocol):
    name: str
    version: int

    def analyze(self, audio: CanonicalAudio) -> TrackAnalysis:
        ...
