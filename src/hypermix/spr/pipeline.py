"""SPR pipeline orchestrator.

Boundary contract:
  - Demucs + Basic Pitch run in .venv-stems (torch/tensorflow) via subprocess.
  - CyberSynth + punk fallback + mixing run HERE in .venv-hypermix.
  - Exchange between interpreters via WAV + JSON files only.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

import numpy as np

from .types import (
    SPRConfig, SPRRequest, SPRResult, SPRCandidate, SPRFlag, NoteEvent,
)
from . import cyber_synth, punk


def _apply_4x_filter(layer: np.ndarray, cfg: SPRConfig, bpm: float) -> np.ndarray:
    """CyberLuke2 voice-tag '4x filter' on OUR SYNTH layer (not master): a slow
    1-bar MS-20 LP open followed by 4x fast 1/4-bar sweeps (Vengeance envelope).
    Uses the same `filter_automation` as the main render so it sounds identical."""
    if not getattr(cfg, 'synth_4x_filter', True):
        return layer
    try:
        from src.hypermix.transitions.dsp import filter_automation
    except Exception:
        return layer  # MS-20 not available — leave layer as-is
    n = len(layer)
    sr = cfg.sr
    spb = sr * 60.0 / float(bpm)
    bar_n = int(round(cfg.synth_4x_filter_slow_bars * 4.0 * spb))
    # reset knob so each render starts fresh & deterministic
    try:
        filter_automation._knob = None
    except Exception:
        pass
    out = layer.copy()
    # SLOW: one 1-bar sweep
    if bar_n <= n:
        out[:bar_n] = filter_automation(out[:bar_n].copy(), sr, bpm,
                                        bars=cfg.synth_4x_filter_slow_bars,
                                        lp_from_hz=700.0, lp_to_hz=15000.0,
                                        res=cfg.synth_4x_filter_res,
                                        drive=cfg.synth_4x_filter_drive)
    # FAST: 4 x 1/4-bar sweeps right after
    fast_start = bar_n
    qbar_n = int(round(spb))
    for r in range(int(cfg.synth_4x_filter_fast_reps)):
        s0 = fast_start + r * qbar_n
        if s0 + qbar_n > n:
            break
        out[s0:s0 + qbar_n] = filter_automation(out[s0:s0 + qbar_n].copy(), sr, bpm,
                                                bars=0.25, lp_from_hz=1000.0,
                                                lp_to_hz=15000.0,
                                                res=min(1.0, cfg.synth_4x_filter_res + 0.05),
                                                drive=cfg.synth_4x_filter_drive * 1.1)
    return out.astype(np.float32)


# ---------------------------------------------------------------------------
# subprocess helpers
# ---------------------------------------------------------------------------

def _stems_python() -> str:
    """Resolve the .venv-stems interpreter (repo-rooted)."""
    root = Path(__file__).resolve().parents[3]  # src/hypermix/spr/pipeline.py → repo root
    p = root / ".venv-stems" / "Scripts" / "python.exe"
    return str(p) if p.exists() else sys.executable


def _run_stems_module(module: str, args: list[str], cwd: Path) -> dict:
    """Run `python -m src.hypermix.spr.<module> ...` under .venv-stems."""
    py = _stems_python()
    cmd = [py, "-m", f"src.hypermix.spr.{module}", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd))
    if proc.returncode != 0:
        raise RuntimeError(
            f"spr.{module} failed (rc={proc.returncode})\n"
            f"cmd: {' '.join(cmd)}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    # Last non-empty stdout line is the JSON summary
    lines = [l for l in proc.stdout.strip().splitlines() if l.strip()]
    return json.loads(lines[-1])


# ---------------------------------------------------------------------------
# key-aware transposition
# ---------------------------------------------------------------------------

_MINOR_SCALE = {0, 2, 3, 5, 7, 8, 10}
_MAJOR_SCALE = {0, 2, 4, 5, 7, 9, 11}


def _in_scale(midi: int, root_midi: int, scale: str) -> bool:
    pc = (midi - root_midi) % 12
    if scale == "chromatic":
        return True
    return pc in (_MINOR_SCALE if scale == "minor" else _MAJOR_SCALE)


def choose_transpositions(request: SPRRequest, cfg: SPRConfig,
                          notes: list[NoteEvent]) -> list[int]:
    """Return ordered candidate transpositions (semitones), key-aware.

    Always includes +12 (SAFE_OCTAVE). Adds +7 (POWER_FIFTH) and +5
    (FOURTH_COLOR) only when the transposed median pitch stays in-scale.
    """
    choices: list[int] = [cfg.transpose_safe_octave]
    if not notes or request.root_midi is None:
        choices += [cfg.transpose_power_fifth, cfg.transpose_fourth_color]
        return choices

    median_pitch = int(round(float(np.median([n.midi for n in notes]))))
    for t in (cfg.transpose_power_fifth, cfg.transpose_fourth_color):
        if _in_scale(median_pitch + t, request.root_midi, request.scale):
            choices.append(t)
    return choices


# ---------------------------------------------------------------------------
# main entry
# ---------------------------------------------------------------------------

def run_spr(request: SPRRequest, out_dir: str, cfg: Optional[SPRConfig] = None,
            do_branch2: bool = True, do_branch1: bool = True) -> SPRResult:
    cfg = cfg or SPRConfig()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).resolve().parents[3]
    result = SPRResult(request=request)

    # --- 1) isolate (subprocess: .venv-stems) -------------------------------
    other_wav = out / "spr.other.wav"
    crop_wav = out / "spr.crop.wav"
    backing_wav = out / "spr.backing.wav"   # clean-sum: drums+bass+vocals, NO synth
    iso = _run_stems_module("isolate", [
        "--source", request.source_wav,
        "--start-s", str(request.start_s),
        "--bars", str(request.bars),
        "--bpm", str(request.bpm),
        "--out", str(other_wav),
        "--crop-out", str(crop_wav),
        "--backing-out", str(backing_wav),
        "--sr", str(cfg.sr),
    ], cwd=repo_root)
    result.isolated_wav = iso["other_wav"]
    result.vocal_bleed = iso["vocal_bleed"]
    result.log.append(f"isolate: other={iso['other_wav']} bleed={iso['vocal_bleed']}")

    import soundfile as sf
    other, sr = sf.read(str(other_wav), dtype="float32", always_2d=True)
    crop, _ = sf.read(str(crop_wav), dtype="float32", always_2d=True)
    # Clean backing bed (Demucs stems re-summed WITHOUT the 'other'/synth stem).
    # This is the phase-artefact-free way to keep every other element original
    # and lay ONLY our replacement synth over the top, so notes poke through.
    try:
        backing, _ = sf.read(str(backing_wav), dtype="float32", always_2d=True)
    except Exception:
        backing = crop.copy()
    if backing.shape[0] != crop.shape[0]:
        n = min(backing.shape[0], crop.shape[0])
        backing = backing[:n]; crop = crop[:n]

    # --- 2) Branch 1: transcribe → CyberSynth (PRIMARY) ---------------------
    notes: list[NoteEvent] = []
    conf = 0.0
    if do_branch1 and result.vocal_bleed < cfg.vocal_bleed_threshold:
        notes_json = out / "spr.notes.json"
        tr = _run_stems_module("transcribe", [
            "--wav", str(other_wav),
            "--bpm", str(request.bpm),
            "--out", str(notes_json),
            "--quantize-grid", cfg.quantize_grid,
            "--ghost-min-vel", str(cfg.ghost_note_min_vel),
            "--swing", str(getattr(cfg, 'quantize_swing', 0.0)),
            "--humanize-s", str(getattr(cfg, 'quantize_humanize_s', 0.0)),
            "--sr", str(cfg.sr),
        ], cwd=repo_root)
        conf = float(tr["confidence"])
        result.transcription_confidence = conf
        notes = [NoteEvent(**n) for n in tr["notes"]]
        result.log.append(
            f"transcribe: kept={tr['kept_count']}/{tr['raw_count']} conf={conf}"
        )
    else:
        result.log.append(
            f"Branch 1 skipped (vocal_bleed={result.vocal_bleed} ≥ {cfg.vocal_bleed_threshold})"
        )

    # CyberSynth melody layer: render the transcribed MELODY whenever we have
    # notes. conf >= threshold → it's the headline Branch 1; below threshold we
    # still emit it (marked low-conf) so the user always gets a pure CyberSynth
    # playing the exact melody, alongside the Branch 2 fallbacks.
    if notes:
        trusted = conf >= cfg.transcribe_confidence
        if trusted:
            result.branch_used = "branch1"
        transpositions = choose_transpositions(request, cfg, notes)
        # Register: use the transcribed notes as-is; the +12st transpose IS the
        # lift. (v11's extra note_lift pushed it to 2 octaves = too high.)
        note_lift = int(getattr(cfg, 'cybersynth_note_lift_st', 0))
        notes_up = [NoteEvent(midi=n.midi + note_lift, start_s=n.start_s,
                              dur_s=n.dur_s, velocity=n.velocity,
                              bend_cents=n.bend_cents) for n in notes]
        for t in transpositions:
            layer = cyber_synth.render_notes(notes_up, cfg, transpose_semitones=t,
                                             bpm=request.bpm,
                                             min_total=len(crop))
            # MEGAMIX groove-filler (universal, every song): echo-repeat the
            # previous note into EVERY silent gap between notes so the loop
            # never loses rhythm. Deterministic, driven by the note grid.
            if getattr(cfg, 'cybersynth_gap_fill', True):
                layer = cyber_synth.gap_fill_repeats(
                    layer, cfg.sr, notes_up,
                    min_gap_s=cfg.cybersynth_gap_min_s,
                    interval_s=cfg.cybersynth_gap_repeat_interval_s,
                    decay=cfg.cybersynth_gap_repeat_decay,
                )
            # Low-conf DJ trick: duplicate penultimate note to cover missing last.
            if (not trusted) and getattr(cfg, 'cybersynth_sync_delay_on_low_conf', True):
                layer = cyber_synth.repeat_note_throw(
                    layer, cfg.sr, notes,
                    count=cfg.cybersynth_repeat_count,
                    interval_s=cfg.cybersynth_repeat_interval_s,
                    decay=cfg.cybersynth_repeat_decay,
                )
            # De-mud: high-pass the synth so it sits ABOVE the bass/drums, not
            # buried in the low-mid bed (this is why it sounded dull/inaudible).
            layer = cyber_synth.highpass(layer, cfg.sr,
                                         cutoff_hz=getattr(cfg, 'cybersynth_hp_hz', 160.0))
            # CyberLuke2 '4x filter' on the CyberSynth layer too.
            layer = _apply_4x_filter(layer, cfg, request.bpm)
            # Poke-through: brighten the supersaw (harmonic exciter + presence
            # shelf) so the notes sit ABOVE the dense mix instead of under it.
            layer = cyber_synth.brighten(
                layer, cfg.sr,
                drive=getattr(cfg, 'cybersynth_excite_drive', 1.0),
                mix=getattr(cfg, 'cybersynth_excite_mix', 0.5),
                shelf_hz=getattr(cfg, 'cybersynth_presence_hz', 3200.0),
                shelf_db=getattr(cfg, 'cybersynth_presence_db', 8.0),
            )
            # Brickwall: clamp any repeat/drive sum spikes so volume stays flat.
            if getattr(cfg, 'cybersynth_limiter', True):
                layer = cyber_synth.brickwall(
                    layer, threshold=getattr(cfg, 'cybersynth_limiter_threshold', 0.7))
            layer_path = out / f"spr.cybersynth.{t:+d}st.wav"
            sf.write(str(layer_path), layer, cfg.sr)
            # Mix over the CLEAN BACKING (no original synth) so notes poke
            # through; duck the backing a touch under the layer for clarity.
            mix = cyber_synth.mix_layers(
                backing, layer, cfg.original_gain_db,
                cfg.reinforcement_gain_db,
                layer_duck_db=getattr(cfg, 'backing_duck_db', -1.0))
            mix_path = out / f"spr.mix.cybersynth.{t:+d}st.wav"
            sf.write(str(mix_path), mix, cfg.sr)
            result.candidates.append(SPRCandidate(
                flag=SPRFlag.TRANSCRIBED,
                wav_path=str(layer_path),
                mix_wav_path=str(mix_path),
                transpose_semitones=t,
                confidence=conf,
                notes=notes,
                description=f"CyberSynth supersaw melody {t:+d} st (conf={conf:.2f})"
                            + ("" if trusted else " [low-conf]"),
            ))
            result.log.append(
                f"branch1: rendered CyberSynth melody {t:+d} st"
                + ("" if trusted else f" (low conf {conf:.2f})")
            )

    # --- 3) Branch 2: punk fallback (FALLBACK) -------------------------------
    if do_branch2 and (result.branch_used == "" or not notes):
        result.branch_used = "branch2" if result.branch_used == "" else result.branch_used

        # 3a) resample +12 at SAME length (phase vocoder), no gated retrigger
        if cfg.resample_keep_length:
            retriggered = punk.pitch_shift_keep_length(
                other, semitones=cfg.resample_semitones, sr=cfg.sr)
        else:
            res = punk.resample_octave_up(other, semitones=cfg.resample_semitones)
            retriggered = punk.retrigger_on_beats(
                res, orig_len=len(crop), bpm=request.bpm, sr=cfg.sr, bars=request.bars,
            )
        # Malugi metallic highs: tame the +12st shimmer with a gentle LP (synth-
        # shape / oscillator retune), then boost + rhythmic LFO filter wobble.
        retriggered = punk.tone_shape_lp(retriggered, cfg.sr, cutoff_hz=6500.0)
        if getattr(cfg, 'resample_boost_db', 0.0):
            retriggered = (retriggered * float(10.0 ** (cfg.resample_boost_db / 20.0))).astype(np.float32)
        if getattr(cfg, 'resample_lfo_filter', True):
            retriggered = punk.rhythmic_lfo_filter(
                retriggered, cfg.sr, bpm=request.bpm,
                min_hz=cfg.resample_lfo_min_hz, max_hz=cfg.resample_lfo_max_hz,
                cycles_per_beat=1.0 if getattr(cfg, 'resample_lfo_per_beat', True) else 0.5,
            )
        # Soothing flanger so the dry resample layer gets lush movement.
        if getattr(cfg, 'resample_flanger', True):
            wet = min(0.95, cfg.resample_flanger_wet + getattr(cfg, 'resample_flanger_wet_boost', 0.0))
            retriggered = punk.flanger(
                retriggered, cfg.sr, wet=wet,
                rate_hz=cfg.resample_flanger_rate_hz,
                depth_ms=cfg.resample_flanger_depth_ms,
                base_ms=cfg.resample_flanger_base_ms,
                feedback=cfg.resample_flanger_feedback,
            )
        # De-mud the resample too so it isn't swallowed by the low-mid bed.
        retriggered = cyber_synth.highpass(retriggered, cfg.sr, cutoff_hz=140.0)
        # CyberLuke2 '4x filter' on OUR SYNTH layer (slow bar open + 4x fast).
        retriggered = _apply_4x_filter(retriggered, cfg, request.bpm)
        if getattr(cfg, 'cybersynth_limiter', True):
            retriggered = cyber_synth.brickwall(
                retriggered, threshold=getattr(cfg, 'cybersynth_limiter_threshold', 0.7))
        rs_path = out / "spr.resampled.+12st.wav"
        sf.write(str(rs_path), retriggered, cfg.sr)
        mix = cyber_synth.mix_layers(
            backing, retriggered, cfg.original_gain_db,
            cfg.reinforcement_gain_db,
            layer_duck_db=getattr(cfg, 'backing_duck_db', -1.0))
        rs_mix_path = out / "spr.mix.resampled.+12st.wav"
        sf.write(str(rs_mix_path), mix, cfg.sr)
        result.candidates.append(SPRCandidate(
            flag=SPRFlag.RESAMPLED,
            wav_path=str(rs_path),
            mix_wav_path=str(rs_mix_path),
            transpose_semitones=cfg.resample_semitones,
            confidence=conf,
            description="Kontakt-style +12 st resample, retriggered on beats",
        ))
        result.log.append("branch2: resampled +12 st retriggered")

        # 3b) vocoder: modulator = other stem, carrier = distorted saw pad, octave up
        root = request.root_midi if request.root_midi is not None else cfg.vocoder_root_midi
        carrier = punk.saw_pad_carrier(len(other), cfg.sr, root_midi=root)
        voc = punk.vocoder(carrier, other, cfg.sr, bands=cfg.vocoder_bands,
                           attack_ms=cfg.vocoder_attack_ms,
                           release_ms=cfg.vocoder_release_ms,
                           drive=cfg.vocoder_drive)
        # Cleanup: HP >300 Hz (no bass/drums fight) + notch cheap resonances +
        # gentle high de-emphasis (dynamic-EQ-ish).
        voc = punk.vocoder_cleanup(voc, cfg.sr,
                                   highpass_hz=cfg.vocoder_highpass_hz,
                                   notch_hz=cfg.vocoder_notch_hz,
                                   notch_q=cfg.vocoder_notch_q,
                                   deemphasis_hz=cfg.vocoder_deemphasis_hz)
        voc_path = out / "spr.vocoded.wav"
        sf.write(str(voc_path), voc, cfg.sr)
        mix = cyber_synth.mix_layers(
            backing, voc, cfg.original_gain_db,
            cfg.reinforcement_gain_db,
            layer_duck_db=getattr(cfg, 'backing_duck_db', -1.0))
        voc_mix_path = out / "spr.mix.vocoded.wav"
        sf.write(str(voc_mix_path), mix, cfg.sr)
        result.candidates.append(SPRCandidate(
            flag=SPRFlag.VOCODED,
            wav_path=str(voc_path),
            mix_wav_path=str(voc_mix_path),
            confidence=conf,
            description=f"{cfg.vocoder_bands}-band distorted vocoder (root MIDI {root})",
        ))
        result.log.append("branch2: vocoded")



    # --- 4) summary ----------------------------------------------------------
    summary_path = out / "spr.result.json"
    summary = {
        "branch_used": result.branch_used,
        "vocal_bleed": result.vocal_bleed,
        "transcription_confidence": result.transcription_confidence,
        "candidates": [
            {
                "flag": c.flag.value,
                "wav": c.wav_path,
                "mix": c.mix_wav_path,
                "transpose": c.transpose_semitones,
                "confidence": c.confidence,
                "description": c.description,
                "n_notes": len(c.notes),
            }
            for c in result.candidates
        ],
        "log": result.log,
    }
    summary_path.write_text(json.dumps(summary, indent=2))
    result.log.append(f"summary → {summary_path}")
    return result
