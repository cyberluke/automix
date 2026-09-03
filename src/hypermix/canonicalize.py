"""Canonical audio ingest (§7). Decode → strip metadata → deterministic resample
→ 48 kHz stereo float32 WAV → SHA-256 → atomic cache.

FFmpeg args are passed as an argument array, never a shell string (§38).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .audio_io import CanonicalAudio, read_wav
from .cache import LayeredCache
from .config import CANONICALIZER_VERSION, HyperMixConfig, DEFAULT_CONFIG
from .errors import ErrorCode, HyperMixError
from .hashing import sha256_file, sha256_text, short_hash


@dataclass
class CanonicalResult:
    audio: CanonicalAudio
    canonical_path: Path
    canonical_sha256: str
    source_sha256: str
    cache_key: str
    from_cache: bool

    @property
    def cache_hit(self) -> bool:
        return self.from_cache

    @property
    def duration_sec(self) -> float:
        return self.audio.duration_sec


def ffmpeg_version() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        return "unavailable"
    try:
        out = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=15)
        return out.stdout.splitlines()[0] if out.stdout else "unknown"
    except Exception:
        return "unknown"


class Canonicalizer:
    def __init__(self, cache_or_config=None, config: HyperMixConfig = DEFAULT_CONFIG) -> None:
        # Accept either a LayeredCache (canonicalize.py native) or a HyperMixConfig
        # (handlers/CLI style). When given a config, build a default cache under var/cache.
        if isinstance(cache_or_config, LayeredCache):
            self.cache = cache_or_config
            self.config = config
        elif isinstance(cache_or_config, HyperMixConfig):
            self.config = cache_or_config
            self.cache = LayeredCache(self.default_private_root() / "cache")
        elif cache_or_config is None:
            self.config = config
            self.cache = LayeredCache(self.default_private_root() / "cache")
        else:
            raise TypeError(f"unsupported Canonicalizer arg: {type(cache_or_config)}")
        self.ffmpeg = shutil.which("ffmpeg")
        if not self.ffmpeg:
            raise HyperMixError(ErrorCode.HMX_CANONICALIZE_FAILED,
                                "ffmpeg not found on PATH; install FFmpeg and retry")

    def default_private_root(self) -> Path:
        from .config import DEFAULT_PRIVATE_ROOT
        return Path(DEFAULT_PRIVATE_ROOT)

    def cache_key(self, source_sha256: str) -> str:
        cfg = f"{CANONICALIZER_VERSION}|{self.config.sample_rate}|{self.config.channels}"
        return short_hash(source_sha256) + "-" + short_hash(sha256_text(cfg), 8)

    def canonicalize(self, source: Path, private_root: Optional[Path] = None) -> CanonicalResult:
        source = Path(source)
        if not source.exists():
            raise HyperMixError(ErrorCode.HMX_SOURCE_NOT_FOUND, f"source not found: {source}")

        src_hash = sha256_file(source)
        key = self.cache_key(src_hash)
        suffix = ".wav"
        cfg_hash = self.config.config_hash()

        if self.cache.validate("canonical", key, suffix, src_hash, cfg_hash,
                               CANONICALIZER_VERSION):
            path = self.cache.path("canonical", key, suffix)
            audio = read_wav(path, self.config.sample_rate, self.config.channels)
            audio.sha256 = sha256_file(path)
            return CanonicalResult(audio, path, audio.sha256, src_hash, key, from_cache=True)

        # Decode via FFmpeg to canonical WAV (float32, stripped metadata).
        out_path = self.cache.path("canonical", key, suffix)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_suffix(f".dec.{__import__('os').getpid()}.wav")
        args = [
            self.ffmpeg, "-y",
            "-i", str(source),
            "-map_metadata", "-1",
            "-vn",
            "-ac", str(self.config.channels),
            "-ar", str(self.config.sample_rate),
            "-c:a", "pcm_f32le",
            str(tmp),
        ]
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=600)
        except Exception as exc:
            raise HyperMixError(ErrorCode.HMX_CANONICALIZE_FAILED,
                                f"ffmpeg failed for {source}", detail=repr(exc))
        if proc.returncode != 0 or not tmp.exists():
            raise HyperMixError(ErrorCode.HMX_CANONICALIZE_FAILED,
                                f"ffmpeg could not canonicalize {source}",
                                detail=proc.stderr[-2000:] if proc.stderr else None)
        os.replace(tmp, out_path)  # atomic publish

        audio = read_wav(out_path, self.config.sample_rate, self.config.channels)
        canon_hash = sha256_file(out_path)
        audio.sha256 = canon_hash

        meta = self.cache.make_meta("canonical", key, src_hash, cfg_hash,
                                    CANONICALIZER_VERSION)
        self.cache.write_meta("canonical", key, meta)
        return CanonicalResult(audio, out_path, canon_hash, src_hash, key, from_cache=False)

    def source_changed(self, source: Path, recorded_sha256: Optional[str]) -> bool:
        """Detect source change → caller marks cues stale, never moves them (§10)."""
        if not recorded_sha256:
            return True
        p = Path(source)
        if not p.exists():
            raise HyperMixError(ErrorCode.HMX_SOURCE_NOT_FOUND, f"source not found: {source}")
        return sha256_file(p) != recorded_sha256
