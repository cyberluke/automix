"""MS-20M capture harness — probe WAV generation + capture metadata format.

Generates the probe matrix (revision x peak x input level x cutoff) as WAVs
with a JSON sidecar recording the exact physical knob / CV state. Route the
probe through the MS-20M external VCF input (<= ~3 Vp-p), record the output,
and align captures sample-accurately before fitting.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict

import numpy as np

from . import probes


# Measurement matrix from the CTO spec.
REVISIONS = ["rev1", "rev2"]
PEAKS = [0.00, 0.25, 0.50, 0.75, 0.90, 1.00]
INPUT_LEVELS = {"low": 0.2, "medium": 0.5, "nominal": 0.7, "hot": 0.9}
CUTOFFS = [80, 160, 320, 640, 1250, 2500, 5000, 10000, 15000]


@dataclass
class CaptureMeta:
    probe: str
    revision: str
    peak: float
    input_level_name: str
    input_level_lin: float
    hpf_cutoff_hz: float
    lpf_cutoff_hz: float
    sr: int
    vp_p_max: float = 3.0          # MS-20M external VCF input ceiling
    seed: int = 0
    notes: str = ""


def write_probe_set(out_dir: str, sr: int = 48000,
                    probe_names=("log_sine_sweep", "stepped_sine", "impulse",
                                 "saw", "kick_transient", "silence")):
    """Write probe WAVs + JSON metadata for the full measurement matrix.

    One WAV per (probe, level) — knob state is *not* baked into the audio; it
    is recorded in the sidecar so a single probe file can be reused across the
    matrix by physically setting the knobs per row.
    """
    os.makedirs(out_dir, exist_ok=True)
    from scipy.io import wavfile

    written = []
    for pname in probe_names:
        fn = probes.PROBE_FAMILIES[pname]
        for lvl_name, lvl in INPUT_LEVELS.items():
            y = fn(sr=sr) if pname != "silence" else fn(sr=sr)
            y = (y * lvl).astype(np.float32)
            base = f"{pname}_{lvl_name}"
            wav_path = os.path.join(out_dir, base + ".wav")
            wavfile.write(wav_path, sr, y)
            written.append(wav_path)

    # Matrix metadata (knob states to set physically per capture row).
    rows = []
    for pname in probe_names:
        for rev in REVISIONS:
            for peak in PEAKS:
                for lvl_name, lvl in INPUT_LEVELS.items():
                    for fc in CUTOFFS:
                        rows.append(asdict(CaptureMeta(
                            probe=pname, revision=rev, peak=peak,
                            input_level_name=lvl_name, input_level_lin=lvl,
                            hpf_cutoff_hz=20.0, lpf_cutoff_hz=float(fc),
                            sr=sr)))
    meta_path = os.path.join(out_dir, "capture_matrix.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"sr": sr, "vp_p_max": 3.0, "rows": rows}, f, indent=2)
    written.append(meta_path)
    return written
