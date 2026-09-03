"""Dump crate cue times per track, flagging drop/hook entries."""
from __future__ import annotations

import json
import os
import sys


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "crates/my-library/crate.json"
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    cues = d.get("cues", {})
    for k, v in cues.items():
        parts = []
        for c in v:
            sec = c.get("sample", 0) / 48000.0
            star = "*" if c.get("isDropEntry") else ""
            parts.append(f"{sec:.1f}{star}")
        print(f"{os.path.basename(k)} :: {', '.join(parts)}")
    print("TOTAL", sum(len(v) for v in cues.values()))


if __name__ == "__main__":
    main()
