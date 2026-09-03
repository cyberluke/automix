"""power_down / power_up — energy collapse and phrase-aligned build (§12).
power_down uses optional deterministic offline slowdown/reset; no realtime
master-tempo engine."""
from __future__ import annotations

import numpy as np

from ..model import PackEvent, TransitionCapabilities, TransitionTimeline
from .dsp import (apply_gain, declick_join, filter_sweep, fit_len, gain_ramp,
                  normalize_peak, variable_rate_resample)
from .model import PlannedTransition, RenderedTransition, SegmentContext


class PowerDown:
    id = "power_down"
    capabilities = TransitionCapabilities(
        tempo_continuity_required=False, phrase_safe=True, supports_hot_swap=True)

    def plan(self, ctx: SegmentContext) -> PlannedTransition:
        sr = ctx.sample_rate
        collapse = int(sr * ctx.beat_sec_out * 4)   # 1 bar collapse
        head = int(sr * 0.05)
        tl = TransitionTimeline(t1_sample=0, t2_sample=collapse,
                                t3_sample=collapse + head)
        return PlannedTransition(
            technique=self.id, timeline=tl,
            tempo_continuity_required=False, phrase_safe=True, quality=0.85,
            params={"collapse": collapse, "drop_head": head},
            render_length=tl.t3_sample, switch_offset=collapse,
            events=[PackEvent(sample=collapse, type="transition.switch",
                              payload={"technique": self.id})])

    def render(self, plan: PlannedTransition, ctx: SegmentContext) -> RenderedTransition:
        sr = ctx.sample_rate
        n = plan.params["collapse"]
        src = ctx.outgoing_audio.samples[max(0, ctx.outgoing_end - n):ctx.outgoing_end]
        src = fit_len(src, n)
        # Energy collapse: LP filter sweep down + gain fall + optional slowdown.
        body = filter_sweep(src, sr, 6000.0, 200.0, mode="lowpass")
        if ctx.params.get("slowdown", True):
            t = np.linspace(0, 1, n, dtype=np.float32)
            rate = 1.0 - 0.5 * (t ** 2)
            body = variable_rate_resample(body, rate)
            body = fit_len(body, n)
        body = apply_gain(body, gain_ramp(body.shape[0], 1.0, 0.05, curve="exp"))
        head = ctx.incoming_audio.samples[
            ctx.incoming_start:ctx.incoming_start + plan.params["drop_head"]]
        out = declick_join(body, head, sr, fade_ms=8.0)
        out = normalize_peak(fit_len(out, plan.render_length))
        return RenderedTransition(out, sr, plan.timeline,
                                  plan.switch_offset, plan.events)


class PowerUp:
    id = "power_up"
    capabilities = TransitionCapabilities(
        tempo_continuity_required=False, phrase_safe=True, supports_hot_swap=True)

    def plan(self, ctx: SegmentContext) -> PlannedTransition:
        sr = ctx.sample_rate
        build = int(sr * ctx.beat_sec_in * 8)       # 2-bar build into incoming
        tl = TransitionTimeline(t1_sample=0, t2_sample=build, t3_sample=build + 1)
        return PlannedTransition(
            technique=self.id, timeline=tl,
            tempo_continuity_required=False, phrase_safe=True, quality=0.85,
            params={"build": build},
            render_length=tl.t3_sample, switch_offset=build,
            events=[PackEvent(sample=build, type="transition.switch",
                              payload={"technique": self.id})])

    def render(self, plan: PlannedTransition, ctx: SegmentContext) -> RenderedTransition:
        sr = ctx.sample_rate
        n = plan.params["build"]
        # Build from the *incoming* head: HP filter opens + gain rises into drop.
        src = ctx.incoming_audio.samples[ctx.incoming_start:ctx.incoming_start + n]
        src = fit_len(src, n)
        body = filter_sweep(src, sr, 3000.0, 100.0, mode="highpass")
        body = apply_gain(body, gain_ramp(body.shape[0], 0.3, 1.0))
        out = normalize_peak(fit_len(body, plan.render_length))
        return RenderedTransition(out, sr, plan.timeline,
                                  plan.switch_offset, plan.events)
