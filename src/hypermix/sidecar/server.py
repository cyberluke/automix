"""Sidecar server loop (§19-§21). Reads NDJSON JSON-RPC requests from stdin,
dispatches to handlers, writes responses to stdout. Logs to stderr + JSONL."""
from __future__ import annotations

import sys
import time
from pathlib import Path

from ..errors import ErrorCode, HyperMixError
from .diagnostics import Diagnostics
from .handlers import Handlers, METHOD_MAP
from .protocol import (Response, log_stderr, read_frame, send_progress,
                       send_response)


class SidecarServer:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        log_path = self.root / "var" / "logs" / "sidecar.jsonl"
        self.diagnostics = Diagnostics(log_path)
        self.handlers = Handlers(self.root, self.diagnostics)
        self._running = True

    def dispatch(self, request) -> None:
        method = request.method
        attr = METHOD_MAP.get(method)
        if attr is None:
            send_response(Response(id=request.id, error={
                "code": ErrorCode.HMX_UNKNOWN.value,
                "message": f"unknown method {method!r}",
            }))
            return
        op_id = (request.params or {}).get("operationId")
        cancel_ev = self.handlers.operations.register(op_id) if op_id else None
        start = time.time()
        try:
            fn = getattr(self.handlers, attr)
            # Opportunistic cooperative cancellation between work chunks.
            if cancel_ev and cancel_ev.is_set():
                raise HyperMixError(ErrorCode.HMX_OPERATION_CANCELLED,
                                    f"operation {op_id} cancelled")
            result = fn(request.params or {})
            send_response(Response(id=request.id, result=result))
        except HyperMixError as e:
            send_response(Response(id=request.id, error=e.to_dict()))
        except Exception as e:  # pragma: no cover - defensive
            send_response(Response(id=request.id,
                                   error=HyperMixError.from_exception(e).to_dict()))
        finally:
            if op_id:
                self.handlers.operations.finish(op_id)
            if method == "shutdown":
                self._running = False

    def run(self) -> int:
        log_stderr(f"hypermix sidecar ready (root={self.root})")
        for line in sys.stdin:
            if not self._running:
                break
            line = line.strip()
            if not line:
                continue
            try:
                req = read_frame(line)
            except Exception as e:
                log_stderr(f"protocol error: {e}")
                continue
            if req is None:
                continue
            self.dispatch(req)
        log_stderr("hypermix sidecar stopped")
        return 0
