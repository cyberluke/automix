"""HyperMix production wrappers built on the MS-20M device model.

These are the *musical* FX (sweeps, scream) — they use MS20MFilter as the
physical device and add only beat/phrase automation. No physical-model hacks
here; transition composition (declick, gain comp, glitch) stays in
`transitions/dsp.py`.
"""
from __future__ import annotations

import numpy as np

from .ms20m import MS20MFilter


def _exp_sweep(n, from_hz, to_hz):
    t = np.linspace(0.0, 1.0, n, dtype=np.float64)
    return from_hz * (to_hz / from_hz) ** t


def ms20m_open(x, sr, bpm, *, beats=8.0, from_hz=700.0, to_hz=16000.0,
               peak=0.75, revision="rev1", quality="production"):
    """MS-20M 'filter open' intro sweep: LPF from_hz -> to_hz over `beats`.

    The default starts in the musical midrange instead of the old 90 Hz closed
    filter so the first transient remains audible. Callers can still request a
    lower start explicitly for special effects.
    """
    n = x.shape[0]
    spb = 60.0 / bpm
    sweep_n = min(n, int(round(beats * spb * sr)))
    lpf = np.full(n, to_hz, dtype=np.float64)
    lpf[:sweep_n] = _exp_sweep(sweep_n, from_hz, to_hz)
    f = MS20MFilter(sr, revision=revision, hpf_cutoff_hz=20.0, hpf_peak=0.0,
                    lpf_cutoff_hz=lpf, lpf_peak=peak, quality=quality)
    return f.process(x)


def ms20m_close(x, sr, bpm, *, beats=8.0, from_hz=16000.0, to_hz=300.0,
                peak=0.75, revision="rev1", quality="production"):
    """Filter close sweep; ends at a musical low-mid point by default."""
    n = x.shape[0]
    spb = 60.0 / bpm
    sweep_n = min(n, int(round(beats * spb * sr)))
    lpf = np.full(n, to_hz, dtype=np.float64)
    lpf[:sweep_n] = _exp_sweep(sweep_n, from_hz, to_hz)
    f = MS20MFilter(sr, revision=revision, hpf_cutoff_hz=20.0, hpf_peak=0.0,
                    lpf_cutoff_hz=lpf, lpf_peak=peak, quality=quality)
    return f.process(x)


def ms20m_band_sweep(x, sr, bpm, *, beats=8.0, hpf_from=60.0, hpf_to=800.0,
                     lpf_from=16000.0, lpf_to=800.0, peak=0.7,
                     revision="rev1", quality="production"):
    """Band-narrowing sweep: HPF rises while LPF falls (HPF + LPF movement)."""
    n = x.shape[0]
    spb = 60.0 / bpm
    sweep_n = min(n, int(round(beats * spb * sr)))
    hpf = np.full(n, hpf_to, dtype=np.float64)
    lpf = np.full(n, lpf_to, dtype=np.float64)
    hpf[:sweep_n] = _exp_sweep(sweep_n, hpf_from, hpf_to)
    lpf[:sweep_n] = _exp_sweep(sweep_n, lpf_from, lpf_to)
    f = MS20MFilter(sr, revision=revision, hpf_cutoff_hz=hpf, hpf_peak=peak * 0.6,
                    lpf_cutoff_hz=lpf, lpf_peak=peak, quality=quality)
    return f.process(x)


def ms20m_scream(x, sr, bpm, *, beats=4.0, cutoff_hz=1200.0, peak=0.95,
                 revision="rev1", quality="production"):
    """High-peak resonant scream at a fixed cutoff (revision-specific behavior)."""
    n = x.shape[0]
    spb = 60.0 / bpm
    n_on = min(n, int(round(beats * spb * sr)))
    pk = np.zeros(n, dtype=np.float64)
    pk[:n_on] = peak
    f = MS20MFilter(sr, revision=revision, hpf_cutoff_hz=20.0, hpf_peak=0.0,
                    lpf_cutoff_hz=cutoff_hz, lpf_peak=pk, quality=quality)
    return f.process(x)
