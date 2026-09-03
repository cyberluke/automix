"""JuggleMiner — Performance Gesture Search / beat-juggle discovery operator.

Pioneer DJM-style BEAT EFFECT (ROLL) and Technics beat-juggle/backstep are the
SAME musical act: grab a slice of the MASTER buffer (kick+bass+synth+vocal+
reverb tail+stereo image — the whole moment), step it back, and re-trigger it
in time. One happy accident can stack a vocal syllable + kick retrigger + synth
stab + reverb tail into a NEW HOOK that sounds like a deliberate producer edit.

This is NOT realtime. Offline we brute-force many offset×duration candidates
around a hot phrase boundary, score them, and rank the musically-useful
accidents — a luxury a DJ on Technics doesn't get.

  MASTER_JUGGLE → render candidate offsets → score punch / transient density /
  spectral novelty / vocal-syllable alignment → save interesting accidents.

Runs entirely in .venv-hypermix (numpy/scipy/soundfile/librosa). No stems venv.
"""

from .types import (
    JuggleGesture,
    JuggleScores,
    JuggleCandidate,
    JuggleMinerConfig,
    JuggleMinerRequest,
    JuggleMinerResult,
    JugglePreset,
    JUGGLE_PRESETS,
    PhraseRole,
    role_default_settings,
    get_preset,
)
from .miner import run_juggle_mine

__all__ = [
    "JuggleGesture",
    "JuggleScores",
    "JuggleCandidate",
    "JuggleMinerConfig",
    "JuggleMinerRequest",
    "JuggleMinerResult",
    "JugglePreset",
    "JUGGLE_PRESETS",
    "PhraseRole",
    "role_default_settings",
    "get_preset",
    "run_juggle_mine",
]
