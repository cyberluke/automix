"""MS-20M grey-box fitting — circuit structure + hardware-fitted parameters.

Strategy (hardware is the oracle):

    schematic / topology
      -> analytic / VA model
      -> oversampled stable implementation
      -> hardware measurement
      -> parameter fitting          <-- THIS MODULE
      -> residual analysis
      -> optional tiny correction model

Fits the uncertain parameters only (cutoff mapping, peak/feedback mapping,
gain, nonlinear strength, revision-specific saturation, small freq/Q
corrections). Does NOT train an opaque NN first.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares

from ..dsp.ms20m import ms20m_filter
from . import ms20m_measure as meas


def fit_peak_mapping(hw_captures, sr, revision="rev1", quality="preview"):
    """Fit the normalized peak -> feedback mapping against captured resonant
    peak gain. `hw_captures` = list of (peak_norm, audio) tuples at fixed cutoff.

    Returns a monotone correction curve callable pk -> corrected pk. This is the
    revision-specific transfer function the CTO spec requires to be measured,
    not guessed.
    """
    measured = []
    for pk, audio in hw_captures:
        f, g = meas.resonant_peak(audio, sr)
        measured.append((pk, g))
    measured.sort()
    pks = np.array([m[0] for m in measured])
    gains = np.array([m[1] for m in measured])

    def model_gain(pk, a, b, c):
        corrected = np.clip(a * pk + b * pk * pk, 0.0, 1.0)
        y = ms20m_filter(np.zeros(int(sr * 0.5), np.float32), sr,
                         revision=revision, lpf_cutoff_hz=1000.0,
                         lpf_peak=corrected, quality=quality, oversample=8)
        _, g = meas.resonant_peak(y + 1e-6, sr)
        return c * g

    def resid(params):
        a, b, c = params
        return np.array([model_gain(p, a, b, c) - g for p, g in zip(pks, gains)])

    sol = least_squares(resid, x0=[1.0, 1.0, 1.0],
                        bounds=([0, 0, 0], [3, 4, 3]))
    a, b, c = sol.x

    def mapping(pk):
        return float(np.clip(a * pk + b * pk * pk, 0.0, 1.0))

    mapping.params = {"a": float(a), "b": float(b), "c": float(c),
                      "cost": float(sol.cost)}
    return mapping


def fit_cutoff_mapping(hw_captures, sr, revision="rev1"):
    """Fit commanded-cutoff -> measured -6 dB point correction (tracking).

    `hw_captures` = list of (commanded_hz, measured_hz). Returns a callable
    linear correction hz -> corrected hz.
    """
    cmd = np.array([c for c, _ in hw_captures], dtype=np.float64)
    mea = np.array([m for _, m in hw_captures], dtype=np.float64)
    A = np.vstack([np.log(cmd), np.ones_like(cmd)]).T
    coef, *_ = np.linalg.lstsq(A, np.log(mea), rcond=None)

    def mapping(hz):
        hz = np.asarray(hz, dtype=np.float64)
        return np.exp(coef[0] * np.log(np.clip(hz, 20.0, sr * 0.45)) + coef[1])

    mapping.coef = {"log_slope": float(coef[0]), "log_intercept": float(coef[1])}
    return mapping
