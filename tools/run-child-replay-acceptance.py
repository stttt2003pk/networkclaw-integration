#!/usr/bin/env python3
"""Verify durable Lobby child authority using isolated PostgreSQL and OS workers."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    source = subprocess.check_output(
        [sys.executable, str(ROOT / "tools/resolve_sources.py"), "--get", "networkclaw"], text=True,
    ).strip()
    evidence = ROOT / ".integration-state/evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    report = evidence / "event-e06-child-restart.json"
    report.unlink(missing_ok=True)
    env = os.environ.copy()
    env["NETWORKCLAW_CHILD_REPLAY_REPORT"] = str(report)
    container = None
    cleanup = 0
    result = 1
    with tempfile.TemporaryDirectory(prefix="networkclaw-e06-child-postgres-") as data:
        try:
            if not env.get("NETWORKCLAW_CHILD_DATABASE_URL"):
                container = "networkclaw-e06-child-" + uuid.uuid4().hex[:12]
                subprocess.run([
                    "docker", "run", "-d", "--name", container,
                    "-p", "127.0.0.1::5432", "-e", "POSTGRES_USER=e06",
                    "-e", "POSTGRES_PASSWORD=e06-fixture", "-e", "POSTGRES_DB=e06",
                    "--mount", f"type=bind,src={data},dst=/var/lib/postgresql/data", "postgres:16-alpine",
                ], check=True, capture_output=True, text=True, timeout=120)
                port = subprocess.check_output([
                    "docker", "inspect", "--format",
                    '{{(index (index .NetworkSettings.Ports "5432/tcp") 0).HostPort}}', container,
                ], text=True).strip()
                env["NETWORKCLAW_CHILD_DATABASE_URL"] = f"postgres://e06:e06-fixture@127.0.0.1:{port}/e06?sslmode=disable"
                deadline = time.monotonic() + 30
                while subprocess.run(["docker", "exec", container, "pg_isready", "-U", "e06"], capture_output=True).returncode:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("isolated PostgreSQL did not become ready")
                    time.sleep(0.2)
            completed = subprocess.run([
                "go", "test", "-json", "-race", "./tests/integration/harnessinterop",
                "-run=^TestCanonicalChildAuthoritySurvivesLobbyProcessRestart$", "-count=1",
            ], cwd=source, env=env, capture_output=True, text=True, timeout=180)
            log = evidence / "event-e06-child-restart.log"
            log.write_text(completed.stdout + completed.stderr)
            log.chmod(0o600)
            result = completed.returncode
            if result == 0 and (not report.exists() or json.loads(report.read_text()).get("status") != "passed"):
                raise RuntimeError("child replay acceptance produced no passing report")
        finally:
            if container:
                # Linux initdb changes bind-directory ownership to the postgres UID.
                ownership = subprocess.run([
                    "docker", "exec", "-u", "0", container, "chown", "-R",
                    f"{os.getuid()}:{os.getgid()}", "/var/lib/postgresql/data",
                ], capture_output=True, timeout=30).returncode
                cleanup = subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=30).returncode
                cleanup = cleanup or ownership
            if report.exists():
                record = json.loads(report.read_text())
                record["cleanup_exit_code"] = cleanup
                record["schema_cleanup_verified"] = result == 0
                if cleanup:
                    record["status"] = "failed"
                report.write_text(json.dumps(record, indent=2) + "\n")
    return result or cleanup


if __name__ == "__main__":
    raise SystemExit(main())
