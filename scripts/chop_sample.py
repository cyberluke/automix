"""Sample-chop utility: split any sample on its internal silence gaps and
prepare beat-aligned cues/chops for the mix.

Usage:
  .\.venv-hypermix\Scripts\python.exe scripts\chop_sample.py \
      samples/voice_tags/deep_dance2.wav --bpm 148.03 --note 1/8 \
      --out renders/_chops/deep_dance --prefix dd

Writes: <out>/<prefix>_0.wav ... per chop, and <out>/<prefix>.cues.json with
onset sample, beat, second, and per-chop source bounds. Deterministic.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.hypermix.transitions.dsp import (chop_on_gaps, chop_cues,
                                          load_voice_tag)

_DIV = {"1/1": 4.0, "1/2": 2.0, "1/4": 1.0, "1/8": 0.5, "1/16": 0.25,
        "1/32": 0.125, "1 Bar": 4.0}


def main() -> int:
    ap = argparse.ArgumentParser(description="Chop a sample on silence gaps.")
    ap.add_argument("input", help="path to WAV sample")
    ap.add_argument("--sr", type=int, default=48000)
    ap.add_argument("--bpm", type=float, default=148.0,
                    help="BPM used for beat-aligned cue grid")
    ap.add_argument("--note", default="1/8", choices=sorted(_DIV),
                    help="cue grid division (default 1/8)")
    ap.add_argument("--thresh", type=float, default=0.12,
                    help="silence threshold as ratio of active median")
    ap.add_argument("--min-gap-ms", type=float, default=45.0)
    ap.add_argument("--min-chop-ms", type=float, default=40.0)
    ap.add_argument("--out", default="renders/_chops", help="output dir")
    ap.add_argument("--prefix", default="chop", help="chop filename prefix")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        raise SystemExit(f"input not found: {src}")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    x = load_voice_tag(src, args.sr)
    chops = chop_on_gaps(x, args.sr, thresh_ratio=args.thresh,
                         min_gap_ms=args.min_gap_ms,
                         min_chop_ms=args.min_chop_ms)
    div = _DIV[args.note]
    cues = chop_cues(chops, args.sr, args.bpm, division=div)

    written = []
    for i, c in enumerate(chops):
        p = out_dir / f"{args.prefix}_{i}.wav"
        sf.write(str(p), c, args.sr, subtype="FLOAT")
        written.append(str(p))

    meta = {
        "source": str(src), "sr": args.sr, "bpm": args.bpm,
        "division": args.note, "divBeats": div,
        "chops": len(chops), "files": written, "cues": cues,
    }
    cues_path = out_dir / f"{args.prefix}.cues.json"
    cues_path.write_text(json.dumps(meta, indent=2))
    print(f"chopped {len(chops)} -> {out_dir} (cues: {cues_path})")
    for i, (c, cu) in enumerate(zip(chops, cues)):
        print(f"  [{i}] {c.shape[0]/args.sr*1000.0:6.1f} ms  "
              f"onset beat {cu['beat']:5.2f}  @ {cu['sec']:.4f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
