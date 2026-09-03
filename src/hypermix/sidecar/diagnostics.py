"""Structured diagnostics snapshot for the sidecar (§22)."""
from __future__ import annotations

import json
import platform
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional


class Diagnostics:
    def __init__(self, log_path: Optional[Path] = None) -> None:
        self.started = time.time()
        self.operations: List[Dict] = []
        self._lock = threading.Lock()
        self.log_path = Path(log_path) if log_path else None
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, method: str, ok: bool, duration_ms: float,
               detail: Optional[dict] = None) -> None:
        entry = {"ts": time.time(), "method": method, "ok": ok,
                 "durationMs": round(duration_ms, 2)}
        if detail:
            entry["detail"] = detail
        with self._lock:
            self.operations.append(entry)
            if len(self.operations) > 500:
                self.operations = self.operations[-500:]
            if self.log_path:
                with self.log_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry) + "\n")

    def snapshot(self) -> dict:
        with self._lock:
            ops = list(self.operations)
        return {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "uptimeSec": round(time.time() - self.started, 2),
            "operations": ops[-50:],
            "counts": {
                "total": len(ops),
                "errors": sum(1 for o in ops if not o["ok"]),
            },
        }
