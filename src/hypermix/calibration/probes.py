"""Probe-signal generation for MS-20M hardware calibration.

All probes are generated at the canonical 48 kHz, float32, mono. The external
VCF input on the MS-20M is documented up to ~3 Vp-p — generate at known levels
and attenuate the interface appropriately before hitting the hardware.
"""
from __future__ import annotations

import numpy as np

SR = 48000


def log_sine_sweep(sr=SR, dur_s=10.0, f0=20.0, f1=20000.0, level=0.5):
    """Logarithmic sine sweep (ESS-style) for magnitude/phase response."""
    n = int(sr * dur_s)
    t = np.arange(n, dtype=np.float64) / sr
    k = np.log(f1 / f0)
    phase = 2.0 * np.pi * f0 * (dur_s / k) * (np.exp(k * t / dur_s) - 1.0)
    return (level * np.sin(phase)).astype(np.float32)


def stepped_sine(sr=SR, freqs=(80, 160, 320, 640, 1250, 2500, 5000, 10000, 15000),
                 step_s=0.5, level=0.5):
    """Stepped sine across cutoff targets (for cutoff tracking / THD)."""
    parts = []
    for f in freqs:
        n = int(sr * step_s)
        t = np.arange(n, dtype=np.float64) / sr
        parts.append(level * np.sin(2 * np.pi * f * t))
    return np.concatenate(parts).astype(np.float32)


def multisine(sr=SR, dur_s=4.0, n_tones=24, f0=40.0, f1=16000.0, level=0.4,
              seed=0):
    """Random-phase multisine — dense frequency sampling, controlled crest."""
    rng = np.random.default_rng(seed)
    n = int(sr * dur_s)
    t = np.arange(n, dtype=np.float64) / sr
    freqs = np.exp(np.linspace(np.log(f0), np.log(f1), n_tones))
    y = np.zeros(n, dtype=np.float64)
    for f in freqs:
        y += np.sin(2 * np.pi * f * t + rng.uniform(0, 2 * np.pi))
    y /= np.max(np.abs(y))
    return (level * y).astype(np.float32)


def pink_noise(sr=SR, dur_s=6.0, level=0.4, seed=1):
    """Pink-ish noise via filtered white (spectral tilt ~ -3 dB/oct)."""
    rng = np.random.default_rng(seed)
    n = int(sr * dur_s)
    w = rng.standard_normal(n)
    x = np.fft.rfft(w)
    f = np.fft.rfftfreq(n, 1.0 / sr)
    f[0] = 1.0
    x /= np.sqrt(f)
    y = np.fft.irfft(x, n)
    y /= np.max(np.abs(y))
    return (level * y).astype(np.float32)


def white_noise(sr=SR, dur_s=4.0, level=0.3, seed=2):
    rng = np.random.default_rng(seed)
    n = int(sr * dur_s)
    return (level * rng.standard_normal(n)).astype(np.float32)


def impulse(sr=SR, dur_s=1.0, level=0.9):
    n = int(sr * dur_s)
    y = np.zeros(n, dtype=np.float32)
    y[0] = level
    return y


def saw(sr=SR, freq=110.0, dur_s=4.0, level=0.5):
    n = int(sr * dur_s)
    t = np.arange(n, dtype=np.float64) / sr
    return (level * (2.0 * (t * freq % 1.0) - 1.0)).astype(np.float32)


def square(sr=SR, freq=110.0, dur_s=4.0, level=0.5):
    n = int(sr * dur_s)
    t = np.arange(n, dtype=np.float64) / sr
    return (level * np.sign(np.sin(2 * np.pi * freq * t))).astype(np.float32)


def kick_transient(sr=SR, dur_s=1.0, level=0.8):
    """Synthesized kick — pitch-dropping sine burst with a fast transient."""
    n = int(sr * dur_s)
    t = np.arange(n, dtype=np.float64) / sr
    f = 120.0 * np.exp(-t * 25.0) + 45.0
    ph = 2 * np.pi * np.cumsum(f) / sr
    env = np.exp(-t * 18.0)
    return (level * np.sin(ph) * env).astype(np.float32)


def silence(sr=SR, dur_s=3.0):
    """Noise-floor / self-oscillation capture (with peak maxed, no input)."""
    return np.zeros(int(sr * dur_s), dtype=np.float32)


PROBE_FAMILIES = {
    "log_sine_sweep": log_sine_sweep,
    "stepped_sine": stepped_sine,
    "multisine": multisine,
    "pink_noise": pink_noise,
    "white_noise": white_noise,
    "impulse": impulse,
    "saw": saw,
    "square": square,
    "kick_transient": kick_transient,
    "silence": silence,
}
