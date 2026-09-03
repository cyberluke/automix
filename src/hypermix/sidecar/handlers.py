"""Sidecar method handlers (§21). All 16 methods."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from ..cache import LayeredCache
from ..canonicalize import Canonicalizer, ffmpeg_version
from .. import COMPILER_NAME
from ..config import ANALYZER_VERSION, DEFAULT_CONFIG, PACK_COMPILER_VERSION
from ..errors import ErrorCode, HyperMixError
from .diagnostics import Diagnostics
from .protocol import ProgressEvent


class OperationRegistry:
    def __init__(self) -> None:
        self._cancel: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def register(self, op_id: str) -> threading.Event:
        ev = threading.Event()
        with self._lock:
            self._cancel[op_id] = ev
        return ev

    def cancel(self, op_id: str) -> bool:
        with self._lock:
            ev = self._cancel.get(op_id)
        if ev:
            ev.set()
            return True
        return False

    def finish(self, op_id: str) -> None:
        with self._lock:
            self._cancel.pop(op_id, None)


class Handlers:
    def __init__(self, root: Path, diagnostics: Diagnostics) -> None:
        self.root = Path(root)
        self.config = DEFAULT_CONFIG
        self.cache = LayeredCache(self.root / "var" / "cache")
        self.canonicalizer = Canonicalizer(self.config)
        self.diagnostics = diagnostics
        self.operations = OperationRegistry()
        self._tracks: Dict[str, Any] = {}
        self._crates: Dict[str, Any] = {}

    # -- helpers ------------------------------------------------------------
    def _time(self, method: str, fn: Callable[[], Any]) -> Any:
        start = time.time()
        try:
            out = fn()
            self.diagnostics.record(method, True, (time.time() - start) * 1000)
            return out
        except HyperMixError as e:
            self.diagnostics.record(method, False, (time.time() - start) * 1000,
                                    {"code": e.code.value})
            raise
        except Exception as e:
            self.diagnostics.record(method, False, (time.time() - start) * 1000,
                                    {"error": str(e)})
            raise HyperMixError.from_exception(e)

    # -- methods ------------------------------------------------------------
    def health(self, params: dict) -> dict:
        def _run():
            return {
                "ok": True,
                "compiler": COMPILER_NAME,
                "ffmpeg": ffmpeg_version(),
                "sampleRate": self.config.sample_rate,
                "channels": self.config.channels,
            }
        return self._time("health", _run)

    def capabilities(self, params: dict) -> dict:
        def _run():
            from ..transitions.registry import default_registry
            reg = default_registry()
            return {
                "techniques": reg.ids(),
                "hotSwap": reg.hot_swap_ids(),
                "packCompilerVersion": PACK_COMPILER_VERSION,
                "analyzerVersion": ANALYZER_VERSION,
            }
        return self._time("capabilities", _run)

    def track_import(self, params: dict) -> dict:
        def _run():
            path = Path(params["path"])
            res = self.canonicalizer.canonicalize(path, self.canonicalizer.default_private_root())
            return {
                "trackId": path.stem,
                "canonicalPath": str(res.canonical_path),
                "durationSec": res.duration_sec,
                "cacheHit": res.cache_hit,
            }
        return self._time("track.import", _run)

    def track_analyze(self, params: dict) -> dict:
        def _run():
            from ..analysis.automix_analyzer import AutomixAnalyzer
            from ..audio_io import read_wav
            path = Path(params["path"])
            audio = read_wav(path)
            analysis = AutomixAnalyzer(self.config).analyze(audio, self.config.phrase_bars)
            track_id = params.get("trackId", path.stem)
            self._tracks[track_id] = analysis
            return {"trackId": track_id, "analysis": analysis.to_dict()}
        return self._time("track.analyze", _run)

    def track_get(self, params: dict) -> dict:
        def _run():
            tid = params["trackId"]
            if tid not in self._tracks:
                raise HyperMixError(ErrorCode.HMX_TRACK_NOT_FOUND, f"no analysis for {tid!r}")
            return {"trackId": tid, "analysis": self._tracks[tid].to_dict()}
        return self._time("track.get", _run)

    def crate_open(self, params: dict) -> dict:
        def _run():
            from ..compiler.crate_compiler import load_crate
            crate = load_crate(Path(params["path"]))
            self._crates[crate.id] = crate
            return {"crateId": crate.id, "name": crate.name,
                    "tracks": len(crate.tracks)}
        return self._time("crate.open", _run)

    def crate_save(self, params: dict) -> dict:
        def _run():
            crate = self._crates.get(params["crateId"])
            if crate is None:
                raise HyperMixError(ErrorCode.HMX_CRATE_INVALID, "crate not open")
            path = Path(params["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(crate.to_dict(), indent=2), encoding="utf-8")
            tmp.replace(path)
            return {"path": str(path)}
        return self._time("crate.save", _run)

    def transition_preview(self, params: dict) -> dict:
        def _run():
            from ..audio_io import read_wav, atomic_write_wav
            from ..transitions.model import SegmentContext
            from ..transitions.planner import TransitionPlanner
            from ..hashing import sha256_file
            out_path = Path(params["outPath"])
            a = read_wav(Path(params["outgoingPath"]))
            b = read_wav(Path(params["incomingPath"]))
            sr = self.config.sample_rate
            overlap = int(sr * float(params.get("seconds", 8.0)))
            ctx = SegmentContext(
                outgoing_audio=a, incoming_audio=b,
                outgoing_start=0, outgoing_end=a.n_samples,
                incoming_start=0, incoming_end=b.n_samples,
                outgoing_bpm=float(params.get("outgoingBpm", 120.0)),
                incoming_bpm=float(params.get("incomingBpm", 120.0)),
                sample_rate=sr, params={},
            )
            planner = TransitionPlanner(fallback=params.get("fallback", "rewind"))
            plan = planner.plan(params.get("technique", "rewind"), ctx)
            rendered = planner.render(plan, ctx)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_wav(out_path, rendered.samples, sr)
            return {"technique": plan.technique, "path": str(out_path),
                    "sha256": sha256_file(out_path),
                    "timeline": plan.timeline.to_dict()}
        return self._time("transition.preview", _run)

    def pack_compile(self, params: dict) -> dict:
        def _run():
            from ..packcompile import compile_pack_from_crate
            return compile_pack_from_crate(self, params)
        return self._time("pack.compile", _run)

    def pack_inspect(self, params: dict) -> dict:
        def _run():
            from ..compiler.pack_writer import verify_pack
            pack_dir = Path(params["packDir"])
            manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
            return {"manifest": manifest, "integrityOk": verify_pack(pack_dir)}
        return self._time("pack.inspect", _run)

    def pack_render_golden(self, params: dict) -> dict:
        def _run():
            from ..goldenrun import render_golden_from_pack
            return render_golden_from_pack(Path(params["packDir"]),
                                           Path(params["outDir"]),
                                           int(params.get("seed", 0)),
                                           params)
        return self._time("pack.renderGolden", _run)

    def cache_stats(self, params: dict) -> dict:
        return self._time("cache.stats", lambda: self.cache.stats())

    def cache_prune(self, params: dict) -> dict:
        return self._time("cache.prune", lambda: {"removed": self.cache.prune()})

    def diagnostics_snapshot(self, params: dict) -> dict:
        return self._time("diagnostics.snapshot", lambda: self.diagnostics.snapshot())

    def operation_cancel(self, params: dict) -> dict:
        def _run():
            ok = self.operations.cancel(params["operationId"])
            return {"cancelled": ok}
        return self._time("operation.cancel", _run)

    def shutdown(self, params: dict) -> dict:
        return self._time("shutdown", lambda: {"ok": True})


METHOD_MAP = {
    "health": "health",
    "capabilities": "capabilities",
    "track.import": "track_import",
    "track.analyze": "track_analyze",
    "track.get": "track_get",
    "crate.open": "crate_open",
    "crate.save": "crate_save",
    "transition.preview": "transition_preview",
    "pack.compile": "pack_compile",
    "pack.inspect": "pack_inspect",
    "pack.renderGolden": "pack_render_golden",
    "cache.stats": "cache_stats",
    "cache.prune": "cache_prune",
    "diagnostics.snapshot": "diagnostics_snapshot",
    "operation.cancel": "operation_cancel",
    "shutdown": "shutdown",
}
