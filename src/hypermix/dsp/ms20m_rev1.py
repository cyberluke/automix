"""MS-20M REV.1 — Korg-35-style filter backend.

Earlier character: more aggressive, characteristic distortion, characteristic
self-oscillation, noisier / rougher. Korg-35 LPF and HPF are modelled as
*independent* virtual-analog models (mirroring the Faust VA library approach),
not as two taps of one generic SVF.

Topology notes: 2-pole Korg-35 cell with a saturating resonant feedback path
and input OTA-style saturation. The resonance approaches true self-oscillation
(peak -> 1) rather than a hard "just under unstable" clamp.
"""
from __future__ import annotations

import numpy as np

from .nonlinear_backend import korg35_lpf, korg35_hpf


class MS20MRev1Korg35:
    """REV.1 device core. Processes a signal at the *internal* oversampled rate.

    cutoff/peak may be scalar or per-sample float64 arrays (already interpolated
    into the oversampled domain, log-space for cutoff).
    """

    #: Revision-specific normalized peak -> feedback mapping is applied inside
    #: the backend (squaring law for a smooth scream onset).
    revision = "rev1"

    def process_lpf(self, x, sr, cutoff_hz, peak, drive=1.0, seed=0, noise_amp=0.0):
        return korg35_lpf(x, sr, cutoff_hz, peak, drive=drive, seed=seed,
                          noise_amp=noise_amp)

    def process_hpf(self, x, sr, cutoff_hz, peak, drive=1.0, seed=0, noise_amp=0.0):
        return korg35_hpf(x, sr, cutoff_hz, peak, drive=drive, seed=seed,
                          noise_amp=noise_amp)
