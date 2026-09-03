"""HyperMix configuration. Every sound-affecting value is explicit here and
participates in the relevant artifact/cache config hash.

HyperMix deliberately keeps its own sample-rate world (48 kHz) independent of
legacy src/settings.py::SR (44.1 kHz) so the existing club/server paths remain
usable during migration.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Tuple

HYPERMIX_SAMPLE_RATE = 48_000
HYPERMIX_CHANNELS = 2
HYPERMIX_PHRASE_BARS = 8
HYPERMIX_CACHE_VERSION = 1
HYPERMIX_RENDER_HEADROOM_DBTP = -1.0
HYPERMIX_DEFAULT_LOOKAHEAD_SEC = 6.0
HYPERMIX_MIN_LOOKAHEAD_SEC = 2.0
HYPERMIX_MAX_LOOKAHEAD_SEC = 15.0
HYPERMIX_DEFAULT_HOTSWAP = "nextPhrase"
HYPERMIX_DEFAULT_FALLBACK_TRANSITION = "rewind"

# Canonicalizer / subsystem versions. Bump when the output of that stage changes
# so cache keys invalidate exactly the right layer (§41).
CANONICALIZER_VERSION = 1
ANALYZER_VERSION = 1
WAVEFORM_VERSION = 1
SEGMENT_COMPILER_VERSION = 1
TRANSITION_RENDERER_VERSION = 1
PACK_COMPILER_VERSION = 1

# Default lengths compiled around curated cues (bars). 64 added so V1
# DeepDance can hold a full 64-bar drop/hook section (§ deepMix.maxPhraseBars).
DEFAULT_SEGMENT_BARS: Tuple[int, ...] = (8, 16, 32, 64)
SUPPORTED_PHRASE_BARS: Tuple[int, ...] = (4, 8, 16, 32)

# Bounded worker concurrency (§20, §38).
DEFAULT_DECODE_WORKERS = 2
DEFAULT_ANALYSIS_WORKERS = 2
DEFAULT_RENDER_WORKERS = 2

# Sidecar idle shutdown (seconds). 0 = never.
SIDECAR_IDLE_SHUTDOWN_SEC = 0


@dataclass(frozen=True)
class HyperMixConfig:
    """Fully explicit sound-affecting configuration. Frozen + hashable so it can
    be embedded in cache/artifact config hashes (§5)."""

    sample_rate: int = HYPERMIX_SAMPLE_RATE
    channels: int = HYPERMIX_CHANNELS
    phrase_bars: int = HYPERMIX_PHRASE_BARS
    cache_version: int = HYPERMIX_CACHE_VERSION
    render_headroom_dbtp: float = HYPERMIX_RENDER_HEADROOM_DBTP
    lookahead_sec: float = HYPERMIX_DEFAULT_LOOKAHEAD_SEC
    fallback_transition: str = HYPERMIX_DEFAULT_FALLBACK_TRANSITION
    default_hotswap: str = HYPERMIX_DEFAULT_HOTSWAP
    segment_bars: Tuple[int, ...] = DEFAULT_SEGMENT_BARS
    decode_workers: int = DEFAULT_DECODE_WORKERS
    analysis_workers: int = DEFAULT_ANALYSIS_WORKERS
    render_workers: int = DEFAULT_RENDER_WORKERS
    # Optional offline time-stretch backend adapter name; default unavailable (§39).
    time_stretch_backend: str = "none"
    # Optional stems directory; default absent (§39).
    stems_enabled: bool = False

    def __post_init__(self) -> None:
        if self.phrase_bars not in SUPPORTED_PHRASE_BARS:
            raise ValueError(f"phrase_bars must be one of {SUPPORTED_PHRASE_BARS}")
        if not (HYPERMIX_MIN_LOOKAHEAD_SEC <= self.lookahead_sec <= HYPERMIX_MAX_LOOKAHEAD_SEC):
            raise ValueError(
                f"lookahead_sec must be within "
                f"[{HYPERMIX_MIN_LOOKAHEAD_SEC}, {HYPERMIX_MAX_LOOKAHEAD_SEC}]"
            )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["segment_bars"] = list(self.segment_bars)
        return d

    def config_hash(self) -> str:
        """Stable hash over every sound-affecting value (§5)."""
        from .hashing import sha256_text

        return sha256_text(json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")))


DEFAULT_CONFIG = HyperMixConfig()

# Root for private local data (crates, caches, packs). Kept out of Git (§1.6).
DEFAULT_PRIVATE_ROOT = Path("var")
