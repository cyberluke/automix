"""HyperMix domain model (§6). Canonical time is integer sample index.
All dataclasses round-trip to/from the versioned JSON contracts in contracts/."""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

SCHEMA_TRACK = "hypermix.track.v1"
SCHEMA_CRATE = "hypermix.crate.v1"
SCHEMA_PACK = "hypermix.pack.v1"
SCHEMA_TRANSITION = "hypermix.transition.v1"
SCHEMA_EVENTS = "hypermix.events.v1"
SCHEMA_SIDECAR = "hypermix.sidecar.v1"
SCHEMA_WEBVIEW = "hypermix.webview.v1"

CUE_KINDS = (
    "intro", "build", "breakdown", "drop", "hero", "hook", "vocal",
    "outro", "transition-in", "transition-out", "reset", "custom",
)

SNAP_MODES = (
    "nearestBeat", "nearestDownbeat", "nearestBar", "nearestPhrase",
    "previousBeat", "previousBar", "previousPhrase",
    "nextBeat", "nextBar", "nextPhrase", "none",
)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --------------------------------------------------------------------- track #
@dataclass
class SourceRef:
    path: str
    sha256: Optional[str] = None
    canonical_sha256: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in {
            "path": self.path, "sha256": self.sha256,
            "canonicalSha256": self.canonical_sha256,
        }.items() if v is not None}


@dataclass
class AudioInfo:
    sample_rate: int
    channels: int
    samples: int

    @property
    def duration_sec(self) -> float:
        return self.samples / self.sample_rate if self.sample_rate else 0.0

    def to_dict(self) -> dict:
        return {
            "sampleRate": self.sample_rate,
            "channels": self.channels,
            "samples": self.samples,
            "durationSec": self.duration_sec,
        }


@dataclass
class Section:
    start_sample: int
    end_sample: int
    label: str            # 'high' | 'low'
    energy: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TrackAnalysis:
    bpm: float = 0.0
    beat_samples: List[int] = field(default_factory=list)
    downbeats: List[int] = field(default_factory=list)      # sample indices
    bars: List[int] = field(default_factory=list)           # bar boundary samples
    phrases: List[int] = field(default_factory=list)        # phrase boundary samples
    bar_energy: List[float] = field(default_factory=list)
    phrase_energy: List[float] = field(default_factory=list)
    # Phrase-native feature vectors (§-phrase-native). One dict per phrase,
    # aligned with `phrases` boundaries. Raw features + roles + perceived
    # energy. Optional: populated by the analyzer when enabled.
    phrase_features: List[Dict[str, Any]] = field(default_factory=list)
    sections: List[Section] = field(default_factory=list)
    hero_candidates: List[Dict[str, Any]] = field(default_factory=list)  # {sample,score}
    entry_candidates: List[int] = field(default_factory=list)
    exit_candidates: List[int] = field(default_factory=list)
    confidence: float = 0.0
    phrase_phase_offset_bars: int = 0
    analyzer: str = "automix"
    analyzer_version: int = 1

    def to_dict(self) -> dict:
        d = asdict(self)
        d["sections"] = [s.to_dict() for s in self.sections]
        return d


@dataclass
class Cue:
    id: str
    sample: int
    kind: str = "hero"
    locked: bool = False
    stale: bool = False
    beat: Optional[int] = None
    bar: Optional[int] = None
    phrase: Optional[int] = None
    rating: float = 5.0
    energy: float = 0.0
    allowed_entry: bool = True
    allowed_exit: bool = True
    preferred_bars: List[int] = field(default_factory=lambda: [8, 16, 32])
    tags: List[str] = field(default_factory=list)
    snap: str = "nearestBar"
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "sample": self.sample, "kind": self.kind,
            "locked": self.locked, "stale": self.stale,
            "beat": self.beat, "bar": self.bar, "phrase": self.phrase,
            "rating": self.rating, "energy": self.energy,
            "allowedEntry": self.allowed_entry, "allowedExit": self.allowed_exit,
            "preferredBars": list(self.preferred_bars), "tags": list(self.tags),
            "snap": self.snap, "notes": self.notes,
        }


@dataclass
class Track:
    id: str
    artist: str = ""
    title: str = ""
    source: Optional[SourceRef] = None
    audio: Optional[AudioInfo] = None
    analysis: Optional[TrackAnalysis] = None
    tags: List[str] = field(default_factory=list)
    energy: float = 0.0
    cues: List[Cue] = field(default_factory=list)
    schema: str = SCHEMA_TRACK

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "id": self.id, "artist": self.artist, "title": self.title,
            "source": self.source.to_dict() if self.source else None,
            "audio": self.audio.to_dict() if self.audio else None,
            "analysis": self.analysis.to_dict() if self.analysis else None,
            "tags": list(self.tags), "energy": self.energy,
            "cues": [c.to_dict() for c in self.cues],
        }


# ------------------------------------------------------------------ segments #
@dataclass
class Segment:
    id: str
    track_id: str
    start_sample: int
    end_sample: int
    bars: int
    bpm: float
    entry_class: str = "downbeat"
    exit_class: str = "phrase"
    energy_start: float = 0.0
    energy_end: float = 0.0
    rating: float = 5.0
    mood_tags: List[str] = field(default_factory=list)
    asset: Optional[str] = None
    asset_sha256: Optional[str] = None
    asset_samples: Optional[int] = None

    @property
    def length_samples(self) -> int:
        return self.end_sample - self.start_sample

    def to_dict(self) -> dict:
        return {k: v for k, v in {
            "id": self.id, "trackId": self.track_id,
            "startSample": self.start_sample, "endSample": self.end_sample,
            "lengthSamples": self.length_samples, "bars": self.bars,
            "bpm": self.bpm, "entryClass": self.entry_class,
            "exitClass": self.exit_class, "energyStart": self.energy_start,
            "energyEnd": self.energy_end, "rating": self.rating,
            "tags": list(self.mood_tags), "asset": self.asset,
            "assetSha256": self.asset_sha256, "assetSamples": self.asset_samples,
        }.items() if v is not None}

    @classmethod
    def from_dict(cls, d: dict) -> "Segment":
        return cls(
            id=d["id"], track_id=d["trackId"],
            start_sample=int(d["startSample"]), end_sample=int(d["endSample"]),
            bars=int(d.get("bars", 8)), bpm=float(d.get("bpm", 0.0)),
            entry_class=d.get("entryClass", "downbeat"),
            exit_class=d.get("exitClass", "phrase"),
            energy_start=float(d.get("energyStart", 0.0)),
            energy_end=float(d.get("energyEnd", 0.0)),
            rating=float(d.get("rating", 5.0)),
            mood_tags=list(d.get("tags", [])),
            asset=d.get("asset"), asset_sha256=d.get("assetSha256"),
            asset_samples=d.get("assetSamples"),
        )


# ---------------------------------------------------------------- transition #
@dataclass
class TransitionCapabilities:
    tempo_continuity_required: bool = False
    requires_stems: bool = False
    requires_harmony: bool = False
    requires_vocal_stem: bool = False
    phrase_safe: bool = True
    supports_hot_swap: bool = True

    def to_dict(self) -> dict:
        return {
            "tempoContinuityRequired": self.tempo_continuity_required,
            "requiresStems": self.requires_stems,
            "requiresHarmony": self.requires_harmony,
            "requiresVocalStem": self.requires_vocal_stem,
            "phraseSafe": self.phrase_safe,
            "supportsHotSwap": self.supports_hot_swap,
        }


@dataclass
class TransitionTimeline:
    t1_sample: int
    t2_sample: int
    t3_sample: int

    def to_dict(self) -> dict:
        return {
            "t1Sample": self.t1_sample,
            "t2Sample": self.t2_sample,
            "t3Sample": self.t3_sample,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TransitionTimeline":
        return cls(t1_sample=int(d["t1Sample"]), t2_sample=int(d["t2Sample"]),
                   t3_sample=int(d["t3Sample"]))


@dataclass
class PackEvent:
    sample: int
    type: str
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"sample": self.sample, "type": self.type, "payload": self.payload}

    @classmethod
    def from_dict(cls, d: dict) -> "PackEvent":
        return cls(sample=int(d["sample"]), type=d["type"],
                   payload=dict(d.get("payload", {})))


@dataclass
class TransitionEdge:
    id: str
    from_segment: str
    to_segment: str
    technique: str
    timeline: TransitionTimeline
    tempo_continuity_required: bool = False
    phrase_safe: bool = True
    quality: float = 1.0
    asset: Optional[str] = None
    asset_sha256: Optional[str] = None
    asset_samples: Optional[int] = None
    events: List[PackEvent] = field(default_factory=list)
    schema: str = SCHEMA_TRANSITION

    def to_dict(self) -> dict:
        return {k: v for k, v in {
            "schema": self.schema, "id": self.id,
            "from": self.from_segment, "to": self.to_segment,
            "technique": self.technique, "timeline": self.timeline.to_dict(),
            "tempoContinuityRequired": self.tempo_continuity_required,
            "phraseSafe": self.phrase_safe, "quality": self.quality,
            "asset": self.asset, "assetSha256": self.asset_sha256,
            "assetSamples": self.asset_samples,
            "events": [e.to_dict() for e in self.events],
        }.items() if v is not None}

    @classmethod
    def from_dict(cls, d: dict) -> "TransitionEdge":
        return cls(
            id=d["id"], from_segment=d["from"], to_segment=d["to"],
            technique=d["technique"],
            timeline=TransitionTimeline.from_dict(d["timeline"]),
            tempo_continuity_required=bool(d.get("tempoContinuityRequired", False)),
            phrase_safe=bool(d.get("phraseSafe", True)),
            quality=float(d.get("quality", 1.0)),
            asset=d.get("asset"), asset_sha256=d.get("assetSha256"),
            asset_samples=d.get("assetSamples"),
            events=[PackEvent.from_dict(e) for e in d.get("events", [])],
        )


# ---------------------------------------------------------------------- crate #
@dataclass
class Crate:
    """Authoring unit: curated tracks + manual cues + sequencing intent.
    Schema hypermix.crate.v1. Manual cues are authoritative."""
    id: str
    name: str = ""
    version: str = "1.0.0"
    default_energy_min: float = 0.2
    default_energy_max: float = 0.9
    default_phrase_bars: int = 8
    allowed_techniques: List[str] = field(default_factory=list)
    fallback_transition: str = "rewind"
    tracks: List[str] = field(default_factory=list)          # source paths
    cues: Dict[str, List[Cue]] = field(default_factory=dict)  # track path -> cues
    curated_edges: List[Dict[str, Any]] = field(default_factory=list)
    schema: str = SCHEMA_CRATE

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "id": self.id,
            "name": self.name or self.id,
            "version": self.version,
            "defaults": {
                "phraseBars": self.default_phrase_bars,
                "energy": {"min": self.default_energy_min,
                           "max": self.default_energy_max},
                "allowedTechniques": list(self.allowed_techniques),
                "fallbackTransition": self.fallback_transition,
            },
            "tracks": list(self.tracks),
            "cues": {k: [c.to_dict() for c in v] for k, v in self.cues.items()},
            "edges": list(self.curated_edges),
        }
