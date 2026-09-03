"""slam / drop_on_the_one — universal reset transitions (§12).

`slam` is the 'hard brake + snap back on the one' reset. Original produced a
~30 ms blip which was too short to be heard in a mix (it read as a plain
gapless cut). Now it is a full ~1-bar reset: the outgoing phrase is braked
(LP sweep down + gain fall) so the energy visibly drops, then lands hard on
the incoming downbeat — an audible, musical 'reset'.
"""
from __future__ import annotations

from ..model import PackEvent, TransitionCapabilities, TransitionTimeline
from .dsp import (apply_gain, declick_join, filter_sweep, fit_len, gain_ramp,
                  normalize_peak)
from .model import PlannedTransition, RenderedTransition, SegmentContext


class Slam:
    id = "slam"
    capabilities = TransitionCapabilities(
        tempo_continuity_required=False, phrase_safe=True, supports_hot_swap=True)

    def _bars(self, ctx: SegmentContext) -> float:
        # A whole bar of reset so the transition is audible, not a 30ms blip.
        return float(ctx.params.get("bars", 1.0))

    def _switch_frac(self, ctx: SegmentContext) -> float:
        # The switch lands near the end of the reset window.
        return float(ctx.params.get("switch_frac", 0.85))

    def plan(self, ctx: SegmentContext) -> PlannedTransition:
        sr = ctx.sample_rate
        bars = max(0.25, self._bars(ctx))
        reset = int(round(bars * 4.0 * sr * ctx.beat_sec_in))
        sw = int(round(reset * self._switch_frac(ctx)))
        # t3 just after the switch (1 extra sample).
        tl = TransitionTimeline(t1_sample=0, t2_sample=sw, t3_sample=sw + 1)
        return PlannedTransition(
            technique=self.id, timeline=tl,
            tempo_continuity_required=False, phrase_safe=True, quality=0.9,
            render_length=reset, switch_offset=sw,
            events=[PackEvent(sample=sw, type="transition.switch",
                              payload={"technique": self.id})])

    def render(self, plan: PlannedTransition, ctx: SegmentContext) -> RenderedTransition:
        sr = ctx.sample_rate
        reset = plan.render_length
        sw = plan.switch_offset
        # Outgoing tail we brake (roughly the reset window, clamped to source).
        src = ctx.outgoing_audio.samples[
            max(0, ctx.outgoing_end - reset):ctx.outgoing_end]
        src = fit_len(src, reset)
        # BRAKE: LP sweep high->low + gain fall => a clear audible reset.
        braked = filter_sweep(src, sr, 16000.0, 300.0, mode="lowpass")
        braked = apply_gain(braked, gain_ramp(reset, 1.0, 0.25, curve="exp"))
        # LAND hard on the incoming downbeat: a short incoming head at the switch.
        head_n = reset - sw
        in_head = ctx.incoming_audio.samples[
            ctx.incoming_start:ctx.incoming_start + head_n]
        in_head = fit_len(in_head, head_n)
        # Join braked outgoing tail with the incoming head (the 'slam in').
        body = declick_join(braked, in_head, sr, fade_ms=min(20.0, 0.03 * sr))
        body = fit_len(body, reset)
        body = normalize_peak(body)
        return RenderedTransition(body, sr, plan.timeline,
                                  plan.switch_offset, plan.events)


class DropOnTheOne(Slam):
    """Hard cut exactly on the incoming downbeat (§12)."""
    id = "drop_on_the_one"

    def _bars(self, ctx: SegmentContext) -> float:
        return float(ctx.params.get("bars", 0.5))
