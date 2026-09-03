"""drum_roll — source-derived escalating roll with shortening subdivisions and
final impact at t2 (§12)."""
from __future__ import annotations

import numpy as np

from ..model import PackEvent, TransitionCapabilities, TransitionTimeline
from .dsp import declick_join, filter_sweep, fit_len, gain_ramp, apply_gain, normalize_peak
from .model import PlannedTransition, RenderedTransition, SegmentContext


class DrumRoll:
    id = "drum_roll"
    capabilities = TransitionCapabilities(
        tempo_continuity_required=False, phrase_safe=True, supports_hot_swap=True)

    def plan(self, ctx: SegmentContext) -> PlannedTransition:
        sr = ctx.sample_rate
        beat = ctx.beat_sec_out
        # Roll of shortening subdivisions: 1/2, 1/4, 1/8, 1/16 repeated to fill ~2 bars.
        subdivs = ctx.params.get("subdivs", [0.5, 0.25, 0.125, 0.0625])
        bars = float(ctx.params.get("bars", 2.0))
        total = int(sr * beat * 4 * bars)
        head = int(sr * 0.05)
        tl = TransitionTimeline(t1_sample=0, t2_sample=total, t3_sample=total + head)
        return PlannedTransition(
            technique=self.id, timeline=tl,
            tempo_continuity_required=False, phrase_safe=True, quality=0.85,
            params={"subdivs": subdivs, "total": total, "drop_head": head,
                    "beat_samples": int(sr * beat)},
            render_length=tl.t3_sample, switch_offset=total,
            events=[PackEvent(sample=total, type="transition.switch",
                              payload={"technique": self.id})])

    def render(self, plan: PlannedTransition, ctx: SegmentContext) -> RenderedTransition:
        sr = ctx.sample_rate
        beat_samples = plan.params["beat_samples"]
        total = plan.params["total"]
        subdivs = plan.params["subdivs"]
        # Use the last 4 beats (1 bar) of the outgoing track as the roll source so
        # the content ADVANCES as the roll accelerates (like a real DJ snare roll),
        # instead of re-triggering the same single beat -> machine-gun stutter.
        src_len = max(beat_samples * 4, beat_samples)
        src = ctx.outgoing_audio.samples[
            max(0, ctx.outgoing_end - src_len):ctx.outgoing_end]
        src = fit_len(src, src_len)
        # Short per-hit declick fade (ms) so chopped hits don't click.
        fade = max(1, int(sr * 0.004))
        parts = []
        filled = 0
        pos = src_len - beat_samples  # start the window at the final beat
        sub_idx = 0
        while filled < total:
            frac = subdivs[min(sub_idx, len(subdivs) - 1)]
            step = max(2 * fade + 1, int(beat_samples * frac))
            hit = src[max(0, pos):max(0, pos) + step]
            hit = fit_len(hit, step).copy()
            # declick the chopped hit: quick fade-in/out on the slice
            hit[:fade] *= np.linspace(0.0, 1.0, fade, dtype=np.float32)[:, None]
            hit[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)[:, None]
            parts.append(hit)
            filled += step
            # Escalate to shorter subdivision roughly every beat.
            sub_idx = min(len(subdivs) - 1, filled // beat_samples)
            # Advance the source window backwards as subdivisions shorten so the
            # roll walks through the bar; wrap around the bar when we run out.
            stride = max(1, int(step * 0.5))
            pos -= stride
            if pos < 0:
                pos = src_len - step
        roll = np.vstack(parts)[:total]
        roll = filter_sweep(roll, sr, 200.0, 4000.0, mode="highpass")
        roll = apply_gain(roll, gain_ramp(roll.shape[0], 0.7, 1.1))
        head = ctx.incoming_audio.samples[
            ctx.incoming_start:ctx.incoming_start + plan.params["drop_head"]]
        body = declick_join(roll, head, sr, fade_ms=5.0)
        body = normalize_peak(fit_len(body, plan.render_length))
        return RenderedTransition(body, sr, plan.timeline,
                                  plan.switch_offset, plan.events)
