# HyperMix operations

## Bootstrap (Windows)

```powershell
tools/bootstrap-windows.ps1
```

Creates `.venv-hypermix`, installs `requirements-hypermix.txt`, verifies
FFmpeg, runs an import smoke test. Idempotent.

## Build

```powershell
tools/build-player.ps1          # TS packages
tools/build-sidecar-windows.ps1 # dist/sidecar/win32-x64/hypermixd.exe
tools/build-integration-bundle.ps1
```

## Caches

All compiler outputs live under `var/<layer>/`, content-addressed and
self-healing. Clear everything with `Remove-Item -Recurse var/` — results are
reproducible from sources + config.

Inspect: `python -m src.hypermix.cli cache stats`
Prune:  `python -m src.hypermix.cli cache prune --layer segment`

## Diagnostics

Sidecar ring buffer (500 entries) + `var/diagnostics/sidecar.jsonl`.
Snapshot via CLI: `python -m src.hypermix.cli diagnostics snapshot` or the
`diagnostics.snapshot` RPC.

## Privacy / licensing

- No copyrighted audio in git. `crates/private/`, `packs/private/`, `var/` are
  gitignored.
- Demo crate references only generated tones / fixtures.
- Player makes no network calls and sends no telemetry.

## Troubleshooting

| Symptom | Check |
|---|---|
| `HMX_FFMPEG_MISSING` | `ffmpeg -version` on PATH |
| import errors | `tools/bootstrap-windows.ps1` re-run |
| stale cues (amber) | source changed; explicit resnap in studio |
| integrity FAILED | recompile pack; assets are content-addressed |
