"""Capability-gated advanced registry entries (§12). Registered so the DSL/graph
can reference them, but each declares explicit capability requirements and
raises CapabilityMiss with a deterministic fallback when stems/harmony are
absent. We never pretend stem processing occurred when stems are missing."""
from __future__ import annotations

from ..model import TransitionCapabilities
from .model import (CapabilityMiss, PlannedTransition, RenderedTransition,
                    SegmentContext)
from .slam import Slam


class _CapabilityGated:
    id = "capability_gated"
    capabilities = TransitionCapabilities()
    _missing: tuple = ()

    def _check(self, ctx: SegmentContext) -> None:
        missing = []
        if self.capabilities.requires_stems and not ctx.params.get("stems_available"):
            missing.append("stems")
        if self.capabilities.requires_vocal_stem and not ctx.params.get("vocal_stem_available"):
            missing.append("vocal_stem")
        if self.capabilities.requires_harmony and not ctx.params.get("harmony_available"):
            missing.append("harmony")
        if missing:
            raise CapabilityMiss(self.id, missing)

    def plan(self, ctx: SegmentContext) -> PlannedTransition:
        self._check(ctx)
        # Deterministic fallback when capabilities exist: slam-class execution.
        return Slam().plan(ctx)

    def render(self, plan: PlannedTransition, ctx: SegmentContext) -> RenderedTransition:
        return Slam().render(plan, ctx)


class AcapellaOverlay(_CapabilityGated):
    id = "acapella_overlay"
    capabilities = TransitionCapabilities(
        requires_stems=True, requires_vocal_stem=True, supports_hot_swap=False)


class MelodicMix(_CapabilityGated):
    id = "melodic_mix"
    capabilities = TransitionCapabilities(
        tempo_continuity_required=True, requires_harmony=True,
        supports_hot_swap=False)


class Modulation(_CapabilityGated):
    id = "modulation"
    capabilities = TransitionCapabilities(
        tempo_continuity_required=True, requires_harmony=True,
        supports_hot_swap=False)


class ThematicHandoff(_CapabilityGated):
    id = "thematic_handoff"
    capabilities = TransitionCapabilities(
        requires_stems=True, requires_harmony=True, supports_hot_swap=False)


class TripleDrop(_CapabilityGated):
    id = "triple_drop"
    capabilities = TransitionCapabilities(
        tempo_continuity_required=True, requires_stems=True,
        supports_hot_swap=False)
