"""Crate model helpers + crate compiler entry point (§4, §9)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from ..audio_io import read_wav
from ..canonicalize import Canonicalizer
from ..config import HyperMixConfig, DEFAULT_CONFIG
from ..errors import ErrorCode, HyperMixError
from ..hashing import sha256_file
from ..model import (Cue, Crate, SCHEMA_CRATE, SCHEMA_TRACK, Track, TrackAnalysis)
from .segment_compiler import SegmentCompiler


def load_crate(path: Path) -> Crate:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA_CRATE:
        raise HyperMixError(ErrorCode.HMX_CRATE_INVALID, "unsupported crate schema")
    cues = {}
    for tid, cue_list in (data.get("cues") or {}).items():
        cues[tid] = [Cue(
            id=c["id"], sample=int(c["sample"]), kind=c.get("kind", "custom"),
            locked=c.get("locked", False), rating=float(c.get("rating", 7.0)),
            tags=list(c.get("tags", [])), notes=c.get("notes", ""),
            snap=c.get("snap", "nearestBar"),
            allowed_entry=c.get("allowedEntry", True),
            allowed_exit=c.get("allowedExit", True),
            preferred_bars=list(c.get("preferredBars", [8, 16, 32])),
            stale=c.get("stale", False),
        ) for c in cue_list]
    defaults = data.get("defaults", {})
    crate = Crate(
        id=data.get("id", "crate"),
        name=data.get("name", data.get("id", "crate")),
        version=data.get("version", "1.0.0"),
        default_energy_min=defaults.get("energy", {}).get("min", 0.2),
        default_energy_max=defaults.get("energy", {}).get("max", 0.9),
        default_phrase_bars=defaults.get("phraseBars", 8),
        allowed_techniques=list(defaults.get("allowedTechniques", [])),
        fallback_transition=defaults.get("fallbackTransition", "rewind"),
        tracks=[str(t) for t in data.get("tracks", [])],
        cues=cues,
    )
    return crate


class CrateCompiler:
    """Compiles a crate's tracks into segments (Phase F/G front end)."""

    def __init__(self, config: HyperMixConfig = DEFAULT_CONFIG,
                 canonicalizer: Optional[Canonicalizer] = None) -> None:
        self.config = config
        self.canonicalizer = canonicalizer or Canonicalizer(config)
        self.segment_compiler = SegmentCompiler(config)

    def compile_crate(self, crate: Crate, out_dir: Path,
                      cached_analysis=None):
        """Compile all tracks into segments. `cached_analysis` is an optional
        callable(track_id, source_path) -> Track (with analysis + cues filled in).
        Returns (segments, audio_by_track)."""
        from ..analysis.automix_analyzer import AutomixAnalyzer
        from ..analysis.structure import derive_bars_from_downbeats, derive_phrases
        from ..analysis.energy import phrase_energies, track_energy
        from ..analysis.peaks import hero_candidates

        analyzer = AutomixAnalyzer(self.config)
        segments = []
        audio_by_track = {}
        for src in crate.tracks:
            res = self.canonicalizer.canonicalize(Path(src), self.canonicalizer.default_private_root())
            audio = read_wav(res.canonical_path)
            audio_by_track[src] = audio
            track = cached_analysis(src, res.canonical_path) if cached_analysis else None
            if track is None:
                analysis = analyzer.analyze(audio, self.config.phrase_bars)
                track = Track(id=Path(src).stem, title=Path(src).stem,
                              artist="unknown", source=Path(src).stem,
                              analysis=analysis, cues=crate.cues.get(src, []))
            track.id = track.id or Path(src).stem
            track.cues = track.cues or crate.cues.get(src, [])
            track.source_hash = sha256_file(Path(src))
            segments.extend(self.segment_compiler.compile_track(track, audio, out_dir))
        return segments, audio_by_track
