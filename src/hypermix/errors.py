"""HyperMix stable error model (§31). Normal UI receives concise errors; full
tracebacks go to diagnostics logs."""
from __future__ import annotations

from enum import Enum
from typing import Optional


class ErrorCode(str, Enum):
    HMX_SOURCE_NOT_FOUND = "HMX_SOURCE_NOT_FOUND"
    HMX_SOURCE_CHANGED = "HMX_SOURCE_CHANGED"
    HMX_CANONICALIZE_FAILED = "HMX_CANONICALIZE_FAILED"
    HMX_ANALYSIS_FAILED = "HMX_ANALYSIS_FAILED"
    HMX_NO_DOWNBEAT_GRID = "HMX_NO_DOWNBEAT_GRID"
    HMX_CUE_OUT_OF_RANGE = "HMX_CUE_OUT_OF_RANGE"
    HMX_TRANSITION_NOT_POSSIBLE = "HMX_TRANSITION_NOT_POSSIBLE"
    HMX_PACK_INVALID = "HMX_PACK_INVALID"
    HMX_PACK_INTEGRITY_FAILED = "HMX_PACK_INTEGRITY_FAILED"
    HMX_ASSET_DECODE_FAILED = "HMX_ASSET_DECODE_FAILED"
    HMX_HOTSWAP_DEADLINE_MISSED = "HMX_HOTSWAP_DEADLINE_MISSED"
    HMX_AUDIO_CONTEXT_SUSPENDED = "HMX_AUDIO_CONTEXT_SUSPENDED"
    HMX_SIDECAR_CRASHED = "HMX_SIDECAR_CRASHED"
    HMX_SIDECAR_PROTOCOL_ERROR = "HMX_SIDECAR_PROTOCOL_ERROR"
    HMX_CAPABILITY_MISSING = "HMX_CAPABILITY_MISSING"
    HMX_OPERATION_CANCELLED = "HMX_OPERATION_CANCELLED"
    HMX_UNKNOWN = "HMX_UNKNOWN"


class HyperMixError(Exception):
    """Concise, stable-coded error. `detail` is for diagnostics only."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        detail: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail
        self.context = context or {}

    def to_dict(self) -> dict:
        return {
            "code": self.code.value,
            "message": self.message,
            "detail": self.detail,
            "context": self.context,
        }

    @classmethod
    def from_exception(cls, exc: BaseException, code: ErrorCode = ErrorCode.HMX_UNKNOWN) -> "HyperMixError":
        if isinstance(exc, HyperMixError):
            return exc
        return cls(code=code, message=str(exc) or exc.__class__.__name__,
                   detail=repr(exc))
