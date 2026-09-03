"""transformer_cuts — rhythmic gain gating on beat subdivisions (§12). No
scratch engine; deterministic gate pattern."""
from __future__ import annotations

import numpy as np

from ..model import PackEvent, TransitionCapabilities, TransitionTimeline
from .dsp import declick_join, fit_len, normalize_peak
from .model import PlannedTransition, RenderedTransition, SegmentContext


class TransformerCuts:
    id = "transformer_cuts"
    capabilities = TransitionCapabilities(
        tempo_continuity_required=False, phrase_safe=True, supports_hot_swap=True)

    def plan(self, ctx: SegmentContext) -> PlannedTransition:
        sr = ctx.sample_rate
        bars = float(ctx.params.get("bars", 1.0))
        total = int(sr * ctx.beat_sec_out * 4 * bars)
        head = int(sr * 0.05)
        tl = TransitionTimeline(t1_sample=0, t2_sample=total, t3_sample=total + head)
        return PlannedTransition(
            technique=self.id, timeline=tl,
            tempo_continuity_required=False, phrase_safe=True, quality=0.8,
            params={"total": total, "drop_head": head,
                    "gate": int(sr * ctx.beat_sec_out / 4)},  # 16th-note gate
            render_length=tl.t3_sample, switch_offset=total,
            events=[PackEvent(sample=total, type="transition.switch",
                              payload={"technique": self.id})])

    def render(self, plan: PlannedTransition, ctx: SegmentContext) -> RenderedTransition:
        sr = ctx.sample_rate
        total = plan.params["total"]
        gate = max(1, plan.params["gate"])
        src = ctx.outgoing_audio.samples[max(0, ctx.outgoing_end - total):ctx.outgoing_end]
        src = fit_len(src, total)
        # Deterministic 16th-note gate: on-off-on-off with a tiny ramp to declick.
        env = np.zeros(total, dtype=np.float32)
        ramp = min(32, gate // 8)
        for i in range(0, total, gate):
            on = ((i // gate) % 2) == 0
            if not on:
                continue
            end = min(total, i + gate)
            env[i:end] = 1.0
            if ramp > 0:
                env[i:i + ramp] = np.linspace(0, 1, end - i if end - i < ramp else ramp)[:end - i]
        body = (src.T * env).T
        head = ctx.incoming_audio.samples[
            ctx.incoming_start:ctx.incoming_start + plan.params["drop_head"]]
        out = declick_join(body, head, sr, fade_ms=5.0)
        out = normalize_peak(fit_len(out, plan.render_length))
        return RenderedTransition(out, sr, plan.timeline,
                                  plan.switch_offset, plan.events)
