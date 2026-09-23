#!/usr/bin/env python3
"""Build, run, and observe the real chatsvc + headless Harness pair."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

from dotenv import dotenv_values

from resolve_sources import resolve


def state_paths(config: dict[str, object]) -> dict[str, Path]:
    state = Path(str(config["state_dir"]))
    return {"root": state, **{name: state / name for name in ("logs", "pids", "bin", "sockets", "diagnostics")}}


def ensure_dirs(paths: dict[str, Path]) -> None:
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path, 0o700)


def pid_path(paths: dict[str, Path], name: str = "chatsvc") -> Path:
    return paths["pids"] / f"{name}.pid"


def harness_pid_path(paths: dict[str, Path]) -> Path:
    return paths["pids"] / "harness.pid"


def harness_child(pid: int) -> tuple[int, str] | None:
    try:
        output = subprocess.check_output(["ps", "-axo", "pid=,ppid=,command="], text=True)
    except subprocess.CalledProcessError:
        return None
    children: dict[int, list[tuple[int, str]]] = {}
    for line in output.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) != 3:
            continue
        try:
            process_id, parent_id = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        children.setdefault(parent_id, []).append((process_id, parts[2]))
    pending = list(children.get(pid, []))
    while pending:
        process_id, command = pending.pop(0)
        if "networkclaw_harness.host" in command:
            return process_id, command
        pending.extend(children.get(process_id, []))
    return None


def process_running(pid_file: Path) -> int | None:
    try:
        record = json.loads(pid_file.read_text(encoding="utf-8"))
        pid = int(record["pid"])
        expected_command = str(record["command"])
        os.kill(pid, 0)
        actual_command = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], text=True).strip()
        if actual_command == expected_command or actual_command.startswith(expected_command + " "):
            return pid
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, subprocess.CalledProcessError):
        pass
    if pid_file.exists():
        pid_file.unlink(missing_ok=True)
    return None


def wait_exit(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    return False


def stop_process(pid_file: Path) -> None:
    pid = process_running(pid_file)
    if pid is None:
        pid_file.unlink(missing_ok=True)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    if not wait_exit(pid, 10):
        os.kill(pid, signal.SIGKILL)
        if not wait_exit(pid, 3):
            raise RuntimeError(f"process {pid} did not exit after SIGKILL")
    pid_file.unlink(missing_ok=True)


def go_binary(config: dict[str, object], paths: dict[str, Path]) -> Path:
    binary = paths["bin"] / "chatsvc"
    source = Path(str(config["networkclaw"]["path"]))
    cmd = [str(config["go_binary"]), "build", "-o", str(binary), "./cmd/chatsvc"]
    result = subprocess.run(cmd, cwd=source, check=False)
    if result.returncode:
        raise RuntimeError(f"Go chatsvc build failed with exit code {result.returncode}")
    return binary


def health_check(socket_path: Path, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    request = struct.pack(">II", 3, 0)
    while time.monotonic() < deadline:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                conn.settimeout(0.5)
                conn.connect(str(socket_path))
                conn.sendall(request)
                header = recv_exact(conn, 8)
                message_type, length = struct.unpack(">II", header)
                if message_type != 3 or length > 1024 * 1024:
                    return False
                response = json.loads(recv_exact(conn, length))
                return response.get("status") == "active"
        except (OSError, ValueError, json.JSONDecodeError):
            time.sleep(0.15)
    return False


def recv_exact(conn: socket.socket, length: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        part = conn.recv(length - len(chunks))
        if not part:
            raise OSError("unexpected EOF from chatsvc")
        chunks.extend(part)
    return bytes(chunks)


def provider_environment(config: dict[str, object], parent_env: dict[str, str]) -> dict[str, str]:
    env = parent_env.copy()
    env_file = config["provider_env_file"]
    if env_file:
        for key, value in dotenv_values(str(env_file)).items():
            if value is not None and not env.get(key):
                env[key] = value
    return env


def start(config: dict[str, object], paths: dict[str, Path], component: str = "go") -> None:
    if component not in {"go", "harness"}:
        raise ValueError(f"unsupported component: {component}")
    existing = process_running(pid_path(paths))
    if existing:
        raise RuntimeError(f"chatsvc already running (pid {existing}); use restart-go or dev-down")
    socket_path = paths["sockets"] / "chatsvc.sock"
    socket_path.unlink(missing_ok=True)
    binary = go_binary(config, paths)
    command = [str(binary), "--service-id", str(config["service_id"]), "--socket-path", str(socket_path),
               "--harness-enabled=true", "--harness-command", str(Path(__file__).with_name("harness-launcher.sh"))]
    log_path = paths["logs"] / "chatsvc.log"
    env = provider_environment(config, os.environ)
    env["PYTHONPATH"] = str(Path(str(config["harness"]["path"])) / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["NETWORKCLAW_HARNESS_FRAME_LOG"] = str(paths["logs"] / "harness-frames.jsonl")
    log_fd = os.open(log_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    os.chmod(log_path, 0o600)
    with os.fdopen(log_fd, "ab") as log:
        log.write(("\n[start] " + json.dumps(command) + "\n").encode())
        process = subprocess.Popen(command, cwd=str(config["networkclaw"]["path"]), env=env,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True, close_fds=True)
    pid_file = pid_path(paths)
    pid_fd = os.open(pid_file, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(pid_fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"pid": process.pid, "command": str(binary)}) + "\n")
    timeout = int(config["startup_timeout_seconds"])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = process.poll()
        if status is not None:
            pid_path(paths).unlink(missing_ok=True)
            socket_path.unlink(missing_ok=True)
            raise RuntimeError(f"chatsvc exited during startup with status {status}; see {log_path}")
        if health_check(socket_path, 0.25):
            child = harness_child(process.pid)
            if child is None:
                stop_process(pid_path(paths))
                socket_path.unlink(missing_ok=True)
                raise RuntimeError("chatsvc is healthy but its managed Harness child could not be located")
            child_pid, child_command = child
            harness_file = harness_pid_path(paths)
            harness_file.write_text(json.dumps({"pid": child_pid, "command": child_command, "parent_pid": process.pid}) + "\n", encoding="utf-8")
            os.chmod(harness_file, 0o600)
            print(f"chatsvc ready pid={process.pid} socket={socket_path}")
            print(f"Harness ready pid={child_pid}; command={child_command}")
            if component == "harness":
                print("Harness is supervised by chatsvc; this restart restarted the owning JSONL process.")
            return
        time.sleep(0.1)
    stop_process(pid_path(paths))
    socket_path.unlink(missing_ok=True)
    raise RuntimeError(f"chatsvc health check timed out after {timeout}s; see {log_path}")


def shutdown(paths: dict[str, Path]) -> None:
    stop_process(pid_path(paths))
    harness_pid_path(paths).unlink(missing_ok=True)
    (paths["sockets"] / "chatsvc.sock").unlink(missing_ok=True)
    print("chatsvc stopped; integration-owned socket removed")


def collect_diagnostics(config: dict[str, object], paths: dict[str, Path]) -> Path:
    paths["diagnostics"].mkdir(parents=True, exist_ok=True)
    report = paths["diagnostics"] / f"workspace-{int(time.time())}.json"
    details = {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "integration": config["integration_path"],
        "networkclaw": config["networkclaw"],
        "harness": config["harness"],
        "service_id": config["service_id"],
        "provider_env_configured": bool(config["provider_env_file"]),
        "chatsvc_pid": process_running(pid_path(paths)),
        "harness_process": json.loads(harness_pid_path(paths).read_text(encoding="utf-8")) if harness_pid_path(paths).is_file() else None,
        "socket_path": str(paths["sockets"] / "chatsvc.sock"),
        "harness_launcher": str(Path(__file__).with_name("harness-launcher.sh")),
        "log_path": str(paths["logs"] / "chatsvc.log"),
        "protocol": {"version": "1.0", "transport": "JSONL stdin/stdout", "secret_payload_logging": False},
    }
    report_fd = os.open(report, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(report_fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(details, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("up", "down", "restart-go", "restart-harness", "logs", "collect-diagnostics"))
    args = parser.parse_args()
    try:
        config = resolve()
        paths = state_paths(config)
        if args.command != "logs":
            ensure_dirs(paths)
        if args.command in {"up", "restart-go", "restart-harness"}:
            if args.command != "up":
                shutdown(paths)
            start(config, paths, "harness" if args.command == "restart-harness" else "go")
        elif args.command == "down":
            shutdown(paths)
        elif args.command == "logs":
            log_path = paths["logs"] / "chatsvc.log"
            if not log_path.is_file():
                raise RuntimeError(f"no logs found: {log_path}")
            os.execvp("tail", ["tail", "-n", "100", "-f", str(log_path)])
        elif args.command == "collect-diagnostics":
            collect_diagnostics(config, paths)
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"dev: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
