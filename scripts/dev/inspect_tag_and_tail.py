"""Diagnose: (a) glitched voice-tag level vs the drop it sits under,
(b) how many tail beats of segment 2 are beatless (kick dropped out)."""
import json
import pathlib
import sys

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfiltfilt

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))
from src.hypermix.compiler.deterministic_render import _glitched_voice_tag  # noqa: E402

SR = 48000
PACK = pathlib.Path(r"packs\my-library")


def _beat_bass_energy(mono, sr, bpm):
    sos = butter(4, 160.0 / (sr / 2.0), btype="low", output="sos")
    bass = sosfiltfilt(sos, mono)
    spb = int(round(sr * 60.0 / float(bpm)))
    nb = mono.shape[0] // spb
    tr = bass[: nb * spb]
    return np.sqrt((tr.reshape(nb, spb) ** 2).mean(axis=1)), spb


def main():
    tl = json.load(open(r"renders\mix-arc\golden.timeline.json", encoding="utf-8"))
    segs = json.load(open(PACK / "graph" / "segments.json", encoding="utf-8"))
    rows = segs["segments"] if isinstance(segs, dict) else segs
    amap = {s["id"]: s for s in rows}

    # --- (a) voice tag vs drop -------------------------------------------------
    s0 = amap[tl[0]["segmentId"]]
    bpm0 = float(s0["bpm"])
    x, fs = sf.read(str(PACK / s0["asset"]), dtype="float32", always_2d=True)
    vt = _glitched_voice_tag(SR, bpm0)
    on = int(round(8.0 * SR * 60.0 / bpm0))
    drop = x[on:on + (vt.shape[0] if vt is not None else SR)]
    drop_rms = float(np.sqrt((drop ** 2).mean()))
    print("tag:      peak %.3f  rms %.4f  len %.2f s" % (
        float(np.abs(vt).max()), float(np.sqrt((vt ** 2).mean())), vt.shape[0] / SR))
    print("drop@tag: rms %.4f  -> tag/drop rms ratio %.2f (%.1f dB)" % (
        drop_rms, float(np.sqrt((vt ** 2).mean())) / drop_rms,
        20 * np.log10(float(np.sqrt((vt ** 2).mean())) / drop_rms)))

    # --- (b) tail beats of segment 2 ------------------------------------------
    s1 = amap[tl[1]["segmentId"]]
    bpm1 = float(s1["bpm"])
    y, fs = sf.read(str(PACK / s1["asset"]), dtype="float32", always_2d=True)
    n = min(int(tl[1]["lengthSamples"]), y.shape[0])
    y = y[:n]
    mono = y.mean(1)
    be, spb = _beat_bass_energy(mono, SR, bpm1)
    hot = float(np.median(be[be > 1e-4]))
    print("\nseg2: %s  bpm %.1f  beats %d  hot-med %.4f" % (tl[1]["segmentId"][:40], bpm1, len(be), hot))
    for k in range(max(0, len(be) - 16), len(be)):
        bar = "#" * int(min(40, 40 * be[k] / (hot * 1.5)))
        print("  beat %3d  %.4f %s%s" % (k, be[k], bar, "  <- dead" if be[k] < 0.25 * hot else ""))


if __name__ == "__main__":
    main()
