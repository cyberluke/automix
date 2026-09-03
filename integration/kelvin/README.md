# HyperMix × Kelvin / Zoo Code integration

This folder shows how to embed HyperMix into the Kelvin (Zoo Code) VS Code
extension as a webview feature. HyperMix ships as a self-contained integration
bundle (`dist/integration-bundle/`) with:

- `@hypermix/player` — sample-clock player (no Python, no localhost, no VS Code imports)
- `@hypermix/bridge` — versioned `hypermix.webview.v1` message protocol
- JSON schemas (`schemas/`)
- the Windows sidecar binary (`sidecar/win32-x64/hypermixd.exe`)
- docs (`docs/`)

## What you wire up

1. **Host side** — spawn the sidecar and expose pack loading to the webview via
   `HyperMixService.example.ts`.
2. **Webview side** — create a `HyperMixBridge` over `vscode.postMessage` using
   `HyperMixWebviewBridge.example.ts`, then drive the player.
3. **Manifest** — merge `package.fragment.example.json` into your extension's
   `package.json` to register the view and commands.

See `KELVIN_INTEGRATION.md` for the full walkthrough.
