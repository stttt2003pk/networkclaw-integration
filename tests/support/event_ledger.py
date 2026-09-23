from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Any


_ALLOWED_FIELDS = frozenset({"chunk_count", "delay_ms", "mode", "model", "status", "stream"})
_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MAX_LEDGER_BYTES = 4 * 1024 * 1024
_MAX_MEMORY_EVENTS = 2048


class EventLedger:
    """Bounded, payload-free JSONL event log for local integration fixtures."""

    def __init__(self, path: Path | None = None, *, max_bytes: int = _MAX_LEDGER_BYTES) -> None:
        if max_bytes < 128:
            raise ValueError("ledger byte limit must be at least 128")
        self.path = path
        self.max_bytes = max_bytes
        self._events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(path.parent, 0o700)

    def record(self, event: str, reason_code: str, **metadata: Any) -> dict[str, Any]:
        if not event or not event.isascii() or len(event) > 96:
            raise ValueError("event name must be bounded ASCII")
        if not _REASON_CODE.fullmatch(reason_code):
            raise ValueError("reason_code must be stable snake_case ASCII")
        unknown = set(metadata) - _ALLOWED_FIELDS
        if unknown:
            raise ValueError(f"unsupported ledger fields: {', '.join(sorted(unknown))}")
        entry = {
            "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": event,
            "reason_code": reason_code,
            **metadata,
        }
        encoded = (json.dumps(entry, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode()
        with self._lock:
            if len(self._events) >= _MAX_MEMORY_EVENTS:
                raise OverflowError("fixture event ledger reached its in-memory limit")
            if self.path is not None:
                descriptor = os.open(self.path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
                try:
                    os.fchmod(descriptor, 0o600)
                    fcntl.flock(descriptor, fcntl.LOCK_EX)
                    current_size = os.fstat(descriptor).st_size
                    if current_size + len(encoded) > self.max_bytes:
                        raise OverflowError("fixture event ledger reached its byte limit")
                    written = os.write(descriptor, encoded)
                    if written != len(encoded):
                        raise OSError("short write to fixture event ledger")
                finally:
                    os.close(descriptor)
            self._events.append(entry)
        return dict(entry)

    def snapshot(self) -> list[dict[str, Any]]:
        if self.path is None:
            with self._lock:
                return [dict(event) for event in self._events]
        if not self.path.exists():
            return []
        content = self.path.read_bytes()
        if len(content) > self.max_bytes:
            raise OverflowError("fixture event ledger exceeds its byte limit")
        events: list[dict[str, Any]] = []
        for line in content.splitlines():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("fixture event ledger entry must be an object")
            events.append(value)
        return events

    def wait_for(
        self,
        predicate: Callable[[Mapping[str, Any]], bool],
        *,
        timeout: float,
        interval: float = 0.02,
    ) -> dict[str, Any]:
        if timeout <= 0 or interval <= 0:
            raise ValueError("wait timeout and interval must be positive")
        deadline = time.monotonic() + timeout
        while True:
            for event in self.snapshot():
                if predicate(event):
                    return event
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for fixture event")
            time.sleep(min(interval, remaining))
