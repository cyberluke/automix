# HyperMix architecture

HyperMix turns curated music into a **graph of high-value musical moments** and
a **sample-clock runtime** that jumps between them with DJ-grade transitions.

## Three products

| Product | Language | Constraints |
|---|---|---|
| Compiler | Python (`src/hypermix/`) | Heavy deps OK (librosa, scipy, FFmpeg) |
| Player | TypeScript (`packages/hypermix-player/`) | Zero Python / localhost / VS Code deps |
| Integration bundle | Assembled | For Kelvin / Zoo Code webviews |

## Pipeline

```
sources ──► canonicalize (48k/2ch/f32) ──► analyze (adapter over club_mixer)
        ──► cues (manual authoritative, snapped) ──► segment compiler
        ──► edge compiler (curated + sparse auto-graph) ──► MixGraph
        ──► PackWriter (manifest + integrity) ──► .hmxpack
```

The player loads the pack, picks segments with a seeded Director, and schedules
transitions on the Web Audio clock at integer-sample precision.

## Hard rules

- Canonical time = **integer sample index**. Seconds are derived views only.
- Canonical audio = 48000 Hz, 2 channels, float32.
- Manual cues are authoritative; auto-detected cues are suggestions.
- All behavior is deterministic given a seed (mulberry32 / `random.Random`).
- Writes are atomic (`os.replace`); caches are content-addressed per layer.
- **No automated tests** (embargo §1.7); validation is via smoke runs + golden renders.

## Layers & caches

`LayeredCache` separates seven layers: canonical, analysis, waveform, segment,
transition, pack, render. Each layer has its own version constant; bumping a
version invalidates only that layer.

## Transition system

`TransitionRegistry` holds all 19 techniques. Universal fallbacks are
`rewind`, `slam`, `echo_cut`, `backspin`. Capability-gated techniques
(acapella, melodic mix, modulation, thematic handoff, triple drop) raise
`CapabilityMiss` when stems are absent and the planner substitutes a fallback.

## Director

`Director.choose_next` scores candidates on rating, mood, energy match, edge
quality, novelty, and artist repetition. Modes: `deterministic` (best score) or
`weighted-random` (seeded).
