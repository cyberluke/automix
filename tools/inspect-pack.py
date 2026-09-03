"""inspect-pack — pretty-print a .hmxpack manifest and verify integrity (§R)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running as a script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.hypermix.compiler.pack_writer import verify_pack  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(prog="inspect-pack")
    p.add_argument("pack", help="pack directory")
    args = p.parse_args()

    pack_dir = Path(args.pack)
    manifest_path = pack_dir / "manifest.json"
    if not manifest_path.is_file():
        print(f"no manifest.json in {pack_dir}")
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ok = verify_pack(pack_dir)

    print(f"pack:      {manifest.get('name')} ({manifest.get('id')}) v{manifest.get('version')}")
    print(f"schema:    {manifest.get('schema')}")
    print(f"audio:     {manifest.get('sampleRate')} Hz x{manifest.get('channels')}")
    print(f"segments:  {manifest.get('segments')}   edges: {manifest.get('edges')}")
    print(f"fallback:  {manifest.get('fallbackTransition')}")
    print(f"assets:    {len(manifest.get('integrity', {}).get('assets', []))}")
    print(f"integrity: {'OK' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
