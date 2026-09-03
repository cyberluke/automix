"""Render the golden playlist: exact Malugi 64-bar opening, then local tracks."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, '.')
from src.hypermix.canonicalize import Canonicalizer
from src.hypermix.config import DEFAULT_CONFIG
from src.hypermix.dna import design_phrase_dna
from src.hypermix.dna.engine import apply_recipe
from src.hypermix.dna.recipe import load_recipe
from src.hypermix.audio_io import read_wav

MUSIC = Path('music')
OPENING = Path('renders/malugi-phrases/malugi.segment64.bar103.108s.wav')
OUT = Path('renders/malugi-phrases/malugi.golden.playlist.wav')
TRACE = Path('data/dna_recipes/malugi_golden_playlist_trace.json')
BPM = 144.23076923076923
SR = 48000
CROSSFADE_BARS = 8


def canonical_audio(path: Path) -> tuple[np.ndarray, int, Path]:
    c = Canonicalizer(DEFAULT_CONFIG)
    result = c.canonicalize(path, c.default_private_root())
    audio = read_wav(result.canonical_path)
    return audio.samples.astype(np.float32), audio.sample_rate, Path(result.canonical_path)


def load_stems(audio: np.ndarray, sr: int, label: str) -> dict:
    tmp = Path('renders/malugi-phrases') / f'_golden_{label}.wav'
    sf.write(str(tmp), audio, sr)
    bass_path = Path(str(tmp) + '.bass.wav')
    vocals_path = Path(str(tmp) + '.vocals.wav')
    helper = (
        "import sys,soundfile as sf; sys.path.insert(0,'.');"
        "from src.hypermix.spr.isolate import demucs_all_stems;"
        "y,s=sf.read(sys.argv[1],dtype='float32',always_2d=True);"
        "x=demucs_all_stems(y,s);sf.write(sys.argv[2],x['bass'],s);sf.write(sys.argv[3],x['vocals'],s)"
    )
    subprocess.run(['.venv-stems/Scripts/python.exe', '-W', 'ignore', '-c', helper,
                    str(tmp), str(bass_path), str(vocals_path)], check=True)
    stems = {}
    for name, path in [('bass', bass_path), ('vocals', vocals_path)]:
        value, _ = sf.read(str(path), dtype='float32', always_2d=True)
        stems[name] = np.pad(value[:len(audio)],
                              ((0, max(0, len(audio) - len(value))), (0, 0)))[:len(audio)]
    return stems


def process_track(audio: np.ndarray, sr: int, name: str, use_stems: bool) -> tuple[np.ndarray, dict]:
    track_hash = hashlib.sha256(audio.tobytes()).hexdigest()
    recipe, rows = design_phrase_dna(audio, sr, BPM, track_hash, name, phrase_bars=8)
    stems = load_stems(audio, sr, name) if use_stems else None
    return apply_recipe(recipe, audio, sr, bpm=BPM, stems=stems), {
        'name': name,
        'selected': [(r['phrase_index'], r['selected_edit']) for r in rows],
        'recipe_steps': recipe.to_dict()['steps'],
    }


def crossfade(left: np.ndarray, right: np.ndarray, n: int) -> np.ndarray:
    n = min(n, len(left), len(right))
    if n <= 0:
        return np.concatenate([left, right], axis=0)
    t = np.linspace(0.0, np.pi / 2.0, n, dtype=np.float32)
    out = np.concatenate([left[:-n], left[-n:] * np.cos(t)[:, None] +
                          right[:n] * np.sin(t)[:, None], right[n:]], axis=0)
    return out.astype(np.float32)


def main() -> None:
    opening, opening_sr = sf.read(str(OPENING), dtype='float32', always_2d=True)
    if opening_sr != SR:
        raise ValueError(f'opening must be {SR} Hz, got {opening_sr}')
    # The first 64 bars are the exact selected Malugi segment, processed by the
    # saved profile. New autonomous decisions begin only on later tracks.
    opening_recipe = load_recipe('malugi_dna_polished_v1')
    opening_processed = apply_recipe(
        opening_recipe, opening, SR, bpm=BPM,
        stems=load_stems(opening, SR, 'malugi_opening64'),
    )
    opening_meta = {
        'name': 'malugi_opening64',
        'profile': 'malugi_dna_polished_v1',
        'selected_segment': 'bar 103, 64 bars',
        'recipe_steps': opening_recipe.to_dict()['steps'],
    }
    tracks = [p for p in sorted(MUSIC.iterdir(), key=lambda p: p.name.lower())
              if p.suffix.lower() in {'.mp4', '.wav', '.mp3', '.flac'}
              and p.name != 'Malugi MCYL - Knees Break.mp4']
    output = opening_processed
    trace = {'opening': str(OPENING), 'opening_bars': 64,
             'tracks': [opening_meta], 'crossfade_bars': CROSSFADE_BARS}
    crossfade_n = int(round(CROSSFADE_BARS * 4.0 * SR * 60.0 / BPM))
    for index, path in enumerate(tracks, 1):
        audio, source_sr, canonical = canonical_audio(path)
        if source_sr != SR:
            raise ValueError(f'{path} canonicalized to {source_sr} Hz')
        processed, meta = process_track(audio, SR, f'track_{index}_{path.stem}', False)
        output = crossfade(output, processed, crossfade_n)
        meta['source'] = str(path)
        meta['canonical'] = str(canonical)
        trace['tracks'].append(meta)
        print(f'added {index}/{len(tracks)} {path.name}')
    peak = float(np.max(np.abs(output)))
    if peak > 0.98:
        output *= np.float32(0.98 / peak)
    sf.write(str(OUT), output.astype(np.float32), SR)
    trace['render'] = {'output': str(OUT), 'duration_seconds': len(output) / SR,
                       'sample_rate': SR, 'peak': float(np.max(np.abs(output)))}
    TRACE.write_text(json.dumps(trace, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('peak %.3f dur %.3fs -> %s' % (np.max(np.abs(output)), len(output) / SR, OUT.resolve()))


if __name__ == '__main__':
    main()