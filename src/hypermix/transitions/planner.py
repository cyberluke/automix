"""Transition planner (§11–§13). Routes a requested technique through capability
checks and tempo-compatibility rules to a concrete plan, with deterministic
fallbacks. No giant if/elif: rules live in the DSL/technique declarations."""
from __future__ import annotations

from typing import List, Optional

from ..errors import ErrorCode, HyperMixError
from .model import (CapabilityMiss, PlannedTransition, SegmentContext)
from .phrase_match import tempo_compatible
from .registry import TransitionRegistry, UNIVERSAL_FALLBACKS, default_registry

# Techniques that require tempo continuity get routed to a reset transition when
# BPMs are incompatible and no stretch backend is enabled (§12).
_TEMPO_CONTINUITY = {"phrase_match", "double_drop", "back_and_forth",
                     "melodic_mix", "modulation", "triple_drop"}


class TransitionPlanner:
    def __init__(self, registry: Optional[TransitionRegistry] = None,
                 stretch_enabled: bool = False,
                 fallback: str = "rewind") -> None:
        self.registry = registry or default_registry()
        self.stretch_enabled = stretch_enabled
        self.fallback = fallback if fallback in UNIVERSAL_FALLBACKS else "rewind"

    def plan(self, technique_id: str, ctx: SegmentContext,
             allowed: Optional[List[str]] = None) -> PlannedTransition:
        """Plan `technique_id`; on capability miss or unsafe tempo, pick a
        deterministic fallback. Returns the plan actually used."""
        tid = technique_id
        if allowed and tid not in allowed and tid in _TEMPO_CONTINUITY:
            tid = self.fallback

        # Route tempo-continuity techniques away when unsafe.
        if tid in _TEMPO_CONTINUITY and not self.stretch_enabled:
            if not tempo_compatible(ctx.outgoing_bpm, ctx.incoming_bpm):
                tid = self._reset_fallback(ctx, preferred="slam" if tid == "double_drop" else self.fallback)

        try:
            technique = self.registry.get(tid)
        except KeyError:
            raise HyperMixError(ErrorCode.HMX_TRANSITION_NOT_POSSIBLE,
                                f"unknown transition technique {tid!r}")

        try:
            plan = technique.plan(ctx)
        except CapabilityMiss as miss:
            # Deterministic fallback; never pretend stems/harmony existed (§12).
            tid = self.fallback
            technique = self.registry.get(tid)
            plan = technique.plan(ctx)
            plan.params["fallback_from"] = miss.technique
        plan.technique = tid
        return plan

    def plan_with_fallback(self, technique_id: str, ctx: SegmentContext,
                           allowed: Optional[List[str]] = None):
        """Return (plan, actually_used_technique_id)."""
        plan = self.plan(technique_id, ctx, allowed)
        return plan, plan.technique

    def render(self, plan: PlannedTransition, ctx: SegmentContext):
        technique = self.registry.get(plan.technique)
        return technique.render(plan, ctx)

    def _reset_fallback(self, ctx: SegmentContext, preferred: str) -> str:
        return preferred if preferred in UNIVERSAL_FALLBACKS else self.fallback
