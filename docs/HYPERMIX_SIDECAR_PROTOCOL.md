# HyperMix sidecar protocol

The sidecar (`python -m src.hypermix.sidecar`) exposes the compiler to hosts
over **NDJSON JSON-RPC 2.0** on stdin/stdout. stdout carries protocol frames
only; all logs go to stderr.

## Framing

One JSON object per line, UTF-8.

```
→ {"jsonrpc":"2.0","id":1,"method":"health","params":{}}
← {"jsonrpc":"2.0","id":1,"result":{"status":"ok","compiler":"hypermix-compiler",...}}
```

Long-running operations may emit progress events before the final response:

```
← {"jsonrpc":"2.0","method":"progress","params":{"op":"pack.compile","pct":40,"msg":"edges"}}
```

## Methods (16)

| Method | Purpose |
|---|---|
| `health` | Liveness + versions + FFmpeg |
| `capabilities` | Registered transitions, snap modes, cue kinds |
| `track.import` | Canonicalize a source |
| `track.analyze` | Full analysis for a track |
| `track.get` | Fetch analysis record |
| `crate.open` / `crate.save` | Crate CRUD |
| `transition.preview` | Render one transition, return events |
| `pack.compile` | Crate → pack |
| `pack.inspect` | Manifest + integrity status |
| `pack.render_golden` | Deterministic golden render |
| `cache.stats` / `cache.prune` | Layer cache introspection |
| `diagnostics.snapshot` | Ring buffer of recent ops |
| `operation.cancel` | Cooperative cancel via `threading.Event` |
| `shutdown` | Stop the server loop |

## Errors

Errors use the codes in `src/hypermix/errors.py`:

```
← {"jsonrpc":"2.0","id":1,"error":{"code":"HMX_SOURCE_MISSING","message":"..."}}
```

## Diagnostics

`Diagnostics` keeps a 500-entry ring buffer plus appends JSONL to
`var/diagnostics/sidecar.jsonl`. `diagnostics.snapshot` returns the buffer.
