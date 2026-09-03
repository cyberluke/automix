"""MS-20M REV.2 — later OTA-based filter backend.

Later character: lower noise, smoother / sweeter / rounder, still resonant and
capable of self-oscillation. Derived from the later circuit (Sallen-Key-ish
2-pole with LM13700 OTA gain elements and a 1N4148 diode pair in the resonance
feedback path — the nonlinearity is placed where the diodes actually live).

Uses physically-meaningful states (two integrator cells) and a ZDF /
topology-preserving update. The DAFx-19 nonlinear state-space MS-20 work is the
research reference for the state-trajectory / grey-box calibration path.
"""
from __future__ import annotations

import numpy as np

from .nonlinear_backend import ota_lpf, ota_hpf


class MS20MRev2OTA:
    """REV.2 device core at the internal oversampled rate."""

    revision = "rev2"

    def process_lpf(self, x, sr, cutoff_hz, peak, drive=1.0, seed=0, noise_amp=0.0):
        return ota_lpf(x, sr, cutoff_hz, peak, drive=drive, seed=seed,
                       noise_amp=noise_amp)

    def process_hpf(self, x, sr, cutoff_hz, peak, drive=1.0, seed=0, noise_amp=0.0):
        return ota_hpf(x, sr, cutoff_hz, peak, drive=drive, seed=seed,
                       noise_amp=noise_amp)
