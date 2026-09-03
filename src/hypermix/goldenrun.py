"""pack.renderGolden orchestration (§18). Shared by sidecar handler and CLI."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .audio_io import read_wav
from .compiler.deterministic_render import GoldenRenderer
from .compiler.set_compiler import SetCompiler
from .director.graph import MixGraph
from .model import Segment, TransitionEdge


def _phrase_energy_gradient(samples, sr: int) -> float:
    """Normalized climbing-energy of a phrase: early RMS vs late RMS. Positive
    means the phrase is building (rising into a drop); negative means it is
    decaying. Bounded to roughly [-1, +1]."""
    import numpy as np
    mono = samples.mean(axis=1) if samples.ndim > 1 else samples
    n = mono.shape[0]
    if n < sr // 2:
        return 0.0
    q = max(1, n // 4)
    early = float(np.sqrt((mono[:q] ** 2).mean()))
    late = float(np.sqrt((mono[-q:] ** 2).mean()))
    if early + late < 1e-6:
        return 0.0
    return float((late - early) / (early + late + 1e-9))


def _segment_level(samples) -> float:
    """Absolute perceived level of a phrase (full-band RMS). This is the
    ENERGY-CONTINUITY axis: a climax phrase has high level, a breakdown low.
    Normalized later against the crate's 95th percentile."""
    import numpy as np
    mono = samples.mean(axis=1) if samples.ndim > 1 else samples
    if mono.shape[0] < 1:
        return 0.0
    return float(np.sqrt((mono ** 2).mean()))


def _spectral_features(samples, sr: int) -> Dict[str, Any]:
    """Spectral signature of a phrase for SPECTRAL-SIMILARITY matching:
    - brightness: spectral centroid normalized to Nyquist (0..1) — how much
      synth/hat top-end vs dark bass;
    - low_ratio: fraction of spectral energy below 200 Hz (kick+bass weight);
    - mid_ratio: 200 Hz..2 kHz (bass/synth body);
    - high_ratio: >2 kHz (synths, hats, vocals, FX).
    A 'just beat + off-beat bass, no synth/vocal/FX' phrase has HIGH low_ratio
    and LOW high_ratio/brightness; a climax has high high_ratio+brightness.
    Deterministic (librosa STFT)."""
    import numpy as np
    mono = samples.mean(axis=1) if samples.ndim > 1 else samples
    n = mono.shape[0]
    if n < 2048:
        return {"brightness": 0.0, "low_ratio": 0.0, "mid_ratio": 0.0,
                "high_ratio": 0.0}
    try:
        import librosa
        S = np.abs(librosa.stft(mono.astype(np.float32), n_fft=2048,
                                hop_length=1024))
        power = (S ** 2)
        freq = librosa.fft_frequencies(sr=sr, n_fft=2048)
        tot = float(power.sum()) + 1e-9
        low = float(power[freq < 200.0].sum())
        mid = float(power[(freq >= 200.0) & (freq < 2000.0)].sum())
        high = float(power[freq >= 2000.0].sum())
        cent = librosa.feature.spectral_centroid(S=S, sr=sr)[0]
        bright = float(np.clip(np.mean(cent) / (sr / 2.0), 0.0, 1.0))
        return {"brightness": bright, "low_ratio": low / tot,
                "mid_ratio": mid / tot, "high_ratio": high / tot}
    except Exception:
        return {"brightness": 0.0, "low_ratio": 0.0, "mid_ratio": 0.0,
                "high_ratio": 0.0}


def render_golden_from_pack(pack_dir: Path, out_dir: Path, seed: int,
                            params: Dict[str, Any]) -> Dict[str, Any]:
    pack_dir = Path(pack_dir)
    seg_doc = json.loads((pack_dir / "graph" / "segments.json").read_text(encoding="utf-8"))
    edge_doc = json.loads((pack_dir / "graph" / "edges.json").read_text(encoding="utf-8"))
    graph_doc = json.loads((pack_dir / "graph" / "graph.json").read_text(encoding="utf-8"))

    segments = {s["id"]: Segment.from_dict(s) for s in seg_doc["segments"]}
    edges = {e["id"]: TransitionEdge.from_dict(e) for e in edge_doc["edges"]}
    graph = MixGraph(segments=segments, edges=edges,
                     adjacency=graph_doc["adjacency"],
                     entry_segments=graph_doc["entrySegments"],
                     fallback_transition=graph_doc["fallbackTransition"])

    seg_audio = {}
    for seg in segments.values():
        seg_audio[seg.id] = read_wav(pack_dir / seg.asset)
    for e in edges.values():
        seg_audio[e.id] = read_wav(pack_dir / e.asset)

    # ASCENDING_ENERGY_ARC (V1): compute Camelot key + climbing-energy per
    # phrase (segment) so the director can keep a monotonic perceived-energy
    # gradient. Key is one axis; phrase energy delta is the other.
    harmonic_arc = bool(params.get("harmonicArc", False))
    seg_keys = seg_energy = seg_level = seg_spec = None
    if harmonic_arc:
        import numpy as np
        from .analysis.phrase_key import detect_key
        from .analysis.phrase_features import extract_phrase_features
        seg_keys = {}
        seg_energy = {}
        seg_level = {}
        seg_spec = {}
        raw_level = {}
        for seg in segments.values():
            a = seg_audio.get(seg.id)
            if a is None:
                continue
            try:
                seg_keys[seg.id] = detect_key(a.samples, a.sample_rate)["camelot"]
            except Exception:
                seg_keys[seg.id] = ""
            seg_energy[seg.id] = _phrase_energy_gradient(a.samples, a.sample_rate)
            raw_level[seg.id] = _segment_level(a.samples)
            # Phrase-native feature vector (STFT distributions + roles +
            # perceived energy). Stored under seg_spec keyed by segment id;
            # the selector consumes the nested dict directly.
            bpm = float(getattr(seg, "bpm", 0.0) or 0.0) or 128.0
            try:
                seg_spec[seg.id] = extract_phrase_features(
                    a.samples, a.sample_rate, bpm)
            except Exception:
                seg_spec[seg.id] = _spectral_features(a.samples, a.sample_rate)
        # Global normalization (§6): perceived energy + level normalized
        # against the LIBRARY (crate) 95th percentile, so heavily-mastered
        # tracks do not dominate the ranking purely by loudness.
        if raw_level:
            ref = float(np.percentile(list(raw_level.values()), 95)) or 1e-9
            for sid, lv in raw_level.items():
                seg_level[sid] = max(0.0, min(1.0, lv / ref))
        # Attach energy_global to each feature vector.
        pe_vals = [float(v.get("perceived_energy", 0.0)) for v in seg_spec.values()
                   if isinstance(v, dict) and "perceived_energy" in v]
        if pe_vals:
            import numpy as _np
            pe_ref = float(_np.percentile(pe_vals, 95)) or 1e-9
            for sid, v in seg_spec.items():
                if isinstance(v, dict) and "perceived_energy" in v:
                    v["energy_global"] = max(0.0, min(1.0, float(v["perceived_energy"]) / pe_ref))

    plan = SetCompiler(graph).compile(
        seed=seed,
        length=int(params.get("length", 12)),
        mode=params.get("mode", "weighted-random"),
        target_mood=params.get("targetMood"),
        energy_min=float(params.get("energyMin", 0.0)),
        energy_max=float(params.get("energyMax", 1.0)),
        segment_bars=params.get("segmentBars"),
        sr=graph_doc.get("sampleRate", 48000),
        seg_keys=seg_keys,
        seg_energy=seg_energy,
        seg_level=seg_level,
        seg_spec=seg_spec,
        harmonic_arc=harmonic_arc,
    )
    (Path(out_dir)).mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / "set.plan.json").write_text(json.dumps(plan.to_dict(), indent=2))
    if harmonic_arc and seg_keys:
        (Path(out_dir) / "harmonic.arc.json").write_text(json.dumps({
            "camelotChain": [seg_keys.get(s.segment_id, "") for s in plan.steps],
            "phraseEnergyGradient": {sid: seg_energy.get(sid) for sid in seg_keys},
        }, indent=2))

    report = GoldenRenderer().render(
        plan, segments, edges, seg_audio, Path(out_dir),
        force_cut=bool(params.get("cut", False)))
    report["seed"] = seed
    report["steps"] = len(plan.steps)
    return report
