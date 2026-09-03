"""Pack writer (§17). Writes .hmxpack directories and ZIP archives with an
integrity block. Extraction helpers guard against path traversal, absolute
paths, symlinks and decompression bombs."""
from __future__ import annotations

import json
import os
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from ..config import PACK_COMPILER_VERSION
from ..hashing import sha256_bytes, sha256_file

_MAX_UNCOMPRESSED = 4 * 1024 * 1024 * 1024  # 4 GiB decompression-bomb guard


@dataclass
class AssetEntry:
    path: str
    sha256: str
    bytes: int
    samples: Optional[int] = None

    def to_dict(self) -> dict:
        d = {"path": self.path, "sha256": self.sha256, "bytes": self.bytes}
        if self.samples is not None:
            d["samples"] = self.samples
        return d


class PackWriter:
    """Builds a pack directory then optionally zips it."""

    def __init__(self, pack_dir: Path) -> None:
        self.pack_dir = Path(pack_dir)
        self.assets: List[AssetEntry] = []

    def add_asset(self, src: Path, rel_path: str,
                  samples: Optional[int] = None) -> AssetEntry:
        rel_path = rel_path.replace("\\", "/")
        if rel_path.startswith("/") or ".." in rel_path.split("/"):
            raise ValueError(f"unsafe pack asset path {rel_path!r}")
        dest = self.pack_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = Path(src)
        if src.resolve() != dest.resolve():
            shutil.copyfile(src, dest)
        entry = AssetEntry(path=rel_path, sha256=sha256_file(src),
                           bytes=src.stat().st_size, samples=samples)
        self.assets.append(entry)
        return entry

    def write_json(self, rel_path: str, data: dict) -> None:
        rel_path = rel_path.replace("\\", "/")
        dest = self.pack_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, indent=2, sort_keys=True).encode("utf-8")
        dest.write_bytes(payload)
        self.assets.append(AssetEntry(path=rel_path, sha256=sha256_bytes(payload),
                                      bytes=len(payload)))

    def finalize_manifest(self, manifest: dict) -> Path:
        """Attach the integrity block and write manifest.json (§17)."""
        manifest = dict(manifest)
        manifest["integrity"] = {
            "manifestSha256": "",
            "assets": [a.to_dict() for a in sorted(self.assets, key=lambda a: a.path)],
        }
        body = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
        # Hash of manifest body with the integrity hash field zeroed.
        manifest["integrity"]["manifestSha256"] = sha256_bytes(body)
        final = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
        path = self.pack_dir / "manifest.json"
        path.write_bytes(final)
        return path

    def zip_pack(self, out_zip: Path) -> Path:
        out_zip = Path(out_zip)
        if out_zip.exists():
            out_zip.unlink()
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(self.pack_dir.rglob("*")):
                if p.is_file():
                    zf.write(p, p.relative_to(self.pack_dir).as_posix())
        return out_zip


# ---- Safe extraction (§17) -------------------------------------------------

def _is_safe_member(name: str) -> bool:
    name = name.replace("\\", "/")
    if name.startswith("/") or name.startswith("../"):
        return False
    parts = name.split("/")
    return ".." not in parts and not name.endswith("/..")


def extract_pack(zip_path: Path, dest_dir: Path) -> Path:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if not _is_safe_member(info.filename):
                raise ValueError(f"unsafe pack member {info.filename!r}")
            # Reject symlinks (unix mode high bits).
            if (info.external_attr >> 16) & 0o120000 == 0o120000:
                raise ValueError(f"symlink member not allowed {info.filename!r}")
            total += info.file_size
            if total > _MAX_UNCOMPRESSED:
                raise ValueError("pack exceeds maximum uncompressed size")
            zf.extract(info, dest_dir)
    return dest_dir


def verify_pack(pack_dir: Path) -> bool:
    """Verify manifest integrity block against on-disk assets (§17)."""
    pack_dir = Path(pack_dir)
    manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    integrity = manifest.get("integrity", {})
    recorded = dict(manifest)
    recorded["integrity"] = dict(integrity)
    recorded["integrity"]["manifestSha256"] = ""
    body = json.dumps(recorded, indent=2, sort_keys=True).encode("utf-8")
    if integrity.get("manifestSha256") != sha256_bytes(body):
        return False
    for asset in integrity.get("assets", []):
        p = pack_dir / asset["path"]
        if not p.is_file():
            return False
        if p.stat().st_size != asset["bytes"]:
            return False
        if sha256_file(p) != asset["sha256"]:
            return False
    return True
