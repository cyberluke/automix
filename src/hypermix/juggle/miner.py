"""JuggleMiner orchestrator — offline brute-force master-juggle discovery.

  MASTER_JUGGLE
      ↓ render candidate offsets (offset × duration × repeat grid)
      ↓ score punch / transient density / spectral novelty / vocal-hook / groove
      ↓ rank, keep top_k, save the interesting accidents as WAV previews.

Runs entirely in .venv-hypermix. No stems venv (no Demucs / Basic Pitch).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

from .types import (
    JuggleCandidate, JuggleGesture, JuggleMinerConfig, JuggleMinerRequest,
    JuggleMinerResult, PhraseRole, role_default_settings,
)
from . import dsp


def run_juggle_mine(request: JuggleMinerRequest, out_dir: str,
                    cfg: Optional[JuggleMinerConfig] = None) -> JuggleMinerResult:
    cfg = cfg or JuggleMinerConfig()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result = JuggleMinerResult(request=request)

    import soundfile as sf
    master, sr = sf.read(request.source_wav, dtype="float32", always_2d=True)
    if sr != cfg.sr:
        # cheap resample via librosa if needed
        try:
            import librosa
            mono = master.T
            master = np.stack(
                [librosa.resample(ch, orig_sr=sr, target_sr=cfg.sr) for ch in mono],
                axis=-1)
            sr = cfg.sr
        except Exception as exc:
            raise RuntimeError(f"sr mismatch {sr} != {cfg.sr} and resample failed: {exc}")

    role_sets = role_default_settings(request.role)
    boost = role_sets.get("boost", "punch")
    # If the caller overrode the grids (preset / --mode / --loop-count), honour
    # cfg EXACTLY; otherwise fall back to the role's intelligent defaults.
    default_cfg = JuggleMinerConfig(sr=cfg.sr)
    overridden = (
        cfg.offsets_beats != default_cfg.offsets_beats or
        cfg.durations_beats != default_cfg.durations_beats or
        cfg.repeats != default_cfg.repeats or
        cfg.loop_counts != default_cfg.loop_counts
    )
    if overridden:
        offsets = cfg.offsets_beats
        durations = cfg.durations_beats
        repeats = cfg.repeats
        loop_counts = cfg.loop_counts
    else:
        offsets = role_sets.get("offsets", cfg.offsets_beats)
        durations = role_sets.get("durations", cfg.durations_beats)
        repeats = role_sets.get("repeats", cfg.repeats)
        loop_counts = role_sets.get("loop_counts", cfg.loop_counts)
    result.log.append(
        f"role={request.role.value} boost={boost} offsets={offsets} "
        f"durations={durations} repeats={repeats} loop_counts={loop_counts} "
        f"phases={getattr(cfg, 'phases', ['onbeat'])}"
        + (" [preset/override]" if overridden else ""))

    beat_s = 60.0 / float(request.bpm)
    boundary_i = int(round(request.boundary_s * cfg.sr))
    ctx_n = int(round(cfg.novelty_win_beats * beat_s * cfg.sr))
    ctx_lo = max(0, boundary_i - ctx_n)
    ctx_hi = min(len(master), boundary_i + ctx_n)
    context = master[ctx_lo:boundary_i]  # pre-boundary context for novelty

    best: list[JuggleCandidate] = []
    n_rendered = 0
    phases = getattr(cfg, 'phases', ['onbeat'])
    grids = getattr(cfg, 'grids', ['straight'])
    for off in offsets:
        for dur in durations:
            for phase in phases:
              for grid in grids:
                # anchor (slice head) shifts half a beat on offbeat
                anchor_i = boundary_i + (int(round(0.5 * beat_s * cfg.sr))
                                         if phase == 'offbeat' else 0)
                # backstep: score the SAME slice the renderer repeats — the
                # LAST `dur` beats immediately BEFORE the anchor.
                d_n = max(1, int(round(dur * beat_s * cfg.sr)))
                s_i = max(0, anchor_i - d_n)
                slice_audio = master[s_i:anchor_i]
                if slice_audio.shape[0] == 0:
                    continue
                # two placements: retrigger at the anchor, and end-of-loop double/triple
                placements = [("retrigger", r, 1) for r in repeats] + \
                             [("loop", 1, lc) for lc in loop_counts]
                for mode, rep, lc in placements:
                    total, scores = dsp.score_candidate(
                        master, slice_audio, context, cfg.sr, request.bpm, cfg, boost)
                    g = JuggleGesture(offset_beats=off, duration_beats=dur,
                                      repeat=rep, phase=phase, mode=mode,
                                      loop_count=lc, grid=grid)
                    desc = _describe(g, scores)
                    best.append(JuggleCandidate(gesture=g, scores=scores, description=desc))
                    n_rendered += 1

    # rank by composite score, keep top_k, render previews only for winners
    best.sort(key=lambda c: c.scores.total, reverse=True)
    top = best[: cfg.top_k]
    for rank, cand in enumerate(top):
        g = cand.gesture
        # Render LONG enough for the whole effect to be audible: the post-anchor
        # window must cover duration × (repeat | loop_count) plus a tail, else a
        # 2-beat triple (or a loop) gets truncated and the activation is cut off.
        n_hits = g.loop_count if g.mode == "loop" else g.repeat
        needed_post = g.duration_beats * max(1, n_hits) + 4.0
        ctx = max(request.context_beats, needed_post)
        preview = dsp.render_juggle(
            master, cfg.sr, request.bpm, request.boundary_s,
            offset_beats=g.offset_beats,
            duration_beats=g.duration_beats,
            repeat=g.repeat,
            phase=g.phase,
            mode=g.mode,
            loop_count=g.loop_count,
            declick_ms=cfg.declick_ms,
            context_beats=ctx,
            peak_ceiling=cfg.peak_ceiling,
            vinyl=getattr(cfg, 'vinyl', False),
            vinyl_depth=getattr(cfg, 'vinyl_depth', 0.5),
            reverse_flourish=getattr(cfg, 'reverse_flourish', False),
            grid=getattr(g, 'grid', 'straight'),
            slap_beats=getattr(g, 'slap_beats', 0.75),
            humanize=getattr(cfg, 'humanize', False),
            humanize_timing_ms=getattr(cfg, 'humanize_timing_ms', 9.0),
            humanize_gain=getattr(cfg, 'humanize_gain', 0.10),
            humanize_pitch=getattr(cfg, 'humanize_pitch', 0.008),
            swing=getattr(cfg, 'swing', 0.0),
            accelerate=getattr(cfg, 'accelerate', 0.0),
            buffer_hack=getattr(cfg, 'buffer_hack', False),
            hack_div=getattr(cfg, 'hack_div', 4),
            hack_shrink=getattr(cfg, 'hack_shrink', 0.6),
            hack_rate=getattr(cfg, 'hack_rate', 0.9),
            hack_cut_ms=getattr(cfg, 'hack_cut_ms', 10.0),
            chirp=getattr(cfg, 'chirp', False),
            chirp_ms=getattr(cfg, 'chirp_ms', 38.0),
            chirp_swing=getattr(cfg, 'chirp_swing', 1.8),
            skip_bars=getattr(cfg, 'skip_bars', 0.0),
            power_down=getattr(cfg, 'power_down', False),
            power_down_s=getattr(cfg, 'power_down_s', 0.7),
            forward_last=getattr(cfg, 'forward_last', False),
            forward_shift=getattr(cfg, 'forward_shift', 0.5),
            fader_cut_ms=getattr(cfg, 'fader_cut_ms', 0.0),
            power_down_overlap_beats=getattr(cfg, 'power_down_overlap_beats', 0.0),
            seed=getattr(cfg, 'seed', 0) + rank,
        )
        tag = _tag(g)
        wav_path = out / f"juggle.{rank:02d}.{tag}.wav"
        sf.write(str(wav_path), preview, cfg.sr)
        cand.wav_path = str(wav_path)

    result.candidates = top
    result.log.append(
        f"rendered {n_rendered} candidates, kept top {len(top)} "
        f"(boundary={request.boundary_s:.2f}s bpm={request.bpm})")
    return result


def _tag(g: JuggleGesture) -> str:
    def f(x: float) -> str:
        # beats → friendly fraction-ish tag
        return (f"{x:.3f}".rstrip("0").rstrip(".")).replace(".", "p")
    mode = "loop" if g.mode == "loop" else f"r{g.repeat}"
    ph = "on" if g.phase == "onbeat" else "off"
    gr = {"straight": "", "slap": "_slap", "swing": "_swing"}.get(
        getattr(g, 'grid', 'straight'), "")
    base = f"-{f(g.offset_beats)}b_x{f(g.duration_beats)}b_{mode}"
    if g.mode == "loop":
        base += f"{g.loop_count}"
    return f"{base}_{ph}{gr}"


def _describe(g: JuggleGesture, s) -> str:
    mode = f"loop×{g.loop_count}" if g.mode == "loop" else f"r{g.repeat}"
    ph = "on-beat" if g.phase == "onbeat" else "off-beat"
    gr = {"straight": "", "slap": " slap(3/4)", "swing": " swing"}.get(
        getattr(g, 'grid', 'straight'), "")
    bits = [f"-{g.offset_beats:g}b × {g.duration_beats:g}b {mode} {ph}{gr}"]
    if s.punch > 0.6:
        bits.append("punchy")
    if s.vocal_hook > 0.5:
        bits.append("vocal hook")
    if s.spectral_novelty > 0.5:
        bits.append("novel")
    if s.groove > 0.7:
        bits.append("on-grid")
    return " ".join(bits)
