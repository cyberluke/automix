"""Standalone entry point for Nuitka binary builds.

Uses absolute imports so it can be compiled as a top-level script.
Normal usage remains: python -m src.hypermix.sidecar [--root PATH]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from src.hypermix.sidecar.server import SidecarServer


def main() -> int:
    parser = argparse.ArgumentParser(prog="hypermix-sidecar")
    parser.add_argument("--root", default=".", help="workspace root (default: cwd)")
    args = parser.parse_args()
    server = SidecarServer(Path(args.root).resolve())
    return server.run()


if __name__ == "__main__":
    raise SystemExit(main())
