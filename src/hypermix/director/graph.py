"""Lightweight mix graph model used by the director (§16)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..model import Segment, TransitionEdge


@dataclass
class MixGraph:
    segments: Dict[str, Segment]
    edges: Dict[str, TransitionEdge]            # edge id -> edge
    adjacency: Dict[str, List[str]] = field(default_factory=dict)  # from -> [to ids]
    entry_segments: List[str] = field(default_factory=list)
    fallback_transition: str = "rewind"

    def outgoing(self, segment_id: str) -> List[str]:
        return self.adjacency.get(segment_id, [])

    def edge_between(self, a: str, b: str) -> Optional[TransitionEdge]:
        for e in self.edges.values():
            if e.from_segment == a and e.to_segment == b:
                return e
        return None
