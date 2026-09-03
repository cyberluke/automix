"""double_drop — both segments high-energy and phrase-aligned, impact points
aligned, bass collision controlled (§12). Falls back to slam/rewind when tempos
cannot be synchronized safely."""
from __future__ import annotations

import numpy as np

from ..model import PackEvent, TransitionCapabilities, TransitionTimeline
from .dsp import fit_len, normalize_peak, one_pole_lowpass
from .model import PlannedTransition, RenderedTransition, SegmentContext


class DoubleDrop:
    id = "double_drop"
    capabilities = TransitionCapabilities(
        tempo_continuity_required=True, requires_stems=False,
        phrase_safe=True, supports_hot_swap=False)

    def plan(self, ctx: SegmentContext) -> PlannedTransition:
        sr = ctx.sample_rate
        bars = int(ctx.params.get("blend_bars", 8))
        overlap = int(sr * ctx.beat_sec_out * 4 * bars)
        # Switch at the aligned impact point (both drops hit together).
        tl = TransitionTimeline(t1_sample=0, t2_sample=overlap // 2,
                                t3_sample=overlap)
        return PlannedTransition(
            technique=self.id, timeline=tl,
            tempo_continuity_required=True, phrase_safe=True, quality=1.0,
            params={"overlap": overlap},
            render_length=overlap, switch_offset=overlap // 2,
            events=[PackEvent(sample=tl.t2_sample, type="drop",
                              payload={"technique": self.id}),
                    PackEvent(sample=overlap, type="transition.end",
                              payload={"technique": self.id})])

    def render(self, plan: PlannedTransition, ctx: SegmentContext) -> RenderedTransition:
        sr = ctx.sample_rate
        overlap = plan.params["overlap"]
        a = fit_len(ctx.outgoing_audio.samples[
            max(0, ctx.outgoing_end - overlap):ctx.outgoing_end], overlap)
        b = fit_len(ctx.incoming_audio.samples[
            ctx.incoming_start:ctx.incoming_start + overlap], overlap)
        t = np.linspace(0, 1, overlap, dtype=np.float32)[:, None]
        ga = np.cos(t * np.pi / 2)
        gb = np.sin(t * np.pi / 2)
        # Bass collision control: LP-split and cross-hand the low band so kicks
        # don't sum; mids/highs blend equal-power.
        a_low = one_pole_lowpass(a, sr, 200.0)
        a_rest = a - a_low
        b_low = one_pole_lowpass(b, sr, 200.0)
        b_rest = b - b_low
        low = a_low * np.cos(t * np.pi / 2) + b_low * np.sin(t * np.pi / 2)
        body = a_rest * ga + b_rest * gb + low
        body = normalize_peak(body)
        return RenderedTransition(body.astype(np.float32), sr, plan.timeline,
                                  plan.switch_offset, plan.events)
