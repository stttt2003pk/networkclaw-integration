#!/usr/bin/env python3
"""Resolve the two source worktrees without requiring PyYAML."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from source_tree import included_files, tree_hash, git_diff_hash


ROOT = Path(__file__).resolve().parents[1]


def parse_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def read_local_config(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line or line.startswith("-"):
            continue
        key, value = line.split(":", 1)
        if key.strip() in {"networkclaw_path", "harness_path", "state_dir", "python", "go_binary", "provider_env_file", "service_id", "startup_timeout_seconds", "schema_version", "mode"}:
            result[key.strip()] = parse_scalar(value)
    if path.exists():
        missing = {"schema_version", "mode", "networkclaw_path", "harness_path"} - result.keys()
        if missing:
            raise ValueError(f"{path} is missing required keys: {', '.join(sorted(missing))}")
        if result["schema_version"] != "1" or result["mode"] != "local":
            raise ValueError(f"{path} must declare schema_version: 1 and mode: local")
    return result


def command(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()


def source_metadata(path: Path, marker: str) -> dict[str, object]:
    if not path.is_dir() or not (path / marker).is_file():
        raise ValueError(f"repository is unavailable or missing {marker}: {path}")
    commit: str | None = None
    dirty: bool | None = None
    diff_hash: str | None = None
    try:
        commit = command("git", "rev-parse", "HEAD", cwd=path)
        status = command("git", "status", "--porcelain", cwd=path)
        dirty = bool(status)
        diff_hash = git_diff_hash(path)
    except subprocess.CalledProcessError:
        # Customer source archives may intentionally have no Git metadata.
        dirty = None
    except OSError as exc:
        raise ValueError(f"cannot inspect source tree {path}: {exc}") from exc
    tree = tree_hash(path, included_files(path))
    return {"path": str(path), "commit": commit, "dirty": dirty, "tree_sha256": tree, "diff_sha256": diff_hash}


def resolve() -> dict[str, object]:
    config_path = Path(os.environ.get("NETWORKCLAW_WORKSPACE_FILE", ROOT / "workspace.local.yaml"))
    if not config_path.is_absolute():
        config_path = (ROOT / config_path).resolve()
    config = read_local_config(config_path)
    networkclaw = os.environ.get("NETWORKCLAW_PATH", config.get("networkclaw_path", "../NetworkClaw"))
    harness = os.environ.get("HARNESS_PATH", config.get("harness_path", "../networkclaw-harness"))
    def resolve_path(raw: str) -> Path:
        path = Path(raw)
        return path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    networkclaw_path = resolve_path(networkclaw)
    harness_path = resolve_path(harness)
    configured_python = os.environ.get("NETWORKCLAW_PYTHON", config.get("python", ""))
    python = configured_python or str(harness_path / ".venv" / "bin" / "python")
    if not configured_python and not Path(python).is_file():
        python = "python3.12"
    go_binary = os.environ.get("NETWORKCLAW_GO", config.get("go_binary", "go"))
    state_raw = os.environ.get("NETWORKCLAW_STATE_DIR", config.get("state_dir", ".integration-state"))
    state_path = resolve_path(state_raw)
    provider_env_raw = os.environ.get("NETWORKCLAW_PROVIDER_ENV_FILE", config.get("provider_env_file", ""))
    provider_env_path = resolve_path(provider_env_raw) if provider_env_raw else networkclaw_path / ".env"
    if provider_env_raw and not provider_env_path.is_file():
        raise ValueError(f"configured provider environment file does not exist: {provider_env_path}")
    result = {
        "integration_path": str(ROOT),
        "config_path": str(config_path),
        "networkclaw": source_metadata(networkclaw_path, "go.mod"),
        "harness": source_metadata(harness_path, "pyproject.toml"),
        "python": python,
        "go_binary": go_binary,
        "state_dir": str(state_path),
        "provider_env_file": str(provider_env_path) if provider_env_path.is_file() else None,
        "service_id": os.environ.get("NETWORKCLAW_SERVICE_ID", config.get("service_id", "integration-gateway")),
        "startup_timeout_seconds": int(os.environ.get("NETWORKCLAW_STARTUP_TIMEOUT", config.get("startup_timeout_seconds", "15"))),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--get", choices=("networkclaw", "harness", "python", "go_binary", "state_dir", "service_id"))
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args()
    try:
        result = resolve()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        if args.allow_missing:
            print(json.dumps({"error": str(exc)}))
            return 0
        print(f"resolve-sources: {exc}", file=sys.stderr)
        return 1
    if args.get:
        value = result[args.get]
        if isinstance(value, dict):
            value = value["path"]
        print(value)
    elif args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        for key in ("networkclaw", "harness", "python", "go_binary", "state_dir"):
            value = result[key]
            if isinstance(value, dict):
                value = value["path"]
            print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
