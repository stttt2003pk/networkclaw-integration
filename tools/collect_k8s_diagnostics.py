#!/usr/bin/env python3
"""Collect Kubernetes metadata and optionally redacted recent logs."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


_SECRET = re.compile(
    r"(?i)(\b[\w-]*(?:api[_-]?key|access[_-]?token|authorization|cookie|password|secret|token)\b\s*[:=]\s*)([^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+")


def redact_text(text: str) -> str:
    return _SECRET.sub(r"\1[REDACTED]", _BEARER.sub("Bearer [REDACTED]", text))


def run_kubectl(kubectl: str, context: str, namespace: str, args: list[str]) -> tuple[int, str]:
    command = [kubectl]
    if context:
        command.extend(["--context", context])
    command.extend(["-n", namespace, *args])
    try:
        completed = subprocess.run(command, text=True, capture_output=True, check=False, timeout=30)
    except subprocess.TimeoutExpired:
        return 1, "kubectl command timed out\n"
    output = completed.stdout
    if completed.stderr:
        output += "\n[stderr]\n" + completed.stderr
    return completed.returncode, redact_text(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--selector", default="app.kubernetes.io/part-of=networkclaw-bundle")
    parser.add_argument("--kubectl", default="kubectl")
    parser.add_argument("--context", default="", help="kubectl context to inspect")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-logs", action="store_true", help="include recent logs after redaction")
    parser.add_argument("--since", default="10m")
    args = parser.parse_args()

    args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    args.output.chmod(0o700)
    commands = {
        "pods.txt": ["get", "pods", "-l", args.selector, "-o", "custom-columns=NAME:.metadata.name,PHASE:.status.phase,READY:.status.containerStatuses[*].ready,RESTARTS:.status.containerStatuses[*].restartCount"],
        "deployments.txt": ["get", "deployments", "-l", args.selector, "-o", "custom-columns=NAME:.metadata.name,DESIRED:.spec.replicas,READY:.status.readyReplicas,AVAILABLE:.status.availableReplicas"],
        "services.txt": ["get", "services", "-l", args.selector, "-o", "custom-columns=NAME:.metadata.name,TYPE:.spec.type,CLUSTER-IP:.spec.clusterIP,PORTS:.spec.ports[*].port"],
    }
    failures = 0
    for filename, command in commands.items():
        code, output = run_kubectl(args.kubectl, args.context, args.namespace, command)
        if code:
            failures += 1
        (args.output / filename).write_text(output, encoding="utf-8")
        (args.output / filename).chmod(0o600)

    if args.include_logs:
        code, output = run_kubectl(args.kubectl, args.context, args.namespace, [
            "logs", "-l", args.selector, "--all-containers", "--prefix", "--since", args.since,
        ])
        if code:
            failures += 1
        (args.output / "logs.txt").write_text(output, encoding="utf-8")
        (args.output / "logs.txt").chmod(0o600)

    metadata = (
        f"collected_at={datetime.now(timezone.utc).isoformat()}\n"
        f"namespace={args.namespace}\nselector={args.selector}\nlogs_included={args.include_logs}\n"
        f"context={args.context or '<current>'}\n"
    )
    (args.output / "README.txt").write_text(metadata, encoding="utf-8")
    (args.output / "README.txt").chmod(0o600)
    if failures:
        print(f"diagnostics: {failures} kubectl command(s) failed", file=sys.stderr)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
