"""pack.compile orchestration (§17). Shared by the sidecar handler and the CLI."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .compiler.crate_compiler import load_crate
from .compiler.edge_compiler import EdgeCompiler
from .compiler.pack_writer import PackWriter
from .compiler.segment_compiler import SegmentCompiler
from .director.graph import MixGraph
from .errors import ErrorCode, HyperMixError


def compile_pack_from_crate(handlers, params: dict) -> Dict[str, Any]:
    """Compile a crate into a .hmxpack directory (+ optional zip)."""
    from .analysis.automix_analyzer import AutomixAnalyzer
    from .audio_io import read_wav
    from .model import Track

    crate_path = Path(params["cratePath"])
    out_dir = Path(params["outDir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    crate = load_crate(crate_path)

    cfg = handlers.config
    canonicalizer = handlers.canonicalizer
    seg_dir = out_dir / "audio" / "segments"
    edge_dir = out_dir / "audio" / "transitions"

    # 1. Canonicalize + analyze each track; compile segments.
    segc = SegmentCompiler(cfg)
    analyzer = AutomixAnalyzer(cfg)
    segments = []
    audio_by_track = {}
    seg_audio = {}
    track_models = {}
    for src in crate.tracks:
        p = Path(src)
        res = canonicalizer.canonicalize(p, canonicalizer.default_private_root())
        audio = read_wav(res.canonical_path)
        audio_by_track[p.stem] = audio
        analysis = analyzer.analyze(audio, cfg.phrase_bars)
        track = Track(id=p.stem, title=p.stem, artist="unknown",
                      source=str(p), analysis=analysis,
                      cues=crate.cues.get(src, []))
        track_models[p.stem] = track
        for seg in segc.compile_track(track, audio, seg_dir):
            segments.append(seg)
            seg_audio[seg.id] = read_wav(seg_dir / Path(seg.asset).name)

    if not segments:
        raise HyperMixError(ErrorCode.HMX_CRATE_INVALID,
                            "crate produced no playable segments")

    # 2. Edges + graph (universal fallback exit for every segment).
    edgec = EdgeCompiler(config=cfg)
    edges, adjacency = edgec.compile_graph(
        segments, audio_by_track_for_edges(audio_by_track, track_models),
        crate.curated_edges, crate.fallback_transition, edge_dir,
        allowed=crate.allowed_techniques or None)

    edge_audio = {}
    for e in edges:
        edge_audio[e.id] = read_wav(edge_dir / Path(e.asset).name)

    # 3. Entry segments: highest-rated, entry-allowed.
    entry_segments = [s.id for s in sorted(
        segments, key=lambda s: -s.rating)[:max(1, min(4, len(segments)))]]

    graph = MixGraph(
        segments={s.id: s for s in segments},
        edges={e.id: e for e in edges},
        adjacency=adjacency,
        entry_segments=entry_segments,
        fallback_transition=crate.fallback_transition,
    )

    # 4. Write pack.
    writer = PackWriter(out_dir)
    for seg in segments:
        writer.add_asset(seg_dir / Path(seg.asset).name, seg.asset,
                         samples=seg.asset_samples)
    for e in edges:
        writer.add_asset(edge_dir / Path(e.asset).name, e.asset,
                         samples=e.asset_samples)
    writer.write_json("graph/segments.json",
                      {"schema": "hypermix.segments.v1",
                       "segments": [s.to_dict() for s in segments]})
    writer.write_json("graph/edges.json",
                      {"schema": "hypermix.edges.v1",
                       "edges": [e.to_dict() for e in edges],
                       "adjacency": adjacency})
    writer.write_json("graph/graph.json", {
        "schema": "hypermix.graph.v1",
        "entrySegments": entry_segments,
        "fallbackTransition": crate.fallback_transition,
        "adjacency": adjacency,
    })
    writer.write_json("crate/crate.json", crate.to_dict())

    manifest = {
        "schema": "hypermix.pack.v1",
        "id": crate.id,
        "name": crate.name,
        "version": crate.version,
        "sampleRate": cfg.sample_rate,
        "channels": cfg.channels,
        "fallbackTransition": crate.fallback_transition,
        "segments": len(segments),
        "edges": len(edges),
        "entrySegments": entry_segments,
    }
    writer.finalize_manifest(manifest)

    result = {"packDir": str(out_dir), "segments": len(segments),
              "edges": len(edges)}
    if params.get("zip"):
        zip_path = writer.zip_pack(Path(params["zipPath"]) if params.get("zipPath")
                                   else out_dir.with_suffix(".hmxpack.zip"))
        result["zipPath"] = str(zip_path)
    return result


def audio_by_track_for_edges(audio_by_track, track_models):
    """Map track_id -> CanonicalAudio (edges key on Segment.track_id)."""
    return {tid: audio_by_track[tid] for tid in audio_by_track}
