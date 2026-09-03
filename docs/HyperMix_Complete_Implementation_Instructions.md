# HyperMix — Complete Implementation Instructions

**Repository:** `D:\_SATIN_AI_2\automix\`  
**GitHub fork:** `cyberluke/automix`  
**Target integration:** Roo Code / Zoo Code / Kelvin Clyne VS Code extension webview  
**Execution mode:** implement the complete architecture now, across all phases and all vertical slices. Do not stop after a prototype or first vertical slice.

---

# 0. Mission

Transform the existing `automix` fork into **HyperMix**, a phrase-native, sample-clock-driven music compiler and playback runtime optimized for:

- hyper-frantic, nonstop DJ-style flow;
- manual/curated hot cues;
- phrase matching rather than generic playlist crossfades;
- immediate jumping between the strongest sections of tracks;
- deterministic offline compilation;
- sample-accurate runtime scheduling;
- runtime hot-swap at the next beat/bar/phrase boundary;
- deliberate DJ transition masking such as rewind, backspin, echo cut, slam, stutter and drum-roll;
- zero requirement for a full Traktor / Serato / Elastique-style realtime DJ engine;
- eventual integration into Kelvin Clyne / Zoo Code where AI personas can trigger music and avatar events while the user works.

The core product idea is:

> **Do not build a realtime beatmatching workstation. Build a curated, phrase-aware compiler plus a deterministic sample-clock player.**

The system should feel like a highly edited DJ megamix where intros, filler sections and dead air have been removed and the strongest musical phrases are connected aggressively.

The primary target music is modern high-energy electronic music, especially melodic / trancey / bouncy / hard-groove techno, but the implementation must not hard-code a genre or BPM range.

---

# 1. Non-negotiable engineering rules

## 1.1 Implement all phases

Do not stop after:

- a schema;
- a CLI prototype;
- one renderer;
- one transition;
- a demo HTML page;
- a standalone player;
- a sidecar;
- or an integration stub.

Implement the complete system described in this document.

Intermediate commits are allowed, but the task is complete only when the full architecture is present and the integration bundle can be consumed by Kelvin/Zoo Code.

## 1.2 Preserve useful upstream behavior

The current fork already contains valuable working primitives:

- `src/club_mixer.py`
- `club_server.py`
- `templates/club_player.html`
- phrase/downbeat logic;
- structural segmentation;
- `t1 / t2 / t3` transition semantics;
- equal-power fades;
- three-band bass handoff;
- streaming/chunk scheduling;
- optional stems;
- current DJ-technique documentation.

Do **not** rewrite or delete these prematurely.

Treat the existing implementation as a reference and donor layer.

Add HyperMix beside it, migrate useful logic through explicit adapters, and only remove legacy paths when the replacement is proven and no longer needed.

## 1.3 Sample indices are canonical

Inside HyperMix, canonical time is:

```text
integer sample index
```

not floating-point seconds.

Every canonical asset must have an explicit sample rate.

For HyperMix use:

```text
sampleRate = 48000
channels   = 2
```

Do not globally change legacy `src/settings.py::SR` on the first pass. Existing club/server paths currently use 44.1 kHz. HyperMix must have its own configuration and canonicalization boundary so the existing implementation remains usable during migration.

All UI seconds, timestamps and progress bars are derived views:

```text
seconds = sample / sampleRate
```

All phrase boundaries, cue points, transition boundaries and avatar events must ultimately resolve to exact integer sample positions.

## 1.4 No hidden realtime tempo engine

Do not introduce a mandatory:

- phase vocoder;
- Elastique equivalent;
- WSOLA realtime engine;
- master-tempo engine;
- pitch-preserving realtime BPM matching system.

HyperMix must work extremely well without any of these.

A future micro-stretch backend may be added through an adapter, but the default production path is phrase selection plus reset-style transitions.

## 1.5 Manual cues are authoritative

Automated analysis is advisory.

The system may detect:

- beats;
- downbeats;
- bars;
- phrases;
- structural sections;
- energy;
- candidate drops;
- candidate mix-in/mix-out points.

But once a curator manually places or confirms a cue, the manual cue wins.

Never silently move an explicitly locked cue during recompilation.

## 1.6 No copyrighted source music in the public repository

Personal source tracks, private curated packs and rendered mixes must be excluded from Git.

Only:

- metadata;
- schemas;
- code;
- generated royalty-free demo assets;
- existing repo demo material

may be committed publicly unless explicit rights are known.

Create appropriate `.gitignore` entries for local crates, personal audio and compiled private packs.

## 1.7 Test embargo

Do **not** create new automated test suites and do **not** run test runners.

Specifically, do not add or run:

- pytest;
- unittest suites;
- Jest;
- Vitest;
- Playwright;
- Cypress;
- snapshot tests;
- new automated integration tests.

Implementation verification may use:

- imports;
- build/type-check commands;
- deterministic hashes;
- diagnostic CLI commands;
- existing demo playback;
- generated manifests;
- manual runtime inspection.

Do not let the absence of tests become a reason to stop implementation.

---

# 2. Current repository facts to preserve

The current fork already has a surprisingly useful foundation.

## 2.1 `src/club_mixer.py`

This is the primary donor implementation.

It already models:

```text
PhraseGrid
TransitionPlan
t1
t2
t3
downbeats
bar energy
sections
transition type
overlap_samples
```

It performs:

- beat tracking;
- downbeat phase estimation;
- per-bar energy analysis;
- self-similarity / novelty structural segmentation;
- downbeat-snapped section boundaries;
- phrase-aware transition planning;
- low/high section classification;
- relaxed / rolling / double-drop transition selection;
- rendering primitives;
- EQ/bass handoff;
- loudness handling.

Keep this file working while extracting reusable HyperMix modules.

## 2.2 `docs/BOILER_ROOM_MIXING_PLAN.md`

Treat this as part of the design source.

Important concepts to preserve:

- transition as `t1 / t2 / t3`;
- switch point `t2` as the musically critical boundary;
- switch on downbeat / phrase boundary;
- 4/8/16/32 bar musical structure;
- deliberate double-drop behavior;
- structural mix-in / mix-out logic;
- bass handoff;
- multiple transition types rather than one generic crossfade.

HyperMix will change the **tempo philosophy** and **density of edits**, not throw away the musical reasoning.

## 2.3 `docs/dj_techniques_knowledge_base.md`

Do not leave this as passive prose.

Convert the useful parts into an executable technique registry / transition DSL.

At minimum support executable forms for:

- phrase match;
- double drop;
- backspin;
- rewind/reverse;
- power down;
- power up;
- loop transition;
- breakdown-to-build;
- energy build;
- hot cue mixing;
- transformer cuts;
- drop on the one;
- back-and-forth switching;
- drum roll / percussion bridge;
- slam/cut;
- echo cut.

Techniques requiring semantic/stem capabilities such as acapella layering or thematic handoff must still exist in the registry, but can declare explicit capability requirements and deterministic fallbacks.

## 2.4 `club_server.py`

The current server already provides useful ideas:

- lazy audio loading;
- bounded sessions;
- chunked rendering;
- background producer;
- `/healthz`;
- progressive output;
- markers;
- resource cleanup.

Do not make the future Kelvin runtime depend on this Flask server.

Instead:

- reuse useful orchestration concepts;
- add a clean stdio sidecar for authoring/compilation;
- make final pack playback independent of Python.

## 2.5 `templates/club_player.html`

This contains the seed of the future TypeScript runtime:

- `AudioContext`;
- prebuffer;
- lookahead;
- `decodeAudioData`;
- `AudioBufferSourceNode`;
- exact scheduled `start(nextTime)`;
- marker-driven UI state;
- output analyser;
- gapless chunk sequence.

Extract these concepts into a reusable TypeScript package rather than keeping them embedded in HTML.

---

# 3. Target architecture

Implement this complete architecture:

```text
                         ┌───────────────────────────────┐
                         │       HYPERMIX AUTHORING      │
                         │                               │
source audio ───────────►│ canonicalizer                │
                         │ analyzer                     │
                         │ cue editor                   │
                         │ phrase compiler              │
                         │ transition compiler          │
                         │ set / graph compiler         │
                         └──────────────┬────────────────┘
                                        │
                                        ▼
                               .hmxpack artifact
                                        │
                  ┌─────────────────────┴─────────────────────┐
                  │                                           │
                  ▼                                           ▼
       deterministic golden render                    phrase-native assets
              full-set WAV                             + transition edges
                  │                                           │
                  └─────────────────────┬─────────────────────┘
                                        ▼
                           ┌────────────────────────┐
                           │ HyperMixPlayer (TS)    │
                           │ Web Audio sample clock │
                           └────────────┬───────────┘
                                        │
                           hot-swap / phrase events
                                        │
                                        ▼
                            HyperMix UI Bridge API
                                        │
                                        ▼
                       Kelvin / Zoo Code VS Code webview
                                        │
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
                 avatars             persona mood       work events
```

There are **three intentionally separate products** inside one repository:

1. **HyperMix Compiler**
   - Python.
   - Offline analysis and rendering.
   - Deterministic.
   - Heavy dependencies allowed.

2. **HyperMix Player**
   - TypeScript.
   - Browser/Webview compatible.
   - No Python dependency.
   - No localhost dependency.
   - Small bundle.
   - Runtime hot-swap.

3. **HyperMix Integration Bundle**
   - stable types;
   - schemas;
   - player bundle;
   - bridge contracts;
   - sidecar launcher metadata;
   - documentation for Kelvin/Zoo Code.

---

# 4. Required repository layout

Create or converge toward:

```text
automix/
├─ src/
│  ├─ club_mixer.py
│  ├─ ...
│  └─ hypermix/
│     ├─ __init__.py
│     ├─ config.py
│     ├─ model.py
│     ├─ errors.py
│     ├─ hashing.py
│     ├─ canonicalize.py
│     ├─ audio_io.py
│     ├─ cache.py
│     ├─ analysis/
│     │  ├─ base.py
│     │  ├─ automix_analyzer.py
│     │  ├─ structure.py
│     │  ├─ energy.py
│     │  └─ peaks.py
│     ├─ cues/
│     │  ├─ resolver.py
│     │  ├─ snapping.py
│     │  └─ scoring.py
│     ├─ transitions/
│     │  ├─ model.py
│     │  ├─ registry.py
│     │  ├─ planner.py
│     │  ├─ renderer.py
│     │  ├─ phrase_match.py
│     │  ├─ double_drop.py
│     │  ├─ slam.py
│     │  ├─ rewind.py
│     │  ├─ backspin.py
│     │  ├─ echo_cut.py
│     │  ├─ stutter.py
│     │  ├─ drum_roll.py
│     │  ├─ loop_transition.py
│     │  ├─ power.py
│     │  └─ back_and_forth.py
│     ├─ compiler/
│     │  ├─ crate_compiler.py
│     │  ├─ segment_compiler.py
│     │  ├─ edge_compiler.py
│     │  ├─ set_compiler.py
│     │  ├─ pack_writer.py
│     │  └─ deterministic_render.py
│     ├─ director/
│     │  ├─ graph.py
│     │  ├─ selector.py
│     │  └─ seeded_rng.py
│     ├─ sidecar/
│     │  ├─ __main__.py
│     │  ├─ protocol.py
│     │  ├─ server.py
│     │  ├─ handlers.py
│     │  └─ diagnostics.py
│     └─ cli/
│        └─ __main__.py
│
├─ contracts/
│  ├─ hypermix-track.v1.schema.json
│  ├─ hypermix-crate.v1.schema.json
│  ├─ hypermix-pack.v1.schema.json
│  ├─ hypermix-transition.v1.schema.json
│  ├─ hypermix-events.v1.schema.json
│  └─ hypermix-sidecar.v1.schema.json
│
├─ packages/
│  ├─ hypermix-player/
│  │  ├─ package.json
│  │  ├─ tsconfig.json
│  │  ├─ src/
│  │  │  ├─ index.ts
│  │  │  ├─ types.ts
│  │  │  ├─ HyperMixPlayer.ts
│  │  │  ├─ HyperMixScheduler.ts
│  │  │  ├─ HyperMixAssetLoader.ts
│  │  │  ├─ HyperMixClock.ts
│  │  │  ├─ HyperMixHotSwap.ts
│  │  │  ├─ HyperMixStateMachine.ts
│  │  │  ├─ HyperMixEventBus.ts
│  │  │  └─ HyperMixDiagnostics.ts
│  │  └─ dist/
│  │
│  ├─ hypermix-bridge/
│  │  ├─ package.json
│  │  └─ src/
│  │     ├─ index.ts
│  │     ├─ messages.ts
│  │     ├─ commands.ts
│  │     └─ types.ts
│  │
│  └─ hypermix-studio/
│     ├─ package.json
│     ├─ src/
│     │  ├─ main.ts
│     │  ├─ editor/
│     │  ├─ waveform/
│     │  ├─ cues/
│     │  └─ transitions/
│     └─ dist/
│
├─ crates/
│  ├─ demo/
│  │  └─ crate.json
│  └─ .gitkeep
│
├─ packs/
│  ├─ demo/
│  └─ .gitkeep
│
├─ tools/
│  ├─ bootstrap-windows.ps1
│  ├─ build-player.ps1
│  ├─ build-sidecar-windows.ps1
│  ├─ build-integration-bundle.ps1
│  └─ inspect-pack.py
│
├─ integration/
│  └─ kelvin/
│     ├─ README.md
│     ├─ KELVIN_INTEGRATION.md
│     ├─ package.fragment.example.json
│     ├─ HyperMixService.example.ts
│     └─ HyperMixWebviewBridge.example.ts
│
├─ dist/
│  └─ integration-bundle/
│
└─ docs/
   ├─ existing docs...
   ├─ HYPERMIX_ARCHITECTURE.md
   ├─ HYPERMIX_AUTHORING.md
   ├─ HYPERMIX_PACK_FORMAT.md
   ├─ HYPERMIX_TRANSITION_DSL.md
   ├─ HYPERMIX_RUNTIME_API.md
   ├─ HYPERMIX_SIDECAR_PROTOCOL.md
   ├─ HYPERMIX_KELVIN_INTEGRATION.md
   └─ HYPERMIX_OPERATIONS.md
```

Do not move unrelated upstream files merely to make the tree pretty.

---

# 5. Configuration and contracts

Create `src/hypermix/config.py`.

Defaults:

```python
HYPERMIX_SAMPLE_RATE = 48_000
HYPERMIX_CHANNELS = 2
HYPERMIX_PHRASE_BARS = 8
HYPERMIX_CACHE_VERSION = 1
HYPERMIX_RENDER_HEADROOM_DBTP = -1.0
HYPERMIX_DEFAULT_LOOKAHEAD_SEC = 6.0
HYPERMIX_MIN_LOOKAHEAD_SEC = 2.0
HYPERMIX_MAX_LOOKAHEAD_SEC = 15.0
HYPERMIX_DEFAULT_HOTSWAP = "nextPhrase"
HYPERMIX_DEFAULT_FALLBACK_TRANSITION = "rewind"
```

Every sound-affecting value must be explicit in a config object and included in the relevant artifact/cache config hash.

Version all contracts independently:

```text
hypermix.track.v1
hypermix.crate.v1
hypermix.pack.v1
hypermix.transition.v1
hypermix.events.v1
hypermix.webview.v1
hypermix.sidecar.v1
```

Never silently reinterpret an old manifest.

---

# 6. Domain model

Create strongly typed Python dataclasses and equivalent TypeScript interfaces.

## 6.1 Track

```json
{
  "schema": "hypermix.track.v1",
  "id": "malugi-mcyl-knees-break",
  "artist": "Malugi, MCYL",
  "title": "Knees Break",
  "source": {
    "path": "D:/Music/Knees Break.wav",
    "sha256": "...",
    "canonicalSha256": "..."
  },
  "audio": {
    "sampleRate": 48000,
    "channels": 2,
    "samples": 10485760,
    "durationSec": 218.4533333333
  },
  "analysis": {
    "bpm": 150.12,
    "downbeats": [],
    "bars": [],
    "phrases": [],
    "sections": []
  },
  "tags": ["trancey", "melodic", "bouncy", "heavy-bass"],
  "energy": 0.96,
  "cues": []
}
```

## 6.2 Cue

```json
{
  "id": "hero.01",
  "sample": 4377792,
  "kind": "hero",
  "locked": true,
  "beat": 224,
  "bar": 56,
  "phrase": 7,
  "rating": 10,
  "energy": 0.98,
  "allowedEntry": true,
  "allowedExit": true,
  "preferredBars": [8, 16, 32],
  "tags": ["drop", "hook", "vocal-free"]
}
```

Required cue kinds:

```text
intro
build
breakdown
drop
hero
hook
vocal
outro
transition-in
transition-out
reset
custom
```

## 6.3 Phrase segment

```json
{
  "id": "knees-break.hero.01.16b",
  "trackId": "malugi-mcyl-knees-break",
  "startSample": 4377792,
  "endSample": 5606592,
  "lengthSamples": 1228800,
  "bars": 16,
  "bpm": 150.0,
  "entryClass": "downbeat",
  "exitClass": "phrase",
  "energyStart": 0.94,
  "energyEnd": 0.98,
  "tags": ["hero", "melodic", "heavy-bass"],
  "asset": "audio/segments/knees-break.hero.01.16b.wav"
}
```

## 6.4 Transition edge

HyperMix is a graph, not merely a playlist.

Nodes are phrase segments. Edges are valid transitions.

```json
{
  "id": "edge-knees-to-holdon-rewind",
  "from": "knees-break.hero.01.16b",
  "to": "hold-on.hero.02.16b",
  "technique": "rewind",
  "timeline": {
    "t1Sample": 0,
    "t2Sample": 72192,
    "t3Sample": 96000
  },
  "tempoContinuityRequired": false,
  "phraseSafe": true,
  "asset": "audio/transitions/edge-knees-to-holdon-rewind.wav",
  "events": []
}
```

If a high-quality precompiled edge exists, use it. If not, use a universal reset transition such as rewind/slam/echo-cut/backspin.

---

# 7. Canonical audio ingest

Implement `src/hypermix/canonicalize.py`.

Target:

```text
WAV
48,000 Hz
stereo
float32 during authoring/rendering
```

Canonicalization must:

1. decode input;
2. remove irrelevant source metadata from canonical identity;
3. resample deterministically;
4. normalize channel layout;
5. preserve exact sample count;
6. write atomically;
7. compute SHA-256;
8. cache by source content hash + canonicalization version.

FFmpeg shape:

```powershell
ffmpeg -y `
  -i input.ext `
  -map_metadata -1 `
  -vn `
  -ac 2 `
  -ar 48000 `
  -c:a pcm_f32le `
  canonical.wav
```

Do not use compressed audio as the authoritative timing source.

Cache key:

```text
sha256(source bytes)
+
canonicalizer version
+
sample rate
+
channel layout
```

Use atomic temp-file + rename. Never trust cache metadata whose hash/length does not match.

---

# 8. Analysis pipeline

Create:

```python
class HyperMixAnalyzer(Protocol):
    def analyze(self, audio: CanonicalAudio) -> TrackAnalysis:
        ...
```

Default backend:

```text
AutomixAnalyzer
```

It delegates to existing `build_phrase_grid()` and related primitives.

Convert returned seconds to integer sample indices immediately.

Return:

```text
estimated BPM
beat samples
downbeat samples
bar boundaries
phrase boundaries
bar energy
phrase energy
structural sections
candidate hero regions
candidate entry cues
candidate exit cues
confidence values
```

Default phrase basis is 8 bars, while supporting 4/8/16/32.

Support manual `phrasePhaseOffsetBars` when automatic phrase phase is wrong.

Create heuristic HERO ranking from energy, onset density, low-frequency energy, spectral flux, novelty, repetition and optional tags. This is advisory only.

Design optional analyzer adapters for future `BeatThisAnalyzer`, `AllInOneAnalyzer`, etc., but do not make them mandatory.

---

# 9. Curated crate format

A crate is the human-authored compiler input.

```json
{
  "schema": "hypermix.crate.v1",
  "id": "frantic-german-melodic-001",
  "title": "Frantic German Melodic 001",
  "defaults": {
    "phraseBars": 8,
    "preferredSegmentBars": [8, 16, 32],
    "fallbackTransition": "rewind"
  },
  "tracks": [
    {
      "trackFile": "tracks/knees-break.json",
      "enabled": true,
      "weight": 1.0
    }
  ],
  "mood": {
    "tags": ["melodic", "hard", "bouncy", "nonstop"],
    "energyMin": 0.85,
    "energyMax": 1.0
  },
  "sequencing": {
    "allowRepeatTrack": false,
    "maxConsecutiveArtist": 1,
    "seed": 271
  }
}
```

The user must be able to maintain this manually in JSON. Studio edits the same format.

Optional discovery metadata is permitted:

```json
{
  "discovery": {
    "seed": "Funk Tribu - Hold On",
    "similarity": 0.931,
    "source": "cosine"
  }
}
```

HyperMix must not depend on the discovery service.

---

# 10. Cue snapping and stale handling

Support:

```text
nearestBeat
nearestDownbeat
nearestBar
nearestPhrase
previousBeat
previousBar
previousPhrase
nextBeat
nextBar
nextPhrase
none
```

Editor shows raw sample, snapped sample, delta ms and delta samples.

If `locked=true`, never silently resnap.

If canonical source changes, mark cues stale rather than moving them.

---

# 11. Transition architecture

All transitions implement a common interface:

```python
class TransitionTechnique(Protocol):
    id: str
    capabilities: TransitionCapabilities

    def plan(self, outgoing, incoming, context) -> TransitionPlan:
        ...

    def render(self, plan, assets) -> RenderedTransition:
        ...
```

Keep universal:

```text
t1 = transition begins
t2 = musical switch point
t3 = transition completes
```

Store all as integer samples.

Each technique declares:

```json
{
  "tempoContinuityRequired": false,
  "requiresStems": false,
  "requiresHarmony": false,
  "requiresVocalStem": false,
  "phraseSafe": true,
  "supportsHotSwap": true
}
```

---

# 12. Implement the full transition registry

## `phrase_match`

Use existing Automix phrase/downbeat logic. It can use equal-power overlap and bass handoff. If BPMs are incompatible and no stretch backend is enabled, route to reset transition.

## `double_drop`

Both segments high-energy and phrase-aligned. Align impact points. Control bass collision. If tempos cannot be synchronized safely, fall back to `slam` or `rewind`.

## `slam`

Universal instant transition:

- outgoing ends on phrase/downbeat;
- 10–50 ms click-safe splice;
- optional impact FX;
- incoming begins exactly at curated entry.

No tempo continuity requirement.

## `rewind`

Support:

### generic

```text
outgoing cut -> generic rewind FX -> incoming drop
```

### source-derived

1. take outgoing tail;
2. reverse;
3. optional filter ramp;
4. optional acceleration/pitch contour;
5. shape gain;
6. deliberate reset;
7. incoming starts on exact cue.

Prefer source-derived during compilation.

## `backspin`

Offline DJ-style decelerating tail using deterministic variable-rate resampling. No realtime master-tempo dependency.

## `echo_cut`

Offline-render outgoing delay/echo tail. Parameters include beat fraction, feedback, filtering, tail length and wet gain. Incoming may start underneath tail.

## `stutter`

Support source slices:

```text
1/2 beat
1/4 beat
1/8 beat
1/16 beat
```

Patterns may escalate before impact.

## `drum_roll`

Source-derived escalating roll via repeated slices, shortening subdivisions, filtering/gain and final impact at `t2`.

## `loop_transition`

Beat/bar-safe loops:

```text
1 beat
2 beats
1 bar
2 bars
4 bars
```

with repeat count.

## `power_down`

Energy collapse via filtering, gain and optional offline slowdown/reset.

## `power_up`

Phrase-aligned build using filters, repeated percussion, optional riser and incoming drop.

## `drop_on_the_one`

Hard cut exactly on incoming downbeat.

## `back_and_forth`

Alternate A/B by bar blocks and settle on B. Only if tempo/rhythm compatibility is sufficient.

## `transformer_cuts`

Rhythmic gain gating on beat subdivisions. No scratch engine.

## Capability-gated advanced registry entries

Register:

```text
acapella_overlay
melodic_mix
modulation
thematic_handoff
triple_drop
```

Execute when capabilities exist. Otherwise return explicit capability miss and choose deterministic fallback.

Never pretend stem-based processing occurred when stems are absent.

---

# 13. Transition DSL

Turn the DJ knowledge base into data-driven executable definitions.

Example:

```yaml
id: rewind_drop

capabilities:
  supportsHotSwap: true
  tempoContinuityRequired: false
  requiresStems: false

outgoing:
  allowedKinds: [hero, drop, hook]

timing:
  anchor: nextPhrase

fx:
  - type: sourceReverse
    bars: 0.5

  - type: filter
    mode: highpass
    fromHz: 80
    toHz: 3000

switch:
  at: t2

incoming:
  requireDownbeat: true
  preferredKinds: [drop, hero]

fallback: [slam]
```

Implement strongly typed internal representation. JSON is fine if YAML would add unnecessary dependency. Do not create one giant transition `if/elif`.

---

# 14. Segment compiler

Compile useful lengths around curated cues:

```text
8 bars
16 bars
32 bars
```

subject to bounds and cue preferences.

Use content-addressed physical assets:

```text
packs/<pack>/audio/segments/<sha256>.wav
```

Manifest IDs remain readable.

Do not randomly fade every phrase boundary. Preserve downbeat transients. Apply tiny de-click envelopes only when needed, and let transition renderers own transition boundaries.

---

# 15. Transition edge compiler

Do not pre-render an N×N×technique explosion.

Compile edges based on:

- curated adjacency;
- explicit choices;
- graph neighbors;
- fallback needs.

Every playable segment must have at least one safe exit path.

---

# 16. Director / sequencing engine

Implement lightweight deterministic selection.

Inputs:

- curated weights;
- mood tags;
- energy;
- segment rating;
- transition quality;
- recent history;
- persona preferences;
- optional discovery similarity.

Scoring can combine:

```text
segment_rating
+ mood_match
+ energy_match
+ transition_quality
+ novelty_bonus
- repetition_penalty
```

Use seeded PRNG.

Modes:

```text
deterministic
weighted-random
manual
```

Same pack + seed + commands must produce same choices.

---

# 17. `.hmxpack`

Support unpacked authoring directory and ZIP-compatible distribution archive.

Required internal layout:

```text
manifest.json
audio/
events/
metadata/
```

Optional:

```text
renders/
waveforms/
artwork/
```

Manifest:

```json
{
  "schema": "hypermix.pack.v1",
  "packId": "frantic-001",
  "version": 1,
  "sampleRate": 48000,
  "channels": 2,
  "createdBy": {
    "compiler": "hypermix",
    "compilerVersion": "..."
  },
  "segments": [],
  "transitions": [],
  "graph": {},
  "events": [],
  "entrySegments": ["hold-on.hero.01.16b"],
  "fallbackTransition": "rewind",
  "integrity": {
    "manifestSha256": "...",
    "assets": {}
  }
}
```

Every asset has SHA-256, byte length and expected sample count for PCM.

Protect archive extraction against path traversal, absolute paths, symlink escape and decompression bombs.

---

# 18. Golden deterministic render

Optional per pack:

```text
renders/golden.wav
renders/golden.timeline.json
renders/golden.events.json
renders/golden.report.json
```

Input:

```text
pack
seed
entry segment
duration/max segments
```

Report includes:

```text
source hashes
segment sequence
transition sequence
sample positions
total samples
peak
LUFS if available
warnings
compiler version
```

---

# 19. HyperMix Studio

Build the standalone authoring UI now.

Required:

## Library view

- tracks;
- BPM;
- analysis state;
- tags;
- energy;
- cue count;
- stale/hash state.

## Waveform

Generate decimated peak data in Python:

```json
{
  "sampleRate": 48000,
  "sourceSamples": 12000000,
  "bucketSize": 1024,
  "min": [],
  "max": []
}
```

Render with Canvas. Do not send full PCM just to draw waveform.

## Grid overlays

Show beats, downbeats, bars, phrases, sections and cues.

## Cue editing

Support add/delete/lock/unlock/kind/rating/preferred length and all snapping modes.

Provide instant 8/16/32-bar audition.

## Transition audition

Choose outgoing, incoming and technique; render preview, play it, promote it to curated edge.

## Crate editor

Edit tracks, mood, weights, seed, allowed transitions, fallback and persona tags.

## Compile controls

```text
Analyze changed
Compile segments
Compile transitions
Build pack
Render golden mix
Build integration bundle
```

The UI must call real sidecar compiler operations.

---

# 20. `hypermixd` sidecar

Use JSON-RPC-style NDJSON over stdin/stdout.

No HTTP requirement.

`stdout` is protocol-only. Human logs go to stderr/files.

Request:

```json
{
  "jsonrpc": "2.0",
  "id": "42",
  "method": "pack.compile",
  "params": {
    "crate": "crates/private/frantic.json"
  }
}
```

Response:

```json
{
  "jsonrpc": "2.0",
  "id": "42",
  "result": {
    "packPath": "...",
    "packId": "frantic-001"
  }
}
```

Progress event:

```json
{
  "jsonrpc": "2.0",
  "method": "event.progress",
  "params": {
    "operationId": "...",
    "phase": "transition.compile",
    "done": 14,
    "total": 42
  }
}
```

Required methods:

```text
health
capabilities

track.import
track.analyze
track.get

crate.open
crate.save

transition.preview

pack.compile
pack.inspect
pack.renderGolden

cache.stats
cache.prune

diagnostics.snapshot

operation.cancel
shutdown
```

Use bounded worker concurrency for decode, analysis and render jobs.

Cancellation stops at safe boundaries and removes temp files.

---

# 21. Windows development and production bundles

Create `tools/bootstrap-windows.ps1`.

It must:

1. detect usable Python;
2. create `.venv-hypermix`;
3. install pinned HyperMix requirements;
4. verify FFmpeg;
5. print actionable diagnostics;
6. never alter system Python;
7. expose sidecar/Studio/compiler commands.

Use a dedicated requirements file/lock for HyperMix.

For production create:

```text
tools/build-sidecar-windows.ps1
```

Output:

```text
dist/sidecar/win32-x64/
  hypermixd.exe
  ...
  BUILD_INFO.json
```

Prefer Nuitka standalone directory first. Do not make playback depend on this binary.

---

# 22. TypeScript `hypermix-player`

Extract the current `club_player.html` runtime ideas into a clean library.

No VS Code imports inside the player.

Public API:

```ts
export interface HyperMixPlayer {
  initialize(options: HyperMixPlayerOptions): Promise<void>

  loadPack(source: HyperMixPackSource): Promise<void>
  unloadPack(): Promise<void>

  arm(): Promise<HyperMixArmResult>

  play(options?: PlayOptions): Promise<void>
  pause(): Promise<void>
  stop(): Promise<void>

  seekToSample(sample: bigint | number): Promise<void>

  hotSwap(request: HyperMixHotSwapRequest): Promise<HyperMixHotSwapResult>

  setGain(value: number): void
  setMuted(value: boolean): void

  getState(): HyperMixPlayerState
  getPosition(): HyperMixPosition
  getDiagnostics(): HyperMixDiagnosticsSnapshot

  on<K extends keyof HyperMixEventMap>(
    type: K,
    handler: (event: HyperMixEventMap[K]) => void
  ): Disposable

  dispose(): Promise<void>
}
```

Hot-swap request:

```ts
interface HyperMixHotSwapRequest {
  targetSegmentId?: string
  targetTrackId?: string
  targetMood?: string[]

  transition?:
    | "auto"
    | "phraseMatch"
    | "doubleDrop"
    | "slam"
    | "rewind"
    | "backspin"
    | "echoCut"
    | "stutter"
    | "drumRoll"

  timing:
    | "immediate"
    | "nextBeat"
    | "nextBar"
    | "nextPhrase"

  maxWaitBars?: number
}
```

---

# 23. Player state machine

Implement:

```text
cold
initializing
armed
ready
playing
paused
swapping
stopping
error
disposed
```

Reject illegal transitions predictably. Do not scatter booleans across the runtime.

---

# 24. Sample-clock scheduler

The audio clock is authoritative.

Never use `setTimeout()` as the musical clock.

Maintain:

```text
epochContextTime
epochTimelineSample
sampleRate
```

Mapping:

```text
contextTime =
  epochContextTime
  + (targetSample - epochTimelineSample) / sampleRate
```

Schedule source nodes with Web Audio `start()` against context time.

Use a configurable lookahead, default around 6 seconds.

Pause stores exact logical sample and invalidates future scheduling generation. Resume creates a new epoch.

Reuse the existing generation-token concept so stale async decodes cannot schedule audio after restart/seek/hot-swap.

---

# 25. Runtime audio graph

Keep DSP tiny:

```text
source nodes
     │
segment gain
     │
master gain
     ├── analyser
     ▼
destination
```

Canonical transition sound comes from precompiled transition assets.

Optional compressor/limiter only if useful.

---

# 26. Runtime modes

Implement both:

## `compiled-set`

Consumes deterministic timeline.

Best for exact soundtrack/avatar choreography.

## `graph`

Assembles:

```text
segment -> transition -> segment -> ...
```

from precompiled assets.

Best for HYPER hot-swap, persona changes and interactive work events.

Same scheduler for both.

---

# 27. HYPER hot-swap algorithm

1. receive request;
2. read logical sample;
3. identify current segment/phrase;
4. resolve requested boundary;
5. choose target;
6. query graph;
7. prefer high-quality precompiled edge;
8. otherwise use universal fallback;
9. preload/decode before deadline;
10. schedule transition;
11. cancel only future sources after handoff;
12. emit scheduled event;
13. emit executed event at actual switch.

Deadline miss must never create silence.

Fallback order:

1. postpone to next equivalent boundary;
2. use cached universal transition;
3. continue current/next safe phrase;
4. report degraded swap.

---

# 28. Decoded asset cache

Priorities:

```text
P0 current segment
P0 scheduled transition
P0 next segment

P1 likely next transitions
P1 likely targets

P2 background graph neighbors
```

Bound by decoded bytes and asset count.

Do not decode whole packs into RAM.

---

# 29. Web Audio auto-start / arming

Do not assume audio with sound can autoplay.

Implement:

```text
music.enabled
music.autoStart
```

Flow:

1. webview opens;
2. player initializes;
3. manifest/first assets preload;
4. auto-start marks request;
5. attempt context resume;
6. if suspended, install one-shot pointer/click/keydown listeners;
7. first user gesture resumes `AudioContext`;
8. if auto-start requested, start immediately;
9. remove listeners once running.

Expose concise states:

```text
ENGINE READY
AUDIO ARMED
WAITING FOR USER GESTURE
PLAYING
```

No modal nagging.

---

# 30. A/V and avatar synchronization

Pack event:

```json
{
  "sample": 1920000,
  "type": "avatar.motion",
  "payload": {
    "persona": "xiaoxiao",
    "animation": "dance.drop.03",
    "intensity": 0.96
  }
}
```

Event classes:

```text
track.enter
segment.enter
phrase.enter
transition.start
transition.switch
transition.end
drop
hook
energy
avatar.motion
avatar.expression
avatar.fx
persona.musicLine
custom
```

Drive visual event timing from audio context, not `Date.now()`.

Where available use `AudioContext.getOutputTimestamp()` to map audio context time to `performance.now()`.

Feature-detect `outputLatency` and experimental playback statistics; diagnostics only, no hard dependency.

---

# 31. Diagnostics and error model

Python JSONL logs include timestamp, level, operation ID, component, event, duration, track/segment/transition ID, cache hit and error code.

Player diagnostics expose:

```text
AudioContext state
sample rate
base latency
output latency if available
current timeline sample
scheduled horizon
decoded cache bytes
underrun count
hot-swap count
deadline misses
fallback transition count
active pack
generation
```

Stable error codes include:

```text
HMX_SOURCE_NOT_FOUND
HMX_SOURCE_CHANGED
HMX_CANONICALIZE_FAILED
HMX_ANALYSIS_FAILED
HMX_NO_DOWNBEAT_GRID
HMX_CUE_OUT_OF_RANGE
HMX_TRANSITION_NOT_POSSIBLE
HMX_PACK_INVALID
HMX_PACK_INTEGRITY_FAILED
HMX_ASSET_DECODE_FAILED
HMX_HOTSWAP_DEADLINE_MISSED
HMX_AUDIO_CONTEXT_SUSPENDED
HMX_SIDECAR_CRASHED
HMX_SIDECAR_PROTOCOL_ERROR
```

Normal UI receives concise errors. Full traceback goes to diagnostics.

---

# 32. VS Code sidecar lifecycle manager

Prepare TypeScript manager responsibilities:

```text
discover bundled sidecar
spawn lazily
handshake
health
request correlation
progress
stderr capture
crash detection
restart
shutdown
```

Do not spawn sidecar merely because VS Code launched.

Spawn for authoring/analysis/compilation.

Normal playback of precompiled packs must remain sidecar-free.

If sidecar crashes, player keeps running.

---

# 33. Integration bundle

`tools/build-integration-bundle.ps1` outputs:

```text
dist/integration-bundle/
├─ player/
│  ├─ hypermix-player.js
│  ├─ hypermix-player.d.ts
│  └─ BUILD_INFO.json
├─ bridge/
│  ├─ index.js
│  ├─ index.d.ts
│  └─ BUILD_INFO.json
├─ schemas/
│  └─ *.schema.json
├─ sidecar/
│  └─ win32-x64/
├─ docs/
│  └─ KELVIN_INTEGRATION.md
└─ manifest.json
```

This bundle must be consumable by Kelvin without copying the whole Automix repo.

---

# 34. Kelvin / Zoo Code integration contract

Layers:

```text
Kelvin UI/persona
        │
HyperMixService
        │
webview message bridge
        │
HyperMixPlayer
```

Authoring:

```text
Kelvin extension host
        │
HyperMixSidecarManager
        │
hypermixd
```

Reserve commands:

```text
kelvin.hypermix.enable
kelvin.hypermix.disable
kelvin.hypermix.play
kelvin.hypermix.pause
kelvin.hypermix.stop
kelvin.hypermix.loadPack
kelvin.hypermix.next
kelvin.hypermix.hotSwap
kelvin.hypermix.setMood
kelvin.hypermix.setPersona
kelvin.hypermix.openStudio
kelvin.hypermix.compilePack
kelvin.hypermix.showDiagnostics
```

Keep command arguments JSON-serializable.

Version webview messages:

```json
{
  "protocol": "hypermix.webview.v1",
  "id": "cmd-271",
  "type": "hypermix.hotSwap",
  "payload": {
    "timing": "nextPhrase",
    "transition": "rewind",
    "targetMood": ["melodic", "heavy-bass"]
  }
}
```

Events:

```text
hypermix.state
hypermix.position
hypermix.segment
hypermix.transition
hypermix.energy
hypermix.avatarEvent
hypermix.error
hypermix.diagnostics
```

Throttle UI position events to 10–30 Hz. Internal scheduler remains sample-clock accurate.

---

# 35. VS Code webview and Remote SSH rules

During Kelvin integration:

- use `webview.asWebviewUri()` for player and pack assets;
- configure restrictive `localResourceRoots`;
- use strict CSP;
- do not hard-code old resource schemes;
- do not depend on localhost.

The webview/audio executes on the UI/client side, which is correct for local speakers.

Avoid:

```text
webview -> localhost:7860
```

under Remote SSH.

Control flows through message passing.

Pack resources should resolve through VS Code resource URIs.

If arbitrary local Windows music authoring is needed while the workspace extension runs remotely, preserve a future boundary for a tiny local UI companion extension. Do not make that companion mandatory yet unless Kelvin's real architecture demands it.

---

# 36. Kelvin settings

Prepare:

```json
{
  "kelvin.hypermix.enabled": true,
  "kelvin.hypermix.autoStart": true,
  "kelvin.hypermix.volume": 0.72,
  "kelvin.hypermix.defaultPack": "frantic-001",
  "kelvin.hypermix.defaultTransition": "auto",
  "kelvin.hypermix.fallbackTransition": "rewind",
  "kelvin.hypermix.hotSwapTiming": "nextPhrase",
  "kelvin.hypermix.avatarSync": true,
  "kelvin.hypermix.preloadNeighbors": 4,
  "kelvin.hypermix.diagnostics": false
}
```

Settings are not a second source of pack metadata.

---

# 37. Persona and work-event integration

Personas provide preferences, not raw DSP.

```json
{
  "persona": "xiaoxiao",
  "music": {
    "tags": ["melodic", "trancey", "bouncy", "heavy-bass"],
    "energy": [0.85, 1.0],
    "transitionWeights": {
      "rewind": 0.30,
      "slam": 0.22,
      "echoCut": 0.15,
      "stutter": 0.18,
      "doubleDrop": 0.15
    }
  }
}
```

Work-event API example:

```ts
music.onWorkEvent({ type: "build.started", intensity: 0.5 })
music.onWorkEvent({ type: "task.completed", intensity: 0.9 })
music.onWorkEvent({ type: "agent.breakthrough", intensity: 1.0 })
```

Use cooldowns. Do not transition on every tiny tool event.

Semantic avatar events such as:

```text
dance.energy.90
drop.hit
rewind.react
```

are resolved by Kelvin to GenAI video assets. Do not couple audio packs to one exact video file.

---

# 38. Security and resource governance

Webview:

- CSP nonce;
- restrictive roots;
- no eval;
- no arbitrary remote scripts;
- validate inbound messages.

Sidecar:

- stdio by default;
- validate paths;
- allow-listed methods;
- no arbitrary shell commands;
- FFmpeg args passed as argument arrays.

Bound:

- decoded track cache;
- analysis workers;
- FFmpeg workers;
- render workers;
- waveform data;
- stem cache;
- browser AudioBuffer cache;
- graph neighbor preload.

Allow sidecar idle shutdown after configurable inactivity.

---

# 39. Optional stems and future stretch

Stems remain optional.

Use them for:

```text
acapella
bass swap
vocal handoff
drum-only bridge
```

If unavailable, explicit capability fallback.

Create a future `TimeStretchBackend` interface, default unavailable. HyperMix base operation must not depend on it.

---

# 40. Build and CLI

Use reproducible TypeScript builds with lockfiles, no CDN runtime dependencies and a compact browser/webview bundle.

Required CLI operations:

```text
hypermix health
hypermix import <audio>
hypermix analyze <track>
hypermix crate inspect <crate>
hypermix crate compile <crate>
hypermix transition preview --from <segment> --to <segment> --technique rewind
hypermix pack inspect <pack>
hypermix pack build <crate>
hypermix pack render <pack>
hypermix studio
hypermix sidecar
```

Return nonzero exit codes on failure.

---

# 41. Cache and reproducibility

Separate caches:

```text
canonical/
analysis/
waveforms/
segments/
transitions/
stems/
packs/
```

Metadata includes schema version, compiler version, source hash, config hash and timestamp.

A transition renderer change invalidates transition assets, not canonical WAV/analysis.

Every compiled pack records:

```text
compiler git SHA
compiler version
Python version
FFmpeg version
config hash
crate SHA-256
canonical source hashes
random seed
```

---

# 42. UI integration principles

Kelvin controls stay compact:

```text
play/pause
next
volume
current track
transition indicator
mood
```

Expanded diagnostics are optional.

Do not flood the integrated terminal. Use OutputChannel/diagnostics panel for extension-side logs.

HyperMix Studio is the dedicated deep authoring surface.

---

# 43. Complete implementation phases

All phases below are mandatory in this task. They are sequencing guidance, not scope cuts.

## Phase A — Namespace and contracts

Create package structure, config, error model, schemas, Python models, TS types, hashing and cache metadata.

## Phase B — Canonical ingest

FFmpeg conversion, SHA-256, atomic cache, source-change detection, private roots.

## Phase C — Analysis extraction

AutomixAnalyzer adapter around existing PhraseGrid, integer sample conversion, structure, energy, cue candidates.

## Phase D — Curated cues

Cue model, snapping, locking/stale behavior, crate format, candidate scoring.

## Phase E — Transition registry

Implement all transitions in this document with common capabilities/planner/renderer architecture.

## Phase F — Segment and edge compiler

8/16/32-bar assets, content addressing, graph, transition edges, universal fallbacks.

## Phase G — Pack compiler

Manifest, integrity, directory/archive pack and inspection.

## Phase H — Golden renderer

Seeded deterministic sequencing, WAV, timeline, events and report.

## Phase I — HyperMix Studio

Library, waveform, grids, cue editor, audition, transition previews, crate editor and compile controls.

## Phase J — Sidecar

NDJSON JSON-RPC, progress, cancellation, bounded concurrency, logs and diagnostics.

## Phase K — Windows sidecar bundle

Development bootstrap and packaged standalone runtime.

## Phase L — TypeScript player

State machine, pack loader, graph, decode cache, sample clock, scheduling, pause/resume/seek.

## Phase M — Graph runtime

Realtime assembly of precompiled segments/transitions with fallback edges.

## Phase N — HYPER hot-swap

Immediate/beat/bar/phrase scheduling with all major transition choices and no silent gaps.

## Phase O — A/V events

Sample-clock event stream, output timestamp mapping, semantic avatar events.

## Phase P — Auto-start arming

Audio policy handling, preload and first-gesture resume.

## Phase Q — Bridge package

Versioned webview protocol and command contracts.

## Phase R — Integration bundle

Player, bridge, schemas, Windows sidecar and docs in a copyable artifact.

## Phase S — Kelvin integration documentation/examples

Real example `HyperMixService`, `HyperMixWebviewBridge`, `HyperMixSidecarManager`. Do not edit Kelvin repo until that repo is explicitly opened.

## Phase T — Remote development

No localhost dependency, resource abstraction and future local companion boundary.

## Phase U — Observability/failure isolation

Health, logs, diagnostics, crash handling, cache stats and stable error codes.

## Phase V — Production hardening

Archive/path safety, caps, atomic writes, cancellation, cleanup, stale detection and migration hooks.

---

# 44. Migration strategy

Do not delete `club_server.py`.

1. Extract player concepts into `packages/hypermix-player`.
2. Optionally make legacy demo consume the new player.
3. Add Studio separately.
4. Mark old inline scheduler legacy only after replacement works.
5. Clean duplicates last.

For `club_mixer.py`:

```text
adapt first
extract second
migrate third
clean last
```

Preserve two high-level products:

```text
ClubMix
HyperMix
```

ClubMix keeps traditional long blends/tempo matching/bass swap.

HyperMix provides curated HERO phrases, aggressive edits, reset transitions and hot-swap.

---

# 45. Private demonstration crate

Even though all architecture is implemented now, create a private/local manual demo crate using 3–5 curated tracks.

Do not commit copyrighted music.

Include:

```text
multiple HERO cues
8/16/32-bar variants
rewind
slam
echo-cut
stutter
double-drop where compatible
```

Generate a 2–5 minute golden mix with almost no filler.

This is a listening artifact, not the project scope boundary.

---

# 46. Manual verification gates

Because automated tests are embargoed, expose deterministic/manual checks.

Compiler:

```text
canonical WAV = 48 kHz stereo
hash stable
same crate + seed = same timeline
```

Pack:

```text
schema valid
assets exist
hashes match
sample counts match
fallback graph exits exist
```

Player diagnostics:

```text
no scheduling gap
logical sample monotonic
expected transition sample reached
generation invalidation works
decoded cache bounded
```

Hot-swap manual verification:

```text
request nextPhrase
old phrase completes
FX executes
new HERO begins
no pause
```

Avatar verification:

```text
drop event emits expected semantic animation event near audible drop
```

Do not add test files to automate these.

---

# 47. Coding-agent execution policy

1. Inspect relevant files before modifying.
2. After initial inspection, implement rather than producing another plan.
3. Do not stop for minor ambiguity.
4. Ask only for genuinely missing user-owned information.
5. Do not replace working code with placeholders.
6. Do not leave core TODOs.
7. Avoid duplicate layers.
8. Keep legacy working while HyperMix is introduced.
9. Prefer deterministic offline processing to realtime DSP.
10. Keep runtime small.
11. Do not add/run automated tests.
12. Do not perform unrelated lint/format sweeps over the legacy repo.
13. Do not commit private music.
14. Use feature flags for experimental capabilities.
15. Build the actual integration bundle, not merely docs describing one.

---

# 48. Definition of done

The task is complete only when all exist:

## Authoring

- canonicalizer;
- analysis adapter;
- cue system;
- crate format;
- waveform generation;
- Studio;
- transition preview.

## DSP/compiler

- segment compiler;
- full transition registry;
- graph compiler;
- pack writer;
- deterministic golden renderer.

## Runtime

- standalone TS player;
- compiled-set mode;
- graph mode;
- bounded decode cache;
- sample-clock scheduler;
- hot-swap;
- deadline fallback;
- auto-start arming;
- event dispatcher;
- diagnostics.

## Process/API

- stdio sidecar;
- progress;
- cancellation;
- health;
- logs;
- Windows bootstrap;
- packaged Windows sidecar.

## Integration

- bridge package;
- versioned webview protocol;
- VS Code commands;
- Kelvin examples/docs;
- Remote SSH-safe boundary;
- generated integration bundle.

## Documentation

- architecture;
- authoring;
- pack format;
- transition DSL;
- runtime API;
- sidecar protocol;
- Kelvin integration;
- operations/debugging.

## Preservation

- classic Automix club mixer remains available;
- current useful docs remain;
- current useful demo paths are not gratuitously destroyed.

---

# 49. Final architectural invariant

At completion:

```text
                         HEAVY AUTHORING SIDE
                         ────────────────────

                         Python / FFmpeg
                              │
                              ▼
                  analyze / curate / compile
                              │
                              ▼
                           HMX PACK
                              │
                              │ stable contract
                              ▼

                         LIGHT RUNTIME SIDE
                         ──────────────────

                     TypeScript + Web Audio
                              │
                ┌─────────────┴─────────────┐
                ▼                           ▼
          deterministic play           HYPER HOT-SWAP
                │                           │
                └─────────────┬─────────────┘
                              ▼
                     sample-clock events
                              │
                              ▼
                       Kelvin webview
                              │
                 avatars / persona / UI
```

If Kelvin needs SciPy, Flask, Demucs, FFmpeg or Python merely to play an already compiled pack, the boundary is wrong.

If HyperMix needs a full realtime time-stretch engine before rewind/slam/phrase hot-swap works, the design has drifted.

If arbitrary wall-clock timers become the musical timing authority, the design has drifted.

The intended product is:

> **A phrase-aware compiler that turns curated music into a graph of high-value musical moments, plus a tiny sample-clock runtime that can jump between those moments with DJ-grade intentional transitions.**

That is HyperMix. 🎧⚡
