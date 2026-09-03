"""SPR shared types — pure dataclasses, no heavy deps (importable from both venvs)."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import List, Optional


class SPRFlag(str, enum.Enum):
    """Which reinforcement path was taken for a candidate."""
    TRANSCRIBED = "SPR_TRANSCRIBED"      # Branch 1: MIDI transcription → CyberSynth
    RESAMPLED = "SPR_RESAMPLED"          # Branch 2: Kontakt-style pitch-up resample
    VOCODED = "SPR_VOCODED"              # Branch 2: envelope-follower vocoder
    RESYNTHESIZED = "SPR_RESYNTHESIZED"  # Branch 2: spectral resynthesis (last resort)
    HYBRID = "SPR_HYBRID"                # Blend of the above


@dataclass
class NoteEvent:
    """A quantized, cleaned note ready for CyberSynth rendering."""
    midi: int            # MIDI note number 0-127
    start_s: float       # seconds, relative to phrase start
    dur_s: float         # seconds
    velocity: float      # 0.0-1.0
    bend_cents: float = 0.0  # average pitch bend over the note


@dataclass
class SPRConfig:
    """Pipeline tunables. Defaults chosen for neurofunk D&B synth loops."""
    sr: int = 44100
    # --- gates ---
    vocal_bleed_threshold: float = 0.45   # if Demucs-other has > this, skip Branch 1
    transcribe_confidence: float = 0.80   # ≥ this → Branch 1
    # --- CyberSynth ---
    supersaw_voices: int = 7
    supersaw_detune_cents: float = 18.0   # total spread across voices
    filter_cutoff_hz: float = 3200.0      # darker JP supersaw (was 8000 = shrill)
    filter_resonance: float = 0.3         # 0..1 (JP-8080-ish)
    # 'Korg' MS-20-style drive on the supersaw filter. Was too hot — halve it
    # and let a slow LFO wobble it ±10% over 1 beat for an organic feel.
    filter_drive: float = 0.5             # was effectively ~1.0; -50%
    filter_drive_lfo_depth: float = 0.10  # ±10% on the drive
    filter_drive_lfo_per_beat: bool = True  # LFO rate = 1/beat (needs bpm)
    # DJ effect: when confidence is low, paper over a missing last note by
    # MANUALLY duplicating the penultimate note 2x in quick succession with
    # decreasing volume (a real 'echo repeat', not a wonky ping-pong delay).
    cybersynth_sync_delay_on_low_conf: bool = True
    cybersynth_repeat_note: bool = True    # manual duplicate instead of delay
    cybersynth_repeat_count: int = 2       # play it 2 more times
    cybersynth_repeat_interval_s: float = 0.16  # quick succession (s)
    cybersynth_repeat_decay: float = 0.55  # each repeat is x0.55 of previous
    # LIGHT gap-fill: user wants melody SPACES filled (echo-repeat), but v10's
    # full-strength fill was a wall of sound. Now ON but gentler: slower decay
    # (quieter repeats), wider spacing, fewer repeats. Fills holes w/o spikes.
    cybersynth_gap_fill: bool = True
    cybersynth_gap_min_s: float = 0.12     # only fill real spaces (>120 ms)
    cybersynth_gap_repeat_interval_s: float = 0.22  # wider spacing (calmer)
    cybersynth_gap_repeat_decay: float = 0.38  # much quieter each repeat
    # De-mud: gentle high-pass so the synth doesn't fight the bass, but NOT so
    # high that it thins the body out.
    cybersynth_hp_hz: float = 90.0
    # Brickwall the final layer so no repeat/drive sum can spike (volume spikes).
    cybersynth_limiter: bool = True
    cybersynth_limiter_threshold: float = 0.7
    chorus_rate_hz: float = 0.6
    chorus_depth_ms: float = 4.0
    chorus_mix: float = 0.35
    # Register: single octave up only. v11 added +12st ON TOP of the +12st
    # transpose = 2 octaves = too high / 'moc ve vyskach'. Now lift=0 so the
    # +12st transpose is the only lift. Brightness kept SUBTLE (dark JP tone).
    cybersynth_note_lift_st: int = 0
    cybersynth_excite_drive: float = 0.4
    cybersynth_excite_mix: float = 0.22
    cybersynth_presence_hz: float = 3200.0
    cybersynth_presence_db: float = 2.0
    # Mix bed = clean Demucs backing (no original synth); duck it under the layer.
    backing_duck_db: float = -1.0
    attack_s: float = 0.005
    release_s: float = 0.08
    # --- layering (starting point from design contract) ---
    # Gain staging for the preview mix. Layer is RMS-normalized to the phrase
    # before these offsets apply (see mix_layers), so reinforcement_gain_db is
    # the layer's loudness relative to the (ducked) phrase. Original is ducked
    # ~-3 dB so the summed mix does not slam the 0.98-peak limiter.
    original_gain_db: float = -3.0
    reinforcement_gain_db: float = -1.0
    # --- transposition choices (semitones; picked key-aware) ---
    transpose_safe_octave: int = 12
    transpose_power_fifth: int = 7
    transpose_fourth_color: int = 5
    # --- Branch 2 ---
    resample_semitones: int = 12
    resample_keep_length: bool = True  # same-duration pitch shift (phase vocoder)
    # Resample: boost + rhythmic LFO filter (per-beat cutoff wobble) for movement
    resample_boost_db: float = 3.0     # extra push so the +12st layer bites
    resample_lfo_filter: bool = True   # rhythmic LFO on a lowpass cutoff
    resample_lfo_min_hz: float = 1200.0
    resample_lfo_max_hz: float = 8000.0
    resample_lfo_per_beat: bool = True  # 1-cycle-per-beat sinus cutoff LFO
    # Soothing flanger on the resample layer — must be ALIVE and moving, with an
    # upward 'vacuum-cleaner' sweep (flange pitch climbs up). Higher feedback +
    # deeper modulation so it's clearly audible.
    resample_flanger: bool = True
    resample_flanger_wet: float = 0.45   # 45% wet — audible
    resample_flanger_rate_hz: float = 0.50  # faster modulation
    resample_flanger_depth_ms: float = 6.0  # deep sweep
    resample_flanger_base_ms: float = 0.5
    resample_flanger_feedback: float = 0.60  # resonant 'whoosh'
    resample_flanger_wet_boost: float = 0.15  # extra wet push
    # --- vocoder (Scooter) cleanup ---
    vocoder_bands: int = 12            # old-school (Scooter/Music Instructor)
    vocoder_root_midi: int = 57        # carrier root (A3) — octave up from A2
    vocoder_attack_ms: float = 0.5     # very fast attack → hard electro bite
    vocoder_release_ms: float = 30.0   # slower release → choppy sustain
    vocoder_drive: float = 4.0         # carrier distortion (tanh waveshaper)
    vocoder_highpass_hz: float = 300.0  # HP so it doesn't fight bass/drums
    # Static notch filters to kill cheap resonances in mids/highs (Hz, Q).
    vocoder_notch_hz: tuple = (2500.0, 4000.0, 6300.0)
    vocoder_notch_q: float = 4.0
    vocoder_deemphasis_hz: float = 6000.0  # gentle dynamic-EQ-ish high shelf cut
    # --- CyberLuke2 voice-tag '4x filter' on OUR SYNTH layer (not master) ---
    # The Vengeance-envelope sound: slow 1-bar MS-20 LP open then 4x fast
    # 1/4-bar sweeps, applied to the synth layer only (resample & cybersynth).
    # OFF by default: the slow MS-20 sweep starts ~200Hz (muffles the attack) and
    # the drive on top of the gap-fill repeats produced the volume spikes. The
    # clean layer (HP + brighten + brickwall) is the reliable sound.
    synth_4x_filter: bool = False
    synth_4x_filter_res: float = 0.65
    synth_4x_filter_drive: float = 1.1
    synth_4x_filter_slow_bars: float = 1.0   # 1 slow bar sweep
    synth_4x_filter_fast_reps: int = 4       # then 4 fast 1/4-bar sweeps
    # --- quantize ---
    quantize_grid: str = "1/16"   # snap to beat grid fraction
    ghost_note_min_vel: float = 0.15  # drop notes below this velocity
    merge_gap_s: float = 0.030        # merge notes closer than this
    # Groove: AFTER hard quantize, apply swing (push off-8ths late) and/or a
    # tiny humanize jitter, then RE-SNAP to the grid so everything still sits
    # tight to the beat (user: 'at to sedi do beatu').
    quantize_swing: float = 0.0       # 0=straight; 0.5=triplet swing on off-8ths
    quantize_humanize_s: float = 0.0  # ±seconds uniform jitter before re-snap


@dataclass
class SPRRequest:
    """User-selected phrase to reinforce."""
    source_wav: str          # path to source track/segment WAV
    start_s: float           # phrase start in source
    bars: int = 4            # phrase length in bars
    bpm: float = 174.0       # for beat grid + bar duration
    root_midi: Optional[int] = None  # detected key root (optional, enables key-aware transpose)
    scale: str = "minor"               # "minor" | "major" | "chromatic"


@dataclass
class SPRCandidate:
    """One reinforcement layer candidate."""
    flag: SPRFlag
    wav_path: str                       # rendered reinforcement layer (dry)
    mix_wav_path: Optional[str] = None  # original + layer preview mix
    transpose_semitones: int = 0
    confidence: float = 0.0
    notes: List[NoteEvent] = field(default_factory=list)
    description: str = ""


@dataclass
class SPRResult:
    """Result of an SPR run."""
    request: SPRRequest
    isolated_wav: Optional[str] = None   # Demucs "other" stem
    vocal_bleed: float = 0.0
    transcription_confidence: float = 0.0
    candidates: List[SPRCandidate] = field(default_factory=list)
    branch_used: str = ""                # "branch1" | "branch2" | "both"
    log: List[str] = field(default_factory=list)
