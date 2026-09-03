"""Small deterministic DSP helpers shared by transition renderers.

All processing is offline and deterministic — no realtime master-tempo engine
(§1.4). Curves are computed once at render time on integer sample counts.
"""
from __future__ import annotations

import numpy as np

try:  # Physical MS-20M device model (new). Fall back to legacy SVF if absent.
    from ..dsp.ms20m import MS20MFilter
    _HAVE_MS20M = True
except Exception:  # pragma: no cover
    _HAVE_MS20M = False


def fit_len(x: np.ndarray, n: int) -> np.ndarray:
    """Trim or zero-pad to exactly n samples."""
    if x.shape[0] >= n:
        return x[:n]
    pad = np.zeros((n - x.shape[0], x.shape[1]), dtype=x.dtype)
    return np.vstack([x, pad])


def gain_ramp(n: int, g0: float, g1: float, curve: str = "linear") -> np.ndarray:
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)
    if curve == "equal_power":
        # cos/sin equal-power edges
        if g0 > g1:  # fade out
            g = np.cos(t * np.pi / 2)
        else:        # fade in
            g = np.sin(t * np.pi / 2)
        return (g * abs(g1 - g0) + min(g0, g1)).astype(np.float32)[:, None]
    if curve == "exp":
        eps = 1e-4
        g = np.exp(np.linspace(np.log(max(g0, eps)), np.log(max(g1, eps)), n))
        return g.astype(np.float32)[:, None]
    return np.linspace(g0, g1, n, dtype=np.float32)[:, None]


def apply_gain(x: np.ndarray, g: np.ndarray) -> np.ndarray:
    n = min(x.shape[0], g.shape[0])
    out = x[:n] * g[:n]
    if x.shape[0] > n:
        out = np.vstack([out, x[n:]])
    return out.astype(np.float32)


def one_pole_lowpass(x: np.ndarray, sr: int, cutoff_hz: float) -> np.ndarray:
    from scipy.signal import butter, sosfilt
    sos = butter(2, min(cutoff_hz, sr * 0.45), "lowpass", fs=sr, output="sos")
    return sosfilt(sos, x, axis=0).astype(np.float32)


def one_pole_highpass(x: np.ndarray, sr: int, cutoff_hz: float) -> np.ndarray:
    from scipy.signal import butter, sosfilt
    sos = butter(2, max(20.0, cutoff_hz), "highpass", fs=sr, output="sos")
    return sosfilt(sos, x, axis=0).astype(np.float32)


def _slew_limit_series(values: np.ndarray, sr: int, slew_ms: float) -> np.ndarray:
    """Humanizer: first-order slew limiter on a control series.

    A hand on a cutoff knob can't jump instantly — this limits how fast the
    value may move (asymmetric-free exponential approach), so a step-sequenced
    cutoff glides like a human turning a knob instead of snapping and spiking.

    `values`  : 1-D per-sample control targets
    `slew_ms` : ~time constant to reach a new target (higher = slower/smoother)
    """
    values = np.asarray(values, dtype=np.float64)
    if values.size == 0 or slew_ms <= 0.0:
        return values.astype(np.float32)
    a = 1.0 - np.exp(-1.0 / max(1.0, (slew_ms / 1000.0) * sr))
    out = np.empty_like(values)
    prev = values[0]
    for i in range(values.size):
        prev = prev + a * (values[i] - prev)
        out[i] = prev
    return out.astype(np.float32)


def _swept_one_pole(x: np.ndarray, sr: int, cutoff_hz: np.ndarray,
                    f_type: str) -> np.ndarray:
    """Per-sample time-varying one-pole LP/HP with a smoothed cutoff series.

    Unlike `one_pole_lowpass/highpass` (static Butterworth, fresh state per
    buffer -> a click at every step), this integrates a single pole whose cutoff
    follows `cutoff_hz` sample-by-sample, so a rising sweep glides continuously
    and never spikes at step boundaries.
    """
    x2 = x if x.ndim == 2 else x.reshape(-1, 1)
    n, ch = x2.shape
    fc = np.clip(np.asarray(cutoff_hz, dtype=np.float64), 20.0, sr * 0.45)
    if fc.size != n:
        fc = np.resize(fc, n)
    y = np.empty_like(x2, dtype=np.float64)
    lp = np.zeros(ch, dtype=np.float64)
    dt = 1.0 / float(sr)
    for i in range(n):
        a = 1.0 - np.exp(-2.0 * np.pi * fc[i] * dt)
        for c in range(ch):
            lp[c] = lp[c] + a * (x2[i, c] - lp[c])
            if f_type == "lowpass":
                y[i, c] = lp[c]
            else:
                y[i, c] = x2[i, c] - lp[c]
    return y.astype(np.float32)


def legacy_ms20_style_svf(x: np.ndarray, sr: int, cutoff_hz: np.ndarray,
                          res: float = 0.9, drive: float = 1.5,
                          variant: str = "ota") -> np.ndarray:
    """LEGACY effect — a generic nonlinear SVF that was labelled as an MS-20.

    This is **not** a physical MS-20 model. It is kept temporarily for
    compatibility with existing transition programs. The physical model lives in
    `src/hypermix/dsp/` (MS20MFilter).

    A 2-pole state-variable filter with tanh input clip + tanh state damping.
    `variant` is a coefficient hack ("korg35" | "ota"), not a topology switch.
    """
    mono = x.ndim == 1
    sig = x if mono else x
    n = sig.shape[0]
    if np.isscalar(cutoff_hz):
        cutoff_hz = np.full(n, float(cutoff_hz), dtype=np.float32)
    else:
        cutoff_hz = np.asarray(cutoff_hz, dtype=np.float32)
        if cutoff_hz.shape[0] != n:
            cutoff_hz = np.resize(cutoff_hz, n)
    cutoff_hz = np.clip(cutoff_hz, 20.0, sr * 0.45)

    res = float(np.clip(res, 0.0, 1.15))
    k = 2.0 * res
    if variant == "korg35":
        k *= 0.9
        drive *= 0.9
    drive = float(max(0.5, drive))

    ch = 1 if mono else sig.shape[1]
    s1 = np.zeros(ch, dtype=np.float32)
    s2 = np.zeros(ch, dtype=np.float32)
    out = np.empty_like(sig, dtype=np.float32)
    sig = sig.astype(np.float32)

    dt = 1.0 / float(sr)
    two_pi = 2.0 * np.pi
    for i in range(n):
        f = two_pi * float(cutoff_hz[i])
        g = np.tan(np.clip(np.pi * float(cutoff_hz[i]) * dt, 1e-4, np.pi / 2 - 1e-4))
        g = min(g, 1.2)
        inp = sig[i] * drive
        inp = np.tanh(inp) if variant == "ota" else np.tanh(inp * 0.9) * 1.05
        hp = (inp - k * s1 - s2) / (1.0 + k * g + g * g)
        bp = g * hp + s1
        lp = g * bp + s2
        s1 = np.tanh(bp)
        s2 = np.tanh(lp)
        out[i] = lp
    return out


# Backwards-compatible alias (legacy). New code should use MS20MFilter.
ms20_lowpass = legacy_ms20_style_svf


def _legacy_ms20_lowpass(x: np.ndarray, sr: int, cutoff_hz: np.ndarray,
                         res: float = 0.9, drive: float = 1.5,
                         variant: str = "ota") -> np.ndarray:
    """Old implementation body, kept only as a reference for the alias above."""
    return legacy_ms20_style_svf(x, sr, cutoff_hz, res=res, drive=drive,
                                 variant=variant)


def ms20_open(x: np.ndarray, sr: int, bpm: float, beats: float = 8.0,
              from_hz: float = 90.0, to_hz: float = 16000.0,
              res: float = 0.55, drive: float = 1.0,
              variant: str = "ota", curve: str = "exp") -> np.ndarray:
    """MS-20 'filter open' intro: sweep a resonant low-pass from `from_hz` up to
    `to_hz` over `beats` beats, then HARD OFF (full-band, unfiltered) — the
    classic 'filter snap open into the first drop'. The tail after the sweep is
    returned untouched (unity).

    Deterministic. `curve='exp'` keeps the sweep slow in the lows and snapping
    open into the highs (how a hand on an MS-20 cutoff knob actually feels).

    Now built on the physical MS20MFilter device model (REV.2 OTA backend by
    default) when available; the legacy generic SVF is the fallback. `res` is
    mapped to the normalized `lpf_peak`; `drive` becomes `input_gain_db`.
    """
    n = x.shape[0]
    spb = sr * 60.0 / float(bpm)
    sweep_n = int(round(beats * spb))
    sweep_n = max(1, min(sweep_n, n))
    t = np.linspace(0.0, 1.0, sweep_n, dtype=np.float32)
    if curve == "exp":
        f = np.exp(np.linspace(np.log(from_hz), np.log(to_hz), sweep_n)).astype(np.float32)
    else:
        f = np.linspace(from_hz, to_hz, sweep_n, dtype=np.float32)

    if _HAVE_MS20M:
        lpf = np.full(sweep_n, to_hz, dtype=np.float64)
        lpf[:] = f
        # REV.2 (OTA) is the smoother, lower-noise revision; use it for the
        # open sweep regardless of `variant` unless a caller explicitly asks
        # for the aggressive REV.1 Korg-35 character.
        rev = "rev1" if variant == "korg35" else "rev2"
        gain_db = 20.0 * np.log10(max(0.5, drive))
        filt = MS20MFilter(sr, revision=rev, hpf_cutoff_hz=20.0, hpf_peak=0.0,
                           lpf_cutoff_hz=lpf, lpf_peak=float(np.clip(res, 0, 1)),
                           input_gain_db=float(gain_db), quality="production")
        head = filt.process(x[:sweep_n]).astype(np.float32)
    else:
        head = ms20_lowpass(x[:sweep_n], sr, f, res=res, drive=drive, variant=variant)
    if sweep_n >= n:
        return head
    tail = x[sweep_n:]
    # Declick the hard-off boundary so the snap to full-band doesn't click.
    return declick_join(head.astype(np.float32), tail.astype(np.float32), sr, fade_ms=3.0)


# --------------------------------------------------------------------------
# CyberLuke Glitch Bitch edition — VPS GlitchBitch-style BPM-sync buffer-mangle
# engine. Offline + deterministic. Buffers are sliced on the beat grid, gated /
# reversed / pitched / rate-reduced / panned by n-point envelopes, then run
# through the MS-20 OTA filter for the concrete-tearing grit.
# --------------------------------------------------------------------------

_NOTE_DIV = {  # note value -> fraction of one beat (BPM-synced buffer sizes)
    "1/1": 4.0, "1/2": 2.0, "1/4": 1.0, "1/8": 0.5, "1/16": 0.25,
    "1/32": 0.125, "1/64": 0.0625, "1/128": 0.03125, "1/256": 0.015625,
    "1/2T": 4.0 / 3.0, "1/4T": 2.0 / 3.0, "1/8T": 1.0 / 3.0,
    "1/16T": 1.0 / 6.0, "1/32T": 1.0 / 12.0, "1/64T": 1.0 / 24.0,
    "1 Bar": 4.0, "1T Bar": 4.0 / 3.0,
}


def _npoint_env(points, n_steps, default=1.0):
    """Sample an n-point envelope to `n_steps` step values. `points` is a list of
    (pos_in_0..1, value) knots; linear interpolation between knots. Deterministic.
    `default` is returned for every step when `points` is empty/None."""
    if not points:
        return np.full(n_steps, float(default), dtype=np.float32)
    pts = sorted((float(p), float(v)) for p, v in points)
    xs = np.array([p for p, _ in pts], dtype=np.float32)
    ys = np.array([v for _, v in pts], dtype=np.float32)
    grid = np.linspace(0.0, 1.0, n_steps, endpoint=False, dtype=np.float32)
    return np.interp(grid, xs, ys, left=ys[0], right=ys[-1]).astype(np.float32)


def _note_samples(note: str, sr: int, bpm: float) -> int:
    div = _NOTE_DIV.get(note, 0.5)
    return max(16, int(round(sr * 60.0 / float(bpm) * div)))


def glitch_bitch(x: np.ndarray, sr: int, bpm: float, *,
                 buffer_note: str = "1/8",
                 advance_note: str = "1/8",
                 gate: float = 0.7,
                 reverse_prob: float = 0.0,
                 reverse: bool = False,
                 rate: float = 1.0,
                 pitch_semitones: float = 0.0,
                 vol_env=None, pan_env=None, gate_env=None, mix_env=None,
                 lp_env=None, hp_env=None,
                 length_bars: float = 1.0,
                 use_ms20: bool = True,
                 ms20_res: float = 0.5, ms20_drive: float = 1.0,
                 filter_automation: bool = False,
                 lp_from: float = 0.0, lp_to: float = 1.0,
                 seed: int = 0) -> np.ndarray:
    """GlitchBitch-style BPM-synced buffer mangle (offline, deterministic).

    The clip is chopped into beat-synced buffers of `buffer_note`; a sequencer of
    n-point envelopes (vol/pan/gate/mix/lp/hp) steps per `advance_note`. Each
    buffer can be gated, reversed, pitch-shifted and rate-reduced, then the whole
    result is driven through the MS-20 OTA low-pass (CyberLuke edition).

    All randomness comes from `seed` (default fixed -> reproducible). Returns a
    clip of ~the same length (buffered slices re-timed onto the beat grid).
    """
    n = x.shape[0]
    ch = 1 if x.ndim == 1 else x.shape[1]
    x2 = x.reshape(n, ch).astype(np.float32)
    rng = np.random.default_rng(seed)

    spb = sr * 60.0 / float(bpm)
    buf_n = _note_samples(buffer_note, sr, bpm)
    adv_n = _note_samples(advance_note, sr, bpm)
    total = int(round(length_bars * 4.0 * spb))
    total = min(n, max(buf_n, total))

    n_bufs = max(1, total // adv_n)
    vol = _npoint_env(vol_env, n_bufs, default=1.0)
    # Pan default must be CENTER (0), not full-right (1). _npoint_env's neutral
    # default is 1.0 for gain-style envelopes, which pans hard-right on stereo.
    pan = _npoint_env(pan_env, n_bufs, default=0.0)
    gat = _npoint_env(gate_env, n_bufs, default=1.0)
    mix = _npoint_env(mix_env, n_bufs, default=1.0)
    lpe = _npoint_env(lp_env, n_bufs) if lp_env else None
    hpe = _npoint_env(hp_env, n_bufs) if hp_env else None

    rate = float(np.clip(rate, 0.25, 4.0))
    pitch = 2.0 ** (float(pitch_semitones) / 12.0)

    out = np.zeros((total, ch), dtype=np.float32)
    for k in range(n_bufs):
        s = k * adv_n
        if s >= total:
            break
        seg = x2[s:s + buf_n]
        if seg.shape[0] == 0:
            continue
        m = seg.shape[0]
        # Reverse buffer (forced or probabilistic).
        if reverse or (reverse_prob > 0.0 and rng.random() < reverse_prob):
            seg = seg[::-1].copy()
        # Pitch shift (resample). pitch>1 = up = shorter buffer content.
        if abs(pitch - 1.0) > 1e-3:
            idx = np.arange(0, m, pitch)
            idx = idx[idx < m - 1].astype(int)
            seg = seg[idx] if idx.size else seg[:1]
        # Rate reducer (sample-rate decimation = bitcrush-ish lo-fi).
        if rate != 1.0:
            step = max(1, int(round(1.0 / min(rate, 1.0)))) if rate < 1.0 else 1
            if step > 1:
                hold = np.repeat(seg[::step], step, axis=0)[: seg.shape[0]]
                seg = hold
        # Gate (buffer gate time) with a short declick ramp.
        g = float(np.clip(gate * (gat[k] if gat.size else 1.0), 0.0, 1.0))
        gn = int(seg.shape[0] * g)
        if gn < seg.shape[0]:
            ramp = max(4, int(0.005 * sr))
            env = np.ones(seg.shape[0], dtype=np.float32)
            env[gn:] = 0.0
            lo = max(0, gn - ramp)
            env[lo:gn] = np.linspace(1.0, 0.0, gn - lo)
            seg = seg * env[:, None]
        # Per-buffer LP / HP envelopes (pre-MS20 tone shaping).
        if lpe is not None and lpe[k] < 0.999:
            cut = 200.0 * (20000.0 / 200.0) ** float(np.clip(lpe[k], 0, 1))
            seg = one_pole_lowpass(seg, sr, cut)
        if hpe is not None and hpe[k] > 0.001:
            cut = 20.0 * (8000.0 / 20.0) ** float(np.clip(hpe[k], 0, 1))
            seg = one_pole_highpass(seg, sr, cut)
        # Volume envelope.
        seg = seg * float(vol[k])
        # Pan envelope (constant-power).
        if ch == 2:
            p = float(np.clip(pan[k], -1.0, 1.0))
            ang = (p + 1.0) * np.pi / 4.0
            seg[:, 0] *= np.cos(ang)
            seg[:, 1] *= np.sin(ang)
        # Place onto the beat grid (fit to the advance slot, declicked).
        slot = fit_len(seg, adv_n)
        e = min(total, s + adv_n)
        dry = x2[s:e]
        wet = slot[: e - s]
        mk = float(np.clip(mix[k] if mix.size else 1.0, 0.0, 1.0))
        out[s:e] = dry * (1.0 - mk) + wet * mk

    # MS-20 OTA filter on the glitched result (CyberLuke edition grit).
    if use_ms20:
        if _HAVE_MS20M:
            gain_db = 20.0 * np.log10(max(0.5, ms20_drive))
            out = MS20MFilter(sr, revision="rev2", hpf_cutoff_hz=20.0,
                              hpf_peak=0.0, lpf_cutoff_hz=14000.0,
                              lpf_peak=float(np.clip(ms20_res, 0, 1)),
                              input_gain_db=float(gain_db),
                              quality="production").process(out).astype(np.float32)
        else:
            cut = np.full(total, 14000.0, dtype=np.float32)
            out = ms20_lowpass(out, sr, cut, res=ms20_res, drive=ms20_drive,
                               variant="ota")
    return out.reshape(total, ch).astype(np.float32)


def filter_automation(x: np.ndarray, sr: int, bpm: float, *,
                      bars: int = 1, lp_from: float = 0.05,
                      lp_to: float = 1.0, res: float = 0.45,
                      drive: float = 1.0,
                      lp_from_hz: float | None = None,
                      lp_to_hz: float | None = None,
                      hpf_from_hz: float = 20.0,
                      hpf_to_hz: float | None = None,
                      bypass_hpf: bool = False,
                      warmup_s: float = 0.0,
                      revision: str = "rev2") -> np.ndarray:
    """CLEAN filter-automation effect (the 'Vengeance envelope' sound): a 1-bar
    resonant MS-20 low-pass sweep from `lp_from`->`lp_to` (normalized 0..1 over
    200 Hz..16 kHz, log), with NO buffer mangle / gate / pitch / pan. This is
    the clean 'filter opens over 1 bar' automation. `bars` sets the sweep
    length. Deterministic. Returns same shape as input."""
    n = x.shape[0]
    ch = 1 if x.ndim == 1 else x.shape[1]
    x2 = x.reshape(n, ch).astype(np.float32)
    spb = sr * 60.0 / float(bpm)
    warmup_n = min(n, max(0, int(round(warmup_s * sr))))
    total = min(n - warmup_n, int(round(bars * 4.0 * spb)))
    # Log-swept cutoff envelope over the bar.
    lo, hi = 200.0, 16000.0
    if lp_from_hz is None:
        lp_from_hz = lo * (hi / lo) ** float(lp_from)
    if lp_to_hz is None:
        lp_to_hz = lo * (hi / lo) ** float(lp_to)
    sweep = np.geomspace(max(20.0, lp_from_hz),
                         min(hi, lp_to_hz), max(1, total)).astype(np.float64)
    cut = np.concatenate([
        np.full(warmup_n, min(hi, lp_to_hz), dtype=np.float64), sweep
    ])
    hpf_to_hz = hpf_from_hz if hpf_to_hz is None else hpf_to_hz
    hpf_cut = np.geomspace(max(20.0, hpf_from_hz),
                           min(hi, hpf_to_hz), max(1, len(cut))).astype(np.float64)
    # HUMANIZER: a hand on the cutoff knob can't teleport from the previous
    # rep's fully-open position back down to `lp_from` — it glides. Slew-limit
    # the cutoff and, crucially, seed it from the last position of the previous
    # call so consecutive reps (the 4x loop) don't spike at the boundary.
    prev = getattr(filter_automation, "_knob", None)
    if prev is not None:
        cut = np.concatenate([[prev], cut])
    cut = _slew_limit_series(cut, sr, slew_ms=18.0)
    if prev is not None:
        cut = cut[1:]
    filter_automation._knob = float(cut[-1]) if cut.size else None
    out = x2.copy()
    if _HAVE_MS20M:
        gain_db = 20.0 * np.log10(max(0.5, drive))
        filt = MS20MFilter(sr, revision=revision, hpf_cutoff_hz=hpf_cut, hpf_peak=0.0,
                           lpf_cutoff_hz=cut.astype(np.float64),
                   lpf_peak=float(np.clip(res, 0, 1)),
                   bypass_hpf=bypass_hpf,
                           input_gain_db=float(gain_db), quality="production")
        out[:len(cut)] = filt.process(x2[:len(cut)]).astype(np.float32)
    else:
        out[:len(cut)] = ms20_lowpass(x2[:len(cut)], sr, cut.astype(np.float32),
                                   res=res, drive=drive, variant="ota")
    # The nonlinear core can leave a subsonic state/DC residue. Remove only
    # below 10Hz; this does not touch the intended audible low-end.
    from scipy.signal import butter, sosfiltfilt
    dc_sos = butter(2, 10.0, fs=sr, btype="highpass", output="sos")
    out = sosfiltfilt(dc_sos, out, axis=0).astype(np.float32)
    return out.reshape(n, ch).astype(np.float32)


def duck_under(body: np.ndarray, onset: int, length: int, sr: int, *,
               depth: float = 0.35, attack_ms: float = 8.0,
               release_ms: float = 140.0) -> np.ndarray:
    """Sidechain-style DUCK: dip `body[onset:onset+length]` down by `depth`
    (linear gain) so a voice tag / sample overlaid on top cuts through. Smooth
    attack/release so the duck is felt, not heard as a click. Edits in place
    and returns body. Deterministic."""
    n = body.shape[0]
    onset = max(0, min(int(onset), n))
    end = max(onset, min(int(onset) + int(length), n))
    if end <= onset:
        return body
    atk = max(1, int(attack_ms * sr / 1000.0))
    rel = max(1, int(release_ms * sr / 1000.0))
    seg_n = end - onset
    env = np.ones(seg_n, dtype=np.float32)
    a = min(atk, seg_n)
    env[:a] = np.linspace(1.0, depth, a, dtype=np.float32)
    hold_end = max(a, seg_n - rel)
    env[a:hold_end] = depth
    if hold_end < seg_n:
        env[hold_end:] = np.linspace(depth, 1.0, seg_n - hold_end,
                                     dtype=np.float32)
    body[onset:end] *= env[:, None] if body.ndim == 2 else env
    return body


# --------------------------------------------------------------------------
# MICRO_EDIT_PROCESSOR — deterministic automation programs on the Glitch Bitch
# engine. A "program" is a plain JSON dict; same input + program + BPM + seed
# => byte-identical output. Programs describe INTENTION (producer edit), not a
# preset name:
#   {
#     "engine": "glitch", "sync": "1/16", "steps": 16,
#     "buffer":  {"size": "1/16", "ramp": ["1/4","1/8","1/16"],
#                 "reversePattern": [0,0,1,0]},
#     "pitch":   {"values": [0,0,3,7]},          # semitones, cycled per step
#     "gate":    {"values": [1,.8,.5,.25]},      # 0..1, cycled per step
#     "rate":    {"values": [1,1,.5]},           # rate reducer, cycled
#     "pan":     {"values": [-1,1] },            # or {"wiggle": depth}
#     "filter":  {"type": "highpass"|"lowpass", "fromHz": 120, "toHz": 6500},
#     "mix":     {"from": 0.2, "to": 1.0},
#     "ms20":    {"on": true, "res": 0.85, "drive": 1.6, "cutoffHz": 14000}
#   }
# FX classes (same engine, different intent):
#   TRANSITION FX : track A -> track B            (runs on the join window)
#   MICRO EDIT FX : track A -> edited A -> A      (runs inside one segment)
#   IDENTITY FX   : persona/sample branding stab  (runs on a voice/sample clip)
# --------------------------------------------------------------------------

def _cycled(values, k, default):
    if not values:
        return default
    return values[k % len(values)]


def run_fx_program(x: np.ndarray, sr: int, bpm: float, program: dict,
                   seed: int = 0) -> np.ndarray:
    """Execute a deterministic micro-edit automation program (see schema above).
    Offline, beat-synced, sample-exact. `seed` is reserved for probabilistic
    extensions; the stock programs are fully pattern-driven (no randomness)."""
    n = x.shape[0]
    ch = 1 if x.ndim == 1 else x.shape[1]
    x2 = x.reshape(n, ch).astype(np.float32)

    sync = program.get("sync", "1/16")
    steps = int(program.get("steps", 16))
    adv_n = _note_samples(sync, sr, bpm)
    total = min(n, adv_n * steps)
    if total <= 0:
        return x2[:0]

    buf_spec = program.get("buffer", {}) or {}
    buf_ramp = buf_spec.get("ramp") or []
    buf_size = buf_spec.get("size", sync)
    rev_pat = buf_spec.get("reversePattern") or []

    pitch_v = (program.get("pitch") or {}).get("values") or [0.0]
    gate_v = (program.get("gate") or {}).get("values") or [1.0]
    rate_v = (program.get("rate") or {}).get("values") or [1.0]
    pan_spec = program.get("pan") or {}
    pan_v = pan_spec.get("values")
    wiggle = float(pan_spec.get("wiggle", 0.0))

    filt = program.get("filter") or {}
    f_type = filt.get("type", "highpass")
    has_filter = "type" in filt and ("fromHz" in filt or "toHz" in filt)
    # Global fast-start floor for glitch filters: 120 Hz made HP/LP/bandpass
    # cells enter muffled and slow. Keep explicit bandpass windows intact, but
    # lift ordinary sweeps into the musical range unless a program opts out.
    fast_start = bool(filt.get("fast_start", True))
    default_from = 120.0 if f_type == "bandpass" else 300.0
    f_from = float(filt.get("fromHz", default_from))
    if fast_start and has_filter:
        floor = float(filt.get("min_start_hz",
                               120.0 if f_type == "bandpass" else 300.0))
        f_from = max(f_from, floor)
    f_to = float(filt.get("toHz", f_from))

    mix_spec = program.get("mix") or {}
    mix_from = float(mix_spec.get("from", 1.0))
    mix_to = float(mix_spec.get("to", mix_from))

    ms20_spec = program.get("ms20") or {}
    ms20_on = bool(ms20_spec.get("on", True))

    out = np.zeros((total, ch), dtype=np.float32)
    ramp = max(4, int(0.004 * sr))  # 4 ms declick ramp for gated buffer ends
    glitch_bitch._knob_f = None  # reset the humanized cutoff tracker per call

    for k in range(steps):
        s = k * adv_n
        if s >= total:
            break
        e = min(total, s + adv_n)
        slot = e - s
        # Source buffer: possibly a different (ramped) note size than advance.
        bnote = _cycled(buf_ramp, k, buf_size)
        b_n = _note_samples(bnote, sr, bpm)
        seg = x2[s:s + b_n].copy()
        if seg.shape[0] == 0:
            continue
        # Reverse buffer per pattern.
        if int(_cycled(rev_pat, k, 0)):
            seg = seg[::-1].copy()
        # Pitch (semitones): resample, then TILE back to buffer length so the
        # glitch cell stays full (classic pitched-stutter behaviour).
        semi = float(_cycled(pitch_v, k, 0.0))
        if abs(semi) > 1e-6:
            rate_p = 2.0 ** (semi / 12.0)
            idx = (np.arange(seg.shape[0]) * rate_p).astype(int)
            idx = idx[idx < seg.shape[0]]
            if idx.size:
                seg = seg[idx]
            reps = int(np.ceil(b_n / max(1, seg.shape[0])))
            seg = np.tile(seg, (reps, 1))[:b_n]
        # Rate reducer (lo-fi decimation with hold).
        rate = float(_cycled(rate_v, k, 1.0))
        if 0.0 < rate < 1.0:
            step = max(1, int(round(1.0 / rate)))
            seg = np.repeat(seg[::step], step, axis=0)[: seg.shape[0]]
        # Per-step filter (HP/LP), cutoff swept log fromHz -> toHz across steps.
        # The raw per-step target would jump at each step boundary and spike as
        # the filter sweeps up from below; we therefore (a) track a slew-limited
        # 'knob hand' position across steps and (b) within each step glide from
        # the previous smoothed position toward the step target, instead of a
        # hard jump.
        if has_filter and steps > 1:
            tgt = float(np.exp(np.linspace(np.log(max(f_from, 20.0)),
                                           np.log(max(f_to, 20.0)),
                                           steps)[k]))
            # Slew-limit like a hand on the knob (~25 ms). Seed the glide at the
            # previous step's smoothed knob position so the boundary is
            # continuous (no jump -> no spike as the cutoff sweeps up).
            prev_f = glitch_bitch._knob_f if glitch_bitch._knob_f is not None else tgt
            glide = _slew_limit_series(
                np.concatenate([[prev_f], np.full(seg.shape[0], tgt)]),
                sr, slew_ms=25.0)[1:]
            # Apply as a per-sample swept one-pole (time-varying cutoff).
            if f_type == "bandpass":
                seg = _swept_one_pole(seg, sr, glide, "highpass")
                seg = one_pole_lowpass(
                    seg, sr, float(filt.get("upperHz", 3200.0)))
            else:
                seg = _swept_one_pole(seg, sr, glide, f_type)
            glitch_bitch._knob_f = float(glide[-1]) if glide.size else tgt
        # Gate with declick ramp.
        g = float(np.clip(_cycled(gate_v, k, 1.0), 0.0, 1.0))
        seg = fit_len(seg, slot)
        gn = int(slot * g)
        if gn < slot:
            env = np.ones(slot, dtype=np.float32)
            env[gn:] = 0.0
            lo = max(0, gn - ramp)
            env[lo:gn] = np.linspace(1.0, 0.0, gn - lo, dtype=np.float32)
            seg = seg * env[:, None]
        # Pan: explicit values or LFO-ish wiggle (alternating depth).
        if ch == 2:
            if pan_v:
                p = float(np.clip(_cycled(pan_v, k, 0.0), -1.0, 1.0))
            elif wiggle > 0.0:
                p = wiggle * (1.0 if (k % 2) else -1.0)
            else:
                p = 0.0
            if abs(p) > 1e-6:
                ang = (p + 1.0) * np.pi / 4.0
                seg[:, 0] *= np.cos(ang)
                seg[:, 1] *= np.sin(ang)
        # Wet/dry per-step mix ramp.
        mk = mix_from + (mix_to - mix_from) * (k / max(1, steps - 1))
        out[s:e] = x2[s:e] * (1.0 - mk) + seg * mk

    # MS-20 OTA post-filter (CyberLuke grit) — static cutoff, aggressive res.
    if ms20_on:
        if _HAVE_MS20M:
            gain_db = 20.0 * np.log10(max(0.5, float(ms20_spec.get("drive", 1.6))))
            out = MS20MFilter(sr, revision="rev2", hpf_cutoff_hz=20.0,
                              hpf_peak=0.0,
                              lpf_cutoff_hz=float(ms20_spec.get("cutoffHz", 14000.0)),
                              lpf_peak=float(np.clip(ms20_spec.get("res", 0.85), 0, 1)),
                              input_gain_db=float(gain_db),
                              quality="production").process(out).astype(np.float32)
        else:
            cut = np.full(total, float(ms20_spec.get("cutoffHz", 14000.0)),
                          dtype=np.float32)
            out = ms20_lowpass(out, sr, cut,
                               res=float(ms20_spec.get("res", 0.85)),
                               drive=float(ms20_spec.get("drive", 1.6)),
                               variant="ota")
    return out.reshape(total, ch).astype(np.float32)


# Curated micro-edit programs (vocabulary, not presets). Deterministic by design.
FX_PROGRAM_STUTTER_RISE = {
    "engine": "glitch", "sync": "1/8", "steps": 8,
    "buffer": {"ramp": ["1/4", "1/4", "1/8", "1/8", "1/16", "1/16", "1/32", "1/32"],
               "reversePattern": [0, 0, 0, 1, 0, 0, 1, 1]},
    "pitch": {"values": [0, 0, 0, 3, 0, 3, 7, 12]},
    "gate": {"values": [1.0, 0.8, 0.6, 0.5]},
    "rate": {"values": [1.0, 1.0, 1.0, 0.5]},
    "pan": {"wiggle": 0.4},
    "filter": {"type": "highpass", "fromHz": 120.0, "toHz": 6500.0},
    "mix": {"from": 0.2, "to": 1.0},
    "ms20": {"on": True, "res": 0.5, "drive": 1.0, "cutoffHz": 14000.0},
}

FX_PROGRAM_GLITCH_STAB = {
    "engine": "glitch", "sync": "1/8", "steps": 8,
    "buffer": {"size": "1/8", "reversePattern": [0, 1, 0, 1]},
    "pitch": {"values": [0, 7, 12, 7]},
    "gate": {"values": [1.0, 0.7, 0.5, 0.7]},
    "pan": {"values": [-0.8, 0.8, -0.4, 0.4]},
    "filter": {"type": "highpass", "fromHz": 200.0, "toHz": 4000.0},
    "mix": {"from": 1.0, "to": 1.0},
    "ms20": {"on": True, "res": 0.55, "drive": 1.0, "cutoffHz": 12000.0},
}


def load_voice_tag(path, sr: int) -> np.ndarray:
    """Load a voice-tag WAV (any sr/channels) into canonical float32 stereo at
    `sr`. Deterministic linear resample (voice tags are short stabs; a clean
    linear interp is transparent enough and fully reproducible)."""
    import soundfile as sf
    data, srf = sf.read(str(path), dtype="float32", always_2d=True)
    if srf != sr:
        n_out = int(round(data.shape[0] * float(sr) / float(srf)))
        if n_out < 1:
            n_out = 1
        xi = np.arange(data.shape[0], dtype=np.float64)
        xo = np.linspace(0.0, data.shape[0] - 1.0, n_out)
        data = np.stack([np.interp(xo, xi, data[:, c]) for c in range(data.shape[1])],
                        axis=1).astype(np.float32)
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    elif data.shape[1] > 2:
        data = data[:, :2]
    return np.ascontiguousarray(data, dtype=np.float32)


# ---------------------------------------------------------------------------
# SAMPLE CHOP utility — split any sample on its internal silence gaps and
# produce beat-aligned cues (onset trims + cue metadata) so a chopped word/
# hit lands exactly on the beat grid.
# ---------------------------------------------------------------------------

def _frame_rms(mono: np.ndarray, win: int, hop: int) -> np.ndarray:
    n = mono.shape[0]
    if n < win:
        return np.array([float(np.sqrt((mono ** 2).mean()))], dtype=np.float32)
    n_fr = 1 + (n - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(n_fr)[:, None]
    return np.sqrt((mono[idx] ** 2).mean(axis=1)).astype(np.float32)


def chop_on_gaps(x: np.ndarray, sr: int, *, thresh_ratio: float = 0.12,
                 min_gap_ms: float = 45.0, min_chop_ms: float = 40.0,
                 attack_ms: float = 3.0, release_ms: float = 12.0,
                 win_ms: float = 10.0, hop_ms: float = 5.0) -> list:
    """Split a sample into word/hit chops wherever the level drops below
    `thresh_ratio` of the active median for at least `min_gap_ms`.

    Each chop is onset-trimmed (starts on the first loud frame, so it lands ON
    the beat when placed) and gets a short declick attack + release tail.
    Returns a list of float32 stereo arrays. Pure function of (x, sr, params).
    """
    mono = x.mean(axis=1).astype(np.float32)
    n = mono.shape[0]
    win = max(8, int(sr * win_ms / 1000.0))
    hop = max(4, int(sr * hop_ms / 1000.0))
    env = _frame_rms(mono, win, hop)
    active = env[env > 1e-4]
    if active.size == 0:
        return [np.ascontiguousarray(x, dtype=np.float32)]
    thresh = float(np.median(active)) * float(thresh_ratio)
    voiced = env >= thresh
    # Fill short holes so breath noise inside a word doesn't split it.
    gap_frames = max(1, int(round(min_gap_ms / hop_ms)))
    v = voiced.copy()
    i = 0
    while i < v.size:
        if not v[i]:
            j = i
            while j < v.size and not v[j]:
                j += 1
            if 0 < i and j < v.size and (j - i) < gap_frames:
                v[i:j] = True
            i = j
        else:
            i += 1
    # Voiced runs -> chop boundaries (frame idx -> sample idx).
    chops = []
    min_chop = int(sr * min_chop_ms / 1000.0)
    i = 0
    while i < v.size:
        if v[i]:
            j = i
            while j < v.size and v[j]:
                j += 1
            s = max(0, i * hop)
            e = min(n, (j - 1) * hop + win)
            if e - s >= min_chop:
                chops.append((s, e))
            i = j
        else:
            i += 1
    if not chops:
        return [np.ascontiguousarray(x, dtype=np.float32)]
    out = []
    for s, e in chops:
        c = x[s:e].astype(np.float32).copy()
        a = min(c.shape[0], max(1, int(sr * attack_ms / 1000.0)))
        r = min(c.shape[0], max(1, int(sr * release_ms / 1000.0)))
        c[:a] *= np.linspace(0.0, 1.0, a, dtype=np.float32)[:, None]
        c[-r:] *= np.linspace(1.0, 0.0, r, dtype=np.float32)[:, None]
        out.append(np.ascontiguousarray(c, dtype=np.float32))
    return out


def chop_cues(chops: list, sr: int, bpm: float, division: float = 1.0) -> list:
    """Beat-aligned cue/alignment metadata for chops: onset of each chop at
    `division`-beat steps on the grid. Returns [{'index','sample','beat','sec'}].
    """
    step = sr * 60.0 / float(bpm) * float(division)
    cues = []
    for k in range(len(chops)):
        smp = int(round(k * step))
        cues.append({"index": k, "sample": smp, "beat": k * float(division),
                     "sec": smp / float(sr)})
    return cues


def render_chop_sequence(chops: list, pattern, sr: int, bpm: float, *,
                         note_div: float = 1.0, gain: float = 1.0) -> np.ndarray:
    """Place chops from `pattern` (list of chop indices) at successive
    `note_div`-beat grid slots and return the mixed stereo float32 block.
    Length = len(pattern) * note_div beats (last chop's tail may extend past).
    """
    step = max(1, int(round(sr * 60.0 / float(bpm) * float(note_div))))
    n_slots = len(pattern)
    if n_slots == 0:
        return np.zeros((0, 2), dtype=np.float32)
    total = step * n_slots
    # Allow the final chop's tail to ring past the last slot.
    tail = max((chops[i].shape[0] for i in pattern), default=0)
    total = max(total, step * (n_slots - 1) + tail)
    out = np.zeros((total, 2), dtype=np.float32)
    for k, ci in enumerate(pattern):
        c = chops[ci] * np.float32(gain)
        s = k * step
        e = min(total, s + c.shape[0])
        out[s:e] += c[: e - s]
    return out


def filter_sweep(x: np.ndarray, sr: int, from_hz: float, to_hz: float,
                 mode: str = "highpass") -> np.ndarray:
    """Deterministic 4-band stepped filter sweep (offline; avoids per-sample
    time-varying filter state while staying fully reproducible)."""
    n = x.shape[0]
    bands = 4
    out = x.copy().astype(np.float32)
    edges = np.linspace(0, n, bands + 1).astype(int)
    freqs = np.linspace(from_hz, to_hz, bands)
    for i in range(bands):
        s, e = edges[i], edges[i + 1]
        if e <= s:
            continue
        seg = x[s:e]
        try:
            if mode == "highpass":
                out[s:e] = one_pole_highpass(seg, sr, float(freqs[i]))
            else:
                out[s:e] = one_pole_lowpass(seg, sr, float(max(freqs[i], 200.0)))
        except Exception:
            out[s:e] = seg
    return out


def reverse_tail(x: np.ndarray) -> np.ndarray:
    return x[::-1].copy()


def variable_rate_resample(x: np.ndarray, rate_curve: np.ndarray) -> np.ndarray:
    """Deterministic DJ-style variable-rate resample (backspin/power-down).
    rate_curve in (0,2]; 1.0 = unity, 0.5 = half-speed (one octave down).
    Implemented as position-integrated linear interpolation — offline only."""
    n = x.shape[0]
    pos = np.cumsum(rate_curve)
    pos = pos[pos < n - 1]
    idx = np.clip(pos, 0, n - 2)
    i0 = idx.astype(int)
    frac = (idx - i0).astype(np.float32)[:, None]
    out = x[i0] * (1.0 - frac) + x[i0 + 1] * frac
    return out.astype(np.float32)


def echo_tail(x: np.ndarray, sr: int, delay_sec: float, feedback: float,
              tail_sec: float, wet: float = 0.5,
              lowpass_hz: float = 6000.0) -> np.ndarray:
    """Offline feedback-delay echo tail. Deterministic, fixed length."""
    delay = max(1, int(sr * delay_sec))
    tail = int(sr * tail_sec)
    n = x.shape[0]
    buf = np.zeros((n + tail + delay, x.shape[1]), dtype=np.float32)
    buf[:n] += x
    taps = 0
    pos = delay
    gain = wet
    while pos < buf.shape[0] and gain > 1e-3 and taps < 64:
        seg_end = min(pos + n, buf.shape[0])
        seg = x[: seg_end - pos] * gain
        if lowpass_hz < sr * 0.45:
            seg = one_pole_lowpass(seg, sr, lowpass_hz)
        buf[pos:seg_end] += seg
        pos += delay
        gain *= feedback
        taps += 1
    return buf


def declick_join(a: np.ndarray, b: np.ndarray, sr: int, fade_ms: float = 20.0) -> np.ndarray:
    """Click-safe splice: short equal-power crossfade around the join (§12 slam)."""
    f = int(sr * fade_ms / 1000.0)
    if f < 1 or a.shape[0] < f or b.shape[0] < f:
        return np.vstack([a, b])
    n = min(f, a.shape[0], b.shape[0])
    t = np.linspace(0, 1, n, dtype=np.float32)[:, None]
    cross = a[-n:] * np.cos(t * np.pi / 2) + b[:n] * np.sin(t * np.pi / 2)
    return np.vstack([a[:-n], cross, b[n:]])


def stutter_slices(x: np.ndarray, slice_len: int, counts: list) -> np.ndarray:
    """Repeat the leading slice per `counts` (escalating stutter pattern)."""
    base = x[:slice_len]
    parts = [base for _ in range(sum(counts))]
    return np.vstack(parts) if parts else base


def normalize_peak(x: np.ndarray, ceiling: float = 0.89125) -> np.ndarray:
    peak = float(np.max(np.abs(x))) or 1.0
    if peak > ceiling:
        x = x * (ceiling / peak)
    return x.astype(np.float32)
