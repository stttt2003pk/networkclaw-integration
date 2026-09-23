#!/usr/bin/env python3
"""JSONL Harness relay for deterministic transport and stale-epoch injection."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from support.event_ledger import EventLedger
from support.fault_injection import JSONLFaultPlan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("pass", "drop", "reset", "sigkill", "disconnect", "stale-terminal"), default="pass")
    parser.add_argument("--after-frames", type=int, default=2)
    parser.add_argument("--events", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a child command is required after --")
    try:
        plan = JSONLFaultPlan("pass" if args.mode == "disconnect" else args.mode, after_frames=args.after_frames)
    except ValueError as error:
        parser.error(str(error))
    ledger = EventLedger(args.events) if args.events else None
    try:
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr, bufsize=0)
    except OSError as error:
        print(f"fault-proxy: cannot start child: {error}", file=sys.stderr)
        return 127
    assert child.stdin is not None and child.stdout is not None
    disconnect_triggered = threading.Event()

    def enforce_disconnect_bound() -> None:
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill()

    def forward_input() -> None:
        forwarded = 0
        try:
            for line in sys.stdin.buffer:
                child.stdin.write(line)
                child.stdin.flush()
                forwarded += 1
                if args.mode == "disconnect" and forwarded >= args.after_frames:
                    if ledger is not None:
                        ledger.record("fault.injected", "go_client_disconnected", mode="disconnect")
                    child.stdin.close()
                    disconnect_triggered.set()
                    threading.Thread(target=enforce_disconnect_bound, daemon=True).start()
                    return
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                child.stdin.close()
            except OSError:
                pass

    input_thread = threading.Thread(target=forward_input, daemon=True)
    input_thread.start()
    interrupted = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        interrupted.set()
        if child.poll() is None:
            child.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    exit_code = 0
    try:
        while not interrupted.is_set():
            line = child.stdout.readline()
            if not line:
                break
            try:
                result = plan.transform(line)
            except ValueError as error:
                print(f"fault-proxy: child emitted invalid protocol data: {error}", file=sys.stderr)
                exit_code = 76
                break
            for frame in result.frames:
                sys.stdout.buffer.write(frame)
                sys.stdout.buffer.flush()
            if result.reason_code:
                if ledger is not None:
                    ledger.record("fault.injected", result.reason_code, mode=args.mode)
                if result.terminate_child:
                    if args.mode in {"reset", "sigkill"}:
                        child.kill()
                    else:
                        child.terminate()
                    exit_code = {"drop": 75, "reset": 76, "sigkill": 77}[args.mode]
                    break
        if child.poll() is None:
            child.terminate()
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=2)
    finally:
        input_thread.join(timeout=1)
        if child.poll() is None:
            child.kill()
            child.wait(timeout=2)
    if args.mode == "disconnect" and disconnect_triggered.is_set() and exit_code == 0:
        exit_code = 78
    if exit_code:
        return exit_code
    return child.returncode or 0


if __name__ == "__main__":
    raise SystemExit(main())
