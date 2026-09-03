"""SPR Branch 2 — neurofunk punk fallback.

When transcription confidence is too low for CyberSynth layering, we do the
Kontakt-style trick: resample the isolated stem UP an octave (halves its
length), then retrigger the slices on the ORIGINAL beat positions so the
groove is preserved. Optional 64-band envelope-follower vocoder drives the
CyberSynth carrier for a timbral takeover without needing any notes.

Runs in .venv-hypermix (numpy/scipy only).
"""

from __future__ import annotations

import numpy as np

from .types import SPRConfig
from .cyber_synth import _midi_to_hz, _saw, _env, _lowpass


def resample_octave_up(stem: np.ndarray, semitones: int = 12) -> np.ndarray:
    """Kontakt-style pitch-up by naive resampling (shortens output)."""
    from scipy.signal import resample_poly
    from fractions import Fraction
    ratio = 2.0 ** (semitones / 12.0)
    frac = Fraction(1.0 / ratio).limit_denominator(1000)
    up, down = frac.numerator, frac.denominator
    if stem.ndim == 1:
        out = resample_poly(stem, up, down)
    else:
        chans = [resample_poly(stem[:, c], up, down) for c in range(stem.shape[1])]
        out = np.stack(chans, axis=1)
    return out.astype(np.float32)


def pitch_shift_keep_length(stem: np.ndarray, semitones: int = 12,
                            sr: int = 44100) -> np.ndarray:
    """Pitch-shift WITHOUT changing duration, via librosa phase vocoder.

    Time-stretch by the pitch ratio (so a +12st shift first stretches to 2x
    length), then naive-resample back down by the same ratio — net effect is
    +semitones pitch at the ORIGINAL length. This is the 'chipmunk but same
    groove' trick; avoids the gated/wrapped artefacts of retrigger_on_beats.
    """
    import librosa
    ratio = float(2.0 ** (semitones / 12.0))
    if stem.ndim == 1:
        stem = np.column_stack([stem, stem])
    outs = []
    for c in range(stem.shape[1]):
        y = np.ascontiguousarray(stem[:, c], dtype=np.float32)
        # librosa pitch_shift preserves length internally (stretch then resample).
        shifted = librosa.effects.pitch_shift(y, sr=sr, n_steps=float(semitones))
        outs.append(shifted.astype(np.float32))
    out = np.stack(outs, axis=1)
    # length can drift by a few samples; trim/pad to original
    n = stem.shape[0]
    if out.shape[0] >= n:
        out = out[:n]
    else:
        out = np.vstack([out, np.zeros((n - out.shape[0], out.shape[1]), np.float32)])
    return out.astype(np.float32)


def retrigger_on_beats(resampled: np.ndarray, orig_len: int, bpm: float,
                       sr: int, bars: int) -> np.ndarray:
    """Slice the resampled (shortened) stem and retrigger slices so the total
    duration matches the original phrase. Groove preserved by construction."""
    beat_s = 60.0 / bpm
    slice_len = int(beat_s * sr)  # retrigger per beat
    n_slices = int(np.ceil((orig_len / sr) / beat_s))
    out = np.zeros((orig_len, resampled.shape[1] if resampled.ndim > 1 else 1),
                   dtype=np.float32)
    src_len = len(resampled)
    pos = 0
    for i in range(n_slices):
        chunk = resampled[pos:pos + slice_len]
        if len(chunk) == 0:
            break
        # click-free-ish edges
        fade = min(64, len(chunk) // 2)
        if fade > 1:
            chunk = chunk.copy()
            ramp = np.linspace(0, 1, fade, dtype=np.float32)
            if chunk.ndim > 1:
                chunk[:fade] *= ramp[:, None]
                chunk[-fade:] *= ramp[::-1, None]
            else:
                chunk[:fade] *= ramp
                chunk[-fade:] *= ramp[::-1]
        o0 = i * slice_len
        o1 = min(orig_len, o0 + len(chunk))
        if o1 - o0 <= 0:
            break
        out[o0:o1] += chunk[:o1 - o0].reshape(o1 - o0, -1)
        pos = (pos + slice_len) % max(1, src_len)
    if out.shape[1] == 1:
        out = np.column_stack([out[:, 0], out[:, 0]])
    return out


def _tanh_drive(x: np.ndarray, drive: float) -> np.ndarray:
    """Soft-clip waveshaper for carrier distortion (Scooter aggression)."""
    return np.tanh(drive * x).astype(np.float32)


def vocoder(carrier_notes_env: np.ndarray, modulator: np.ndarray,
            sr: int, bands: int = 12, attack_ms: float = 0.5,
            release_ms: float = 30.0, drive: float = 4.0) -> np.ndarray:
    """Hard electro channel vocoder (Scooter / Music Instructor 'Electric City'
    at full tilt): FEW bands (default 12) for robotic bite, carrier DISTORTION
    (tanh waveshaper), and a very-fast-attack / slow-release envelope follower
    for the choppy gated character. Split modulator into log-spaced bands,
    extract envelopes, apply to the (distorted) carrier."""
    from scipy.signal import butter, sosfilt, lfilter

    mod_mono = modulator.mean(axis=1) if modulator.ndim > 1 else modulator
    n = len(mod_mono)
    if len(carrier_notes_env) < n:
        pad = np.zeros(n - len(carrier_notes_env), dtype=np.float32)
        carrier = np.concatenate([carrier_notes_env, pad])
    else:
        carrier = carrier_notes_env[:n]

    # Distort the carrier BEFORE band-splitting → gritty electro timbre.
    carrier = _tanh_drive(carrier, drive)

    # Classic hardware vocoder range: tighter low-mid focus.
    f_lo, f_hi = 100.0, min(8000.0, sr / 2.2)
    edges = np.logspace(np.log10(f_lo), np.log10(f_hi), bands + 1)
    out = np.zeros(n, dtype=np.float32)
    atk = np.exp(-1.0 / max(1, int(sr * attack_ms / 1000.0)))
    rel = np.exp(-1.0 / max(1, int(sr * release_ms / 1000.0)))

    for b in range(bands):
        lo, hi = edges[b], edges[b + 1]
        if hi >= sr / 2:
            hi = sr / 2 * 0.99
        if hi <= lo:
            continue
        sos = butter(2, [lo / (sr / 2), hi / (sr / 2)], btype="band", output="sos")
        mod_band = sosfilt(sos, mod_mono)
        car_band = sosfilt(sos, carrier)
        rect = np.abs(mod_band)
        env_atk = lfilter([1.0 - atk], [1.0, -atk], rect)
        env_rel = lfilter([1.0 - rel], [1.0, -rel], rect)
        env = np.where(rect >= env_rel, env_atk, env_rel)
        out += car_band * env

    peak = float(np.max(np.abs(out)))
    if peak > 1e-6:
        out *= (0.5 / peak)
    stereo = np.column_stack([out, out])
    return stereo.astype(np.float32)


def vocoder_cleanup(voc: np.ndarray, sr: int, highpass_hz: float = 300.0,
                    notch_hz=(2500.0, 4000.0, 6300.0), notch_q: float = 4.0,
                    deemphasis_hz: float = 6000.0) -> np.ndarray:
    """Clean up a harsh vocoder: high-pass so it doesn't fight bass/drums,
    then notch out cheap resonances in mids/highs, then a gentle high-shelf
    de-emphasis. Applied to the stereo vocoder output."""
    from scipy.signal import butter, iirnotch, sosfilt, tf2sos
    y = voc.copy()
    nyq = sr / 2.0
    # 1) high-pass
    hp = butter(4, min(highpass_hz / nyq, 0.95), btype="high", output="sos")
    for c in range(y.shape[1]):
        y[:, c] = sosfilt(hp, y[:, c])
    # 2) notch cheap resonances (mids/highs)
    for f0 in notch_hz:
        if f0 < nyq * 0.98:
            b, a = iirnotch(f0 / nyq, notch_q)
            sos_n = tf2sos(b, a)
            for c in range(y.shape[1]):
                y[:, c] = sosfilt(sos_n, y[:, c])
    # 3) gentle high-shelf-ish de-emphasis (one-pole LP blended in) above ~6k
    c = min(deemphasis_hz / nyq, 0.95)
    lp = butter(2, c, btype="low", output="sos")
    for c_idx in range(y.shape[1]):
        low = sosfilt(lp, y[:, c_idx])
        # subtract a bit of the top band to soften harshness
        y[:, c_idx] = y[:, c_idx] - 0.25 * (y[:, c_idx] - low)
    peak = float(np.max(np.abs(y)))
    if peak > 1e-6:
        y *= (0.5 / peak)
    return y.astype(np.float32)


def tone_shape_lp(x: np.ndarray, sr: int, cutoff_hz: float = 6500.0) -> np.ndarray:
    """Gentle 2-pole lowpass to tame metallic highs from +12st phase-vocoder
    shimmer — the 'change the synth shape / retune the oscillators' pass."""
    from scipy.signal import butter, sosfilt
    if x.ndim == 1:
        x = np.column_stack([x, x])
    nyq = sr / 2.0
    c = min(cutoff_hz / nyq, 0.95)
    sos = butter(2, c, btype="low", output="sos")
    y = x.copy()
    for ch in range(y.shape[1]):
        y[:, ch] = sosfilt(sos, y[:, ch]).astype(np.float32)
    return y.astype(np.float32)


def flanger(x: np.ndarray, sr: int, wet: float = 0.45, rate_hz: float = 0.25,
            depth_ms: float = 6.0, base_ms: float = 0.5,
            feedback: float = 0.60) -> np.ndarray:
    """ALIVE 'soothing' flanger with an upward vacuum-cleaner sweep.
    Feedback comb with a delay time swept by a rising ramp+LFO → the flange
    notch climbs UP in pitch over time (the 'vysavac' rise). High feedback makes
    the whoosh resonant and clearly audible. Blended `wet` with dry."""
    if x.ndim == 1:
        x = np.column_stack([x, x])
    n = len(x)
    t = np.arange(n) / sr
    dur = max(t[-1], 1e-6)
    out = np.zeros_like(x)
    i = np.arange(n)
    for c in range(x.shape[1]):
        # Rising sweep: delay time FALLS over the phrase (flange pitch rises),
        # with a slow LFO wobble on top → upward 'vacuum' movement.
        rise = (t / dur)  # 0..1 across the phrase
        sweep = (1.0 - rise)  # start deep, end shallow = pitch rises
        lfo = 0.5 + 0.5 * np.sin(2 * np.pi * rate_hz * t + (0.0 if c == 0 else np.pi/2))
        delay_ms = base_ms + depth_ms * (0.35 * sweep + 0.65 * lfo)
        d = delay_ms * sr / 1000.0
        i0 = np.clip((i - d).astype(int), 0, n - 1)
        i1 = np.clip(i0 + 1, 0, n - 1)
        frac = np.clip((i - d) - np.floor(i - d), 0.0, 1.0)
        sig = x[:, c]
        delayed = sig[i0] * (1.0 - frac) + sig[i1] * frac
        # feedback comb: run the modulated delay through a short IIR so the
        # whoosh rings. Use a couple of unmodulated feedback taps (vectorized).
        fb_sig = delayed.copy()
        for fb_tap in (1, 2):
            dd = np.clip((i - d * fb_tap).astype(int), 0, n - 1)
            fb_sig = fb_sig + (feedback ** fb_tap) * delayed[dd]
        wet_sig = delayed + feedback * 0.5 * fb_sig
        out[:, c] = (1.0 - wet) * sig + wet * wet_sig
    # normalize so the flanger doesn't blow up
    peak = float(np.max(np.abs(out)))
    if peak > 1e-6:
        out *= (0.9 / peak)
    return out.astype(np.float32)


def rhythmic_lfo_filter(x: np.ndarray, sr: int, bpm: float,
                        min_hz: float = 1200.0, max_hz: float = 8000.0,
                        cycles_per_beat: float = 1.0) -> np.ndarray:
    """Rhythmic sinus LFO sweeping a one-pole lowpass cutoff over 1 beat.
    Gives the resample layer movement ('organic' wobble synced to groove)."""
    from scipy.signal import lfilter
    if x.ndim == 1:
        x = np.column_stack([x, x])
    n = len(x)
    beat_s = 60.0 / bpm
    lfo_rate = cycles_per_beat / beat_s  # Hz
    t = np.arange(n) / sr
    lfo = 0.5 + 0.5 * np.sin(2 * np.pi * lfo_rate * t)  # 0..1
    cutoff = min_hz + (max_hz - min_hz) * lfo
    # Block-based time-varying one-pole LP: constant cutoff within each block,
    # lfilter across it, carry state forward. ~256-sample blocks = smooth LFO.
    two_pi_over_sr = 2.0 * np.pi / sr
    a_arr = np.clip(cutoff * two_pi_over_sr, 0.0, 1.0)
    block = 256
    y = np.zeros_like(x)
    for c in range(x.shape[1]):
        zi = np.zeros(1)
        for s in range(0, n, block):
            e = min(n, s + block)
            a = float(a_arr[s:e].mean())
            seg, zf = lfilter([a], [1.0, -(1.0 - a)], x[s:e, c], zi=zi)
            y[s:e, c] = seg
            zi = zf
    return y.astype(np.float32)


def saw_pad_carrier(n: int, sr: int, root_midi: int = 57) -> np.ndarray:
    """Bright detuned saw pad as vocoder carrier. Default root up an octave
    (A2→A3, 45→57) so the vocoder sits higher and doesn't sound 'smutný'.
    Wider detune + higher LP for a brighter electro carrier."""
    sig = np.zeros(n, dtype=np.float32)
    for det in (-12.0, 0.0, 12.0):
        f = _midi_to_hz(root_midi) * (2.0 ** (det / 1200.0))
        phase = np.cumsum(np.full(n, f / sr, dtype=np.float64))
        sig += _saw(phase)
    sig /= 3.0
    return _lowpass(sig, 12000.0, 0.3, sr)
