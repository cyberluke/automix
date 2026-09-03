# HyperMix runtime API (`@hypermix/player`)

Zero-dependency TypeScript player. No Python, no localhost, no VS Code imports.

## Quick start

```ts
import { HyperMixPlayer } from "@hypermix/player";

const ctx = new AudioContext({ sampleRate: 48000 });
const player = new HyperMixPlayer(ctx);

await player.loadPack("https://host/packs/demo/"); // or a vscode-resource URI
player.play({ seed: 42, mode: "weighted-random" });
player.next();                          // skip to next segment
await player.requestHotSwap("echo_cut"); // deadline-bounded hot swap
player.stop();
```

## Core classes

- **`HyperMixPlayer`** — facade: `loadPack`, `play`, `stop`, `next`,
  `requestHotSwap`, `seek`.
- **`HyperMixClock`** — anchors integer sample position to the AudioContext
  clock; `nowSample()` is the single source of truth.
- **`HyperMixScheduler`** — schedules `AudioBufferSourceNode.start(time)` on the
  context clock. Never uses `setTimeout` for audio timing.
- **`HyperMixStateMachine`** — 10 states with an explicit `ALLOWED` transition
  map: `idle, loading, ready, playing, transitioning, hotSwapping, seeking,
  paused, stopped, error`.
- **`HyperMixHotSwap`** — races candidate fallbacks against
  `HOT_SWAP_DEADLINE_MS = 120` and reports `fellBackTo`.
- **`HyperMixEventBus`** — typed events.

## Determinism

`mulberry32` PRNG seeded from `PlayOptions.seed`. The same pack + seed +
sequence of calls produces the same set. The Python Director and TS Director
implement identical scoring.

## Events

| Event | Payload |
|---|---|
| `position` | `{ sample }` — throttled to ~30 Hz (`POSITION_EVENT_MIN_INTERVAL_MS = 33`) |
| `segment.enter` | `{ segmentId }` |
| `transition.switch` | `{ edgeId, technique, fellBackTo? }` |
| `state` | `{ state }` |
| `error` | `HyperMixError` JSON |

## Asset integrity

`HyperMixAssetLoader` verifies every fetched asset against the manifest's
integrity block (`crypto.subtle` SHA-256) before decoding. Corrupt assets throw
`HMX_ASSET_CORRUPT`.
