"""Show per-step normalized energy level + spectral features for a rendered plan,
so we can verify climax->climax / breakdown->breakdown continuity."""
import json
import sys
import numpy as np

from src.hypermix.audio_io import read_wav

out = sys.argv[1] if len(sys.argv) > 1 else r"renders\mix-arc"
g = json.load(open(r"packs\my-library\graph\segments.json", encoding="utf-8"))
plan = json.load(open(out + r"\set.plan.json", encoding="utf-8"))
segs = {s["id"]: s for s in g["segments"]}


def rms(x):
    m = x.mean(axis=1) if x.ndim > 1 else x
    return float(np.sqrt((m ** 2).mean()))


raw = {}
for s in g["segments"]:
    a = read_wav("packs\\my-library\\" + s["asset"])
    raw[s["id"]] = rms(a.samples)
ref = float(np.percentile(list(raw.values()), 95)) or 1e-9

print(f"{'lvl':>4}  {'grad':>5}  {'bpm':>4}  track")
for st in plan["steps"]:
    sid = st.get("segmentId") or st.get("segment_id")
    s = segs[sid]
    nm = s.get("source", {}).get("title", "")[:34]
    grad = st.get("energy_end", 0.0)
    print(f"{raw[sid]/ref:4.2f}  {grad:+.3f}  {s.get('bpm',0):4.0f}  {nm}")
