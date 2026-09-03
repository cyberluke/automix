"""MS20MFilter — Korg MS-20M dual-revision virtual-analog device model.

Physical device model (the golden reference is the Korg MS-20M desktop module
with a physical REV.1 / REV.2 FILTER TYPE switch). Production HyperMix
transition effects (ms20_open, glitch, declick, beat automation, gain comp)
live OUTSIDE this class, in `transitions/dsp.py`.

Signal path (always HPF -> LPF, matching the hardware):

    INPUT -> revision-specific resonant HPF -> revision-specific resonant LPF
    -> OUTPUT

The recursive nonlinear core runs inside a linear-phase oversampled island
(preview=8x, production=16x, reference=32x) with deterministic group-delay
compensation at the canonical 48 kHz boundary. The physical filter's own phase
response is preserved; only the island boundary filters are linear-phase.
"""
from __future__ import annotations

from typing import Literal, Union
import numpy as np

from .quality import MS20M_QUALITY, DEFAULT_QUALITY
from .oversampling import oversampled_island
from .ms20m_rev1 import MS20MRev1Korg35
from .ms20m_rev2 import MS20MRev2OTA

Array = Union[float, np.ndarray]


def _interp_log(ctrl, n):
    """Broadcast a control to length n at the internal rate, log-space for Hz."""
    if np.isscalar(ctrl):
        return np.full(n, float(ctrl), dtype=np.float64)
    a = np.asarray(ctrl, dtype=np.float64)
    return a if a.shape[0] == n else np.resize(a, n)


class MS20MFilter:
    """Dual-revision MS-20M device model.

    Parameters
    ----------
    revision     : "rev1" (Korg-35, aggressive) | "rev2" (OTA, smoother)
    hpf_cutoff_hz: scalar or per-sample array at 48 kHz authoring rate
    hpf_peak     : 0..1 normalized resonance (self-oscillates near 1)
    lpf_cutoff_hz: scalar or per-sample array at 48 kHz authoring rate
    lpf_peak     : 0..1
    input_gain_db: external VCF input gain (hardware input up to ~3 Vp-p)
    quality      : "preview" | "production" | "reference"
    oversample   : explicit 1/2/4/8/16/32 override (else taken from quality)
    noise_mode   : "off" | "deterministic"  (seeded analog-noise floor)
    seed         : deterministic PRNG seed for noise_mode
    """

    def __init__(
        self,
        sr: float,
        *,
        revision: Literal["rev1", "rev2"] = "rev1",
        hpf_cutoff_hz: Array = 20.0,
        hpf_peak: Array = 0.0,
        lpf_cutoff_hz: Array = 16000.0,
        lpf_peak: Array = 0.75,
        bypass_hpf: bool = False,
        input_gain_db: float = 0.0,
        quality: Literal["preview", "production", "reference"] = DEFAULT_QUALITY,
        oversample: int | None = None,
        noise_mode: Literal["off", "deterministic"] = "off",
        seed: int = 0,
    ):
        self.sr = float(sr)
        self.revision = revision
        self.hpf_cutoff_hz = hpf_cutoff_hz
        self.hpf_peak = hpf_peak
        self.lpf_cutoff_hz = lpf_cutoff_hz
        self.lpf_peak = lpf_peak
        self.bypass_hpf = bool(bypass_hpf)
        self.input_gain_db = float(input_gain_db)
        self.noise_mode = noise_mode
        self.seed = int(seed)

        prof = MS20M_QUALITY[quality]
        self.oversample = int(oversample) if oversample else int(prof["oversample"])
        self.stopband_db = float(prof["fir_stopband_db"])
        self._device = MS20MRev1Korg35() if revision == "rev1" else MS20MRev2OTA()

    # ------------------------------------------------------------------
    def _noise_amp(self) -> float:
        return 0.0 if self.noise_mode == "off" else 2.0e-4  # very low floor

    def _core(self, y_hi: np.ndarray, hi_sr: float) -> np.ndarray:
        n_hi = y_hi.shape[0]
        # Interpolate authoring-rate (48k) controls into the oversampled domain.
        factor = n_hi // max(1, self._author_n)
        def up_ctrl(c, log=False):
            a = _interp_log(c, self._author_n)
            if log:
                a = np.log(np.clip(a, 20.0, hi_sr * 0.45))
            rep = np.repeat(a, factor)  # zero-order hold at authoring rate
            return np.exp(rep) if log else rep

        gain = 10.0 ** (self.input_gain_db / 20.0)
        z = y_hi.astype(np.float64) * gain
        if not self.bypass_hpf:
            z = self._device.process_hpf(
                z, hi_sr, up_ctrl(self.hpf_cutoff_hz, log=True),
                up_ctrl(self.hpf_peak), drive=1.0,
                seed=self.seed, noise_amp=self._noise_amp())
        z = self._device.process_lpf(z, hi_sr, up_ctrl(self.lpf_cutoff_hz, log=True),
                                     up_ctrl(self.lpf_peak), drive=1.0,
                                     seed=self.seed + 1, noise_amp=0.0)
        return z

    # ------------------------------------------------------------------
    def process(self, x: np.ndarray) -> np.ndarray:
        """Run the device on a mono/stereo 48 kHz buffer. Same length out."""
        self._author_n = x.shape[0]
        return oversampled_island(x, self.sr, self.oversample,
                                  self.stopband_db, self._core)


# ----------------------------------------------------------------------
def ms20m_filter(x: np.ndarray, sr: float, *, revision: str = "rev1",
                 hpf_cutoff_hz: Array = 20.0, hpf_peak: Array = 0.0,
                 lpf_cutoff_hz: Array = 16000.0, lpf_peak: Array = 0.75,
                 input_gain_db: float = 0.0,
                 quality: str = DEFAULT_QUALITY,
                 oversample: int | None = None,
                 noise_mode: str = "off", seed: int = 0) -> np.ndarray:
    """One-shot convenience wrapper around MS20MFilter."""
    return MS20MFilter(sr, revision=revision, hpf_cutoff_hz=hpf_cutoff_hz,
                       hpf_peak=hpf_peak, lpf_cutoff_hz=lpf_cutoff_hz,
                       lpf_peak=lpf_peak, input_gain_db=input_gain_db,
                       quality=quality, oversample=oversample,
                       noise_mode=noise_mode, seed=seed).process(x)
