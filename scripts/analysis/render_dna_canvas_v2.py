"""Render the phrase-native, deterministic MixShow DNA v2 edit.

The render script is intentionally thin. HyperMix owns producer know-how in
`src.hypermix.dna.designer` and `src.hypermix.dna.effect_vocabulary`; this
script loads the canvas, asks the engine to design the phrase recipe, renders
it, and writes the audit trace.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, '.')
from src.hypermix.dna import design_phrase_dna
from src.hypermix.dna.designer import extended_features
from src.hypermix.dna.engine import apply_recipe
from src.hypermix.dna.recipe import save_recipe

BASE = Path('renders/malugi-phrases/malugi.canvas.dup16.121s.wav')
OUT = Path('renders/malugi-phrases/malugi.dna.mixshow_v2.wav')
TRACE = Path('data/dna_recipes/malugi_mixshow_v2_trace.json')
RECIPE_NAME = 'malugi_mixshow_v2'
DNA_VERSION = RECIPE_NAME
PHRASE_BARS = 8


def separate_canvas_stems(audio: np.ndarray, sr: int) -> dict:
    """Run Demucs in the stem environment and return aligned full-canvas stems."""
    tmp = Path('renders/malugi-phrases/_canvas_v2.wav')
    bass_path = Path(str(tmp) + '.bass.wav')
    vocals_path = Path(str(tmp) + '.vocals.wav')
    sf.write(str(tmp), audio.astype(np.float32), sr)
    helper = (
        "import sys; sys.path.insert(0,'.');"
        "import soundfile as sf;"
        "from src.hypermix.spr.isolate import demucs_all_stems;"
        "y,sr=sf.read(sys.argv[1],dtype='float32',always_2d=True);"
        "st=demucs_all_stems(y,sr);"
        "sf.write(sys.argv[2],st['bass'],sr);"
        "sf.write(sys.argv[3],st['vocals'],sr)"
    )
    subprocess.run([
        '.venv-stems/Scripts/python.exe', '-W', 'ignore', '-c', helper,
        str(tmp), str(bass_path), str(vocals_path),
    ], check=True)
    bass, _ = sf.read(str(bass_path), dtype='float32', always_2d=True)
    vocals, _ = sf.read(str(vocals_path), dtype='float32', always_2d=True)
    n = len(audio)
    aligned = {}
    for name, stem in (('bass', bass), ('vocals', vocals)):
        aligned[name] = np.pad(stem[:n], ((0, max(0, n - len(stem))), (0, 0)))[:n]
    return aligned


def measure_phrase_delta(before: np.ndarray, after: np.ndarray, sr: int,
                         bpm: float, phrase_index: int) -> dict:
    before_f = extended_features(before, sr, bpm, None, 0.0)
    after_f = extended_features(after, sr, bpm, None, 0.0)
    return {
        'phrase_index': phrase_index,
        'rms_delta': after_f['loudness']['rms'] - before_f['loudness']['rms'],
        'lufs_delta': after_f['lufs'] - before_f['lufs'],
        'spectral_centroid_delta': (
            after_f['spectral']['centroid_mean'] -
            before_f['spectral']['centroid_mean']),
        'bass_ratio_delta': (
            after_f['spectral']['bass_ratio'] -
            before_f['spectral']['bass_ratio']),
        'stereo_correlation_delta': (
            after_f['stereo_correlation'] -
            before_f['stereo_correlation']),
    }


def build_trace(rows: list[dict], source_hash: str, sr: int,
                bpm: float) -> dict:
    return {
        'name': RECIPE_NAME,
        'source': str(BASE),
        'source_track_hash': f'sha256:{source_hash}',
        'dna_version': DNA_VERSION,
        'deterministic_seed_context': f'{source_hash}|phrase_index|{DNA_VERSION}',
        'analysis': {
            'phrase_bars': PHRASE_BARS,
            'phrase_count': len(rows),
            'sample_rate': sr,
            'bpm': bpm,
            'feature_vectors': rows,
        },
        'formalized_engine': {
            'module': 'src.hypermix.dna.designer',
            'vocabulary': 'src.hypermix.dna.effect_vocabulary',
            'api': 'design_phrase_dna(audio, sr, bpm, track_hash, recipe_name)',
        },
        'new_deterministic_rules': [
            'low novelty plus high transient density permits a rhythmic mutation',
            'positive RMS/flux trajectory permits a filter build at the boundary',
            'bass/reese dominance permits a bass spotlight only when vocal collision is low',
            'MS-20 filter questions receive a short horn sample answer at the next phrase boundary',
            'spectral mutations preserve at least half of the original groove energy',
            'the previous two selected techniques receive a diversity penalty',
        ],
    }


def main(dry_run: bool = False) -> None:
    audio, sr = sf.read(str(BASE), dtype='float32', always_2d=True)
    bpm = 144.23076923076923
    source_hash = hashlib.sha256(BASE.read_bytes()).hexdigest()
    recipe, rows = design_phrase_dna(
        audio, sr, bpm,
        track_hash=source_hash,
        recipe_name=RECIPE_NAME,
        phrase_bars=PHRASE_BARS,
    )
    trace = build_trace(rows, source_hash, sr, bpm)
    TRACE.write_text(
        json.dumps(trace, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )
    save_recipe(recipe)
    if dry_run:
        print(json.dumps([
            (r['phrase_index'], r['selected_edit'],
             next(c['scores']['total'] for c in r['candidate_edits']
                  if c['id'] == r['selected_edit']))
            for r in rows
        ], indent=2))
        return
    stems = separate_canvas_stems(audio, sr)
    out = apply_recipe(recipe, audio, sr, bpm=bpm, stems=stems)
    peak = float(np.max(np.abs(out)))
    if peak > 0.98:
        out *= np.float32(0.98 / peak)
    sf.write(str(OUT), out.astype(np.float32), sr)
    spb = sr * 60.0 / bpm
    phrase_samples = int(round(PHRASE_BARS * 4.0 * spb))
    for row in rows:
        i0 = row['phrase_index'] * phrase_samples
        i1 = min(len(audio), i0 + phrase_samples)
        row['measured_post_edit_change'] = measure_phrase_delta(
            audio[i0:i1], out[i0:i1], sr, bpm, row['phrase_index'])
    trace['render'] = {
        'base': str(BASE),
        'output': str(OUT),
        'sample_rate': sr,
        'duration_seconds': len(out) / sr,
        'added_steps': recipe.to_dict()['steps'],
        'peak': float(np.max(np.abs(out))),
    }
    TRACE.write_text(
        json.dumps(trace, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )
    print(f'peak {np.max(np.abs(out)):.3f} dur {len(out) / sr:.3f}s -> {OUT.resolve()}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    main(dry_run=parser.parse_args().dry_run)
