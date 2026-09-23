from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


FAULT_REASON_CODES = frozenset({
    "transport_dropped",
    "transport_reset",
    "harness_sigkill",
    "go_client_disconnected",
    "stale_epoch_injected",
})
_TERMINALS = frozenset({"turn.completed", "turn.failed", "turn.cancelled"})


@dataclass(frozen=True, slots=True)
class ProxyResult:
    frames: tuple[bytes, ...]
    reason_code: str | None = None
    terminate_child: bool = False


class JSONLFaultPlan:
    """Deterministic, payload-preserving fault decisions for a JSONL relay."""

    def __init__(self, mode: str = "pass", *, after_frames: int = 1) -> None:
        if mode not in {"pass", "drop", "reset", "sigkill", "stale-terminal"}:
            raise ValueError(f"unsupported JSONL fault mode: {mode}")
        if after_frames < 1:
            raise ValueError("after_frames must be positive")
        self.mode = mode
        self.after_frames = after_frames
        self._forwarded = 0
        self._triggered = False

    def transform(self, raw_line: bytes) -> ProxyResult:
        if not raw_line.endswith(b"\n"):
            raise ValueError("JSONL frame must end with newline")
        try:
            frame = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("JSONL frame must contain valid JSON") from error
        if not isinstance(frame, dict):
            raise ValueError("JSONL frame must be an object")

        self._forwarded += 1
        if self._triggered:
            return ProxyResult(())
        if self.mode == "pass":
            return ProxyResult((raw_line,))
        if self.mode in {"drop", "reset", "sigkill"} and self._forwarded >= self.after_frames:
            self._triggered = True
            reason_code = {
                "drop": "transport_dropped",
                "reset": "transport_reset",
                "sigkill": "harness_sigkill",
            }[self.mode]
            return ProxyResult((), reason_code, True)
        if self.mode == "stale-terminal" and frame.get("type") in _TERMINALS:
            payload = frame.get("payload")
            epoch = payload.get("execution_epoch") if isinstance(payload, dict) else None
            if isinstance(epoch, int) and not isinstance(epoch, bool) and epoch > 0:
                stale = json.loads(raw_line)
                stale["payload"]["execution_epoch"] = epoch - 1
                self._triggered = True
                return ProxyResult((json.dumps(stale, separators=(",", ":")).encode() + b"\n", raw_line), "stale_epoch_injected")
        return ProxyResult((raw_line,))


def event_metadata(reason_code: str, *, mode: str) -> dict[str, Any]:
    if reason_code not in FAULT_REASON_CODES:
        raise ValueError(f"unknown fault reason code: {reason_code}")
    if mode not in {"pass", "drop", "reset", "stale-terminal", "sigkill", "disconnect"}:
        raise ValueError(f"unknown fault mode: {mode}")
    return {"event": "fault.injected", "reason_code": reason_code, "mode": mode}
