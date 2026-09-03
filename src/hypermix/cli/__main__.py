"""HyperMix CLI (§23). Subcommands: health, import, analyze, crate, transition,
pack, studio, sidecar. Non-zero exit on failure; JSON output on success."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import COMPILER_NAME
from ..config import DEFAULT_CONFIG
from ..errors import ErrorCode, HyperMixError


def _print(data) -> None:
    print(json.dumps(data, indent=2, default=str))


def _die(e: Exception) -> int:
    if isinstance(e, HyperMixError):
        _print({"error": e.to_dict()})
    else:
        _print({"error": HyperMixError.from_exception(e).to_dict()})
    return 1


def cmd_health(args) -> int:
    from ..canonicalize import ffmpeg_version
    _print({"ok": True, "compiler": COMPILER_NAME,
            "ffmpeg": ffmpeg_version(),
            "sampleRate": DEFAULT_CONFIG.sample_rate})
    return 0


def cmd_import(args) -> int:
    from ..canonicalize import Canonicalizer
    c = Canonicalizer(DEFAULT_CONFIG)
    res = c.canonicalize(Path(args.path), c.default_private_root())
    _print({"trackId": Path(args.path).stem,
            "canonicalPath": str(res.canonical_path),
            "durationSec": res.duration_sec, "cacheHit": res.cache_hit})
    return 0


def cmd_analyze(args) -> int:
    from ..analysis.automix_analyzer import AutomixAnalyzer
    from ..audio_io import read_wav
    audio = read_wav(Path(args.path))
    analysis = AutomixAnalyzer(DEFAULT_CONFIG).analyze(audio, DEFAULT_CONFIG.phrase_bars)
    _print({"trackId": Path(args.path).stem, "analysis": analysis.to_dict()})
    return 0


def cmd_crate_inspect(args) -> int:
    from ..compiler.crate_compiler import load_crate
    crate = load_crate(Path(args.path))
    _print({"crateId": crate.id, "name": crate.name, "version": crate.version,
            "tracks": crate.tracks, "fallback": crate.fallback_transition,
            "allowedTechniques": crate.allowed_techniques})
    return 0


def cmd_crate_compile(args) -> int:
    from ..sidecar.diagnostics import Diagnostics
    from ..sidecar.handlers import Handlers
    handlers = Handlers(Path(".").resolve(), Diagnostics())
    result = handlers.pack_compile({
        "cratePath": str(Path(args.crate).resolve()),
        "outDir": str(Path(args.out).resolve()),
        "zip": bool(args.zip),
    })
    _print(result)
    return 0


def cmd_transition_preview(args) -> int:
    from ..sidecar.diagnostics import Diagnostics
    from ..sidecar.handlers import Handlers
    handlers = Handlers(Path(".").resolve(), Diagnostics())
    result = handlers.transition_preview({
        "outgoingPath": str(Path(args.outgoing).resolve()),
        "incomingPath": str(Path(args.incoming).resolve()),
        "outgoingBpm": args.outgoing_bpm, "incomingBpm": args.incoming_bpm,
        "technique": args.technique, "seconds": args.seconds,
        "outPath": str(Path(args.out).resolve()),
    })
    _print(result)
    return 0


def cmd_pack_inspect(args) -> int:
    from ..sidecar.diagnostics import Diagnostics
    from ..sidecar.handlers import Handlers
    handlers = Handlers(Path(".").resolve(), Diagnostics())
    _print(handlers.pack_inspect({"packDir": str(Path(args.pack).resolve())}))
    return 0


def cmd_pack_render(args) -> int:
    from ..sidecar.diagnostics import Diagnostics
    from ..sidecar.handlers import Handlers
    handlers = Handlers(Path(".").resolve(), Diagnostics())
    _print(handlers.pack_render_golden({
        "packDir": str(Path(args.pack).resolve()),
        "outDir": str(Path(args.out).resolve()),
        "seed": args.seed, "length": args.length, "mode": args.mode,
        "segmentBars": args.segment_bars,
        "cut": bool(getattr(args, "cut", False)),
        "harmonicArc": bool(getattr(args, "harmonic_arc", False)),
    }))
    return 0


def cmd_sidecar(args) -> int:
    from ..sidecar.server import SidecarServer
    return SidecarServer(Path(".").resolve()).run()


def cmd_spr(args) -> int:
    from ..spr.types import SPRRequest, SPRConfig
    from ..spr.pipeline import run_spr
    cfg = SPRConfig(
        sr=args.sr,
        transcribe_confidence=args.conf,
        vocal_bleed_threshold=args.bleed,
    )
    req = SPRRequest(
        source_wav=str(Path(args.source).resolve()),
        start_s=args.start,
        bars=args.bars,
        bpm=args.bpm,
        root_midi=args.root,
        scale=args.scale,
    )
    result = run_spr(req, out_dir=str(Path(args.out).resolve()), cfg=cfg,
                     do_branch1=not args.no_branch1, do_branch2=not args.no_branch2)
    _print({
        "ok": True,
        "branch": result.branch_used,
        "vocalBleed": result.vocal_bleed,
        "transcribeConfidence": result.transcription_confidence,
        "candidates": [
            {"flag": c.flag.value, "wav": c.wav_path, "mix": c.mix_wav_path,
             "transpose": c.transpose_semitones, "description": c.description}
            for c in result.candidates
        ],
        "log": result.log,
    })
    return 0


def cmd_juggle(args) -> int:
    from ..juggle.types import (
        JuggleMinerRequest, JuggleMinerConfig, PhraseRole, get_preset,
    )
    from ..juggle.miner import run_juggle_mine
    cfg = JuggleMinerConfig(sr=args.sr, top_k=args.top_k)
    if args.phase != 'both':
        cfg.phases = [args.phase]
    if args.mode != 'both':
        # narrow to one placement by emptying the other grid
        if args.mode == 'retrigger':
            cfg.loop_counts = []
        else:
            cfg.repeats = []
    if args.loop_count:
        cfg.loop_counts = [args.loop_count]
    if getattr(args, 'vinyl', False):
        cfg.vinyl = True
        cfg.vinyl_depth = args.vinyl_depth
    if getattr(args, 'reverse_flourish', False):
        cfg.reverse_flourish = True
    # preset: render just that one curated gesture
    if args.preset:
        p = get_preset(args.preset)
        cfg.offsets_beats = [p.gesture.offset_beats]
        cfg.durations_beats = [p.gesture.duration_beats]
        cfg.repeats = [p.gesture.repeat]
        cfg.phases = [p.gesture.phase]
        if p.gesture.mode == 'loop':
            cfg.repeats = []
            cfg.loop_counts = [p.gesture.loop_count]
        else:
            cfg.loop_counts = []
        # apply the preset's render-time FX overrides (chirp/humanize/vinyl/…)
        for k, v in p.render.items():
            setattr(cfg, k, v)
        cfg.top_k = 1
    req = JuggleMinerRequest(
        source_wav=str(Path(args.source).resolve()),
        boundary_s=args.boundary,
        bpm=args.bpm,
        role=PhraseRole(args.role),
        context_beats=args.context_beats,
    )
    res = run_juggle_mine(req, out_dir=str(Path(args.out).resolve()), cfg=cfg)
    _print({
        "ok": True,
        "role": req.role.value,
        "boundary": req.boundary_s,
        "bpm": req.bpm,
        "candidates": [
            {
                "rank": i,
                "offsetBeats": c.gesture.offset_beats,
                "durationBeats": c.gesture.duration_beats,
                "repeat": c.gesture.repeat,
                "phase": c.gesture.phase,
                "mode": c.gesture.mode,
                "loopCount": c.gesture.loop_count,
                "grid": getattr(c.gesture, "grid", "straight"),
                "scores": {
                    "punch": c.scores.punch,
                    "transient": c.scores.transient_density,
                    "novelty": c.scores.spectral_novelty,
                    "vocal": c.scores.vocal_hook,
                    "groove": c.scores.groove,
                    "total": c.scores.total,
                },
                "wav": c.wav_path,
                "description": c.description,
            }
            for i, c in enumerate(res.candidates)
        ],
        "log": res.log,
    })
    return 0


def cmd_studio(args) -> int:
    _print({"ok": False, "message":
            "studio UI is provided by the hypermix-studio package (Phase Q); "
            "this CLI exposes compile/inspect/render instead."})
    return 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hypermix", description="HyperMix compiler CLI")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("health").set_defaults(fn=cmd_health)

    pi = sub.add_parser("import"); pi.add_argument("path"); pi.set_defaults(fn=cmd_import)
    pa = sub.add_parser("analyze"); pa.add_argument("path"); pa.set_defaults(fn=cmd_analyze)

    pc = sub.add_parser("crate"); csub = pc.add_subparsers(dest="crate_cmd", required=True)
    pci = csub.add_parser("inspect"); pci.add_argument("path"); pci.set_defaults(fn=cmd_crate_inspect)
    pcc = csub.add_parser("compile"); pcc.add_argument("crate"); pcc.add_argument("--out", required=True)
    pcc.add_argument("--zip", action="store_true"); pcc.set_defaults(fn=cmd_crate_compile)

    pt = sub.add_parser("transition"); tsub = pt.add_subparsers(dest="transition_cmd", required=True)
    ptp = tsub.add_parser("preview")
    ptp.add_argument("--outgoing", required=True); ptp.add_argument("--incoming", required=True)
    ptp.add_argument("--outgoing-bpm", type=float, default=120.0)
    ptp.add_argument("--incoming-bpm", type=float, default=120.0)
    ptp.add_argument("--technique", default="rewind")
    ptp.add_argument("--seconds", type=float, default=8.0)
    ptp.add_argument("--out", required=True)
    ptp.set_defaults(fn=cmd_transition_preview)

    pp = sub.add_parser("pack"); psub = pp.add_subparsers(dest="pack_cmd", required=True)
    ppi = psub.add_parser("inspect"); ppi.add_argument("pack"); ppi.set_defaults(fn=cmd_pack_inspect)
    ppr = psub.add_parser("render"); ppr.add_argument("pack"); ppr.add_argument("--out", required=True)
    ppr.add_argument("--seed", type=int, default=0); ppr.add_argument("--length", type=int, default=12)
    ppr.add_argument("--mode", default="weighted-random",
                     choices=["weighted-random", "deterministic", "deep"])
    ppr.add_argument("--segment-bars", type=int, default=None,
                     help="Deep mode: bars to play per segment (default 4)")
    ppr.add_argument("--cut", action="store_true",
                     help="Radio-hit megamix: hard drop->drop cuts, no transition audio")
    ppr.add_argument("--harmonic-arc", action="store_true",
                     help="ASCENDING_ENERGY_ARC: Camelot +2 energy boost + "
                          "climbing-phrase energy gradient in deep sequencing")
    ppr.set_defaults(fn=cmd_pack_render)

    pspr = sub.add_parser("spr", help="Spectral Phrase Reinforcement: layer a selected synth phrase")
    pspr.add_argument("--source", required=True, help="source track WAV")
    pspr.add_argument("--start", type=float, required=True, help="phrase start (seconds)")
    pspr.add_argument("--bars", type=int, default=4)
    pspr.add_argument("--bpm", type=float, required=True)
    pspr.add_argument("--root", type=int, default=None, help="root MIDI note for key-aware transpose")
    pspr.add_argument("--scale", default="minor", choices=["minor", "major", "chromatic"])
    pspr.add_argument("--out", required=True)
    pspr.add_argument("--sr", type=int, default=44100)
    pspr.add_argument("--conf", type=float, default=0.80, help="transcription confidence gate")
    pspr.add_argument("--bleed", type=float, default=0.45, help="vocal-bleed gate")
    pspr.add_argument("--no-branch1", action="store_true", help="skip CyberSynth (debug)")
    pspr.add_argument("--no-branch2", action="store_true", help="skip punk fallback")
    pspr.set_defaults(fn=cmd_spr)

    pjg = sub.add_parser("juggle", help="JuggleMiner: offline beat-juggle / backstep discovery on the master buffer")
    pjg.add_argument("--source", required=True, help="master/segment WAV")
    pjg.add_argument("--boundary", type=float, required=True,
                     help="hot phrase boundary / drop entry (seconds)")
    pjg.add_argument("--bpm", type=float, required=True)
    pjg.add_argument("--role", default="GENERIC",
                     choices=[r.value for r in __import__("src.hypermix.juggle.types", fromlist=["PhraseRole"]).PhraseRole],
                     help="phrase semantics (bias the search)")
    pjg.add_argument("--context-beats", type=float, default=8.0,
                     help="beats of context each side; must cover the whole effect (duration x repeat) or it gets truncated")
    pjg.add_argument("--top-k", type=int, default=8)
    pjg.add_argument("--sr", type=int, default=44100)
    pjg.add_argument("--phase", default="both", choices=["onbeat", "offbeat", "both"],
                     help="trigger the buffer on the kick (onbeat) or the snare (offbeat)")
    pjg.add_argument("--mode", default="both", choices=["retrigger", "loop", "both"],
                     help="retrigger at the anchor vs end-of-phrase double/triple loop")
    pjg.add_argument("--loop-count", type=int, default=None,
                     help="loop mode only: 2=double, 3=triple")
    pjg.add_argument("--preset", default=None,
                     help="render just one curated gesture from the preset registry")
    pjg.add_argument("--vinyl", action="store_true",
                     help="turntable nonlinearity: motor bogs down & re-spins (pitch/time wow)")
    pjg.add_argument("--vinyl-depth", type=float, default=0.5,
                     help="how deep the motor bogs (0..0.6)")
    pjg.add_argument("--reverse-flourish", action="store_true",
                     help="reverse kick back-cue scratch on buffer entry")
    pjg.add_argument("--out", required=True)
    pjg.set_defaults(fn=cmd_juggle)

    sub.add_parser("studio").set_defaults(fn=cmd_studio)
    sub.add_parser("sidecar").set_defaults(fn=cmd_sidecar)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except Exception as e:
        return _die(e)


if __name__ == "__main__":
    raise SystemExit(main())
