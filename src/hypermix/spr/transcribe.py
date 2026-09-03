"""SPR transcription: Basic Pitch → cleaned NoteEvents on the HyperMix beat grid.

Runs INSIDE .venv-stems (basic-pitch pulls tensorflow/onnx + pretty_midi).
Input: isolated 'other' stem WAV. Output: JSON notes on stdout.

The goal is NOT a perfect score — it's a *musically usable* note list for
CyberSynth. So we quantize hard, drop ghost notes, and merge fragments.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

# Import the shared types from the main package — works because both venvs
# have the repo on sys.path when run as `-m src.hypermix.spr.transcribe`.
from .types import NoteEvent, SPRConfig


def basic_pitch_notes(wav_path: str, sr: int = 44100) -> list[NoteEvent]:
    """Run Basic Pitch, return raw NoteEvents (unquantized)."""
    from basic_pitch.inference import predict
    from basic_pitch import ICASSP_2022_MODEL_PATH

    model_output, midi_data, note_events = predict(wav_path, ICASSP_2022_MODEL_PATH)
    # note_events: list of (start_s, end_s, midi, amplitude, bends)
    notes: list[NoteEvent] = []
    for start_s, end_s, midi, amp, bends in note_events:
        if end_s <= start_s:
            continue
        bend_cents = 0.0
        if bends is not None and len(bends) > 0:
            bend_cents = float(np.mean(np.asarray(bends)))
        notes.append(NoteEvent(
            midi=int(midi),
            start_s=float(start_s),
            dur_s=float(end_s - start_s),
            velocity=float(np.clip(amp, 0.0, 1.0)),
            bend_cents=bend_cents,
        ))
    return notes


def quantize_notes(notes: list[NoteEvent], bpm: float, cfg: SPRConfig) -> list[NoteEvent]:
    """Snap to beat grid, drop ghosts, merge repeated fragments."""
    if not notes:
        return []

    # Grid resolution
    grid_map = {"1/8": 0.5, "1/16": 0.25, "1/32": 0.125}
    frac = grid_map.get(cfg.quantize_grid, 0.25)
    beat_s = 60.0 / bpm
    grid_s = beat_s * frac * 4 / 4  # frac is in whole-notes; 1/4 note = beat
    # Simpler: 1/16 note = beat/4
    grid_s = beat_s * ({"1/8": 0.5, "1/16": 0.25, "1/32": 0.125}.get(cfg.quantize_grid, 0.25))

    # 1) Drop ghost notes (very quiet = transcription noise on a synth loop)
    cleaned = [n for n in notes if n.velocity >= cfg.ghost_note_min_vel]

    # 2) Snap starts to grid; keep duration at least one grid cell
    for n in cleaned:
        snapped = round(n.start_s / grid_s) * grid_s
        n.start_s = max(0.0, snapped)
        n.dur_s = max(grid_s, round(n.dur_s / grid_s) * grid_s)

    # 3) Sort + merge same-pitch fragments separated by < merge_gap
    cleaned.sort(key=lambda n: (n.midi, n.start_s))
    merged: list[NoteEvent] = []
    for n in cleaned:
        if merged and n.midi == merged[-1].midi and \
           (n.start_s - (merged[-1].start_s + merged[-1].dur_s)) < cfg.merge_gap_s:
            prev = merged[-1]
            end = max(prev.start_s + prev.dur_s, n.start_s + n.dur_s)
            prev.dur_s = end - prev.start_s
            prev.velocity = max(prev.velocity, n.velocity)
        else:
            merged.append(n)

    # 4) Groove: swing (delay off-8ths) + optional humanize jitter, then RE-SNAP
    #    to the grid so the result is always tight to the beat. Swing>0 gives a
    #    shuffle; humanize adds a tiny live feel but the re-snap keeps the grid.
    swing = float(getattr(cfg, 'quantize_swing', 0.0))
    hum = float(getattr(cfg, 'quantize_humanize_s', 0.0))
    if swing > 0.0 or hum > 0.0:
        eighth_s = beat_s * 0.5
        rng = np.random.default_rng(7)  # deterministic
        for n in merged:
            idx = n.start_s / max(grid_s, 1e-9)
            if swing > 0.0 and int(round(idx)) % 2 == 1:  # off-8th
                n.start_s += swing * (eighth_s * 0.5)  # push up to half an 8th late
            if hum > 0.0:
                n.start_s += float(rng.uniform(-hum, hum))
            # re-snap to grid so it still sits on the beat
            n.start_s = max(0.0, round(n.start_s / grid_s) * grid_s)
        merged.sort(key=lambda n: n.start_s)
    return merged


def transcription_confidence(notes: list[NoteEvent], raw_count: int) -> float:
    """Heuristic 0..1: survival + pitch focus + concurrency bonus.
    - survival: fraction of raw notes kept after cleanup
    - focus: fewer distinct pitches → riff-like (tolerant up to ~24 pitches)
    - concurrency bonus: low average simultaneous notes → cleaner transcription
      (monophonic/duophonic synth loops transcribe more reliably than full pads)
    """
    if raw_count == 0 or not notes:
        return 0.0
    survival = len(notes) / max(1, raw_count)
    distinct = len({n.midi for n in notes})
    # Tolerant focus: ≤4 pitches ≈ 0.83+, ≤8 ≈ 0.71, ≤16 ≈ 0.44, ≥24 → 0
    focus = float(np.clip(1.0 - (distinct - 1) / 23.0, 0.0, 1.0))
    # Average simultaneous notes (crude: mean overlap over note durations)
    if len(notes) > 1:
        total_dur = sum(n.dur_s for n in notes)
        span = max(n.start_s + n.dur_s for n in notes) - min(n.start_s for n in notes)
        avg_concurrency = total_dur / max(span, 1e-6)
    else:
        avg_concurrency = 1.0
    # ≤1.0 concurrency → bonus 1.0; ≥4.0 (full pad) → bonus 0.3
    concurrency_score = float(np.clip(1.0 - (avg_concurrency - 1.0) / 3.0, 0.3, 1.0))
    return float(np.clip(0.4 * survival + 0.3 * focus + 0.3 * concurrency_score, 0.0, 1.0))


def main() -> int:
    p = argparse.ArgumentParser(description="SPR transcribe: Basic Pitch → quantized notes JSON")
    p.add_argument("--wav", required=True, help="isolated 'other' stem WAV")
    p.add_argument("--bpm", type=float, required=True)
    p.add_argument("--out", required=True, help="output JSON for notes")
    p.add_argument("--quantize-grid", default="1/16")
    p.add_argument("--ghost-min-vel", type=float, default=0.15)
    p.add_argument("--swing", type=float, default=0.0)
    p.add_argument("--humanize-s", type=float, default=0.0)
    p.add_argument("--sr", type=int, default=44100)
    args = p.parse_args()

    cfg = SPRConfig(quantize_grid=args.quantize_grid,
                    ghost_note_min_vel=args.ghost_min_vel,
                    quantize_swing=args.swing,
                    quantize_humanize_s=args.humanize_s)

    raw = basic_pitch_notes(args.wav, sr=args.sr)
    quantized = quantize_notes([NoteEvent(**vars(n)) for n in raw], bpm=args.bpm, cfg=cfg)
    conf = transcription_confidence(quantized, raw_count=len(raw))

    payload = {
        "ok": True,
        "wav": str(Path(args.wav).resolve()),
        "raw_count": len(raw),
        "kept_count": len(quantized),
        "confidence": round(conf, 4),
        "notes": [vars(n) for n in quantized],
    }
    Path(args.out).write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
