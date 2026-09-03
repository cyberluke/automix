"""JuggleMiner shared types — pure dataclasses, importable everywhere."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import List, Optional


class PhraseRole(str, enum.Enum):
    """Phrase semantics — how a section wants to be juggled."""
    DROP_HOOK = "DROP_HOOK"      # aggressive juggling
    VOCAL_HOOK = "VOCAL_HOOK"    # hunt syllable retriggers
    PERCUSSIVE = "PERCUSSIVE"    # kick/snare doubles
    BUILD = "BUILD"              # shrink buffer progressively (tension)
    BREAKDOWN = "BREAKDOWN"      # longer phrase callbacks
    GENERIC = "GENERIC"


@dataclass
class JuggleGesture:
    """One backstep/juggle move on the MASTER buffer.

    `phase` picks WHERE the buffer activates relative to the beat:
      - 'onbeat'  → trigger ON the kick (the downbeat/transient at the boundary)
      - 'offbeat' → trigger ON the snare (the backbeat, half a beat later)
    `mode` picks HOW the slice re-triggers:
      - 'retrigger' → play the slice `repeat` times back-to-back AT the boundary
      - 'loop'      → DJ double/triple LOOP: let the phrase play to its end,
                      then loop the LAST `duration_beats` `loop_count` times
                      (this is the musical 'loop roll', NOT a mid-phrase stutter).
    """
    offset_beats: float     # how far back from the boundary (0.5..2.0)
    duration_beats: float   # slice length (0.75 / 1 / 2 — NOT short stutters)
    repeat: int = 1         # retrigger mode: times to re-trigger the slice
    phase: str = "onbeat"   # "onbeat" (kick) | "offbeat" (snare)
    mode: str = "retrigger" # "retrigger" | "loop"
    loop_count: int = 2     # loop mode: 2 = double, 3 = triple
    slice_gain: float = 1.0 # retrigger level (DJ rides the fader)
    # placement grid — the jungle/DnB 'slap': do the repeats land ON the beat
    # ('straight') or BETWEEN beats ('slap' 3/4, 'swing' triplet)? A 0.75 version
    # must NOT sit on the 1-beat grid or it just sounds like 1b.
    grid: str = "straight"  # "straight" | "slap" | "swing"
    slap_beats: float = 0.75 # 'slap' step: 2nd hit closer to 1st, farther from 3rd


@dataclass
class JuggleScores:
    """Per-candidate musicality metrics (0..1, higher = more interesting)."""
    punch: float = 0.0            # onset strength in the retriggered slice
    transient_density: float = 0.0
    spectral_novelty: float = 0.0 # how different the slice is vs its context
    vocal_hook: float = 0.0       # syllable band energy at slice head
    groove: float = 0.0           # does the retrigger reinforce the beat grid
    total: float = 0.0            # weighted composite


@dataclass
class JuggleCandidate:
    """A ranked, rendered juggle variant."""
    gesture: JuggleGesture
    scores: JuggleScores
    wav_path: str = ""
    description: str = ""


@dataclass
class JuggleMinerConfig:
    """Tunables for offline brute-force juggle mining."""
    sr: int = 44100
    # brute-force grids — focused on MUSICAL loop lengths (3/4, 1, 2 beats),
    # not short stutters (0.125/0.25 sounded like a stutter, not a loop).
    offsets_beats: List[float] = field(
        default_factory=lambda: [0.5, 0.75, 1.0, 1.5, 2.0])
    durations_beats: List[float] = field(
        default_factory=lambda: [0.75, 1.0, 2.0])
    repeats: List[int] = field(default_factory=lambda: [1, 2, 3])
    loop_counts: List[int] = field(default_factory=lambda: [2, 3])  # double/triple
    phases: List[str] = field(default_factory=lambda: ["onbeat", "offbeat"])
    # scoring
    top_k: int = 8
    vocal_lo_hz: float = 300.0
    vocal_hi_hz: float = 3400.0
    novelty_win_beats: float = 4.0     # context window for spectral novelty
    # score weights
    w_punch: float = 0.30
    w_transient: float = 0.15
    w_novelty: float = 0.25
    w_vocal: float = 0.20
    w_groove: float = 0.10
    # render hygiene
    declick_ms: float = 6.0            # tiny edge fade so retrigger clicks don't pop
    peak_ceiling: float = 0.95         # normalize candidate under this
    seed: int = 0                      # deterministic
    # turntable nonlinearity ('frajer' vinyl mode)
    vinyl: bool = False                # motor wow: platter bogs down & re-spins
    vinyl_depth: float = 0.5           # how deep the motor bogs (0..0.6)
    reverse_flourish: bool = False     # reverse kick back-cue scratch on entry
    # placement grids to try (jungle slap / swing / straight)
    grids: List[str] = field(default_factory=lambda: ["straight", "slap"])
    # HUMANIZE — take the robot out: per-hit timing jitter + gain/pitch
    # variation + a NEGATIVE swing (pull/drag) so it breathes off the grid.
    humanize: bool = False             # master switch
    humanize_timing_ms: float = 9.0    # per-hit placement jitter (ms)
    humanize_gain: float = 0.10        # per-hit level wobble (0..0.3)
    humanize_pitch: float = 0.008      # per-hit micro pitch/tape wobble (0..0.02)
    swing: float = -0.12               # NEGATIVE = drag/pull (human late feel)
    accelerate: float = 0.0            # 0..1: compress later hits closer together
                                       #   (tempo ramp INTO the drop — tension)
    # BUFFER HACK — dramatic ending: chop the tail into a stutter that
    # decelerates/shrinks, so the last beat 'pokopane' repeats and collapses.
    buffer_hack: bool = False          # tail stutter outro
    hack_div: int = 4                  # chop the last hit into N micro-repeats
    hack_shrink: float = 0.6           # each micro-repeat is X the previous len
    hack_rate: float = 0.9             # each micro-repeat slows/pitches down a bit
    hack_cut_ms: float = 10.0          # smooth cut envelope on each chop (no kick clash)
    # CHIRP SCRATCH — the turntablist chirp between hits: a fast fwd/back
    # shuttle of a tiny grain (that 32-43ms 'zip'), then SKIP 1 BAR because a
    # real hand can't shuttle faster than that. Sounds like a Technics scratch.
    chirp: bool = False                # insert a chirp scratch before the hits
    chirp_ms: float = 38.0             # chirp grain length (the 32-43ms zip)
    chirp_swing: float = 1.8           # how far the grain shuttles fwd/back
    skip_bars: float = 0.0             # drop N bars after the chirp (hand can't keep up)
    # VINYL POWER-DOWN — the turntable motor STOP: platter decelerates, pitch
    # and tempo sag to zero, into silence. The 'someone pulled the plug' outro.
    power_down: bool = False           # motor-stop outro after the effect
    power_down_s: float = 0.7          # how long the platter takes to stop


def role_default_settings(role: PhraseRole) -> dict:
    """Intelligent per-role juggle biases — focused on MUSICAL loop lengths
    (3/4, 1, 2 beats) and loop/retrigger placement, not short stutters."""
    return {
        PhraseRole.DROP_HOOK: dict(
            offsets=[0.5, 0.75, 1.0, 2.0], durations=[0.75, 1.0, 2.0],
            repeats=[2, 3], loop_counts=[2, 3], boost="punch"),
        PhraseRole.VOCAL_HOOK: dict(
            offsets=[0.5, 0.75, 1.0], durations=[0.75, 1.0],
            repeats=[1, 2], loop_counts=[2], boost="vocal_hook"),
        PhraseRole.PERCUSSIVE: dict(
            offsets=[0.5, 0.75, 1.0], durations=[0.75, 1.0],
            repeats=[2, 3], loop_counts=[2, 3], boost="punch"),
        PhraseRole.BUILD: dict(
            offsets=[2.0, 1.0, 0.75], durations=[2.0, 1.0, 0.75],
            repeats=[1], loop_counts=[2], boost="groove"),  # shrink buffer → tension
        PhraseRole.BREAKDOWN: dict(
            offsets=[1.0, 2.0], durations=[1.0, 2.0],
            repeats=[1], loop_counts=[2], boost="spectral_novelty"),
        PhraseRole.GENERIC: dict(
            offsets=[0.5, 0.75, 1.0, 2.0], durations=[0.75, 1.0, 2.0],
            repeats=[1, 2], loop_counts=[2], boost="punch"),
    }[role]


# ---------------------------------------------------------------------------
# PRESET REGISTRY — saved 'good accidents' the user picked by ear.
# ---------------------------------------------------------------------------

@dataclass
class JugglePreset:
    """A named, saved juggle move (a curated gesture + its render-time FX)."""
    name: str
    gesture: JuggleGesture
    note: str = ""
    # render-time FX overrides (chirp / humanize / vinyl / power_down / fader …)
    # applied on top of the gesture when the preset is rendered.
    render: dict = field(default_factory=dict)
    # selection weight: 1.0 = normal, <1.0 = lower priority when a state
    # machine / auto-picker is choosing among presets (still fully usable).
    priority: float = 1.0


JUGGLE_PRESETS: dict[str, JugglePreset] = {}


def _register(p: JugglePreset) -> None:
    JUGGLE_PRESETS[p.name] = p


# First user-picked preset: the v1 winner (malugi juggle.04) — half-beat slice,
# doubled on the kick. 'Tohle je dobre, nenasilne a rychle.'
_register(JugglePreset(
    name="halfstep_double_onbeat",
    gesture=JuggleGesture(offset_beats=0.5, duration_beats=0.5, repeat=2,
                          phase="onbeat", mode="retrigger"),
    note="v1 winner (malugi -0.5b x0.5b r2) — half-beat slice doubled on the kick.",
))

# v2 winner: 'presne tohle jsem chtel, signature DJ kvalita' — half-beat offset,
# 2-beat slice doubled on the kick.
_register(JugglePreset(
    name="signature_dj",
    gesture=JuggleGesture(offset_beats=0.5, duration_beats=2.0, repeat=2,
                          phase="onbeat", mode="retrigger"),
    note="v2 winner (malugi -0.5b x2b r2 on) — 'signature DJ kvalita'.",
))

# v2 'DISCO SHOW / MIX SHOW' — half-beat offset, 1-beat slice doubled on the kick.
_register(JugglePreset(
    name="disco_show",
    gesture=JuggleGesture(offset_beats=0.5, duration_beats=1.0, repeat=2,
                          phase="onbeat", mode="retrigger"),
    note="v2 'DISCO SHOW / MIX SHOW' (malugi -0.5b x1b r2 on).",
))

# v2 vocal-loop: 2-beat slice, end-of-phrase double loop on the kick —
# 'na vokal se to muze hodit' (not for the beat).
_register(JugglePreset(
    name="vocal_loop_double",
    gesture=JuggleGesture(offset_beats=0.5, duration_beats=2.0, repeat=1,
                          phase="onbeat", mode="loop", loop_count=2),
    note="v2 (malugi -0.5b x2b loop2 on) — end-of-phrase double loop; good on VOCAL, not on the beat.",
))


# v16 winner: ONE chirp wind-up slide, then the slap buffer with eased
# accelerate, humanize drag, the last hit shifted FORWARD into the future, and
# sharp hip-hop fader cuts between the kicks. 'super hotovo ulozit preset'.
_register(JugglePreset(
    name="chirp_fader_fwd",
    gesture=JuggleGesture(offset_beats=0.5, duration_beats=2.0, repeat=3,
                          phase="offbeat", mode="retrigger",
                          grid="slap", slap_beats=0.75),
    note="v16 winner — one chirp slide, slap buffer, eased accelerate, forward last hit, sharp fader cuts between kicks.",
    render=dict(chirp=True, chirp_ms=160.0, chirp_swing=1.8,
                humanize=True, swing=-0.12, accelerate=0.35,
                forward_last=True, forward_shift=0.5, fader_cut_ms=35.0),
))

# v16 winner: vinyl slap buffer with the motor STOP→SPIN-UP moved EARLY so it
# overwrites the boring last repeat, dropping in only the aggressive 2nd half
# of the spin-up curve. 'super hotovo ulozit preset'.
_register(JugglePreset(
    name="vinyl_spinup_early",
    gesture=JuggleGesture(offset_beats=0.5, duration_beats=2.0, repeat=2,
                          phase="offbeat", mode="retrigger",
                          grid="slap", slap_beats=0.75),
    note="v16 winner — vinyl slap, motor stop→aggressive 2nd-half spin-up placed 1 beat early to overwrite the last repeat.",
    render=dict(vinyl=True, vinyl_depth=0.5,
                power_down=True, power_down_s=0.9, power_down_overlap_beats=1.0),
))


# --- Older keepers (LOWER PRIORITY) ---------------------------------------
# From the v8 slap exploration — the off-beat slap interleave the user picked.
_register(JugglePreset(
    name="slap_off",
    gesture=JuggleGesture(offset_beats=0.5, duration_beats=1.0, repeat=3,
                          phase="offbeat", mode="retrigger",
                          grid="slap", slap_beats=0.75),
    note="v8 keeper (juggle-slap) — off-beat 1b slap interleave r3.",
    priority=0.4,
))

# Same off-beat slap but with the vinyl motor + reverse back-cue flourish.
_register(JugglePreset(
    name="slap_off_vinyl",
    gesture=JuggleGesture(offset_beats=0.5, duration_beats=1.0, repeat=3,
                          phase="offbeat", mode="retrigger",
                          grid="slap", slap_beats=0.75),
    note="v8 keeper (juggle-slap) — off-beat slap + vinyl + reverse flourish.",
    render=dict(vinyl=True, reverse_flourish=True),
    priority=0.4,
))

# v12 'zni ok' — humanized slap buffer with the BUTCHER tail-hack: short-decay
# exp kicks chopped back-to-back (no gaps), the tail collapses into a stutter.
_register(JugglePreset(
    name="human_hack_butcher",
    gesture=JuggleGesture(offset_beats=0.5, duration_beats=2.0, repeat=3,
                          phase="offbeat", mode="retrigger",
                          grid="slap", slap_beats=0.75),
    note="v12 keeper ('zni ok') — humanized slap + butcher tail-hack stutter outro.",
    render=dict(humanize=True, swing=-0.12, accelerate=0.35,
                buffer_hack=True, hack_div=4, hack_shrink=0.6, hack_rate=0.9),
    priority=0.4,
))


def get_preset(name: str) -> JugglePreset:
    if name not in JUGGLE_PRESETS:
        raise KeyError(f"unknown juggle preset '{name}'. "
                       f"available: {sorted(JUGGLE_PRESETS)}")
    return JUGGLE_PRESETS[name]


def list_presets(min_priority: float = 0.0) -> list[JugglePreset]:
    """All presets at/above a priority, best first — for auto-pickers."""
    return sorted((p for p in JUGGLE_PRESETS.values() if p.priority >= min_priority),
                  key=lambda p: p.priority, reverse=True)


@dataclass
class JuggleMinerRequest:
    """Mine juggle candidates around a hot moment in a master/segment."""
    source_wav: str
    boundary_s: float               # the hot phrase boundary / drop entry (s)
    bpm: float
    role: PhraseRole = PhraseRole.GENERIC
    context_beats: float = 4.0      # how much before/after to render into preview


@dataclass
class JuggleMinerResult:
    """Ranked candidates + the rendered previews."""
    request: JuggleMinerRequest
    candidates: List[JuggleCandidate] = field(default_factory=list)
    log: List[str] = field(default_factory=list)
