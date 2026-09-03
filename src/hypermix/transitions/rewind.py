"""rewind — source-derived reverse-tail reset transition (§12). Preferred
universal fallback; deterministic and offline."""
from __future__ import annotations

import numpy as np

from ..model import PackEvent, TransitionCapabilities, TransitionTimeline
from .dsp import (declick_join, filter_sweep, fit_len, gain_ramp, apply_gain,
                  normalize_peak, reverse_tail)
from .model import PlannedTransition, RenderedTransition, SegmentContext


class Rewind:
    id = "rewind"
    capabilities = TransitionCapabilities(
        tempo_continuity_required=False, phrase_safe=True, supports_hot_swap=True)

    def plan(self, ctx: SegmentContext) -> PlannedTransition:
        sr = ctx.sample_rate
        bars = float(ctx.params.get("bars", 0.5))
        rewind_len = int(sr * ctx.beat_sec_out * 4 * bars)
        drop_head = int(sr * 0.05)  # tiny head of incoming for click-safe join
        tl = TransitionTimeline(t1_sample=0, t2_sample=rewind_len,
                                t3_sample=rewind_len + drop_head)
        return PlannedTransition(
            technique=self.id, timeline=tl,
            tempo_continuity_required=False, phrase_safe=True, quality=0.95,
            params={"rewind_len": rewind_len, "drop_head": drop_head},
            render_length=tl.t3_sample, switch_offset=rewind_len,
            events=[PackEvent(sample=0, type="transition.start",
                              payload={"technique": self.id}),
                    PackEvent(sample=rewind_len, type="transition.switch",
                              payload={"technique": self.id})])

    def render(self, plan: PlannedTransition, ctx: SegmentContext) -> RenderedTransition:
        sr = ctx.sample_rate
        rewind_len = plan.params["rewind_len"]
        # 1. take outgoing tail; 2. reverse; 3. HP filter ramp; 5. shape gain;
        tail = ctx.outgoing_audio.samples[
            max(0, ctx.outgoing_end - rewind_len):ctx.outgoing_end]
        tail = fit_len(tail, rewind_len)
        rev = reverse_tail(tail)
        rev = filter_sweep(rev, sr, from_hz=80.0, to_hz=3000.0, mode="highpass")
        g = gain_ramp(rewind_len, 1.0, 0.15, curve="exp")
        rev = apply_gain(rev, g)
        # 6/7. deliberate reset: incoming starts exactly at cue (switch at t2).
        head = ctx.incoming_audio.samples[
            ctx.incoming_start:ctx.incoming_start + plan.params["drop_head"]]
        body = declick_join(rev, head, sr, fade_ms=10.0)
        body = normalize_peak(fit_len(body, plan.render_length))
        return RenderedTransition(body, sr, plan.timeline,
                                  plan.switch_offset, plan.events)
