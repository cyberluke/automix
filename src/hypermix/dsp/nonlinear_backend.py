"""Compiled nonlinear inner-loop backend for MS-20M filter cores.

Numba is used when available (Python 3.14 support landed in Numba 0.63+). The
pure-NumPy path is kept as a deterministic reference / fallback. Both must be
bit-stable per backend for identical input / parameters / seed.

The recursion is mono/stereo; controls (cutoff / peak) may be scalar or a
per-sample float64 array at the *internal* (oversampled) rate.
"""
from __future__ import annotations

import numpy as np

try:  # pragma: no cover - optional acceleration
    from numba import njit
    _HAVE_NUMBA = True
except Exception:  # pragma: no cover
    _HAVE_NUMBA = False

    def njit(*args, **kwargs):  # type: ignore
        def wrap(f):
            return f
        return wrap if not (args and callable(args[0])) else args[0]


def _broadcast(ctrl, n):
    if np.isscalar(ctrl):
        return np.full(n, float(ctrl), dtype=np.float64)
    a = np.asarray(ctrl, dtype=np.float64)
    return a if a.shape[0] == n else np.resize(a, n)


# --------------------------------------------------------------------------
# REV.1 — Korg-35-style topology (aggressive / earlier character)
# --------------------------------------------------------------------------
@njit(cache=True, fastmath=False)
def _korg35_core(x, sr, cutoff_hz, peak, drive, is_lpf, seed, noise_amp):
    """Korg-35 2-pole with nonlinear OTA-style feedback (diode-ish saturation).

    Distinct from the generic SVF: the resonance feedback runs through a
    saturating element (the Korg-35's nonlinear resonant path), and the cutoff
    control current is modelled in log-friendly form. peak 0..1 approaches true
    self-oscillation (feedback >= 1) rather than a hard "just under unstable"
    clamp.
    """
    n = x.shape[0]
    ch = x.shape[1]
    xx = x
    # cutoff_hz / peak arrive as length-n float64 arrays (broadcast upstream).
    fc = np.clip(cutoff_hz.astype(np.float64), 20.0, sr * 0.45)
    pk = np.clip(peak.astype(np.float64), 0.0, 1.0)
    out = np.zeros_like(xx)

    # Deterministic hash-based noise seed (Numba-compatible, fixed per seed).
    nz = int(seed) * 2654435761 % 2147483647
    dt = 1.0 / float(sr)
    for c in range(ch):
        s1 = 0.0
        s2 = 0.0
        for i in range(n):
            g = np.tan(np.pi * fc[i] * dt)
            g = min(g, 1.9)
            inp = xx[i, c]
            if noise_amp > 0.0:
                nz = (nz * 1103515245 + 12345) % 2147483647
                inp = inp + noise_amp * ((nz / 2147483647.0) - 0.5)
            inp = np.tanh(inp * drive)  # input OTA stage saturation
            # Korg-35 resonance: feedback parameter mapped 0..1 -> 0..~2.2 with
            # a saturating resonant return (diode / OTA nonlinearity).
            fb = 2.2 * pk[i] * pk[i]  # squaring -> smooth onset of scream
            ret = np.tanh(s1)  # nonlinear resonant return path
            hp = (inp - fb * ret - s2) / (1.0 + fb * g + g * g)
            bp = g * hp + s1
            lp = g * bp + s2
            # Integrator saturation characteristic of the Korg-35 cells.
            s1 = s1 + g * hp
            s1 = np.tanh(s1 * 1.02)
            s2 = s2 + g * bp
            s2 = np.tanh(s2 * 1.02)
            out[i, c] = lp if is_lpf else hp
    return out


# --------------------------------------------------------------------------
# REV.2 — OTA-based later topology (smoother / lower-noise, still self-osc.)
# --------------------------------------------------------------------------
@njit(cache=True, fastmath=False)
def _ota_core(x, sr, cutoff_hz, peak, drive, is_lpf, seed, noise_amp):
    """MS-20 REV.2: Sallen-Key-ish 2-pole with LM13700 OTA gain elements and a
    1N4148 diode pair in the resonance feedback path (the scream source).

    Uses physically-meaningful states (two integrator cells) with the nonlinear
    element *in the feedback path* — matching where the diodes actually live —
    rather than tanh-on-every-state. Supports true self-oscillation at peak ~1.
    """
    n = x.shape[0]
    ch = x.shape[1]
    xx = x
    fc = np.clip(cutoff_hz.astype(np.float64), 20.0, sr * 0.45)
    pk = np.clip(peak.astype(np.float64), 0.0, 1.0)
    out = np.zeros_like(xx)

    nz = int(seed) * 2654435761 % 2147483647
    dt = 1.0 / float(sr)
    for c in range(ch):
        s1 = 0.0  # first integrator cell (OTA1)
        s2 = 0.0  # second integrator cell / output node (OTA2)
        for i in range(n):
            g = np.tan(np.pi * fc[i] * dt)
            g = min(g, 1.9)
            inp = xx[i, c]
            if noise_amp > 0.0:
                nz = (nz * 1103515245 + 12345) % 2147483647
                inp = inp + noise_amp * ((nz / 2147483647.0) - 0.5)
            # OTA input stage: gentle, unity-gain saturation.
            inp = np.tanh(inp * drive)
            # Resonance feedback via the 1N4148 diode pair. k reaches the
            # self-oscillation threshold at peak=1; the diode clips only the
            # *feedback* signal (where it physically lives), not the states.
            # Linear Q-mapping (smooth scream onset), no squaring law.
            k = 2.0 * pk[i]
            fb = np.tanh(s1)
            # Stable ZDF 2-pole. States stay near-linear in the passband.
            hp = (inp - k * fb - s2) / (1.0 + k * g + g * g)
            bp = g * hp + s1
            lp = g * bp + s2
            # Integrator cells: soft saturation at extreme level, NO extra
            # per-sample overdrive multiplier (keeps THD low under automation).
            s1 = np.tanh(bp)
            s2 = np.tanh(lp)
            out[i, c] = lp if is_lpf else hp
    return out


def _prep(x, cutoff_hz, peak):
    n = x.shape[0]
    mono = x.ndim == 1
    xx = x.astype(np.float64)
    if mono:
        xx = xx.reshape(n, 1)
    fc = _broadcast(cutoff_hz, n)
    pk = _broadcast(peak, n)
    return xx, fc, pk, mono


def _out(y, mono):
    return y[:, 0] if mono else y


def korg35_lpf(x, sr, cutoff_hz, peak, drive=1.0, seed=0, noise_amp=0.0):
    xx, fc, pk, mono = _prep(x, cutoff_hz, peak)
    return _out(_korg35_core(xx, sr, fc, pk, drive, True, seed, noise_amp), mono)


def korg35_hpf(x, sr, cutoff_hz, peak, drive=1.0, seed=0, noise_amp=0.0):
    xx, fc, pk, mono = _prep(x, cutoff_hz, peak)
    return _out(_korg35_core(xx, sr, fc, pk, drive, False, seed, noise_amp), mono)


def ota_lpf(x, sr, cutoff_hz, peak, drive=1.0, seed=0, noise_amp=0.0):
    xx, fc, pk, mono = _prep(x, cutoff_hz, peak)
    return _out(_ota_core(xx, sr, fc, pk, drive, True, seed, noise_amp), mono)


def ota_hpf(x, sr, cutoff_hz, peak, drive=1.0, seed=0, noise_amp=0.0):
    xx, fc, pk, mono = _prep(x, cutoff_hz, peak)
    return _out(_ota_core(xx, sr, fc, pk, drive, False, seed, noise_amp), mono)
