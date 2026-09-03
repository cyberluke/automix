"""AutomixAnalyzer — adapter over the existing club_mixer PhraseGrid machinery
(§8, §44). Converts returned seconds to integer sample indices immediately.
Heavy DSP stays here in the authoring side, never in the runtime.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

import numpy as np

from ..audio_io import CanonicalAudio
from ..config import ANALYZER_VERSION, HyperMixConfig, DEFAULT_CONFIG
from ..errors import ErrorCode, HyperMixError
from ..model import Section, TrackAnalysis
from .energy import phrase_energies, track_energy
from .structure import derive_phrases, derive_bars_from_downbeats
from .peaks import hero_candidates

# Ensure the legacy src/ package is importable as a donor layer (§1.2).
_SRC_ROOT = Path(__file__).resolve().parents[2]
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))


class AutomixAnalyzer:
    name = "automix"
    version = ANALYZER_VERSION

    def __init__(self, config: HyperMixConfig = DEFAULT_CONFIG) -> None:
        self.config = config

    def analyze(self, audio: CanonicalAudio,
                phrase_phase_offset_bars: int = 0) -> TrackAnalysis:
        try:
            import club_mixer  # legacy donor module
        except Exception as exc:  # pragma: no cover - import guard
            raise HyperMixError(ErrorCode.HMX_ANALYSIS_FAILED,
                                "could not import legacy club_mixer donor",
                                detail=repr(exc))

        sr = audio.sample_rate
        # club_mixer expects [n, ch] float and its own sr; pass canonical values.
        y = audio.samples
        try:
            grid = club_mixer.build_phrase_grid(y, sr, phrase_bars=self.config.phrase_bars)
        except Exception as exc:
            raise HyperMixError(ErrorCode.HMX_ANALYSIS_FAILED,
                                "phrase grid construction failed", detail=repr(exc))

        if len(grid.downbeats) == 0:
            raise HyperMixError(ErrorCode.HMX_NO_DOWNBEAT_GRID,
                                "analysis produced no downbeat grid")

        # seconds -> integer sample indices immediately (§8).
        downbeats = [int(round(t * sr)) for t in grid.downbeats]
        # beats: reconstruct from downbeats (4 beats/bar) using grid tempo.
        beat_sec = grid.bar_dur / 4.0
        beats: List[int] = []
        for db_t in grid.downbeats:
            for k in range(4):
                beats.append(int(round((db_t + k * beat_sec) * sr)))
        beats.sort()

        bars = derive_bars_from_downbeats(downbeats, audio.n_samples)
        phrases = derive_phrases(downbeats, self.config.phrase_bars,
                                 audio.n_samples, phrase_phase_offset_bars)

        bar_energy = [float(e) for e in getattr(grid, "bar_energy", [])]
        ph_energy = phrase_energies(bar_energy, self.config.phrase_bars)

        sections = [
            Section(
                start_sample=int(round(s["start_sec"] * sr)),
                end_sample=int(round(s["end_sec"] * sr)),
                label=str(s.get("label", "high")),
                energy=float(s.get("energy", 0.0)),
            )
            for s in (grid.sections or [])
        ]

        # Confidence: agreement between downbeat spacing and tempo.
        if len(downbeats) > 2:
            intervals = np.diff(downbeats) / sr
            expected = grid.bar_dur
            mad = float(np.mean(np.abs(intervals - expected))) if len(intervals) else 1.0
            confidence = float(max(0.0, min(1.0, 1.0 - mad / max(expected, 1e-6))))
        else:
            confidence = 0.0

        hero = hero_candidates(audio, bars, bar_energy, bpm=float(grid.tempo),
                               phrase_bars=self.config.phrase_bars)
        # V1 DeepDance: entry/exit cues are the drop/hook *entries* (kick+bass
        # slam-in). Fall back to plain top-scored heroes when no clean drop
        # entry is detected (e.g. ambient / breakdown-only material).
        drop_entries = [h["sample"] for h in hero if h.get("isDropEntry")]
        pool = drop_entries if drop_entries else [h["sample"] for h in hero]
        entry_c = pool[:6]
        exit_c = pool[-6:] if len(pool) > 6 else entry_c

        # Phrase-native features (§-phrase-native): one feature vector per
        # phrase window, derived from STFT distributions. Optional flag on
        # config; default ON for the phrase-native upgrade. Fail-safe: any
        # per-phrase error yields the empty feature dict (never breaks
        # analysis).
        phrase_feats: List[dict] = []
        if getattr(self.config, "phrase_native_features", True):
            from .phrase_features import extract_phrase_features, _empty_features
            samples = audio.samples
            total = audio.n_samples
            bounds = list(phrases) + [total]
            for i in range(len(phrases)):
                s0 = int(bounds[i])
                s1 = int(bounds[i + 1]) if i + 1 < len(bounds) else total
                if s1 <= s0:
                    phrase_feats.append(_empty_features())
                    continue
                try:
                    phrase_feats.append(extract_phrase_features(
                        samples[s0:s1], sr, bpm=float(grid.tempo)))
                except Exception:
                    phrase_feats.append(_empty_features())

        return TrackAnalysis(
            bpm=float(grid.tempo),
            beat_samples=beats,
            downbeats=downbeats,
            bars=bars,
            phrases=phrases,
            bar_energy=bar_energy,
            phrase_energy=ph_energy,
            phrase_features=phrase_feats,
            sections=sections,
            hero_candidates=hero,
            entry_candidates=entry_c,
            exit_candidates=exit_c,
            confidence=confidence,
            phrase_phase_offset_bars=phrase_phase_offset_bars,
            analyzer=self.name,
            analyzer_version=self.version,
        )
