"""Oversampled nonlinear-island infrastructure.

Anti-imaging / anti-aliasing around a tightly-coupled nonlinear core, using
cascaded 2x half-band linear-phase FIR stages with deterministic group-delay
compensation at the canonical output rate.

Architecture (offline, latency irrelevant):

    48 kHz
      |
      v
    linear-phase upsampler  (cascaded half-band FIRs)
      |
      v
    [ nonlinear core callback at (factor * sr) ]
      |
      v
    linear-phase anti-alias / downsampler
      |
      v
    48 kHz

The nonlinear core's own phase response is part of the physical emulation and
is preserved — only the *island boundary* filters are linear-phase.
"""
from __future__ import annotations

from typing import Callable
import numpy as np
from scipy.signal import firwin, upfirdn


# Stop-band targets per quality tier (from MS20M_QUALITY); used to size taps.
def _halfband_taps(stopband_db: float) -> int:
    """Half-band FIR tap count scaled to the requested stopband attenuation.

    A Blackman-Harris half-band at ~65 taps gives roughly 100-110 dB; we scale
    up for the reference tier. Kept odd so group delay is an integer.
    """
    if stopband_db >= 140:
        return 257
    if stopband_db >= 120:
        return 129
    return 65


def _halfband_kernel(stopband_db: float) -> np.ndarray:
    """Symmetric 2x half-band FIR (float64), cutoff at fs/4 of the high rate.

    For a 2x rate change the passband must stop at the *input* Nyquist, which
    is fs_high/4 = 0.25 of the high-rate Nyquist. firwin's cutoff is given as
    a fraction of the *output* (high) Nyquist, so 0.25 is correct for the
    half-band. We also normalise DC gain to 1.0 so the island is unity-gain.
    """
    n = _halfband_taps(stopband_db)
    h = firwin(n, 0.25, window="blackmanharris")
    return h / np.sum(h)


def _stages_for(factor: int) -> int:
    """Number of cascaded 2x stages for an overall oversample factor."""
    stages = {1: 0, 2: 1, 4: 2, 8: 3, 16: 4, 32: 5}.get(int(factor))
    if stages is None:
        raise ValueError(f"oversample factor must be one of 1,2,4,8,16,32 (got {factor})")
    return stages


def _resample_linear_phase(x: np.ndarray, up: int, down: int,
                           stopband_db: float) -> np.ndarray:
    """Cascaded half-band resample with group-delay compensation.

    Returns the same length as `x`. Mono or stereo (samples, ch).
    """
    stages = _stages_for(max(up, down)) if (up > 1 or down > 1) else 0
    if up > 1 and down == 1:
        n_st = _stages_for(up)
    elif down > 1 and up == 1:
        n_st = _stages_for(down)
    else:
        n_st = 0
    if n_st == 0:
        return x

    h = _halfband_kernel(stopband_db)
    delay_per_stage = (len(h) - 1) // 2

    mono = x.ndim == 1
    ch = 1 if mono else x.shape[1]
    cols = [x.astype(np.float64)] if mono else \
           [x[:, c].astype(np.float64) for c in range(ch)]

    if up > 1:  # ---- upsample path ----
        outs = []
        for c in range(ch):
            y = cols[c]
            for _ in range(_stages_for(up)):
                # upfirdn(up=2) has a polyphase DC gain of 0.5; multiply by 2
                # so each half-band stage is unity gain through the island.
                y = upfirdn(h, y, up=2, down=1) * 2.0
            outs.append(y)
        # remove the accumulated leading group delay (high-rate samples)
        total_delay = sum(delay_per_stage * (2 ** s) for s in range(_stages_for(up)))
        outs = [y[total_delay:] for y in outs]
        return outs[0] if mono else np.stack(outs, axis=1)

    # ---- downsample path ----
    outs = []
    for c in range(ch):
        y = cols[c]
        for _ in range(_stages_for(down)):
            y = upfirdn(h, y, up=1, down=2)
        outs.append(y)
    # Trim the anti-alias FIR's leading delay so output realigns to input clock.
    total_delay = sum(delay_per_stage // (2 ** s) for s in range(_stages_for(down)))
    outs = [y[total_delay:] for y in outs]
    return outs[0] if mono else np.stack(outs, axis=1)


def oversampled_island(x: np.ndarray, sr: float, factor: int,
                       stopband_db: float,
                       core: Callable[[np.ndarray, float], np.ndarray]
                       ) -> np.ndarray:
    """Run `core(y, sr*factor)` inside a linear-phase oversampled island.

    `x` may be mono or stereo at rate `sr`. The result is the same length and
    rate as `x`, with the boundary FIR group delays compensated so the
    canonical sample clock (phrase / drop boundaries) is preserved.
    """
    factor = int(factor)
    if factor == 1:
        return core(x, sr)

    n = x.shape[0]
    up = _resample_linear_phase(x, up=factor, down=1, stopband_db=stopband_db)
    hi_sr = sr * factor
    y_hi = core(up, hi_sr)
    if y_hi.shape[0] < n * factor:
        y_hi = np.pad(y_hi, [(0, n * factor - y_hi.shape[0])] +
                      ([(0, 0)] if y_hi.ndim == 2 else []))
    elif y_hi.shape[0] > n * factor:
        y_hi = y_hi[: n * factor]
    down = _resample_linear_phase(y_hi, up=1, down=factor, stopband_db=stopband_db)
    if down.shape[0] < n:
        down = np.pad(down, [(0, n - down.shape[0])] +
                      ([(0, 0)] if down.ndim == 2 else []))
    elif down.shape[0] > n:
        down = down[:n]
    return down.astype(np.float32)
