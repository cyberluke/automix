"""Transition edge compiler (§15). Compiles only curated/needed edges — no
N×N×technique explosion. Every playable segment gets at least one safe exit
path via a universal fallback edge."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from ..audio_io import CanonicalAudio, atomic_write_wav
from ..config import HyperMixConfig, DEFAULT_CONFIG
from ..errors import ErrorCode, HyperMixError
from ..hashing import sha256_file, short_hash
from ..model import Segment, TransitionEdge
from ..transitions.model import SegmentContext
from ..transitions.planner import TransitionPlanner


class EdgeCompiler:
    _probe_seq = 0  # process-local counter for short unique probe names

    def __init__(self, planner: Optional[TransitionPlanner] = None,
                 config: HyperMixConfig = DEFAULT_CONFIG) -> None:
        self.planner = planner or TransitionPlanner()
        self.config = config

    def _context(self, a: Segment, b: Segment,
                 audio_a: CanonicalAudio, audio_b: CanonicalAudio,
                 params: Optional[dict] = None) -> SegmentContext:
        return SegmentContext(
            outgoing_audio=audio_a, incoming_audio=audio_b,
            outgoing_start=a.start_sample, outgoing_end=a.end_sample,
            incoming_start=b.start_sample, incoming_end=b.end_sample,
            outgoing_bpm=a.bpm, incoming_bpm=b.bpm,
            sample_rate=self.config.sample_rate,
            params=params or {},
        )

    def compile_edge(self, a: Segment, b: Segment,
                     audio_a: CanonicalAudio, audio_b: CanonicalAudio,
                     technique: str, out_dir: Path,
                     allowed: Optional[List[str]] = None,
                     params: Optional[dict] = None) -> TransitionEdge:
        ctx = self._context(a, b, audio_a, audio_b, params)
        plan = self.planner.plan(technique, ctx, allowed)
        rendered = self.planner.render(plan, ctx)

        edge_id = f"edge-{a.id}-to-{b.id}-{plan.technique}"
        out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
        # Probe is a short-lived temp file; use a short unique name so long
        # track titles never push the path past Windows MAX_PATH (§38). The
        # final asset below is content-addressed and already short.
        import os
        probe = out_dir / f".probe-{os.getpid()}-{EdgeCompiler._probe_seq}.wav"
        EdgeCompiler._probe_seq += 1
        atomic_write_wav(probe, rendered.samples, rendered.sample_rate)
        digest = sha256_file(probe)
        asset_name = f"{short_hash(digest, 20)}.wav"
        asset_path = out_dir / asset_name
        probe.replace(asset_path)

        return TransitionEdge(
            id=edge_id, from_segment=a.id, to_segment=b.id,
            technique=plan.technique, timeline=plan.timeline,
            tempo_continuity_required=plan.tempo_continuity_required,
            phrase_safe=plan.phrase_safe, quality=plan.quality,
            asset=f"audio/transitions/{asset_name}", asset_sha256=digest,
            asset_samples=int(rendered.samples.shape[0]),
            events=rendered.events,
        )

    def compile_graph(self, segments: List[Segment],
                      audio_by_track: Dict[str, CanonicalAudio],
                      curated_edges: Iterable[dict],
                      fallback: str, out_dir: Path,
                      allowed: Optional[List[str]] = None,
                      max_auto_edges_per_segment: int = 8) -> Tuple[List[TransitionEdge], Dict[str, List[str]]]:
        """Compile curated edges + a sparse, safe auto-graph. Returns (edges, graph)."""
        by_id = {s.id: s for s in segments}
        edges: List[TransitionEdge] = []
        graph: Dict[str, List[str]] = {s.id: [] for s in segments}
        seen = set()

        def _add(a: Segment, b: Segment, tech: str) -> None:
            if a.id == b.id:
                return
            key = (a.id, b.id, tech)
            if key in seen:
                return
            seen.add(key)
            try:
                e = self.compile_edge(a, b, audio_by_track[a.track_id],
                                      audio_by_track[b.track_id], tech,
                                      out_dir, allowed)
            except HyperMixError:
                return
            edges.append(e)
            graph[a.id].append(b.id)

        # 1. Curated adjacency first.
        for ce in curated_edges or []:
            a = by_id.get(ce.get("from", "")); b = by_id.get(ce.get("to", ""))
            if a and b:
                _add(a, b, ce.get("technique", fallback))

        # 2. Sparse safe auto-graph: each segment gets at least one exit (§15).
        #    Prefer cross-track targets, spread across distinct tracks so the
        #    whole library is reachable, and rotate through varied techniques
        #    (deterministically) so a mix doesn't collapse to one sound.
        from ..transitions.registry import UNIVERSAL_FALLBACKS
        # Safe, always-available techniques good for variety. Deterministic order.
        variety = [t for t in (
            "phrase_match", "echo_cut", "slam", "backspin", "drum_roll",
            "loop_transition", "stutter", "power_up", "power_down",
        ) if (allowed is None) or (t in allowed) or (t in UNIVERSAL_FALLBACKS)]
        if not variety:
            variety = [fallback]
        seq = 0  # deterministic rotation counter
        for a in segments:
            if graph[a.id]:
                continue
            candidates = [b for b in segments if b.id != a.id]
            # Prefer cross-track, then highest rating, then least-used target
            # track so coverage spreads across the library.
            track_use = {s.track_id: 0 for s in segments}
            for e in edges:
                tb = by_id[e.to_segment].track_id
                track_use[tb] = track_use.get(tb, 0) + 1
            # Rank by rating first so edges point at strong cues; use track usage
            # only as a tiebreak so we still spread without collapsing to one hub.
            # Prefer SAME-BAR-LENGTH targets first (a.track_id==b.track_id already
            # deprioritized): V1 DeepDance holds a full phrase per section, so a
            # 64-bar drop section must be able to transition into another 64-bar
            # drop section (64<->64 edges) instead of collapsing onto 16-bar cues.
            candidates.sort(key=lambda b: (
                b.bars != a.bars,
                b.track_id == a.track_id,
                -b.rating,
                track_use.get(b.track_id, 0),
                b.id,
            ))
            # Spread the out-edges across DISTINCT target tracks (one cue per
            # track first) so the walk always has a fresh track reachable. Only
            # after each track has one slot do we allow a second cue per track.
            limit = max(1, max_auto_edges_per_segment)
            per_track_cap = 1
            picked = 0
            while picked < limit and per_track_cap <= limit:
                counts: Dict[str, int] = {}
                for b in candidates:
                    if picked >= limit:
                        break
                    if counts.get(b.track_id, 0) >= per_track_cap:
                        continue
                    # skip if edge already added this pass
                    if any(e.from_segment == a.id and e.to_segment == b.id for e in edges):
                        continue
                    tech = variety[seq % len(variety)]
                    seq += 1
                    _add(a, b, tech)
                    counts[b.track_id] = counts.get(b.track_id, 0) + 1
                    picked += 1
                per_track_cap += 1

        return edges, graph
