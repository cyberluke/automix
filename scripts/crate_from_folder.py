"""Scan a local music folder, auto-detect hero cues, and emit a HyperMix crate.

Usage:
    .\\.venv-hypermix\\Scripts\\python.exe scripts/crate_from_folder.py \
        --music-dir music --out crates/my-library/crate.json \
        --crate-id my-library --name "My Library" [--cues-per-track 3] [--compile]

Each audio file is canonicalized (48k float32) and analyzed; the top-scoring
hero candidates become `hero` cues snapped to the nearest bar. Manual cues in
an existing crate are preserved (manual cues are authoritative, §1.5).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure repo root on sys.path for `src.hypermix` imports.
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# Audio + video/container formats. The canonicalizer decodes via FFmpeg with -vn
# (drop video), so mp4/mkv/mov/etc. are stripped to their audio track.
AUDIO_EXTS = {
    # audio
    ".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".aiff", ".aif",
    ".wma", ".opus", ".alac",
    # video / container (audio extracted)
    ".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".ts",
}


def _rel(p: Path) -> str:
    """Repo-root-relative POSIX path (crate.json convention)."""
    try:
        return p.resolve().relative_to(_REPO).as_posix()
    except ValueError:
        return p.resolve().as_posix()


def scan_music(music_dir: Path) -> list[Path]:
    files = [p for p in sorted(music_dir.rglob("*"))
             if p.suffix.lower() in AUDIO_EXTS and p.is_file()]
    return files


def auto_cues_for(path: Path, cues_per_track: int, canonicalizer, analyzer, config) -> list[dict]:
    """Canonicalize + analyze one file; return hero cue dicts."""
    from src.hypermix.audio_io import read_wav

    res = canonicalizer.canonicalize(path, canonicalizer.default_private_root())
    audio = read_wav(Path(res.canonical_path))
    analysis = analyzer.analyze(audio, config.phrase_bars)

    cues: list[dict] = []
    for i, h in enumerate(analysis.hero_candidates[:cues_per_track]):
        # Map score (0..1) to a 1..10 rating for the director.
        rating = round(1.0 + 9.0 * float(h.get("score", 0.5)), 1)
        is_drop = bool(h.get("isDropEntry", False))
        cues.append({
            "id": f"hero-{path.stem}-{i + 1}",
            "kind": "hero",
            "sample": int(h["sample"]),
            "rating": rating,
            "snap": "nearestBar",
            "isDropEntry": is_drop,
            # V1 DeepDance: drop/hook entries should hold a long section
            # (16/32/64 bars); other cues keep the short default.
            "preferredBars": [16, 32, 64] if is_drop else [8, 16, 32],
        })
    return cues


def _apply_user_preference(path: Path, cues: list[dict],
                           annotations: dict | None, sr: int = 48000) -> list[dict]:
    """Drop auto-cues that fall inside a user-excluded range (e.g. a disliked
    first half). Manual preference is authoritative over the auto scorer."""
    if not annotations:
        return cues
    pref = (annotations.get("tracks", {}).get(path.name, {})
            .get("userPreference") or {})
    excl = pref.get("excludeRanges") or []
    if not excl:
        return cues
    keep = []
    for c in cues:
        t = c["sample"] / sr
        if any(lo <= t <= hi for lo, hi in excl):
            continue  # inside a disliked range -> not eligible for HyperMix
        keep.append(c)
    return keep


def main() -> int:
    ap = argparse.ArgumentParser(prog="crate_from_folder")
    ap.add_argument("--music-dir", required=True, help="folder of audio files")
    ap.add_argument("--out", required=True, help="output crate.json path")
    ap.add_argument("--crate-id", default=None)
    ap.add_argument("--name", default=None)
    ap.add_argument("--cues-per-track", type=int, default=3)
    ap.add_argument("--fallback", default="rewind")
    ap.add_argument("--techniques", default="phrase_match,echo_cut,slam,backspin,"
                    "drum_roll,loop_transition,stutter,power_up,power_down,rewind",
                    help="comma-separated allowedTechniques (default: varied safe set)")
    ap.add_argument("--phrase-bars", type=int, default=8)
    ap.add_argument("--compile", action="store_true",
                    help="also compile the crate to a pack after writing")
    ap.add_argument("--pack-out", default=None, help="pack output dir (with --compile)")
    ap.add_argument("--annotations", default=None,
                    help="optional CyberLuke annotations JSON; honours per-track "
                         "userPreference.excludeRanges (drop cues in disliked ranges)")
    args = ap.parse_args()

    annotations = None
    if args.annotations:
        annotations = json.loads(Path(args.annotations).read_text(encoding="utf-8"))

    music_dir = Path(args.music_dir)
    if not music_dir.is_dir():
        print(json.dumps({"error": f"music dir not found: {music_dir}"}))
        return 1

    files = scan_music(music_dir)
    if not files:
        print(json.dumps({"error": f"no audio files under {music_dir}",
                          "exts": sorted(AUDIO_EXTS)}))
        return 1

    from src.hypermix.canonicalize import Canonicalizer
    from src.hypermix.analysis.automix_analyzer import AutomixAnalyzer
    from src.hypermix.config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG
    canonicalizer = Canonicalizer(config)
    analyzer = AutomixAnalyzer(config)

    tracks: list[str] = []
    cues: dict[str, list[dict]] = {}
    failures: list[dict] = []

    for f in files:
        rel = _rel(f)
        try:
            c = auto_cues_for(f, args.cues_per_track, canonicalizer, analyzer, config)
            c = _apply_user_preference(f, c, annotations)
        except Exception as exc:  # keep going; report at end
            failures.append({"track": rel, "error": repr(exc)})
            continue
        tracks.append(rel)
        cues[rel] = c

    if not tracks:
        print(json.dumps({"error": "all tracks failed to analyze", "failures": failures}))
        return 1

    crate_id = args.crate_id or music_dir.name or "my-library"
    crate = {
        "schema": "hypermix.crate.v1",
        "id": crate_id,
        "name": args.name or crate_id.replace("-", " ").title(),
        "version": "1.0.0",
        "defaults": {
            "phraseBars": args.phrase_bars,
            "energy": {"min": 0.2, "max": 0.9},
            "allowedTechniques": [t.strip() for t in args.techniques.split(",") if t.strip()],
            "fallbackTransition": args.fallback,
            "deepMix": {
                "preferredPhraseBars": [16, 32, 64],
                "maxPhraseBars": 128,
                "entryKinds": ["drop", "hook"],
                "exitKinds": ["drop", "hook"],
                "skipIntro": True,
                "skipBreakdown": True,
            },
        },
        "tracks": tracks,
        "cues": cues,
        "edges": [],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(crate, indent=2), encoding="utf-8")

    result = {
        "crate": str(out),
        "crateId": crate_id,
        "tracks": len(tracks),
        "cues": sum(len(v) for v in cues.values()),
        "failures": failures,
    }

    if args.compile:
        # Delegate to the CLI subcommand (it wires handlers/config correctly).
        import subprocess
        pack_out = Path(args.pack_out) if args.pack_out else Path("packs") / crate_id
        proc = subprocess.run(
            [sys.executable, "-m", "src.hypermix.cli", "crate", "compile",
             str(out), "--out", str(pack_out)],
            cwd=str(_REPO), capture_output=True, text=True)
        result["pack"] = str(pack_out)
        result["compileReturnCode"] = proc.returncode
        if proc.returncode != 0:
            result["compileError"] = proc.stdout.strip() or proc.stderr.strip()
            print(json.dumps(result, indent=2, default=str))
            return 1
        try:
            result["compile"] = json.loads(proc.stdout)
        except Exception:
            pass

    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
