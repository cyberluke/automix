"""Layered, content-addressed cache (§41).

Separate roots per layer; every entry carries metadata with schema version,
compiler version, source hash, config hash and timestamp. A renderer change
invalidates only its own layer.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from . import __version__
from .audio_io import atomic_write_bytes
from .hashing import sha256_file

LAYERS = ("canonical", "analysis", "waveforms", "segments",
          "transitions", "stems", "packs")


@dataclass
class CacheMeta:
    schema_version: int
    compiler_version: str
    source_hash: str
    config_hash: str
    created: str
    layer: str
    key: str

    def to_dict(self) -> dict:
        return asdict(self)


class LayeredCache:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        for layer in LAYERS:
            (self.root / layer).mkdir(parents=True, exist_ok=True)

    def path(self, layer: str, key: str, suffix: str) -> Path:
        if layer not in LAYERS:
            raise ValueError(f"unknown cache layer {layer!r}")
        return self.root / layer / f"{key}{suffix}"

    def exists(self, layer: str, key: str, suffix: str) -> bool:
        return self.path(layer, key, suffix).exists()

    def meta_path(self, layer: str, key: str) -> Path:
        return self.root / layer / f"{key}.meta.json"

    def write_meta(self, layer: str, key: str, meta: CacheMeta) -> None:
        atomic_write_bytes(self.meta_path(layer, key),
                           json.dumps(meta.to_dict(), indent=1).encode("utf-8"))

    def read_meta(self, layer: str, key: str) -> Optional[CacheMeta]:
        p = self.meta_path(layer, key)
        if not p.exists():
            return None
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return CacheMeta(**d)
        except Exception:
            return None

    def validate(self, layer: str, key: str, suffix: str,
                 expect_source_hash: str, expect_config_hash: str,
                 schema_version: int) -> bool:
        """True only if payload + metadata exist and hashes/versions match (§7)."""
        payload = self.path(layer, key, suffix)
        meta = self.read_meta(layer, key)
        if not payload.exists() or meta is None:
            return False
        if meta.schema_version != schema_version:
            return False
        if meta.source_hash != expect_source_hash or meta.config_hash != expect_config_hash:
            return False
        # Never trust metadata whose payload hash doesn't match (§7).
        if sha256_file(payload) != expect_source_hash and layer == "canonical":
            return False
        return True

    def make_meta(self, layer: str, key: str, source_hash: str,
                  config_hash: str, schema_version: int) -> CacheMeta:
        return CacheMeta(
            schema_version=schema_version,
            compiler_version=__version__,
            source_hash=source_hash,
            config_hash=config_hash,
            created=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            layer=layer, key=key,
        )

    def stats(self) -> dict:
        out = {}
        for layer in LAYERS:
            d = self.root / layer
            files = [p for p in d.iterdir() if p.is_file() and not p.name.endswith(".meta.json")]
            out[layer] = {
                "files": len(files),
                "bytes": sum(p.stat().st_size for p in files),
            }
        return {"root": str(self.root), "layers": out}

    def prune(self, layer: Optional[str] = None) -> dict:
        """Remove payloads whose metadata is missing/corrupt (safe GC)."""
        removed = 0
        layers = (layer,) if layer else LAYERS
        for lay in layers:
            d = self.root / lay
            for p in d.iterdir():
                if p.name.endswith(".meta.json"):
                    continue
                key = p.stem
                if self.read_meta(lay, key) is None:
                    p.unlink(missing_ok=True)
                    removed += 1
        return {"removed": removed}
