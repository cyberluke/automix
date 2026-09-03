"""Report the musical key of each phrase/segment that goes into the mix.

Reads the pack's compiled segment assets (audio/segments/*.wav) — those ARE
exactly the phrases used in the mix — and runs key detection on each.

Usage:
  .\.venv-hypermix\Scripts\python.exe scripts\phrase_keys.py packs\my-library
  .\.venv-hypermix\Scripts\python.exe scripts\phrase_keys.py packs\my-library --compat
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.hypermix.audio_io import read_wav
from src.hypermix.analysis.phrase_key import detect_key, camelot_compatible


def main() -> int:
    ap = argparse.ArgumentParser(description="Phrase key report")
    ap.add_argument("pack", help="pack dir (contains graph/segments.json)")
    ap.add_argument("--compat", action="store_true",
                    help="also print Camelot compatibility between consecutive segments")
    ap.add_argument("--json", default="", help="optional path to write JSON report")
    args = ap.parse_args()

    pack = Path(args.pack)
    seg_doc = json.loads((pack / "graph" / "segments.json").read_text(encoding="utf-8"))
    segs = seg_doc["segments"]

    rows = []
    for s in segs:
        asset = s.get("asset")
        if not asset:
            continue
        try:
            audio = read_wav(pack / asset)
        except Exception as exc:
            print(f"  ! {s['id']}: {exc}")
            continue
        info = detect_key(audio.samples, audio.sample_rate)
        rows.append({
            "segmentId": s["id"], "trackId": s.get("trackId"),
            "bars": s.get("bars"), "bpm": s.get("bpm"),
            "key": info["key"], "camelot": info["camelot"],
            "mode": info["mode"], "confidence": info["confidence"],
        })

    for r in rows:
        print(f"{r['camelot']:>4}  {r['key']:<4} {r['mode']:<5} "
              f"conf {r['confidence']:+.2f}  {r['bars']:>2}b  {r['segmentId'][:60]}")

    if args.compat and len(rows) > 1:
        print("\nCompatibility (consecutive):")
        for a, b in zip(rows, rows[1:]):
            ok = camelot_compatible(a["camelot"], b["camelot"])
            mark = "OK " if ok else "XX "
            print(f"  {mark}{a['camelot']} -> {b['camelot']}")

    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2))
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
