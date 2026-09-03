"""Entry point: python -m src.hypermix.sidecar [--root PATH]"""
from __future__ import annotations

import argparse
from pathlib import Path

from .server import SidecarServer


def main() -> int:
    parser = argparse.ArgumentParser(prog="hypermix-sidecar")
    parser.add_argument("--root", default=".", help="workspace root (default: cwd)")
    args = parser.parse_args()
    server = SidecarServer(Path(args.root).resolve())
    return server.run()


if __name__ == "__main__":
    raise SystemExit(main())
