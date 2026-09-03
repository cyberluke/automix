"""NDJSON JSON-RPC protocol over stdin/stdout (§19-§20). stdout carries protocol
frames only; logs go to stderr and the JSONL diagnostics file."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class Request:
    id: Any
    method: str
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Response:
    id: Any
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        d = {"jsonrpc": "2.0", "id": self.id}
        if self.error is not None:
            d["error"] = self.error
        else:
            d["result"] = self.result
        return d


@dataclass
class ProgressEvent:
    operation_id: str
    progress: float
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "jsonrpc": "2.0",
            "method": "progress",
            "params": {"operationId": self.operation_id,
                       "progress": self.progress,
                       "message": self.message},
        }


def read_frame(line: str) -> Optional[Request]:
    line = line.strip()
    if not line:
        return None
    data = json.loads(line)
    return Request(id=data.get("id"), method=data.get("method", ""),
                   params=data.get("params") or {})


def write_frame(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def send_response(resp: Response) -> None:
    write_frame(resp.to_dict())


def send_progress(ev: ProgressEvent) -> None:
    write_frame(ev.to_dict())


def log_stderr(message: str) -> None:
    sys.stderr.write(message.rstrip() + "\n")
    sys.stderr.flush()
