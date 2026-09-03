"""back_and_forth — alternate A/B by bar blocks and settle on B (§12). Only
when tempo/rhythm compatibility is sufficient (checked by the planner)."""
from __future__ import annotations

import numpy as np

from ..model import PackEvent, TransitionCapabilities, TransitionTimeline
from .dsp import declick_join, fit_len, normalize_peak
from .model import PlannedTransition, RenderedTransition, SegmentContext


class BackAndForth:
    id = "back_and_forth"
    capabilities = TransitionCapabilities(
        tempo_continuity_required=True, phrase_safe=True, supports_hot_swap=False)

    def plan(self, ctx: SegmentContext) -> PlannedTransition:
        sr = ctx.sample_rate
        bar = int(sr * ctx.beat_sec_out * 4)
        switches = int(ctx.params.get("switches", 3))   # A/B alternations before settling
        total = bar * switches * 2
        tl = TransitionTimeline(t1_sample=0, t2_sample=total, t3_sample=total + 1)
        return PlannedTransition(
            technique=self.id, timeline=tl,
            tempo_continuity_required=True, phrase_safe=True, quality=0.8,
            params={"bar": bar, "switches": switches},
            render_length=tl.t3_sample, switch_offset=total,
            events=[PackEvent(sample=total, type="transition.switch",
                              payload={"technique": self.id})])

    def render(self, plan: PlannedTransition, ctx: SegmentContext) -> RenderedTransition:
        sr = ctx.sample_rate
        bar = plan.params["bar"]
        switches = plan.params["switches"]
        parts = []
        a_pos = max(0, ctx.outgoing_end - bar * switches)
        b_pos = ctx.incoming_start
        for i in range(switches * 2):
            if i % 2 == 0:
                seg = ctx.outgoing_audio.samples[a_pos:a_pos + bar]
                a_pos += bar
            else:
                seg = ctx.incoming_audio.samples[b_pos:b_pos + bar]
                b_pos += bar
            parts.append(fit_len(seg, bar))
        body = parts[0]
        for p in parts[1:]:
            body = declick_join(body, p, sr, fade_ms=6.0)
        body = normalize_peak(fit_len(body, plan.render_length))
        return RenderedTransition(body, sr, plan.timeline,
                                  plan.switch_offset, plan.events)
