# HyperMix authoring guide

## Crates

A **crate** is the authoring unit: a curated set of tracks, manual cues, moods,
and sequencing intent. Schema `hypermix.crate.v1`.

```json
{
  "schema": "hypermix.crate.v1",
  "id": "my-crate",
  "name": "My Crate",
  "defaults": { "phraseBars": 8 },
  "tracks": [
    {
      "id": "track-1",
      "path": "audio/track1.wav",
      "rating": 8,
      "cues": [
        { "id": "hero-1", "kind": "hero", "sample": 441000 }
      ]
    }
  ],
  "moods": [{ "id": "peak", "energyMin": 0.7 }],
  "sequencing": { "mode": "weighted-random", "seed": 42 }
}
```

## Cues

Cue kinds: `intro`, `outro`, `build`, `drop`, `hero`, `breakdown`, `riser`,
`impact`, `vocal`, `groove`, `bridge`, `custom`.

- **Sample positions are integer sample indices** at 48 kHz.
- Cues are snapped to the phrase grid per the crate's snap mode (11 modes).
- When a source file changes, auto cues go stale (amber) until explicit resnap;
  manual cues stay authoritative.

## Segments

The compiler emits 8/16/32-bar segments per cue, content-addressed under
`var/segment/<short_hash>.wav`. Edges are declicked only — no time-stretch in
segments.

## Edges

Curated edges are compiled first; a sparse auto-graph then guarantees every
segment has at least one exit. Each edge is a `PlannedTransition` rendered
through the registry, with a `TransitionTimeline` (samples), events, quality,
and the fallback chain.

## CLI

```
python -m src.hypermix.cli crate compile crates/demo/crate.json --out packs/demo
python -m src.hypermix.cli pack render packs/demo --out renders/golden --seed 42
```

## From a folder of music (auto-cue)

`scripts/crate_from_folder.py` scans a directory of audio files, canonicalizes
each one, runs the analyzer, and writes a crate.json with auto-detected `hero`
cues (top-scoring `hero_candidates`, snapped to the nearest bar). Manual cues in
an existing crate are never overwritten.

```
# 1. Drop audio (wav/mp3/flac/ogg/m4a/aac/aiff) into ./music
# 2. Generate + compile a pack:
.\.venv-hypermix\Scripts\python.exe scripts/crate_from_folder.py \
    --music-dir music --out crates/my-library/crate.json \
    --crate-id my-library --name "My Library" --cues-per-track 3 --compile
# 3. Render a deterministic reference mix:
.\.venv-hypermix\Scripts\python.exe -m src.hypermix.cli pack render \
    packs/my-library --out renders/my-library --seed 42
```

The crate's `tracks`/`cues` use repo-root-relative POSIX paths. Re-run the
script after editing audio: auto cues are re-derived; manual cues stay put.

## Golden render

`pack render` produces `golden.wav`, `golden.timeline.json`, `golden.events.json`,
and `golden.report.json` — a deterministic reference of exactly what the player
would do with the same seed.
