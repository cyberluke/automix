"""loop_transition — beat/bar-safe loops of the outgoing tail before switching
(§12). Loop sizes: 1 beat, 2 beats, 1 bar, 2 bars, 4 bars."""
from __future__ import annotations

import numpy as np

from ..model import PackEvent, TransitionCapabilities, TransitionTimeline
from .dsp import declick_join, fit_len, normalize_peak
from .model import PlannedTransition, RenderedTransition, SegmentContext

_LOOP_BEATS = {"1beat": 1, "2beats": 2, "1bar": 4, "2bars": 8, "4bars": 16}


class LoopTransition:
    id = "loop_transition"
    capabilities = TransitionCapabilities(
        tempo_continuity_required=False, phrase_safe=True, supports_hot_swap=True)

    def plan(self, ctx: SegmentContext) -> PlannedTransition:
        sr = ctx.sample_rate
        size = ctx.params.get("loop", "1bar")
        repeats = int(ctx.params.get("repeats", 2))
        beats = _LOOP_BEATS.get(size, 4)
        loop_len = int(sr * ctx.beat_sec_out * beats)
        total = loop_len * repeats
        head = int(sr * 0.05)
        tl = TransitionTimeline(t1_sample=0, t2_sample=total, t3_sample=total + head)
        return PlannedTransition(
            technique=self.id, timeline=tl,
            tempo_continuity_required=False, phrase_safe=True, quality=0.85,
            params={"loop_len": loop_len, "repeats": repeats, "drop_head": head},
            render_length=tl.t3_sample, switch_offset=total,
            events=[PackEvent(sample=total, type="transition.switch",
                              payload={"technique": self.id})])

    def render(self, plan: PlannedTransition, ctx: SegmentContext) -> RenderedTransition:
        sr = ctx.sample_rate
        loop_len = plan.params["loop_len"]
        src = ctx.outgoing_audio.samples[
            max(0, ctx.outgoing_end - loop_len):ctx.outgoing_end]
        src = fit_len(src, loop_len)
        looped = np.vstack([src] * plan.params["repeats"])
        head = ctx.incoming_audio.samples[
            ctx.incoming_start:ctx.incoming_start + plan.params["drop_head"]]
        body = declick_join(looped, head, sr, fade_ms=8.0)
        body = normalize_peak(fit_len(body, plan.render_length))
        return RenderedTransition(body, sr, plan.timeline,
                                  plan.switch_offset, plan.events)
