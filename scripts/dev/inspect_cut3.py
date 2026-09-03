"""Inspect where the cut lands at the END of segment N (default 3rd): beat/bar
position + per-beat bass energy around the cut, to see if it chops a phrase."""
import json
import pathlib
import sys

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfiltfilt

SR = 48000
PACK = pathlib.Path(r"packs\my-library")
IDX = int(sys.argv[1]) if len(sys.argv) > 1 else 2   # timeline index (0-based)


def main():
    tl = json.load(open(r"renders\mix-arc\golden.timeline.json", encoding="utf-8"))
    segs = json.load(open(PACK / "graph" / "segments.json", encoding="utf-8"))
    rows = segs["segments"] if isinstance(segs, dict) else segs
    amap = {s["id"]: s for s in rows}
    st = tl[IDX]
    s = amap[st["segmentId"]]
    bpm = float(s["bpm"])
    spb = SR * 60.0 / bpm
    n = int(st["lengthSamples"])
    x, fs = sf.read(str(PACK / s["asset"]), dtype="float32", always_2d=True)
    x = x[: min(n, x.shape[0])]
    n = x.shape[0]
    beats = n / spb
    bars = beats / 4.0
    print("seg[%d]: %s" % (IDX, st["segmentId"][:60]))
    print("  bpm %.2f  len %.1f beats = %.2f bars (cut at beat %.2f, %.0f%% into bar)"
          % (bpm, beats, bars, beats, (beats % 4.0) / 4.0 * 100))
    # Per-beat bass energy for the last 24 beats.
    sos = butter(4, 160.0 / (SR / 2.0), btype="low", output="sos")
    bass = sosfiltfilt(sos, x.mean(1))
    nb = int(n // int(round(spb)))
    be = np.sqrt((bass[: nb * int(round(spb))].reshape(nb, int(round(spb))) ** 2).mean(axis=1))
    hot = float(np.median(be[be > 1e-4])) if np.any(be > 1e-4) else 1.0
    for k in range(max(0, nb - 24), nb):
        bar = "#" * int(min(40, 40 * be[k] / (hot * 1.5)))
        print("  beat %3d (bar %5.2f)  %.4f %s" % (k, k / 4.0, be[k], bar))
    # Also show where the next segment starts in the timeline.


if __name__ == "__main__":
    main()
