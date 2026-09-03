"""stutter — escalating source-slice repeats before impact (§12). Supports
1/2, 1/4, 1/8, 1/16 beat slices."""
from __future__ import annotations

import numpy as np

from ..model import PackEvent, TransitionCapabilities, TransitionTimeline
from .dsp import declick_join, fit_len, normalize_peak
from .model import PlannedTransition, RenderedTransition, SegmentContext

_FRACTIONS = {"1/2": 0.5, "1/4": 0.25, "1/8": 0.125, "1/16": 0.0625}


class Stutter:
    id = "stutter"
    capabilities = TransitionCapabilities(
        tempo_continuity_required=False, phrase_safe=True, supports_hot_swap=True)

    def plan(self, ctx: SegmentContext) -> PlannedTransition:
        sr = ctx.sample_rate
        # Escalating pattern: 2x 1/4, 4x 1/8, 8x 1/16 (in beats).
        pattern = ctx.params.get("pattern", [("1/4", 2), ("1/8", 4), ("1/16", 8)])
        beat = ctx.beat_sec_out
        total = 0
        steps = []
        for frac, count in pattern:
            step = int(sr * beat * _FRACTIONS[frac]) * count
            steps.append(int(sr * beat * _FRACTIONS[frac]))
            total += step
        head = int(sr * 0.05)
        tl = TransitionTimeline(t1_sample=0, t2_sample=total, t3_sample=total + head)
        return PlannedTransition(
            technique=self.id, timeline=tl,
            tempo_continuity_required=False, phrase_safe=True, quality=0.85,
            params={"steps": steps, "counts": [c for _, c in pattern],
                    "drop_head": head},
            render_length=tl.t3_sample, switch_offset=total,
            events=[PackEvent(sample=total, type="transition.switch",
                              payload={"technique": self.id})])

    def render(self, plan: PlannedTransition, ctx: SegmentContext) -> RenderedTransition:
        sr = ctx.sample_rate
        # Source slice: last beat of outgoing.
        beat_len = int(sr * ctx.beat_sec_out)
        src = ctx.outgoing_audio.samples[max(0, ctx.outgoing_end - beat_len):ctx.outgoing_end]
        src = fit_len(src, beat_len)
        parts = []
        for step, count in zip(plan.params["steps"], plan.params["counts"]):
            slice_ = src[:step]
            for _ in range(count):
                parts.append(slice_)
        stut = np.vstack(parts) if parts else src[:1]
        head = ctx.incoming_audio.samples[
            ctx.incoming_start:ctx.incoming_start + plan.params["drop_head"]]
        body = declick_join(stut, head, sr, fade_ms=5.0)
        body = normalize_peak(fit_len(body, plan.render_length))
        return RenderedTransition(body, sr, plan.timeline,
                                  plan.switch_offset, plan.events)
