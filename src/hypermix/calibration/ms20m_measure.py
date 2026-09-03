"""MS-20M measurement metrics — compare model vs physical hardware.

More than magnitude response: phase, group delay, resonant peak gain / Q,
cutoff tracking, THD vs level, H2/H3/H4, IMD, resonance compression,
self-oscillation threshold/amplitude, transient response, noise floor, DC.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import welch, find_peaks


def _mono(x):
    return x if x.ndim == 1 else x.mean(axis=1)


def magnitude_phase(x, y, sr, nperseg=4096):
    """Transfer estimate H = Pxy/Pxx -> magnitude (dB) + phase (rad) vs freq."""
    x = _mono(x).astype(np.float64)
    y = _mono(y).astype(np.float64)
    f, pxx = welch(x, sr, nperseg=nperseg)
    f, pxy = welch(x, y, sr, nperseg=nperseg)  # cross via welch of stacked
    from scipy.signal import csd
    f, pxy = csd(x, y, sr, nperseg=nperseg)
    h = pxy / np.maximum(pxx, 1e-20)
    mag_db = 20.0 * np.log10(np.maximum(np.abs(h), 1e-12))
    phase = np.unwrap(np.angle(h))
    return f, mag_db, phase


def thd(x, sr, fundamental):
    """Total harmonic distortion against a known fundamental frequency."""
    x = _mono(x).astype(np.float64)
    n = len(x)
    sp = np.abs(np.fft.rfft(x * np.hanning(n)))
    fr = np.fft.rfftfreq(n, 1.0 / sr)
    def amp_at(f):
        i = int(np.argmin(np.abs(fr - f)))
        return sp[max(0, i - 2): i + 3].max()
    fund = amp_at(fundamental)
    harm = sum(amp_at(k * fundamental) ** 2 for k in range(2, 6))
    return float(np.sqrt(harm) / max(fund, 1e-12))


def harmonic_levels(x, sr, fundamental, n_harm=4):
    """H1..Hn levels in dB relative to the fundamental."""
    x = _mono(x).astype(np.float64)
    n = len(x)
    sp = np.abs(np.fft.rfft(x * np.hanning(n)))
    fr = np.fft.rfftfreq(n, 1.0 / sr)
    def amp_at(f):
        i = int(np.argmin(np.abs(fr - f)))
        return sp[max(0, i - 2): i + 3].max()
    fund = max(amp_at(fundamental), 1e-12)
    return {f"H{k}": float(20 * np.log10(amp_at(k * fundamental) / fund))
            for k in range(1, n_harm + 1)}


def resonant_peak(x, sr, fmin=20.0, fmax=20000.0):
    """Largest spectral peak -> (freq, gain_dB). Used for Q / peak gain."""
    x = _mono(x).astype(np.float64)
    f, p = welch(x, sr, nperseg=8192)
    sel = (f >= fmin) & (f <= fmax)
    f, p = f[sel], p[sel]
    idx, _ = find_peaks(20 * np.log10(p + 1e-20), prominence=6)
    if len(idx) == 0:
        return 0.0, 0.0
    best = idx[np.argmax(p[idx])]
    return float(f[best]), float(10 * np.log10(p[best] + 1e-20))


def self_osc_amplitude(x, sr):
    """RMS of output under silence input with peak maxed (self-oscillation)."""
    x = _mono(x).astype(np.float64)
    return float(np.sqrt(np.mean(x * x)))


def noise_floor(x, sr):
    x = _mono(x).astype(np.float64)
    return float(20 * np.log10(np.sqrt(np.mean(x * x)) + 1e-12))


def dc_offset(x):
    return float(np.mean(_mono(x).astype(np.float64)))


def residual(hw, model, sr):
    """Gain/latency-aligned residual: hw - aligned(model)."""
    hw = _mono(hw).astype(np.float64)
    mo = _mono(model).astype(np.float64)
    n = min(len(hw), len(mo))
    hw, mo = hw[:n], mo[:n]
    # latency align via cross-correlation
    c = np.correlate(hw, mo, mode="full")
    lag = int(np.argmax(np.abs(c)) - (n - 1))
    mo = np.roll(mo, lag)
    g = np.dot(hw, mo) / max(np.dot(mo, mo), 1e-12)
    return hw - g * mo, g, lag
