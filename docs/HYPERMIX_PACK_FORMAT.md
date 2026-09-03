# HyperMix pack format (`.hmxpack`)

A pack is the player's unit of distribution: a directory (optionally zipped)
containing pre-compiled segment audio, the mix graph, and an integrity block.

## Layout

```
mypack/
├── manifest.json          # hypermix.pack.v1 + integrity block
├── graph/
│   ├── segments.json      # Segment[] (hypermix-track.v1#Segment)
│   ├── edges.json         # TransitionEdge[] (hypermix-transition.v1)
│   └── graph.json         # entrySegments, adjacency, fallbackTransition
├── crate/
│   └── crate.json         # source crate snapshot
└── assets/
    └── <short_hash>.wav   # 48 kHz / 2ch / float32 segment audio
```

## Manifest

```json
{
  "schema": "hypermix.pack.v1",
  "id": "...", "name": "...", "version": "0.1.0",
  "createdAt": "...",
  "compiler": { "name": "hypermix-compiler", "version": "0.1.0", "configHash": "..." },
  "audio": { "sampleRate": 48000, "channels": 2, "format": "f32le" },
  "segments": 12, "edges": 20,
  "entrySegments": ["seg-1"],
  "fallbackTransition": "rewind",
  "integrity": {
    "manifestSha256": "<computed with this field zeroed>",
    "assets": [{ "path": "assets/xx.wav", "sha256": "...", "samples": 768000 }]
  }
}
```

## Verification

`verify_pack(dir)` / `tools/inspect-pack.py`:
1. Recomputes each asset's SHA-256 and sample count against the integrity block.
2. Recomputes `manifestSha256` with the field zeroed.
3. Any mismatch → failure.

## Extraction guards

`extract_pack()` rejects: absolute paths, `..` traversal, symlinks, and any
single member expanding beyond 4 GiB (decompression-bomb guard).

## Player loading

`HyperMixAssetLoader.loadPack()` fetches `manifest.json` + `graph/*.json`,
then lazily fetches + verifies each asset against the integrity block before
decoding.
