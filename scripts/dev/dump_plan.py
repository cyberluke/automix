"""Dump a set.plan.json: segment bar-length, seconds played, and technique."""
from __future__ import annotations

import json
import sys


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "renders/my-library-deep/set.plan.json"
    seg_path = sys.argv[2] if len(sys.argv) > 2 else "packs/my-library/graph/segments.json"
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    segs = None
    try:
        with open(seg_path, encoding="utf-8") as fh:
            segs = json.load(fh)
        if isinstance(segs, dict):
            segs = segs.get("segments", list(segs.values()))
        segs = {s["id"]: s for s in segs}
    except Exception:
        segs = {}
    for i, s in enumerate(d.get("steps", []), 1):
        sid = s["segmentId"]
        bars = sid.rsplit(".", 1)[-1]
        secs = s["lengthSamples"] / 48000.0
        tech = s["technique"] or "ENTRY"
        nm = sid.split(".hero-")[0][:30]
        start_in_track = ""
        seg = segs.get(sid)
        if seg is not None:
            st = seg.get("startSample", seg.get("start_sample", 0))
            start_in_track = f" enters@{st / 48000.0:6.1f}s"
        print(f"{i:2d}. {nm:30s} {bars:>5s} {secs:6.1f}s  via {tech}{start_in_track}")


if __name__ == "__main__":
    main()
