"""Golden render: a forced DNA-treated opening, then the real DeepMixDirector.

The director chooses the continuation from the pack's phrase graph. The
deterministic `GoldenRenderer` applies graph-edge transitions and keeps its
programmatic DSP. A caller-supplied DNA recipe is applied only to the opening
segment. All parameters are dataset-independent — point `PACK` at your own pack.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, '.')
from src.hypermix.audio_io import read_wav
from src.hypermix.compiler.deterministic_render import GoldenRenderer
from src.hypermix.compiler.set_compiler import SetPlan, SetStep
from src.hypermix.director.deep_selector import DeepMixDirector
from src.hypermix.director.graph import MixGraph
from src.hypermix.dna.engine import apply_recipe
from src.hypermix.dna.recipe import load_recipe
from src.hypermix.goldenrun import (
    _phrase_energy_gradient, _segment_level, _spectral_features,
)
from src.hypermix.model import Segment, TransitionEdge

PACK = Path('packs/my-library')          # your phrase pack (must be populated)
OUT_DIR = Path('renders/my-mix')         # output directory
OUT = OUT_DIR / 'golden.wav'
TRACE = OUT_DIR / 'golden.trace.json'
SEED = 7                                 # selection determinism
SR = 48000                               # sample rate
TARGET_BARS = 64                         # phrase-section length (bars)
# CONTENT-AWARE TRUNCATION: for a vocal-first golden mix, a fixed 64-bar cut
# often leaves a trailing "beat-only, no vocals" tail in each phrase. We trim
# each phrase to end right after the last musically-engaged (vocal/content)
# moment, snapped to a bar boundary, so the mix stays tight and engaging.
CONTENT_TRIM = True                      # master switch
CONTENT_MIN_BARS = 32                    # never cut a phrase shorter than this
CONTENT_ACTIVITY_THRESH = 0.45           # rel. to phrase peak activity to count
CONTENT_MIN_RUN_BARS = 8                 # min length of a sustained vocal run
CONTENT_OUTLIER_QUIET = 4                # allow up to this many quiet bars tail
OPENING_END_S = 53.0                     # trim the opening track to this many s
# DNA recipe applied to the opening segment (a file in data/dna_recipes/).
OPENING_RECIPE = 'my_dna_v1'
# BPM used to resolve the opening recipe's bar/beat steps (from your opening).
OPENING_BPM = 128.0

# --- fire-and-forget pack build (only rebuilds when music/ changes) ---------
# music/ folder whose tracks feed the pack; a crate + pack are generated from
# it. If this folder is unchanged since the last build, we skip the rebuild and
# render the existing pack (no wasted analysis).
MUSIC_DIR = Path('music')
CRATE_ID = 'my-library'
CRATE_FILE = Path(f'crates/{CRATE_ID}/crate.json')
_CRATE_FOLDER_SCRIPT = Path('scripts/crate_from_folder.py')
# Sidecar manifest next to the pack recording the music snapshot we built from.
MANIFEST_FILE = PACK / '.source-manifest.json'
# Pack build dir must exist before writing the manifest beside it.
BUILD_ARGS = ['--cues-per-track', '3', '--phrase-bars', '8',
              '--techniques', 'phrase_match,echo_cut,slam,backspin,drum_roll,'
                              'loop_transition,stutter,power_up,power_down,rewind',
              '--fallback', 'rewind']


def _music_snapshot() -> dict:
    """Cheap change fingerprint of the source tracks: (path, size, mtime)."""
    rec = {}
    if MUSIC_DIR.is_dir():
        for p in sorted(MUSIC_DIR.rglob('*')):
            if p.is_file() and p.name.lower() != '.gitkeep':
                st = p.stat()
                rec[p.as_posix()] = [st.st_size, int(st.st_mtime)]
    return {'files': rec}


def _needs_build() -> bool:
    """Rebuild the pack iff we've never built it or the music folder changed."""
    if not (PACK / 'graph' / 'graph.json').exists():
        return True
    if not MANIFEST_FILE.exists():
        return True
    try:
        prev = json.loads(MANIFEST_FILE.read_text(encoding='utf-8'))
        return prev.get('files') != _music_snapshot()['files']
    except Exception:
        return True


def _build_pack() -> None:
    """Generate crate + pack from music/ (delegates to crate_from_folder)."""
    import subprocess
    CRATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(_CRATE_FOLDER_SCRIPT),
           '--music-dir', str(MUSIC_DIR), '--out', str(CRATE_FILE),
           '--crate-id', CRATE_ID, '--name', CRATE_ID.replace('-', ' ').title(),
           '--compile', '--pack-out', str(PACK)] + BUILD_ARGS
    proc = subprocess.run(cmd, cwd=str(Path(__file__).resolve().parent.parent.parent),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError('pack build failed:\n' + (proc.stdout or proc.stderr))
    PACK.mkdir(parents=True, exist_ok=True)
    MANIFEST_FILE.write_text(json.dumps(_music_snapshot(), indent=2), encoding='utf-8')


def _block_content_activity(samples: np.ndarray, sr: int,
                            start: int, end: int) -> float:
    """Content activity (0..1) of a sample window: how much musical 'foreground'
    (vocals/synth/hat top-end) is present vs an empty beat bed. High when the
    vocal/mid band carries energy AND the band is rhythmically self-modulating
    (real content, not a steady pad or pure kick+bass). Deterministic."""
    mono = samples.mean(axis=1) if samples.ndim > 1 else samples
    seg = mono[start:end].astype(np.float32)
    if len(seg) < 2048:
        return 0.0
    try:
        import librosa
        S = np.abs(librosa.stft(seg, n_fft=2048, hop_length=512))
        power = (S ** 2)
        freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
        tot = power.sum(axis=0) + 1e-9
        m = (freqs >= 300.0) & (freqs < 3400.0)   # vocal/formant region
        vb = power[m].sum(axis=0) / tot
        share = float(np.clip(vb.mean() / 0.28, 0.0, 1.0))       # vs vocal share
        mod = float(np.clip(vb.std() / (vb.mean() + 1e-9), 0.0, 1.0))
        return float(np.clip(share * (0.4 + 0.6 * mod), 0.0, 1.0))
    except Exception:
        return 0.0


def _per_bar_activity(samples: np.ndarray, sr: int, bpm: float,
                      max_bars: int) -> np.ndarray:
    """Vocal/content activity per bar (bar = 4 beats). Returns an array of
    length <= max_bars of 0..1 values, cached-style per call (deterministic).
    The 16-bar compose frame in _content_length still applies; here we resolve
    at bar granularity so the final cut isn't forced onto a coarse 16-bar grid
    (which could slit a vocal phrase mid-musical-thought)."""
    mono = samples.mean(axis=1) if samples.ndim > 1 else samples
    n = mono.shape[0]
    spb = sr * 60.0 / float(bpm)
    import numpy as np
    out = np.zeros(max_bars, dtype=np.float32)
    for k in range(max_bars):
        s0 = int(k * 4.0 * spb)
        s1 = int((k + 1) * 4.0 * spb)
        if s0 >= n:
            break
        out[k] = _block_content_activity(samples, sr, s0, min(s1, n))
    return out


def _content_length(samples: np.ndarray, sr: int, bpm: float,
                    max_samples: int, block_bars: int = 16) -> int:
    """Phrase-aligned truncation (Návrh A). Uses the 16-bar compose frame only
    to cap total length (64 bars), then resolves the cut at BAR precision so a
    phrase ends right after its LAST SUSTAINED vocal/content section decays —
    not on a coarse 16-bar line (which can slit a vocal mid-thought) and not
    fooled by an isolated 1-bar vocal outro at the very end of the segment.

    Logic: per-bar vocal activity, smoothed; mark bars >= threshold as 'vocal';
    find the last CONTIGUOUS run of vocal bars (>= CONTENT_MIN_RUN_BARS, so a
    lone end-of-segment outro hit doesn't read as a song that stays vocal to
    the end); then cut one bar after that run ends so the phrase decays
    naturally. Floored to CONTENT_MIN_BARS, capped at max_samples. If there is
    no such clean run WITH a real quiet outro after it, keep the full length.
    """
    if not CONTENT_TRIM or bpm <= 0:
        return max_samples
    n = samples.shape[0]
    spb = sr * 60.0 / float(bpm)
    bar_n = int(round(4.0 * spb))
    if bar_n < 1:
        return max_samples
    # 16-bar compose frame: cap total bars (64-bar ceiling).
    block_n = int(round(block_bars * 4.0 * spb))
    if block_n < 1:
        return max_samples
    cap_bars = min(int(max_samples // bar_n), int(n // bar_n))
    if cap_bars <= 1:
        return max_samples
    acts = _per_bar_activity(samples, sr, bpm, cap_bars)
    # Smooth over a small window to ignore one-bar dips (breakdown hiccups).
    w = min(3, len(acts))
    sm = np.convolve(acts, np.ones(w, dtype=np.float32) / w, mode="same") \
        if w > 1 else acts
    peak = float(sm.max())
    if peak <= 1e-6:
        return max_samples
    thresh = CONTENT_ACTIVITY_THRESH * peak
    vocal = sm >= thresh
    # Find contiguous vocal runs; keep only runs of meaningful length.
    runs = []
    i = 0
    while i < len(vocal):
        if vocal[i]:
            j = i
            while j < len(vocal) and vocal[j]:
                j += 1
            runs.append((i, j - 1))  # inclusive bar range
            i = j
        else:
            i += 1
    if not runs:
        return max_samples
    # The last sustained (>= CONTENT_MIN_RUN_BARS) run is our musical section.
    long_runs = [r for r in runs if (r[1] - r[0] + 1) >= CONTENT_MIN_RUN_BARS]
    last_run = long_runs[-1] if long_runs else runs[-1]
    last_vocal_bar = last_run[1]
    # A real quiet outro must follow this run (the tail stays below thr).
    tail = sm[last_vocal_bar + 1:]
    if len(tail) == 0:
        return max_samples
    quiet_tail = float(np.mean(tail)) < thresh
    if not quiet_tail:
        return max_samples
    # Cut one bar after the last vocal bar so the phrase decays naturally,
    # floored to CONTENT_MIN_BARS, capped to the 64-bar frame.
    cut_bars = min(cap_bars, last_vocal_bar + 2)
    cut_bars = max(cut_bars, CONTENT_MIN_BARS)
    return min(n, max_samples, cut_bars * bar_n)


def load_pack():
    seg_doc = json.loads((PACK / 'graph/segments.json').read_text(encoding='utf-8'))
    edge_doc = json.loads((PACK / 'graph/edges.json').read_text(encoding='utf-8'))
    graph_doc = json.loads((PACK / 'graph/graph.json').read_text(encoding='utf-8'))
    segments = {s['id']: Segment.from_dict(s) for s in seg_doc['segments']}
    edges = {e['id']: TransitionEdge.from_dict(e) for e in edge_doc['edges']}
    graph = MixGraph(segments=segments, edges=edges,
                     adjacency=graph_doc['adjacency'],
                     entry_segments=graph_doc['entrySegments'],
                     fallback_transition=graph_doc['fallbackTransition'])
    audio = {sid: read_wav(PACK / seg.asset) for sid, seg in segments.items()}
    audio.update({eid: read_wav(PACK / edge.asset) for eid, edge in edges.items()})
    return graph, graph_doc, segments, edges, audio


def build_plan(graph, graph_doc, segments, audio):
    keys, energy, levels, specs, raw = {}, {}, {}, {}, {}
    from src.hypermix.analysis.phrase_key import detect_key
    from src.hypermix.analysis.phrase_features import extract_phrase_features
    for sid, seg in segments.items():
        a = audio[sid]
        try:
            keys[sid] = detect_key(a.samples, a.sample_rate)['camelot']
        except Exception:
            keys[sid] = ''
        energy[sid] = _phrase_energy_gradient(a.samples, a.sample_rate)
        raw[sid] = _segment_level(a.samples)
        try:
            specs[sid] = extract_phrase_features(a.samples, a.sample_rate, seg.bpm or 128.0)
        except Exception:
            specs[sid] = _spectral_features(a.samples, a.sample_rate)
    ref = float(np.percentile(list(raw.values()), 95)) or 1e-9
    levels = {sid: max(0.0, min(1.0, value / ref)) for sid, value in raw.items()}
    director = DeepMixDirector(
        graph, seed=SEED, mode='deterministic', target_bars=TARGET_BARS,
        seg_keys=keys, seg_energy=energy, seg_level=levels, seg_spec=specs,
        harmonic_arc=True,
    )
    # Forced opening: use the pack's first entry segment (dataset-independent).
    entry_id = graph.entry_segments[0] if graph.entry_segments else next(
        iter(segments))
    opening = segments[entry_id]
    plan = SetPlan(seed=SEED)
    first_length = min(len(audio[opening.id].samples),
                       int(round(OPENING_END_S * SR)))
    plan.steps.append(SetStep(opening.id, None, None, 0, first_length))
    current = opening.id
    for _ in range(15):
        nxt = director.advance(current)
        if nxt is None:
            break
        edge = graph.edge_between(current, nxt.id)
        full_len = nxt.end_sample - nxt.start_sample
        # Compose phrase length from whole 16-bar blocks (content-aware): the
        # 64-bar cap, then close that down to the last engaged block so a
        # beat-only tail without vocals is dropped and the mix stays tight.
        cap = min(full_len, int(round(TARGET_BARS * 4.0 * SR * 60.0 / nxt.bpm)))
        step_len = _content_length(audio[nxt.id].samples, SR, nxt.bpm,
                                   cap, block_bars=16)
        print(f'  phrase {nxt.id.split("-")[-1]:>6} cap={cap/SR:.1f}s'
              f' -> {step_len/SR:.1f}s ({(step_len/cap if cap else 0):.2f}x)')
        plan.steps.append(SetStep(nxt.id, edge.id if edge else None,
                                  edge.technique if edge else None, 0, step_len))
        current = nxt.id
    return plan, keys, energy


def main():
    built = False
    if _needs_build():
        _build_pack()
        built = True
    graph, graph_doc, segments, edges, audio = load_pack()
    plan, keys, energy = build_plan(graph, graph_doc, segments, audio)
    profile = load_recipe(OPENING_RECIPE)
    opening_id = plan.steps[0].segment_id
    audio[opening_id] = type(audio[opening_id])(
        samples=apply_recipe(profile, audio[opening_id].samples, SR, bpm=OPENING_BPM),
        sample_rate=SR,
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plan_doc = plan.to_dict()
    (OUT_DIR / 'set.plan.json').write_text(json.dumps(plan_doc, indent=2), encoding='utf-8')
    report = GoldenRenderer().render(plan, segments, edges, audio, OUT_DIR, force_cut=False)
    trace = {'seed': SEED, 'director': 'DeepMixDirector', 'harmonicArc': True,
             'pack_rebuilt': built, 'music_snapshot': _music_snapshot()['files'],
             'opening_recipe': OPENING_RECIPE, 'opening_end_seconds': OPENING_END_S,
             'steps': plan_doc['steps'], 'report': report,
             'camelot': [keys.get(s.segment_id, '') for s in plan.steps]}
    TRACE.write_text(json.dumps(trace, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('steps', [(s.segment_id, s.technique) for s in plan.steps])
    print('output', report)


if __name__ == '__main__':
    main()