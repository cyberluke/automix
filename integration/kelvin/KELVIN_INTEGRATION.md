# Kelvin / Zoo Code integration guide

## Architecture

```
┌─ VS Code extension host ─────────────────┐
│  HyperMixService                         │
│   ├─ spawns hypermixd.exe (sidecar)      │
│   ├─ serves pack assets to webview       │
│   └─ relays hypermix.webview.v1 messages │
└───────────────┬──────────────────────────┘
                │ postMessage (versioned)
┌───────────────┴──────────────────────────┐
│  Webview                                 │
│   HyperMixBridge ── HyperMixPlayer       │
│   (AudioContext lives here)              │
└──────────────────────────────────────────┘
```

The sidecar does heavy compilation; the player runs entirely in the webview's
`AudioContext`. The webview never talks to localhost — it fetches pack assets
through a `vscode-resource:` URI the host maps to the bundle.

## Steps

### 1. Register the view
Merge `package.fragment.example.json` into Kelvin's `package.json`.

### 2. Host service
Copy `HyperMixService.example.ts` into Kelvin's `src/`. It:
- spawns the sidecar (`hypermixd.exe`) as a child process,
- exposes `hypermix.loadPack` / player commands to the webview,
- serves pack files via a custom URI scheme.

### 3. Webview bridge
Copy `HyperMixWebviewBridge.example.ts` into Kelvin's webview bundle. It wraps
`acquireVsCodeApi()` in a `Transport` for `HyperMixBridge`.

### 4. Player
Inside the webview:

```ts
import { HyperMixPlayer } from "@hypermix/player";

const player = new HyperMixPlayer(new AudioContext({ sampleRate: 48000 }));
await player.loadPack(packRootUrl);      // vscode-resource URI from the host
player.play({ seed: 42, mode: "weighted-random" });
```

## Versioning
All webview traffic uses `hypermix.webview.v1`. The host validates `protocol`
on every envelope; mismatched versions are rejected with a clear error.

## Privacy
Pack audio stays local. No telemetry, no network calls from the player.
