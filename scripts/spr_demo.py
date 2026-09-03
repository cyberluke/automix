"""SPR demo — Branch 1 (CyberSynth) + Branch 2 (punk fallback) end-to-end.

Skips the .venv-stems boundary (no Demucs/Basic Pitch needed) by injecting a
hand-written neurofunk riff. Use this to HEAR the CyberSynth + fallback output
immediately, while the heavy transcription deps install.

Run:
    .\\.venv-hypermix\\Scripts\\python.exe scripts/spr_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.hypermix.spr.types import SPRRequest, SPRConfig, NoteEvent, SPRCandidate, SPRFlag
from src.hypermix.spr import cyber_synth, punk
from src.hypermix.spr.pipeline import choose_transpositions


def neurofunk_riff(bpm: float = 174.0) -> list[NoteEvent]:
    """A2-based minor riff, 16th-note grid, 2 bars."""
    beat = 60.0 / bpm          # 0.345 s
    sixteenth = beat / 4.0     # 0.086 s
    # A2=45, C3=48, G2=43, D#3=51 (minor color)
    pat = [
        (45, 0), (45, 1), (48, 2), (45, 3),
        (43, 4), (43, 5), (45, 6), (51, 7),
        (45, 8), (45, 9), (48, 10), (45, 11),
        (43, 12), (43, 13), (45, 14), (45, 15),
    ]
    return [
        NoteEvent(midi=m, start_s=i * sixteenth, dur_s=sixteenth * 0.95, velocity=0.9)
        for m, i in pat
    ]


def main() -> int:
    out = Path("renders/spr-demo")
    out.mkdir(parents=True, exist_ok=True)
    cfg = SPRConfig()
    bpm = 174.0
    notes = neurofunk_riff(bpm)

    print(f"SPR demo — {len(notes)} notes @ {bpm} BPM")
    print(f"  grid: {cfg.quantize_grid}  voices: {cfg.supersaw_voices}  detune: ±{cfg.supersaw_detune_cents}c")

    # Branch 1: CyberSynth with key-aware transpositions
    req = SPRRequest(source_wav="(synth)", start_s=0.0, bars=2, bpm=bpm, root_midi=45, scale="minor")
    trans = choose_transpositions(req, cfg, notes)
    print(f"  key-aware transpositions (root A2, minor): {trans}")

    for t in trans:
        layer = cyber_synth.render_notes(notes, cfg, transpose_semitones=t)
        p = out / f"branch1.cybersynth.{t:+d}st.wav"
        sf.write(str(p), layer, cfg.sr)
        print(f"  ✓ Branch 1  {p.name}  ({len(layer)/cfg.sr:.2f}s, peak {float(np.max(np.abs(layer))):.3f})")

    # Branch 2: punk fallback on the *rendered* riff as a stand-in stem
    dry = cyber_synth.render_notes(notes, cfg, transpose_semitones=0)
    rs = punk.resample_octave_up(dry, semitones=cfg.resample_semitones)
    rt = punk.retrigger_on_beats(rs, orig_len=len(dry), bpm=bpm, sr=cfg.sr, bars=2)
    p = out / f"branch2.resampled.{cfg.resample_semitones:+d}st.wav"
    sf.write(str(p), rt, cfg.sr)
    print(f"  ✓ Branch 2  {p.name}  ({len(rt)/cfg.sr:.2f}s)")

    carrier = punk.saw_pad_carrier(len(dry), cfg.sr, root_midi=45)
    voc = punk.vocoder(carrier, dry, cfg.sr, bands=cfg.vocoder_bands)
    p = out / "branch2.vocoded.wav"
    sf.write(str(p), voc, cfg.sr)
    print(f"  ✓ Branch 2  {p.name}  ({len(voc)/cfg.sr:.2f}s)")

    # Preview mix: original + +12 CyberSynth at design-contract gains
    layer12 = cyber_synth.render_notes(notes, cfg, transpose_semitones=12)
    mix = cyber_synth.mix_layers(dry, layer12, cfg.original_gain_db, cfg.reinforcement_gain_db)
    p = out / "preview.mix.original+cybersynth+12.wav"
    sf.write(str(p), mix, cfg.sr)
    print(f"  ✓ preview   {p.name}  ({cfg.original_gain_db} dB orig / {cfg.reinforcement_gain_db} dB layer)")

    print(f"\nAll outputs in {out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
