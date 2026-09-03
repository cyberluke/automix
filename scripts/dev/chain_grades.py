"""Print the Camelot chain + phrase-energy gradient of a rendered golden mix."""
import json
import pathlib
import sys

import numpy as np
import soundfile as sf

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))
from src.hypermix.analysis.phrase_key import detect_key  # noqa: E402

SR = 48000


def _camelot_move(prev, cur):
    if not prev or not cur:
        return ""
    try:
        na = int(prev[:-1]); nb = int(cur[:-1])
    except Exception:
        return "?"
    d = ((nb - na + 6) % 12) - 6
    la, lb = prev[-1], cur[-1]
    if d == 2 and la == lb:
        return "BOOST"      # +2 Camelot numbers: whole-tone lift
    if d == 1 and la == lb:
        return "lift"
    if cur == prev:
        return "same"
    if d == 0:
        return "rel"        # relative major<->minor
    if abs(d) == 1:
        return "adj"
    return "DOWN" if d < 0 else "CLASH"


def main(render_dir: str, pack_dir: str) -> None:
    pack_root = pathlib.Path(pack_dir)
    graph_dir = pack_root / "graph"
    if not graph_dir.is_dir():
        graph_dir = pack_root          # caller already pointed at graph/
        pack_root = pack_root.parent
    tl = json.load(open(pathlib.Path(render_dir) / "golden.timeline.json", encoding="utf-8"))
    segs = json.load(open(graph_dir / "segments.json", encoding="utf-8"))
    rows = segs["segments"] if isinstance(segs, dict) and "segments" in segs else segs
    amap = {s["id"]: s["asset"] for s in rows}
    prev = None
    print("%-4s %-4s %-7s %-6s %s" % ("#", "key", "grad", "move", "segment"))
    for i, st in enumerate(tl):
        sid = st["segmentId"]
        aid = amap.get(sid)
        if not aid:
            print("%-4d %-4s %-7s %-6s %s" % (i, "?", "", "noasset", sid[:44]))
            continue
        x, fs = sf.read(str(pack_root / aid), dtype="float32", always_2d=True)
        if fs != SR:
            import scipy.signal as sps
            x = sps.resample(x, int(round(x.shape[0] * SR / fs)), axis=0).astype(np.float32)
        key = detect_key(x, SR)["camelot"]
        mono = x.mean(1)
        q = max(1, mono.shape[0] // 4)
        grad = float(np.sqrt((mono[-q:] ** 2).mean())) - float(np.sqrt((mono[:q] ** 2).mean()))
        mv = _camelot_move(prev, key)
        print("%-4d %-4s %+.3f %-6s %s" % (i, key, grad, mv, sid.split(".hero")[0][:44]))
        prev = key


if __name__ == "__main__":
    rd = sys.argv[1] if len(sys.argv) > 1 else r"renders\mix-arc"
    pk = sys.argv[2] if len(sys.argv) > 2 else r"packs\my-library"
    main(rd, pk)
