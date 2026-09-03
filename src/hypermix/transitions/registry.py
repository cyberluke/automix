"""Transition technique registry (§12). One entry per technique; capability
declarations drive planner routing and deterministic fallbacks. The DJ knowledge
base is turned into data-driven executable definitions via the DSL (§13)."""
from __future__ import annotations

from typing import Dict, Iterable, List

from ..model import TransitionCapabilities
from .back_and_forth import BackAndForth
from .backspin import Backspin
from .capability_gated import (AcapellaOverlay, MelodicMix, Modulation,
                               ThematicHandoff, TripleDrop)
from .double_drop import DoubleDrop
from .drum_roll import DrumRoll
from .echo_cut import EchoCut
from .loop_transition import LoopTransition
from .model import CapabilityMiss, TransitionTechnique
from .phrase_match import PhraseMatch
from .power import PowerDown, PowerUp
from .rewind import Rewind
from .slam import DropOnTheOne, Slam
from .stutter import Stutter
from .transformer_cuts import TransformerCuts

# Universal reset transitions usable as safe fallbacks (§6.4).
UNIVERSAL_FALLBACKS = ("rewind", "slam", "echo_cut", "backspin")


class TransitionRegistry:
    def __init__(self) -> None:
        self._techniques: Dict[str, TransitionTechnique] = {}

    def register(self, technique: TransitionTechnique) -> None:
        self._techniques[technique.id] = technique

    def get(self, technique_id: str) -> TransitionTechnique:
        if technique_id not in self._techniques:
            raise KeyError(f"unknown transition technique {technique_id!r}")
        return self._techniques[technique_id]

    def has(self, technique_id: str) -> bool:
        return technique_id in self._techniques

    def capabilities(self, technique_id: str) -> TransitionCapabilities:
        return self.get(technique_id).capabilities

    def ids(self) -> List[str]:
        return sorted(self._techniques)

    def hot_swap_ids(self) -> List[str]:
        return [tid for tid, t in self._techniques.items()
                if t.capabilities.supports_hot_swap]


def default_registry() -> TransitionRegistry:
    reg = TransitionRegistry()
    for t in (
        PhraseMatch(), DoubleDrop(), Slam(), Rewind(), Backspin(), EchoCut(),
        Stutter(), DrumRoll(), LoopTransition(), PowerDown(), PowerUp(),
        DropOnTheOne(), BackAndForth(), TransformerCuts(),
        # Capability-gated advanced entries (§12).
        AcapellaOverlay(), MelodicMix(), Modulation(), ThematicHandoff(),
        TripleDrop(),
    ):
        reg.register(t)
    return reg
