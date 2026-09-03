"""HyperMix linear-phase production EQ / filter utility.

Transparent utility layer — NOT the MS-20 physical model. Uses symmetric FIR
kernels and offline group-delay compensation / centered convolution so the
output stays aligned to the canonical 48 kHz sample clock.

Uses:
  - anti-imaging / anti-aliasing around oversampled nonlinear islands
  - preconditioning before nonlinear DSP
  - post-EQ after the analog model
  - steep cleanup filters
  - exact transition-band shaping
  - hardware magnitude-response matching without corrupting the core topology
"""
from __future__ import annotations

import numpy as np
from scipy.signal import firwin, fftconvolve


def _compensate_group_delay(h: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Centered (zero-phase-at-authoring-rate) FIR convolution.

    Returns the same length as `x`, with the deterministic symmetric-FIR group
    delay ((len(h)-1)/2 samples) removed so phrase / sample-clock boundaries
    do not move. Uses FFT convolution for long kernels.
    """
    h = np.asarray(h, dtype=np.float64)
    delay = (len(h) - 1) // 2
    mono = x.ndim == 1
    if mono:
        y = fftconvolve(x.astype(np.float64), h, mode="full")
        y = y[delay: delay + len(x)]
    else:
        y = np.stack(
            [fftconvolve(x[:, c].astype(np.float64), h, mode="full")
             for c in range(x.shape[1])], axis=1)
        y = y[delay: delay + x.shape[0], :]
    return y.astype(np.float32)


def _fir(numtaps: int, cutoff, sr: float, pass_zero: bool,
         window: str = "blackmanharris") -> np.ndarray:
    """Design a symmetric linear-phase FIR (float64)."""
    return firwin(numtaps, cutoff, fs=sr, pass_zero=pass_zero, window=window)


def linear_phase_lowpass(x: np.ndarray, sr: float, cutoff_hz: float,
                         numtaps: int = 513,
                         window: str = "blackmanharris") -> np.ndarray:
    """Transparent linear-phase low-pass. Delay-compensated, same length out."""
    h = _fir(numtaps, cutoff_hz, sr, pass_zero=True, window=window)
    return _compensate_group_delay(h, x)


def linear_phase_highpass(x: np.ndarray, sr: float, cutoff_hz: float,
                          numtaps: int = 513,
                          window: str = "blackmanharris") -> np.ndarray:
    """Transparent linear-phase high-pass."""
    h = _fir(numtaps, cutoff_hz, sr, pass_zero=False, window=window)
    return _compensate_group_delay(h, x)


def linear_phase_bandpass(x: np.ndarray, sr: float, low_hz: float, high_hz: float,
                          numtaps: int = 1025,
                          window: str = "blackmanharris") -> np.ndarray:
    """Transparent linear-phase band-pass."""
    h = firwin(numtaps, [low_hz, high_hz], fs=sr, pass_zero=False, window=window)
    return _compensate_group_delay(h, x)


def linear_phase_notch(x: np.ndarray, sr: float, low_hz: float, high_hz: float,
                       numtaps: int = 1025,
                       window: str = "blackmanharris") -> np.ndarray:
    """Transparent linear-phase notch (band-reject)."""
    h = firwin(numtaps, [low_hz, high_hz], fs=sr, pass_zero=True, window=window)
    return _compensate_group_delay(h, x)


def linear_phase_eq(x: np.ndarray, sr: float, taps: np.ndarray) -> np.ndarray:
    """Apply a user-supplied symmetric linear-phase FIR, delay-compensated."""
    return _compensate_group_delay(np.asarray(taps, dtype=np.float64), x)
