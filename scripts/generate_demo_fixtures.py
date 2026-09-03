"""Generate royalty-free demo fixtures (demo_tone_a/b.wav) for the demo crate.

No copyrighted material: simple synthesized kick+bass grooves at 120 / 128 BPM,
48 kHz stereo float32. Safe to commit.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.hypermix.audio_io import atomic_write_wav  # noqa: E402

SR = 48000


def groove(bpm: float, root_hz: float, seconds: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    t = np.arange(n) / SR
    beat = 60.0 / bpm

    # Bass drone.
    bass = 0.3 * np.sin(2 * math.pi * root_hz * t)

    # Four-on-the-floor kick (decaying 55 Hz thump).
    kick = np.zeros(n, dtype=np.float64)
    k = 0
    while int(k * beat * SR) < n:
        start = int(k * beat * SR)
        L = min(int(0.25 * SR), n - start)
        tt = np.arange(L) / SR
        kick[start : start + L] += 0.9 * np.sin(2 * math.pi * 55 * tt) * np.exp(-tt * 18)
        k += 1

    # Offbeat hat (noise burst).
    hat = np.zeros(n, dtype=np.float64)
    k = 0
    while int((k + 0.5) * beat * SR) < n:
        start = int((k + 0.5) * beat * SR)
        L = min(int(0.05 * SR), n - start)
        tt = np.arange(L) / SR
        hat[start : start + L] += 0.15 * rng.standard_normal(L) * np.exp(-tt * 120)
        k += 1

    mono = bass + kick + hat
    mono /= max(1e-9, np.max(np.abs(mono)))
    mono *= 0.8
    stereo = np.stack([mono, mono], axis=1)
    return stereo.astype(np.float32)


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "data" / "fixtures"
    out.mkdir(parents=True, exist_ok=True)
    a = groove(120.0, 55.0, 32.0, seed=1)   # A-ish
    b = groove(128.0, 49.0, 32.0, seed=2)   # G-ish
    atomic_write_wav(out / "demo_tone_a.wav", a, SR)
    atomic_write_wav(out / "demo_tone_b.wav", b, SR)
    print(f"wrote {out/'demo_tone_a.wav'}")
    print(f"wrote {out/'demo_tone_b.wav'}")


if __name__ == "__main__":
    main()
