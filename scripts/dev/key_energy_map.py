"""Map pack segments -> Camelot key + energy, grouped by track. Feasibility
check for ASCENDING_ENERGY_ARC. Deterministic; analysis only."""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.hypermix.audio_io import read_wav
from src.hypermix.analysis.phrase_key import detect_key


def main() -> int:
    pack = Path(sys.argv[1] if len(sys.argv) > 1 else "packs/my-library")
    bars = int(sys.argv[2]) if len(sys.argv) > 2 else 64
    segs = json.loads((pack / "graph" / "segments.json").read_text())["segments"]
    key_cache: dict = {}
    by = collections.defaultdict(list)
    for s in segs:
        if s.get("bars") != bars:
            continue
        asset = s.get("asset")
        if not asset:
            continue
        if asset not in key_cache:
            a = read_wav(pack / asset)
            key_cache[asset] = detect_key(a.samples, a.sample_rate)["camelot"]
        cam = key_cache[asset]
        by[cam].append((s["trackId"][:28], round(float(s.get("energyStart", 0.0)), 3)))
    print(f"{bars}b segments by Camelot:")
    for cam in sorted(by, key=lambda c: (int(c[:-1]), c[-1])):
        for t, e in by[cam]:
            print(f"  {cam:>4}  {t:<28} energy {e}")
    nums = sorted({int(c[:-1]) for c in by})
    print("\nCamelot numbers present:", nums)
    # +2 (mod 12) reachable set from each present number
    print("\n+2 Energy-Boost reachability:")
    for c in sorted(by, key=lambda c: (int(c[:-1]), c[-1])):
        n = int(c[:-1]); letter = c[-1]
        up = ((n - 1 + 2) % 12) + 1
        tgt = f"{up}{letter}"
        print(f"  {c:>4} -> {tgt:>4}  {'YES' if tgt in by else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
