from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence


class ManagedProcess:
    """Owns a test child and guarantees bounded shutdown on every path."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self.process = process

    @classmethod
    def start_ready(
        cls,
        command: Sequence[str],
        *,
        prefix: bytes = b"READY ",
        timeout: float = 5,
        env: Mapping[str, str] | None = None,
    ) -> tuple[ManagedProcess, bytes]:
        if timeout <= 0:
            raise ValueError("startup timeout must be positive")
        process = subprocess.Popen(
            list(command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(env) if env is not None else None,
            bufsize=0,
        )
        managed = cls(process)
        assert process.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        pending = bytearray()
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"child exited before readiness with status {process.returncode}")
                events = selector.select(min(0.1, max(0, deadline - time.monotonic())))
                if not events:
                    continue
                chunk = os.read(process.stdout.fileno(), 4096)
                if not chunk:
                    raise RuntimeError("child closed stdout before readiness")
                pending.extend(chunk)
                newline = pending.find(b"\n")
                if newline >= 0:
                    line = bytes(pending[:newline]).rstrip(b"\r")
                    if not line.startswith(prefix):
                        raise RuntimeError(f"child readiness line has unexpected prefix: {line[:160]!r}")
                    return managed, line
            raise TimeoutError("child did not become ready before timeout")
        except BaseException:
            managed.terminate()
            raise
        finally:
            selector.close()

    def disconnect_stdin(self) -> None:
        if self.process.stdin is not None and not self.process.stdin.closed:
            self.process.stdin.close()

    def kill(self) -> None:
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGKILL)

    def terminate(self, *, timeout: float = 2) -> int:
        if self.process.poll() is None:
            self.process.terminate()
        try:
            return self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.kill()
            return self.process.wait(timeout=2)

    def wait(self, *, timeout: float = 2) -> int:
        return self.process.wait(timeout=timeout)

    def close(self) -> None:
        self.terminate()
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()

    def __enter__(self) -> ManagedProcess:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
