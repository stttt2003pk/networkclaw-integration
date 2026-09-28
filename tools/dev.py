#!/usr/bin/env python3
"""Build, run, and observe the real chatrtmgr + Harness Gateway stack."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

from dotenv import dotenv_values

from resolve_sources import resolve

def state_paths(config: dict[str, object]) -> dict[str, Path]:
    state = Path(str(config["state_dir"]))
    return {"root": state, **{name: state / name for name in ("logs", "pids", "bin", "sockets", "diagnostics")}}


def chatrtmgr_socket_dir(paths: dict[str, Path]) -> Path:
    """Return a short, workspace-specific directory for dynamic UDS paths."""
    key = hashlib.sha256(str(paths["root"].resolve()).encode("utf-8")).hexdigest()[:10]
    return Path("/tmp") / f"nc-{key}"


def ensure_dirs(paths: dict[str, Path]) -> None:
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path, 0o700)


def pid_path(paths: dict[str, Path], name: str = "chatrtmgr") -> Path:
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
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        if not wait_exit(pid, 3):
            raise RuntimeError(f"process {pid} did not exit after SIGKILL")
    pid_file.unlink(missing_ok=True)


def go_binary(config: dict[str, object], paths: dict[str, Path]) -> Path:
    binary = paths["bin"] / "chatrtmgr"
    source = Path(str(config["networkclaw"]["path"]))
    cmd = [str(config["go_binary"]), "build", "-o", str(binary), "./cmd/chatrtmgr"]
    result = subprocess.run(cmd, cwd=source, check=False)
    if result.returncode:
        raise RuntimeError(f"Go chatrtmgr build failed with exit code {result.returncode}")
    return binary


def build_binary(config: dict[str, object], paths: dict[str, Path], name: str) -> Path:
    binary = paths["bin"] / name
    source = Path(str(config["networkclaw"]["path"]))
    result = subprocess.run([str(config["go_binary"]), "build", "-o", str(binary), f"./cmd/{name}"], cwd=source, check=False)
    if result.returncode:
        raise RuntimeError(f"Go {name} build failed with exit code {result.returncode}")
    return binary


def run_local_migrations(config: dict[str, object], env: dict[str, str]) -> None:
    migration_dir = Path(str(config["networkclaw"]["path"])) / "internal/lobby/database/migrations"
    for migration in sorted(migration_dir.glob("*.up.sql")):
        result = subprocess.run(["psql", "-X", "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1", "-U",
                                 env.get("POSTGRES_USER", "ongrid"), "-d", env.get("POSTGRES_DB", "ongrid"), "-f", str(migration)],
                                env=env, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if result.returncode:
            if "already exists" in result.stderr:
                continue
            raise RuntimeError(f"local migration failed: {migration.name}: {result.stderr.strip()}")


def write_process_pid(paths: dict[str, Path], name: str, process: subprocess.Popen[str], command: str) -> None:
    path = pid_path(paths, name)
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"pid": process.pid, "command": command}) + "\n")


def start_frontend(config: dict[str, object], paths: dict[str, Path]) -> None:
    frontend = Path(str(config["networkclaw"]["path"])) / "web2"
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node is required to start NetworkClaw web2")
    vite = frontend / "node_modules/vite/bin/vite.js"
    if not vite.is_file():
        raise RuntimeError(f"frontend dependencies are missing; run npm ci in {frontend}")

    log_path = paths["logs"] / "web2.log"
    log_fd = os.open(log_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    os.chmod(log_path, 0o600)
    command = [node, str(vite), "--host", "127.0.0.1", "--strictPort"]
    with os.fdopen(log_fd, "ab") as log:
        log.write(("\n[start] " + json.dumps(command) + "\n").encode())
        process = subprocess.Popen(command, cwd=str(frontend), env=os.environ.copy(),
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True, close_fds=True, text=True)
    write_process_pid(paths, "frontend", process, " ".join(command))

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        try:
            with urlopen("http://127.0.0.1:5174/", timeout=0.5) as response:
                if response.status == 200:
                    print("NetworkClaw web2 ready: http://127.0.0.1:5174/")
                    return
        except OSError:
            time.sleep(0.2)
    stop_process(pid_path(paths, "frontend"))
    raise RuntimeError(f"NetworkClaw web2 did not become ready; see {log_path}")


def spawn_service(config: dict[str, object], paths: dict[str, Path], name: str, binary: Path, env: dict[str, str]) -> subprocess.Popen[str]:
    log_path = paths["logs"] / f"{name}.log"
    log_fd = os.open(log_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    os.chmod(log_path, 0o600)
    with os.fdopen(log_fd, "ab") as log:
        log.write(("\n[start] " + json.dumps([str(binary)]) + "\n").encode())
        process = subprocess.Popen([str(binary)], cwd=str(config["networkclaw"]["path"]), env=env,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True, close_fds=True, text=True)
    write_process_pid(paths, name, process, str(binary))
    return process


def start_full(config: dict[str, object], paths: dict[str, Path]) -> None:
    if any(process_running(pid_path(paths, name)) for name in ("frontend", "lobby", "chatrtmgr")):
        raise RuntimeError("full stack is already running; use dev-down first")
    stop_process(pid_path(paths, "chatrtmgr"))
    binaries = {name: build_binary(config, paths, name) for name in ("chatrtmgr", "lobby")}
    env = provider_environment(config, os.environ)
    common = {**os.environ, **env}
    run_local_migrations(config, common)
    common.update({"CHATRTMGR_PROCESS_TARGET": "gateway",
                   "CHATRTMGR_GATEWAY_BINARY_PATH": str(Path(str(config["harness"]["path"])) / ".venv/bin/networkclaw-harness"),
                   "NETWORKCLAW_GATEWAY_PROFILE": "development", "NETWORKCLAW_HARNESS_PROVIDER_MODE": "live",
                   "PYTHONPATH": str(config["harness"]["path"]) + "/src"})
    socket_dir = chatrtmgr_socket_dir(paths)
    socket_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(socket_dir, 0o700)
    registry = str(paths["root"] / "local-registry.json")
    chatrt_env = dict(common, CHATRTMGR_DISCOVERY_TYPE="local", CHATRTMGR_LOCAL_REGISTRY_PATH=registry,
                      CHATRTMGR_GRPC_ADDR="127.0.0.1:50052",
                      CHATRTMGR_METRICS_ADDR="127.0.0.1:9101", CHATRTMGR_GATEWAY_BINARY_PATH=common["CHATRTMGR_GATEWAY_BINARY_PATH"],
                      CHATRTMGR_SOCKET_DIR=str(socket_dir), NETWORKCLAW_HARNESS_FRAME_LOG=str(paths["logs"] / "gateway-frames.jsonl"))
    spawn_service(config, paths, "chatrtmgr", binaries["chatrtmgr"], chatrt_env)
    deadline = time.monotonic() + int(config["startup_timeout_seconds"])
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", 50052), timeout=0.3):
                break
        except OSError:
            time.sleep(0.2)
    else:
        raise RuntimeError(f"chatrtmgr did not become ready; see {paths['logs'] / 'chatrtmgr.log'}")
    lobby_env = dict(common, ONGRID_HTTP_ADDR=":8080", ONGRID_METRICS_ADDR=":9100", ONGRID_DB_HOST="127.0.0.1",
                     ONGRID_DB_PORT="5432", ONGRID_DB_USER=env.get("POSTGRES_USER", "ongrid"), ONGRID_DB_NAME=env.get("POSTGRES_DB", "ongrid"),
                     ONGRID_DB_SSLMODE="disable", ONGRID_REDIS_ADDR="127.0.0.1:6379", ONGRID_DISCOVERY_TYPE="local",
                     ONGRID_LOCAL_REGISTRY_PATH=registry, ONGRID_JWT_SECRET=env.get("ONGRID_JWT_SECRET", "integration-local-jwt-secret-change-me"),
                     ONGRID_OIDC_SECRET_KEY=env.get("ONGRID_OIDC_SECRET_KEY", "integration-local-oidc-secret-change-me"),
                     ONGRID_WEB2_ORIGINS=env.get("ONGRID_WEB2_ORIGINS", "http://localhost:5174"),
                     ONGRID_SEED_ADMIN_EMAIL=env.get("ONGRID_SEED_ADMIN_EMAIL", "admin"),
                     ONGRID_SEED_ADMIN_PASSWORD=env.get("ONGRID_SEED_ADMIN_PASSWORD", "admin"),
                     ONGRID_HARNESS_ENABLED="true", ONGRID_HARNESS_ROLLOUT_PERCENT="100")
    spawn_service(config, paths, "lobby", binaries["lobby"], lobby_env)
    try:
        start_frontend(config, paths)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        shutdown(paths)
        raise
    print("full stack ready: http://127.0.0.1:5174/ (web2), http://127.0.0.1:8080 (lobby), chatrtmgr=127.0.0.1:50052")


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
            raise OSError("unexpected EOF from Gateway")
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


def start(config: dict[str, object], paths: dict[str, Path], component: str = "gateway") -> None:
    if component not in {"gateway", "go"}:
        raise ValueError(f"unsupported component: {component}")
    existing = process_running(pid_path(paths, "chatrtmgr"))
    if existing:
        raise RuntimeError(f"Gateway already running (pid {existing}); use restart-go or dev-down")
    binary = build_binary(config, paths, "chatrtmgr")
    command = [str(binary)]
    log_path = paths["logs"] / "gateway.log"
    env = provider_environment(config, os.environ)
    env["CHATRTMGR_PROCESS_TARGET"] = "gateway"
    env["CHATRTMGR_GATEWAY_BINARY_PATH"] = str(Path(str(config["harness"]["path"])) / ".venv/bin/networkclaw-harness")
    env["PYTHONPATH"] = str(Path(str(config["harness"]["path"])) / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["NETWORKCLAW_HARNESS_FRAME_LOG"] = str(paths["logs"] / "gateway-frames.jsonl")
    log_fd = os.open(log_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    os.chmod(log_path, 0o600)
    with os.fdopen(log_fd, "ab") as log:
        log.write(("\n[start] " + json.dumps(command) + "\n").encode())
        process = subprocess.Popen(command, cwd=str(config["networkclaw"]["path"]), env=env,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True, close_fds=True)
    pid_file = pid_path(paths, "chatrtmgr")
    pid_fd = os.open(pid_file, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(pid_fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"pid": process.pid, "command": str(binary)}) + "\n")
    timeout = int(config["startup_timeout_seconds"])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = process.poll()
        if status is not None:
            pid_file.unlink(missing_ok=True)
            raise RuntimeError(f"Gateway exited during startup with status {status}; see {log_path}")
        try:
            with socket.create_connection(("127.0.0.1", 50052), timeout=0.3):
                print(f"Gateway ready pid={process.pid}; target=gateway log={log_path}")
                return
        except OSError:
            time.sleep(0.2)
    stop_process(pid_file)
    raise RuntimeError(f"Gateway health check timed out after {timeout}s; see {log_path}")


def shutdown(paths: dict[str, Path]) -> None:
    full_stack = any(process_running(pid_path(paths, name)) for name in ("frontend", "lobby", "chatrtmgr"))
    for name in ("frontend", "lobby", "chatrtmgr"):
        stop_process(pid_path(paths, name))
    socket_dir = chatrtmgr_socket_dir(paths)
    if socket_dir.is_dir():
        for socket_path in socket_dir.glob("*.sock"):
            socket_path.unlink(missing_ok=True)
        try:
            socket_dir.rmdir()
        except OSError:
            pass
    print("full stack stopped; local processes stopped; local dependencies were not modified" if full_stack else "Gateway stopped; integration-owned state removed")


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
        "gateway_pid": process_running(pid_path(paths, "chatrtmgr")),
        "gateway_socket_dir": str(chatrtmgr_socket_dir(paths)),
        "chatrtmgr_socket_dir": str(chatrtmgr_socket_dir(paths)),
        "harness_launcher": str(Path(__file__).with_name("harness-launcher.sh")),
        "log_path": str(paths["logs"] / "gateway.log"),
        "protocol": {"version": "1.0", "transport": "UDS JSONL", "secret_payload_logging": False},
    }
    report_fd = os.open(report, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(report_fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(details, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("up", "down", "restart-go", "restart-gateway", "logs", "collect-diagnostics"))
    args = parser.parse_args()
    try:
        config = resolve()
        paths = state_paths(config)
        if args.command != "logs":
            ensure_dirs(paths)
        if args.command == "up":
            start_full(config, paths)
        elif args.command in {"restart-go", "restart-gateway"}:
            if args.command != "up":
                shutdown(paths)
            start(config, paths, "gateway")
        elif args.command == "down":
            shutdown(paths)
        elif args.command == "logs":
            log_path = paths["logs"] / "gateway.log"
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
