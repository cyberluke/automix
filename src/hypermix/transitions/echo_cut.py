"""echo_cut — offline-rendered outgoing delay/echo tail; incoming may start
underneath the tail (§12)."""
from __future__ import annotations

import numpy as np

from ..model import PackEvent, TransitionCapabilities, TransitionTimeline
from .dsp import echo_tail, fit_len, normalize_peak
from .model import PlannedTransition, RenderedTransition, SegmentContext


class EchoCut:
    id = "echo_cut"
    capabilities = TransitionCapabilities(
        tempo_continuity_required=False, phrase_safe=True, supports_hot_swap=True)

    def plan(self, ctx: SegmentContext) -> PlannedTransition:
        sr = ctx.sample_rate
        beat_fraction = float(ctx.params.get("beat_fraction", 0.75))
        feedback = float(ctx.params.get("feedback", 0.45))
        tail_sec = float(ctx.params.get("tail_sec", 1.5))
        delay_sec = ctx.beat_sec_out * beat_fraction
        source_len = int(sr * ctx.beat_sec_out * 2)
        tail = int(sr * tail_sec)
        total = source_len + tail
        # Switch happens as soon as the outgoing body ends; incoming enters under tail.
        tl = TransitionTimeline(t1_sample=0, t2_sample=source_len, t3_sample=total)
        return PlannedTransition(
            technique=self.id, timeline=tl,
            tempo_continuity_required=False, phrase_safe=True, quality=0.9,
            params={"delay_sec": delay_sec, "feedback": feedback,
                    "tail_sec": tail_sec, "source_len": source_len},
            render_length=total, switch_offset=source_len,
            events=[PackEvent(sample=source_len, type="transition.switch",
                              payload={"technique": self.id}),
                    PackEvent(sample=total, type="transition.end",
                              payload={"technique": self.id})])

    def render(self, plan: PlannedTransition, ctx: SegmentContext) -> RenderedTransition:
        sr = ctx.sample_rate
        source_len = plan.params["source_len"]
        body_src = ctx.outgoing_audio.samples[
            max(0, ctx.outgoing_end - source_len):ctx.outgoing_end]
        body_src = fit_len(body_src, source_len)
        echoed = echo_tail(body_src, sr, plan.params["delay_sec"],
                           plan.params["feedback"], plan.params["tail_sec"],
                           wet=0.5, lowpass_hz=5500.0)
        echoed = fit_len(echoed, plan.render_length)
        # Incoming starts at t2 underneath the tail.
        inc_len = plan.render_length - plan.switch_offset
        incoming = ctx.incoming_audio.samples[
            ctx.incoming_start:ctx.incoming_start + inc_len]
        incoming = fit_len(incoming, inc_len)
        body = echoed.copy()
        body[plan.switch_offset:] += incoming * 0.95
        body = normalize_peak(body)
        return RenderedTransition(body, sr, plan.timeline,
                                  plan.switch_offset, plan.events)
