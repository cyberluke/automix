"""Audio IO helpers for the HyperMix authoring/rendering side.

Canonical in-memory audio is float32 stereo at the configured sample rate.
Compressed formats are never the authoritative timing source (§7).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

import numpy as np
import soundfile as sf

from .errors import ErrorCode, HyperMixError


@dataclass
class CanonicalAudio:
    samples: np.ndarray          # shape [n_samples, 2], float32
    sample_rate: int
    channels: int = 2
    path: str = ""               # canonical cache path (for provenance)
    sha256: str = ""

    @property
    def n_samples(self) -> int:
        return int(self.samples.shape[0])

    @property
    def duration_sec(self) -> float:
        return self.n_samples / self.sample_rate if self.sample_rate else 0.0

    def mono(self) -> np.ndarray:
        return self.samples.mean(axis=1).astype(np.float32) if self.channels == 2 else self.samples[:, 0]


def read_wav(path: Path, expected_sr: int = 48000, expected_channels: int = 2) -> CanonicalAudio:
    """Read a canonical WAV and validate layout. Raises on mismatch."""
    try:
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception as exc:
        raise HyperMixError(ErrorCode.HMX_ASSET_DECODE_FAILED,
                            f"failed to decode {path}", detail=repr(exc))
    if sr != expected_sr:
        raise HyperMixError(ErrorCode.HMX_PACK_INTEGRITY_FAILED,
                            f"{path} sample rate {sr} != expected {expected_sr}")
    if data.shape[1] != expected_channels:
        raise HyperMixError(ErrorCode.HMX_PACK_INTEGRITY_FAILED,
                            f"{path} channels {data.shape[1]} != expected {expected_channels}")
    return CanonicalAudio(samples=np.ascontiguousarray(data, dtype=np.float32),
                          sample_rate=sr, channels=expected_channels, path=str(path))


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Atomic temp-file + rename so interrupted writes never corrupt cache/pack."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _strip_peak_chunk(data: bytes) -> bytes:
    """Remove the libsndfile PEAK chunk (contains a write timestamp) so WAV
    bytes are deterministic across renders (§18 byte-identical golden assets)."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return data
    out = bytearray(data[:12])
    i = 12
    end = len(data)
    while i + 8 <= end:
        cid = data[i:i + 4]
        size = int.from_bytes(data[i + 4:i + 8], "little")
        chunk = data[i:i + 8 + size + (size & 1)]
        if cid != b"PEAK":
            out += chunk
        i += 8 + size + (size & 1)
    # Patch RIFF size.
    out[4:8] = (len(out) - 8).to_bytes(4, "little")
    return bytes(out)


def atomic_write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    """Atomically write float32 stereo WAV (deterministic bytes; PEAK stripped)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    sf.write(str(tmp), samples, sample_rate, subtype="FLOAT", format="WAV")
    with open(tmp, "rb") as f:
        body = f.read()
    with open(tmp, "wb") as f:
        f.write(_strip_peak_chunk(body))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def slice_samples(audio: CanonicalAudio, start: int, end: int) -> np.ndarray:
    start = max(0, min(start, audio.n_samples))
    end = max(start, min(end, audio.n_samples))
    return audio.samples[start:end]


def declick_edges(x: np.ndarray, sr: int, fade_ms: float = 3.0) -> np.ndarray:
    """Tiny de-click envelope at slice edges only (§14). Does not fade phrase
    boundaries musically; only removes splice clicks."""
    n = x.shape[0]
    f = int(sr * fade_ms / 1000.0)
    if n < 2 * f or f < 1:
        return x
    out = x.copy()
    ramp = np.linspace(0.0, 1.0, f, dtype=np.float32)[:, None]
    out[:f] *= ramp
    out[-f:] *= ramp[::-1]
    return out
