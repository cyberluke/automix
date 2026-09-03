"""Render the golden Malugi hybrid: locked DNA first, autonomous engine after it."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, '.')
from src.hypermix.dna import design_phrase_dna
from src.hypermix.dna.engine import apply_recipe
from src.hypermix.dna.recipe import (
    OperatorCall, ProducerRecipe, RecipeStep, load_recipe, save_recipe,
)
from src.hypermix.audio_io import read_wav
from src.hypermix.canonicalize import Canonicalizer
from src.hypermix.config import DEFAULT_CONFIG

TRACK = Path('music/Malugi MCYL - Knees Break.mp4')
BASE = Path('renders/malugi-phrases/malugi.canvas.dup16.121s.wav')
OUT = Path('renders/malugi-phrases/malugi.golden.hybrid.wav')
RECIPE_NAME = 'malugi_golden_hybrid'
PROFILE_NAME = 'malugi_dna_polished_v1'
BPM = 144.23076923076923
LOCKED_BARS = 40.0
PHRASE_BARS = 8


def separate_stems(audio: np.ndarray, sr: int) -> dict:
    tmp = Path('renders/malugi-phrases/_canvas_golden_hybrid.wav')
    bass_path = Path(str(tmp) + '.bass.wav')
    vocals_path = Path(str(tmp) + '.vocals.wav')
    sf.write(str(tmp), audio.astype(np.float32), sr)
    helper = (
        "import sys; sys.path.insert(0,'.');"
        "import soundfile as sf;"
        "from src.hypermix.spr.isolate import demucs_all_stems;"
        "y,sr=sf.read(sys.argv[1],dtype='float32',always_2d=True);"
        "st=demucs_all_stems(y,sr);"
        "sf.write(sys.argv[2],st['bass'],sr); sf.write(sys.argv[3],st['vocals'],sr)"
    )
    subprocess.run([
        '.venv-stems/Scripts/python.exe', '-W', 'ignore', '-c', helper,
        str(tmp), str(bass_path), str(vocals_path),
    ], check=True)
    stems = {}
    for name, path in (('bass', bass_path), ('vocals', vocals_path)):
        value, _ = sf.read(str(path), dtype='float32', always_2d=True)
        stems[name] = np.pad(
            value[:len(audio)], ((0, max(0, len(audio) - len(value))), (0, 0))
        )[:len(audio)]
    return stems


def shifted_autonomous_recipe(audio: np.ndarray, sr: int,
                              source_path: Path) -> tuple[ProducerRecipe, list[dict]]:
    track_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    designed, rows = design_phrase_dna(
        audio, sr, BPM, track_hash=track_hash,
        recipe_name=RECIPE_NAME, phrase_bars=PHRASE_BARS,
    )
    autonomous = []
    for row in rows:
        phrase_start = row['phrase_index'] * PHRASE_BARS
        if phrase_start < LOCKED_BARS:
            continue
        autonomous.append(row)
    recipe = ProducerRecipe(
        name=RECIPE_NAME, phrase_bars=LOCKED_BARS + PHRASE_BARS,
        bpm_ref=BPM, note='golden hybrid: locked polished DNA then autonomous HyperMix',
        description=[
            'Bars 0-40 are locked to malugi_dna_polished_v1.',
            'Bars 40+ are selected deterministically by HyperMix DNA designer.',
            'Autonomous phrase positions are shifted into the full canvas timeline.',
        ],
        principles={
            'locked_profile': PROFILE_NAME,
            'locked_bars': LOCKED_BARS,
            'autonomous_phrase_bars': PHRASE_BARS,
            'selection_seed': track_hash,
        },
    )
    for step in designed.steps:
        if step.bar >= LOCKED_BARS:
            recipe.add(step)
    return recipe, autonomous


def main() -> None:
    canonicalizer = Canonicalizer(DEFAULT_CONFIG)
    source = canonicalizer.canonicalize(TRACK, canonicalizer.default_private_root())
    source_path = Path(source.canonical_path)
    source_audio = read_wav(source_path)
    audio, sr = source_audio.samples.astype(np.float32), source_audio.sample_rate
    locked = load_recipe(PROFILE_NAME)
    auto_recipe, rows = shifted_autonomous_recipe(audio, sr, source_path)
    hybrid = ProducerRecipe(
        name=RECIPE_NAME, phrase_bars=auto_recipe.phrase_bars,
        bpm_ref=BPM, note=auto_recipe.note,
        description=auto_recipe.description,
        principles=auto_recipe.principles,
    )
    for step in locked.steps:
        if step.bar < LOCKED_BARS:
            hybrid.add(RecipeStep(
                id=f'locked_{step.id}', bar=step.bar, beat=step.beat,
                span_bars=step.span_bars, when_role=step.when_role,
                call=OperatorCall(step.call.op, dict(step.call.params)),
                note=f'locked {PROFILE_NAME}: {step.note}',
            ))
    for step in auto_recipe.steps:
        hybrid.add(step)
    save_recipe(hybrid)
    stems = separate_stems(audio, sr)
    out = apply_recipe(hybrid, audio, sr, bpm=BPM, stems=stems)
    peak = float(np.max(np.abs(out)))
    if peak > 0.98:
        out *= np.float32(0.98 / peak)
    sf.write(str(OUT), out.astype(np.float32), sr)
    trace = {
        'name': RECIPE_NAME,
        'source': str(source_path),
        'profile_first': PROFILE_NAME,
        'locked_bars': LOCKED_BARS,
        'autonomous_phrase_bars': PHRASE_BARS,
        'autonomous_rows': rows,
        'recipe': hybrid.to_dict(),
        'render': {'output': str(OUT), 'sample_rate': sr,
                   'duration_seconds': len(out) / sr, 'peak': float(np.max(np.abs(out)))},
    }
    Path('data/dna_recipes/malugi_golden_hybrid_trace.json').write_text(
        json.dumps(trace, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('peak %.3f dur %.3fs -> %s' % (np.max(np.abs(out)), len(out) / sr, OUT.resolve()))
    print('locked bars 0-%.0f; autonomous bars %.0f+' % (LOCKED_BARS, LOCKED_BARS))
    print('autonomous selection', [(r['phrase_index'], r['selected_edit']) for r in rows])


if __name__ == '__main__':
    main()