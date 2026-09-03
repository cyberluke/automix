"""Segment compiler (§14). Compiles 8/16/32-bar assets around curated cues.
Content-addressed physical assets; readable manifest IDs. Downbeat transients
preserved — only tiny de-click envelopes at slice edges, transitions own the
musical boundaries."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..audio_io import CanonicalAudio, atomic_write_wav, declick_edges, slice_samples
from ..config import HyperMixConfig, DEFAULT_CONFIG, SEGMENT_COMPILER_VERSION
from ..hashing import sha256_file, sha256_text, short_hash
from ..model import Cue, Segment, Track


class SegmentCompiler:
    _probe_seq = 0  # process-local counter for short unique probe names

    def __init__(self, config: HyperMixConfig = DEFAULT_CONFIG) -> None:
        self.config = config

    def _bar_len(self, track: Track) -> int:
        a = track.analysis
        if not a or not a.bpm:
            return int(self.config.sample_rate * 2)  # 120bpm bar fallback
        return int(round(self.config.sample_rate * 4 * 60.0 / a.bpm))

    def compile_for_cue(self, track: Track, audio: CanonicalAudio, cue: Cue,
                        bars: int, out_dir: Path) -> Optional[Segment]:
        if cue.stale:
            return None
        a = track.analysis
        bar_len = self._bar_len(track)
        start = cue.sample
        end = min(start + bars * bar_len, audio.n_samples)
        if end - start < bar_len // 2:
            return None
        seg_id = f"{track.id}.{cue.id}.{bars}b"
        energy = cue.energy
        seg = Segment(
            id=seg_id, track_id=track.id, start_sample=start, end_sample=end,
            bars=bars, bpm=a.bpm if a else 0.0,
            entry_class="downbeat", exit_class="phrase",
            energy_start=energy, energy_end=energy, rating=cue.rating,
            mood_tags=list(dict.fromkeys(cue.tags + track.tags)),
        )
        # Content-addressed physical asset (§14).
        body = declick_edges(slice_samples(audio, start, end), audio.sample_rate)
        tmp_dir = Path(out_dir); tmp_dir.mkdir(parents=True, exist_ok=True)
        # Short-lived probe temp file — use a short unique name so long track
        # titles never exceed Windows MAX_PATH; the final asset is hashed.
        import os
        probe = tmp_dir / f".probe-{os.getpid()}-{SegmentCompiler._probe_seq}.wav"
        SegmentCompiler._probe_seq += 1
        atomic_write_wav(probe, body, audio.sample_rate)
        digest = sha256_file(probe)
        asset_name = f"{short_hash(digest, 20)}.wav"
        asset_path = tmp_dir / asset_name
        probe.replace(asset_path)
        seg.asset = f"audio/segments/{asset_name}"
        seg.asset_sha256 = digest
        seg.asset_samples = int(body.shape[0])
        return seg

    def compile_track(self, track: Track, audio: CanonicalAudio,
                      out_dir: Path,
                      bars_options: Optional[List[int]] = None) -> List[Segment]:
        bars_options = bars_options or list(self.config.segment_bars)
        resolver_cues = [c for c in track.cues if c.allowed_entry and not c.stale]
        # Advisory entry candidates become implicit hero cues if no curated cues.
        if not resolver_cues and track.analysis:
            from ..cues.resolver import CueResolver
            resolver = CueResolver()
            for i, s in enumerate(track.analysis.entry_candidates[:4]):
                resolver.add_cue(track, f"auto.hero.{i:02d}", s, "hero",
                                 snap="nearestPhrase", locked=False,
                                 rating=6.0, tags=["auto"])
            resolver_cues = [c for c in track.cues if c.allowed_entry and not c.stale]
        out: List[Segment] = []
        for cue in resolver_cues:
            preferred = [b for b in bars_options if b in cue.preferred_bars] or bars_options
            for bars in preferred:
                seg = self.compile_for_cue(track, audio, cue, bars, out_dir)
                if seg:
                    out.append(seg)
        return out
