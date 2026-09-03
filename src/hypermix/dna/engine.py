"""apply_recipe — resolve a ProducerRecipe onto a concrete phrase.

The engine resolves each bar/beat step to SECONDS via the phrase BPM, then
dispatches the OperatorCall to a registered operator. Operators are registered
by name so the recipe format stays modular — new producers add operators without
touching the engine.

Built-in operators (the ones we've locked this session):
  'bass_solo'  — Variant B bass-solo breakdown (uses a BassProfile)
  'cyber_bass' — Variant A parallel cyber reinforcement (uses a BassProfile)

More operators (juggle preset, filter move, drum fill, duck/mute) register the
same way as we build them.
"""

from __future__ import annotations

import numpy as np

from .recipe import ProducerRecipe, RecipeStep

# operator registry: name -> callable(step, ctx) -> None (mutates ctx['mix'])
OPERATORS = {}


def operator(name):
    def deco(fn):
        OPERATORS[name] = fn
        return fn
    return deco


def bar_to_s(bar: float, beat: float, bpm: float, beats_per_bar: float = 4.0) -> float:
    return (bar * beats_per_bar + beat) * 60.0 / bpm


def apply_recipe(recipe: ProducerRecipe, mix: np.ndarray, sr: int, bpm: float,
                 role: str = "", stems: dict | None = None,
                 beats_per_bar: float = 4.0) -> np.ndarray:
    """Apply every step of `recipe` to `mix` (stereo float32 [n,2]).

    stems: optional {'bass':..., 'vocals':..., 'other':..., 'drums':...} for
           operators that need them (bass_solo, cyber_bass).
    Returns the processed mix (a new array).
    """
    out = mix.copy()
    ctx = {"sr": sr, "bpm": bpm, "role": role, "stems": stems or {},
           "beats_per_bar": beats_per_bar, "recipe": recipe}
    deferred_steps = []
    for step in recipe.steps:
        if step.call.params.get("post_mix", False):
            deferred_steps.append(step)
            continue
        if step.when_role and step.when_role != role:
            continue  # role gate
        fn = OPERATORS.get(step.call.op)
        if fn is None:
            raise KeyError(f"unknown operator {step.call.op!r}; "
                           f"registered: {sorted(OPERATORS)}")
        ctx["step"] = step
        ctx["t0_s"] = bar_to_s(step.bar, step.beat, bpm, beats_per_bar)
        ctx["t1_s"] = (bar_to_s(step.bar + step.span_bars, step.beat, bpm,
                                beats_per_bar) if step.span_bars else None)
        out = fn(out, ctx)
    # Protected overlays (voice tags, signatures) are rendered after all
    # master processing so effects such as beat-juggle cannot touch them.
    for step in deferred_steps:
        if step.when_role and step.when_role != role:
            continue
        fn = OPERATORS.get(step.call.op)
        if fn is None:
            raise KeyError(f"unknown operator {step.call.op!r}; "
                           f"registered: {sorted(OPERATORS)}")
        ctx["step"] = step
        ctx["t0_s"] = bar_to_s(step.bar, step.beat, bpm, beats_per_bar)
        ctx["t1_s"] = (bar_to_s(step.bar + step.span_bars, step.beat, bpm,
                                beats_per_bar) if step.span_bars else None)
        out = fn(out, ctx)
    return out.astype(np.float32)


# ---------------------------------------------------------------------------
# built-in operators (the locked recipes from this session)
# ---------------------------------------------------------------------------

@operator("bass_solo")
def _op_bass_solo(mix: np.ndarray, ctx: dict) -> np.ndarray:
    """Variant B bass-solo breakdown: replace [t0:t0+span] with the cranked,
    multiband-boosted bass + kept vocals, then fade the beat back in."""
    from scipy.signal import butter, sosfiltfilt
    from src.hypermix.spr.bass_character import get_bass_profile

    p = ctx["step"].call.params
    prof = get_bass_profile(p.get("profile", "bass_solo_malugi"))
    sr, stems = ctx["sr"], ctx["stems"]
    bass = stems.get("bass")
    if bass is None:
        return mix  # can't do a bass solo without a bass stem
    vocals = stems.get("vocals", np.zeros_like(bass))

    t0 = ctx["t0_s"]
    solo_len = ctx["t1_s"] - t0 if ctx["t1_s"] else \
        prof.solo_bars * ctx["beats_per_bar"] * 60.0 / ctx["bpm"]
    start = max(0.0, t0 - prof.solo_pre_s)
    i0 = int(start * sr)
    i1 = min(len(mix), int((start + solo_len) * sr))

    # multiband boost: Linkwitz-Riley split, crank ABOVE xover
    sos_lp = butter(4, prof.xover_hz / (sr / 2), 'lowpass', output='sos')
    sos_hp = butter(4, prof.xover_hz / (sr / 2), 'highpass', output='sos')
    b_lo = sosfiltfilt(sos_lp, bass, axis=0)
    b_hi = sosfiltfilt(sos_hp, bass, axis=0)
    boost = b_lo + prof.hi_gain * b_hi
    pk = np.abs(boost).max()
    if pk > prof.norm_peak:
        boost *= prof.norm_peak / pk
    solo = np.clip(boost + prof.vocal_gain * vocals, -0.97, 0.97)

    out = mix.copy()
    xf = int(prof.fade_in_ms / 1000.0 * sr)
    xf_out = int(prof.fade_resume_ms / 1000.0 * sr)
    env_out = np.linspace(1, 0, xf)[:, None]
    env_in = np.linspace(0, 1, xf)[:, None]
    env_res = np.linspace(0, 1, xf_out)[:, None]
    out[i0:i0 + xf] = mix[i0:i0 + xf] * env_out + solo[i0:i0 + xf] * env_in
    out[i0 + xf:i1] = solo[i0 + xf:i1]
    j1 = min(len(mix), i1 + xf_out)
    m = j1 - i1
    out[i1:j1] = solo[i1:j1] * (1 - env_res[:m]) + mix[i1:j1] * env_res[:m]
    return out


@operator("cyber_bass")
def _op_cyber_bass(mix: np.ndarray, ctx: dict) -> np.ndarray:
    """Variant A parallel cyber reinforcement: ADD the cyber layer on the mix
    (hard-clip guard only — the mix may be pre-normalized, no headroom)."""
    from src.hypermix.spr.bass_character import (analyze_bass, cyber_bass_layer,
                                                 get_bass_profile)
    p = ctx["step"].call.params
    prof = get_bass_profile(p.get("profile", "cyber_malugi"))
    sr, stems, bpm = ctx["sr"], ctx["stems"], ctx["bpm"]
    bass = stems.get("bass")
    if bass is None:
        return mix
    char = analyze_bass(bass, sr)
    layer = cyber_bass_layer(bass, char, sr=sr, bpm=bpm,
                             drive=prof.cyber_drive, max_wet=prof.cyber_max_wet,
                             overshoot=prof.cyber_overshoot,
                             chorus_ms=prof.cyber_chorus_ms)
    gain = prof.cyber_gain
    return np.clip(mix + gain * layer, -0.98, 0.98)


# ---------------------------------------------------------------------------
# mix-show operators (voice tags / filter automation / juggle)
# ---------------------------------------------------------------------------

def _load_sample(path: str, sr: int) -> np.ndarray:
    """Load a stab/voice sample -> canonical stereo float32 at `sr`."""
    import soundfile as sf
    y, ssr = sf.read(path, dtype="float32", always_2d=True)
    if ssr != sr:  # linear resample (deterministic, good enough for stabs)
        n_out = int(round(len(y) * sr / ssr))
        xi = np.linspace(0, len(y) - 1, n_out)
        x = np.arange(len(y))
        y = np.stack([np.interp(xi, x, y[:, c]) for c in range(y.shape[1])],
                     axis=1).astype(np.float32)
    return np.ascontiguousarray(y, dtype=np.float32)


def _smooth_duck_envelope(sample: np.ndarray, sr: int, attack_ms: float,
                           release_ms: float) -> np.ndarray:
    """Create a smooth 0..1 sidechain envelope from a stereo sample."""
    from scipy.ndimage import maximum_filter1d
    level = np.max(np.abs(sample), axis=1).astype(np.float32)
    peak = float(np.max(level)) or 1.0
    level = maximum_filter1d(level, size=max(1, int(0.004 * sr))) / peak
    out = np.zeros_like(level)
    attack = np.exp(-1.0 / max(1.0, sr * attack_ms / 1000.0))
    release = np.exp(-1.0 / max(1.0, sr * release_ms / 1000.0))
    for i, value in enumerate(level):
        coeff = attack if value > (out[i - 1] if i else 0.0) else release
        out[i] = coeff * (out[i - 1] if i else 0.0) + (1.0 - coeff) * value
    return np.clip(out, 0.0, 1.0)


def _voice_fx(sample: np.ndarray, sr: int, params: dict) -> np.ndarray:
    """Apply deterministic polish to a voice tag before it reaches the mix."""
    from scipy.signal import lfilter

    out = sample.astype(np.float32, copy=True)
    phaser_wet = float(params.get("phaser_wet", 0.0))
    if phaser_wet > 0.0:
        n = len(out)
        t = np.arange(n, dtype=np.float64) / sr
        rate = float(params.get("phaser_rate_hz", 0.22))
        depth = float(params.get("phaser_depth", 0.65))
        feedback = float(params.get("phaser_feedback", 0.35))
        for c in range(out.shape[1]):
            phase = 0.5 * (1.0 + np.sin(2.0 * np.pi * rate * t + c * np.pi / 2.0))
            wet = np.zeros(n, dtype=np.float32)
            state = 0.0
            signal = out[:, c].copy()
            for i in range(n):
                coeff = 0.18 + 0.42 * depth * phase[i]
                state = signal[i] + feedback * state
                wet[i] = (-coeff * state + signal[i - 1] * (1.0 + coeff)
                          if i else state)
            out[:, c] = (1.0 - phaser_wet) * signal + phaser_wet * wet
    flanger_wet = float(params.get("flanger_wet", 0.0))
    if flanger_wet > 0.0:
        from src.hypermix.spr.punk import flanger
        out = flanger(
            out, sr, wet=flanger_wet,
            rate_hz=float(params.get("flanger_rate_hz", 0.35)),
            depth_ms=float(params.get("flanger_depth_ms", 5.0)),
            base_ms=float(params.get("flanger_base_ms", 0.7)),
            feedback=float(params.get("flanger_feedback", 0.45)),
        )
    return out.astype(np.float32)


@operator("voice_tag")
def _op_voice_tag(mix: np.ndarray, ctx: dict) -> np.ndarray:
    """Overlay a stab/voice sample at the step position.

    params:
      path        sample file (wav/mp3)
      align       'start' (default) | 'end' — 'end' places the sample so its
                  TAIL lands exactly at the step time (e.g. a rewind ending at
                  a section boundary).
    align_end_s optional absolute timeline end in seconds; useful when a
            sample must finish exactly with a separate effect window.
      gain        linear gain (default 1.0)
      hipass_hz   optional low-cut so the stab doesn't fight the bass.
      echo_times  int — repeat the sample N times (stereo ping-pong delay).
      echo_s      seconds between echoes (e.g. a beat).
      echo_decay  gain multiplier per echo.
      echo_pingpong  bool — alternate L/R each echo.
      echo_wet_ramp_last_s  optional — keep echoes fully dry until the final
                  N seconds of the sample, then fade echo wetness from 0 to
                  echo_wet_ramp_to (useful for a delay that blooms only at
                  the end of a rewind/stab).
      echo_wet_ramp_to  final wet amount at the end of the ramp (0.5 = 50% wet).
            duck_depth  group-duck amount driven by this sample (0..1).
            duck_attack_ms / duck_release_ms  smooth group-duck timing.
    sample_tail_cut_s  hard-cut each sample overlay to this duration.
    effect_cut_s  stop placing this effect after this many seconds; the
              master outside the overlay is never modified.
    """
    from scipy.signal import butter, sosfiltfilt
    p = ctx["step"].call.params
    sr = ctx["sr"]
    smp = _load_sample(p["path"], sr) * float(p.get("gain", 1.0))
    hp = p.get("hipass_hz")
    if hp:
        sos = butter(4, float(hp) / (sr / 2), 'highpass', output='sos')
        smp = sosfiltfilt(sos, smp, axis=0).astype(np.float32)
    smp = _voice_fx(smp, sr, p)

    t0 = ctx["t0_s"]
    align = p.get("align", "start")
    if p.get("align_end_s") is not None:
        start = float(p["align_end_s"]) - (len(smp) / sr)
    else:
        start = t0 if align == "start" else t0 - (len(smp) / sr)
    i0 = int(round(start * sr))

    echo_times = int(p.get("echo_times", 1))
    echo_s = float(p.get("echo_s", 0.0))
    echo_decay = float(p.get("echo_decay", 0.6))
    pingpong = bool(p.get("echo_pingpong", False))
    echo_wet_ramp_last_s = p.get("echo_wet_ramp_last_s")
    echo_wet_ramp_to = float(p.get("echo_wet_ramp_to", 1.0))
    sample_tail_cut_s = p.get("sample_tail_cut_s")
    effect_cut_s = p.get("effect_cut_s")
    duck_depth = float(p.get("duck_depth", 0.0))
    duck_attack_ms = float(p.get("duck_attack_ms", 35.0))
    duck_release_ms = float(p.get("duck_release_ms", 240.0))
    if sample_tail_cut_s is not None:
        smp = smp[:max(0, int(round(float(sample_tail_cut_s) * sr)))]

    out = mix.copy()
    n = len(mix)
    wet_env = None
    if echo_wet_ramp_last_s is not None and echo_times > 1:
        ramp_n = max(1, min(len(smp), int(round(float(echo_wet_ramp_last_s) * sr))))
        wet_env = np.zeros(len(smp), dtype=np.float32)
        wet_env[-ramp_n:] = np.linspace(0.0, echo_wet_ramp_to, ramp_n,
                                        dtype=np.float32)
    for e in range(echo_times):
        g = echo_decay ** e
        if wet_env is not None:
            if e == 0:
                # Direct sample stays present; only its delayed energy blooms at
                # the end. Fade a small portion of direct gain down as wet rises.
                seg = smp * (1.0 - 0.5 * wet_env)[:, None]
            else:
                seg = smp * (g * wet_env)[:, None]
        else:
            seg = smp * g
        if pingpong and e % 2 == 1:
            seg = seg[:, ::-1]  # swap L/R
        j0 = i0 + int(round(e * echo_s * sr))
        # Limit only this sample overlay/echo, never the master buffer.
        if effect_cut_s is not None:
            effect_end = i0 + int(round(float(effect_cut_s) * sr))
            seg = seg[:max(0, effect_end - j0)]
        j1 = min(n, j0 + len(seg))
        if j1 <= j0:
            break
        L = j1 - j0
        if duck_depth > 0.0:
            duck = _smooth_duck_envelope(seg[:L], sr, duck_attack_ms,
                                         duck_release_ms)
            out[j0:j1] *= (1.0 - duck_depth * duck)[:, None]
        out[j0:j1] = np.clip(out[j0:j1] + seg[:L], -0.98, 0.98)
    return out


@operator("filter_sweep")
def _op_filter_sweep(mix: np.ndarray, ctx: dict) -> np.ndarray:
    """MS-20 filter automation over the step span: one slow open + fast reps.

    params:
      slow_bars   bars for the slow opening sweep (default = span)
      fast_reps   number of fast 1/4-bar sweeps after the open (0 = off)
      lp_from/lp_to, res, drive  passed to dsp.filter_automation
    """
    from src.hypermix.transitions.dsp import filter_automation
    p = ctx["step"].call.params
    sr, bpm = ctx["sr"], ctx["bpm"]
    t0 = ctx["t0_s"]
    i0 = int(round(t0 * sr))
    slow_bars = int(p.get("slow_bars",
                  ctx["step"].span_bars or 1))
    spb = sr * 60.0 / bpm
    slow_n = int(round(slow_bars * 4 * spb))
    i1 = min(len(mix), i0 + slow_n)
    out = mix.copy()
    seg = out[i0:i1]
    if len(seg) == 0:
        return out
    # Global fast-start policy: unless a recipe explicitly opts out, every
    # MS-20 automation starts already in the musical midrange and uses only a
    # short physical-model warm-up. This removes the old "slow attack from a
    # nearly closed filter" behaviour across DNA, compiler and future recipes.
    fast_start = bool(p.get("fast_start", True))
    min_start_hz = float(p.get("min_start_hz", 700.0 if fast_start else 20.0))
    max_warmup_s = float(p.get("max_warmup_s", 0.08 if fast_start else 0.5))
    warmup_n = min(i0, int(round(min(float(p.get("warmup_s", max_warmup_s)),
                                     max_warmup_s) * sr)))
    pre = out[i0 - warmup_n:i0] if warmup_n else seg[:0]
    filter_input = np.concatenate([pre, seg], axis=0) if warmup_n else seg
    # determinism: reset the knob slew memory between runs
    filter_automation._knob = None
    lp_from_hz = p.get("lp_from_hz")
    if lp_from_hz is None and fast_start:
        lp_norm = float(p.get("lp_from", 0.05))
        lp_from_hz = max(min_start_hz,
                         200.0 * (16000.0 / 200.0) ** lp_norm)
    elif lp_from_hz is not None and fast_start:
        lp_from_hz = max(min_start_hz, float(lp_from_hz))
    fast_from_hz = max(1000.0, float(lp_from_hz or min_start_hz)) if fast_start else None
    # PURE MS-20: no dry blend, unity-ish gain (drive ~1.0 => no distortion).
    filtered = filter_automation(
        filter_input, sr, bpm, bars=slow_bars,
        lp_from=float(p.get("lp_from", 0.05)), lp_to=float(p.get("lp_to", 1.0)),
        res=float(p.get("res", 0.6)), drive=float(p.get("drive", 1.0)),
        lp_from_hz=lp_from_hz, lp_to_hz=p.get("lp_to_hz"),
        hpf_from_hz=float(p.get("hpf_from_hz", 20.0)),
        hpf_to_hz=p.get("hpf_to_hz"),
        bypass_hpf=bool(p.get("bypass_hpf", False)),
        warmup_s=(warmup_n / sr if warmup_n else 0.0),
        revision=p.get("revision", "rev2"))
    out[i0:i1] = filtered[warmup_n:warmup_n + len(seg)]
    fast_reps = int(p.get("fast_reps", 0))
    if fast_reps:
        filter_automation._knob = None
        qbar_n = int(round(spb))  # 1 beat = 1/4 bar
        pos = i1
        for _ in range(fast_reps):
            e = min(len(mix), pos + qbar_n)
            if e <= pos:
                break
            out[pos:e] = filter_automation(
                out[pos:e], sr, bpm, bars=0.25,
                lp_from=0.3, lp_to=1.0, res=float(p.get("res", 0.6)),
                drive=float(p.get("drive", 1.0)),
                lp_from_hz=fast_from_hz,
                bypass_hpf=bool(p.get("bypass_hpf", False)),
                revision=p.get("revision", "rev2"))
            pos = e
    return out


def _juggle_inplace(master: np.ndarray, sr: int, bpm: float, boundary_s: float,
                    gesture, render: dict, seed: int = 0) -> np.ndarray:
    """In-place juggle: replace the buffer region but PRESERVE total length.

    render_juggle returns a context preview window; here we render a wide window
    around the boundary and splice ONLY the effect region back into the master,
    keeping the surrounding audio untouched and the array length identical.
    """
    from src.hypermix.juggle.dsp import render_juggle
    beat_s = 60.0 / float(bpm)
    anchor_i = int(round(boundary_s * sr))
    g = gesture
    # render a window that covers the whole effect + a beat of context each side
    n_hits = g.loop_count if g.mode == "loop" else g.repeat
    step_beats = (g.slap_beats if g.grid == "slap" else
                  g.duration_beats * (0.67 if g.grid == "swing" else 1.0))
    region_beats = step_beats * max(0, n_hits - 1) + g.duration_beats
    ctx_beats = max(2.0, region_beats + 1.0)
    prev = render_juggle(master, sr, bpm, boundary_s,
                         offset_beats=g.offset_beats, duration_beats=g.duration_beats,
                         repeat=g.repeat, phase=g.phase, mode=g.mode,
                         loop_count=g.loop_count, slice_gain=g.slice_gain,
                         context_beats=ctx_beats, seed=seed, **(render or {}))
    # splice: prev starts at max(0, anchor - ctx) in master coords
    pre_n = int(round(ctx_beats * beat_s * sr))
    start = max(0, anchor_i - pre_n)
    out = master.copy()
    L = min(len(prev), len(master) - start)
    out[start:start + L] = prev[:L]
    return np.clip(out, -0.98, 0.98)


@operator("juggle")
def _op_juggle(mix: np.ndarray, ctx: dict) -> np.ndarray:
    """Apply a saved juggle preset as a buffer-replace at the step position.

    params:
      preset  name from JUGGLE_PRESETS (e.g. 'signature_dj')
      seed    rng seed for humanize/vinyl nondeterminism-into-determinism.
    """
    from src.hypermix.juggle.types import get_preset
    p = ctx["step"].call.params
    pr = get_preset(p.get("preset", "signature_dj"))
    return _juggle_inplace(mix, ctx["sr"], ctx["bpm"], ctx["t0_s"],
                           pr.gesture, pr.render, seed=int(p.get("seed", 0)))


@operator("micro_edit")
def _op_micro_edit(mix: np.ndarray, ctx: dict) -> np.ndarray:
    """Apply a deterministic beat-synced GlitchBitch program in-place.

    ``overlay_input`` makes the selected pre-existing overlay part of the
    GlitchBitch source buffer, so a horn/voice tag is filtered and stuttered
    together with the music rather than merely playing beside the effect.
    """
    from src.hypermix.transitions.dsp import run_fx_program

    p = ctx["step"].call.params
    sr, bpm = ctx["sr"], ctx["bpm"]
    i0 = int(round(ctx["t0_s"] * sr))
    length_bars = float(p.get("length_bars", 1.0))
    n = int(round(length_bars * 4.0 * sr * 60.0 / bpm))
    i1 = min(len(mix), i0 + n)
    if i1 <= i0:
        return mix
    program = p.get("program", {})
    source = mix[i0:i1]
    overlay_input = p.get("overlay_input")
    if overlay_input:
        overlay_start = int(round(ctx["t0_s"] * sr))
        overlay_end = min(len(mix), overlay_start + len(source))
        overlay = mix[overlay_start:overlay_end]
        source = source.copy()
        source[:len(overlay)] = overlay
    rendered = run_fx_program(source, sr, bpm, program,
                               seed=int(p.get("seed", 0)))
    out = mix.copy()
    out[i0:i1] = rendered[:i1 - i0]
    return np.clip(out, -0.98, 0.98)
