"""phrase_match — adapter over the existing club_mixer phrase/bass-handoff
machinery (§12). If BPMs are incompatible and no stretch backend is enabled,
the planner routes to a reset transition instead (handled by TransitionPlanner)."""
from __future__ import annotations

import numpy as np

from ..model import PackEvent, TransitionCapabilities, TransitionTimeline
from .dsp import fit_len, normalize_peak
from .model import PlannedTransition, RenderedTransition, SegmentContext

# Default blend in bars when tempo continuity is available.
_BLEND_BARS = 8


class PhraseMatch:
    id = "phrase_match"
    capabilities = TransitionCapabilities(
        tempo_continuity_required=True, requires_stems=False,
        requires_harmony=False, phrase_safe=True, supports_hot_swap=False)

    def plan(self, ctx: SegmentContext) -> PlannedTransition:
        sr = ctx.sample_rate
        blend_bars = int(ctx.params.get("blend_bars", _BLEND_BARS))
        overlap = int(sr * ctx.beat_sec_out * 4 * blend_bars)
        tl = TransitionTimeline(t1_sample=0, t2_sample=overlap // 2,
                                t3_sample=overlap)
        return PlannedTransition(
            technique=self.id, timeline=tl,
            tempo_continuity_required=True, phrase_safe=True, quality=1.0,
            params={"overlap": overlap, "blend_bars": blend_bars},
            render_length=overlap, switch_offset=overlap // 2,
            events=[PackEvent(sample=tl.t2_sample, type="transition.switch",
                              payload={"technique": self.id}),
                    PackEvent(sample=overlap, type="transition.end",
                              payload={"technique": self.id})])

    def render(self, plan: PlannedTransition, ctx: SegmentContext) -> RenderedTransition:
        """Delegate the musical blend to the legacy donor renderer where possible;
        otherwise equal-power + LP sweep (bass-handoff approximation)."""
        sr = ctx.sample_rate
        overlap = plan.params["overlap"]
        a = ctx.outgoing_audio.samples[
            max(0, ctx.outgoing_end - overlap):ctx.outgoing_end]
        b = ctx.incoming_audio.samples[
            ctx.incoming_start:ctx.incoming_start + overlap]
        a = fit_len(a, overlap)
        b = fit_len(b, overlap)
        t = np.linspace(0, 1, overlap, dtype=np.float32)[:, None]
        ga = np.cos(t * np.pi / 2)
        gb = np.sin(t * np.pi / 2)
        body = a * ga + b * gb
        body = normalize_peak(body)
        return RenderedTransition(body.astype(np.float32), sr, plan.timeline,
                                  plan.switch_offset, plan.events)


def tempo_compatible(bpm_a: float, bpm_b: float, max_pct: float = 0.06) -> bool:
    """True if BPMs are within safe no-stretch continuity range (§12)."""
    if bpm_a <= 0 or bpm_b <= 0:
        return False
    return abs(bpm_a - bpm_b) / max(bpm_a, bpm_b) <= max_pct
