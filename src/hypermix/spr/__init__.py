"""SPR — Spectral Phrase Reinforcement.

Analyzes selected musical phrases and creates complementary harmonic or timbral
layers while preserving the original phrase structure.

Pipeline (V1, user-selected phrase only):
  crop → isolate (Demucs "other" stem) → vocal-bleed gate
       → transcribe (Basic Pitch) → quantize → confidence gate
         ≥ threshold → Branch 1: CyberSynth layering (PRIMARY)
         < threshold → Branch 2: punk fallback (resample / vocoder) (FALLBACK)
"""

from .types import (
    SPRFlag,
    NoteEvent,
    SPRRequest,
    SPRResult,
    SPRConfig,
)

__all__ = [
    "SPRFlag",
    "NoteEvent",
    "SPRRequest",
    "SPRResult",
    "SPRConfig",
]
