"""backspin — offline DJ-style decelerating tail via deterministic variable-rate
resampling (§12). No realtime master-tempo dependency."""
from __future__ import annotations

import numpy as np

from ..model import PackEvent, TransitionCapabilities, TransitionTimeline
from .dsp import (apply_gain, declick_join, fit_len, gain_ramp, normalize_peak,
                  variable_rate_resample)
from .model import PlannedTransition, RenderedTransition, SegmentContext


class Backspin:
    id = "backspin"
    capabilities = TransitionCapabilities(
        tempo_continuity_required=False, phrase_safe=True, supports_hot_swap=True)

    def plan(self, ctx: SegmentContext) -> PlannedTransition:
        sr = ctx.sample_rate
        tail_in = int(sr * ctx.beat_sec_out * 2)      # 2-beat source tail
        spin_len = int(tail_in * 1.6)                  # stretched by deceleration
        head = int(sr * 0.05)
        tl = TransitionTimeline(t1_sample=0, t2_sample=spin_len,
                                t3_sample=spin_len + head)
        return PlannedTransition(
            technique=self.id, timeline=tl,
            tempo_continuity_required=False, phrase_safe=True, quality=0.9,
            params={"tail_in": tail_in, "spin_len": spin_len, "drop_head": head},
            render_length=tl.t3_sample, switch_offset=spin_len,
            events=[PackEvent(sample=spin_len, type="transition.switch",
                              payload={"technique": self.id})])

    def render(self, plan: PlannedTransition, ctx: SegmentContext) -> RenderedTransition:
        sr = ctx.sample_rate
        tail_in = plan.params["tail_in"]
        tail = ctx.outgoing_audio.samples[
            max(0, ctx.outgoing_end - tail_in):ctx.outgoing_end]
        tail = fit_len(tail, tail_in)
        # Decelerating rate curve 1.0 -> ~0.15 (DJ platter slow-down), quadratic.
        n = plan.params["spin_len"]
        t = np.linspace(0, 1, n, dtype=np.float32)
        rate = 1.0 - 0.85 * (t ** 2)
        spun = variable_rate_resample(tail, rate)
        spun = fit_len(spun, n)
        spun = apply_gain(spun, gain_ramp(n, 1.0, 0.1, curve="exp"))
        head = ctx.incoming_audio.samples[
            ctx.incoming_start:ctx.incoming_start + plan.params["drop_head"]]
        body = declick_join(spun, head, sr, fade_ms=10.0)
        body = normalize_peak(fit_len(body, plan.render_length))
        return RenderedTransition(body, sr, plan.timeline,
                                  plan.switch_offset, plan.events)
