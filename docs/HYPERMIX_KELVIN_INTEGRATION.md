# HyperMix ↔ Kelvin integration

Pointer doc: the full guide and example code live in
[`integration/kelvin/`](../integration/kelvin/README.md).

## Contract summary

- **Webview protocol**: `hypermix.webview.v1` — every envelope carries
  `protocol`, `id`, `type`, `payload`. Foreign versions are rejected.
- **Assets**: served by the host over a `vscode-resource:` URI; the webview
  player verifies each against the pack's integrity block.
- **Sidecar**: `dist/sidecar/win32-x64/hypermixd.exe` spawned by the host;
  NDJSON JSON-RPC 2.0 over stdio.
- **Player**: runs fully inside the webview `AudioContext` at 48 kHz.

## Bundle contents (`dist/integration-bundle/`)

| Path | What |
|---|---|
| `packages/hypermix-player/` | Built player |
| `packages/hypermix-bridge/` | Built bridge |
| `schemas/` | All JSON schemas + transition DSL |
| `sidecar/win32-x64/` | hypermixd + BUILD_INFO.json |
| `docs/` | These docs |
| `manifest.json` | Bundle manifest |

Build it:

```powershell
tools/build-integration-bundle.ps1
```
