#!/usr/bin/env python3
"""Run the complete Docker Compose validation stack without committing secrets."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

if __package__:
    from .local_image import build_local_image
    from .model_setup import bootstrap_models, runtime_environment, snapshot_secrets
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from local_image import build_local_image
    from model_setup import bootstrap_models, runtime_environment, snapshot_secrets


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "deploy/compose/docker-compose.yml"


def source_path() -> Path:
    raw = os.environ.get("NETWORKCLAW_PATH", str(ROOT.parent / "NetworkClaw"))
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    return path


def environment() -> dict[str, str]:
    env = os.environ.copy()
    provider_file = os.environ.get("NETWORKCLAW_PROVIDER_ENV_FILE")
    path = Path(provider_file).expanduser() if provider_file else source_path() / ".env"
    if path.is_file():
        for key, value in dotenv_values(path).items():
            if value is not None and not env.get(key):
                env[key] = value
    migration_dir = source_path() / "internal/lobby/database/migrations"
    if not migration_dir.is_dir():
        raise SystemExit(f"NetworkClaw migrations not found: {migration_dir}")
    env.setdefault("NETWORKCLAW_MIGRATIONS_DIR", str(migration_dir))
    env.setdefault("NETWORKCLAW_IMAGE", "networkclaw:ci-linux-amd64")
    env.setdefault("POSTGRES_PASSWORD", "integration-local-postgres")
    env.setdefault("ONGRID_JWT_SECRET", "integration-local-jwt-secret-change-me")
    env.setdefault("ONGRID_OIDC_SECRET_KEY", "integration-local-oidc-secret-change-me")
    env.setdefault("ONGRID_SEED_ADMIN_EMAIL", "admin")
    env.setdefault("ONGRID_SEED_ADMIN_PASSWORD", "admin")
    env.setdefault("ONGRID_WEB2_ORIGINS", "http://localhost:5174,http://127.0.0.1:5174")
    return env


def run(action: str, env: dict[str, str]) -> int:
    command = ["docker", "compose", "-f", str(COMPOSE_FILE)]
    runtime = runtime_environment(env)
    runtime.setdefault("NETWORKCLAW_MODEL_SECRET_DIR", str(ROOT / ".integration-state/model-secrets"))
    if action == "up":
        snapshot_secrets(Path(runtime["NETWORKCLAW_MODEL_SECRET_DIR"]), container_readable=True)
        subprocess.run([*command, "down", "--remove-orphans"], cwd=ROOT, env=runtime, check=True)
        if env.get("NETWORKCLAW_REBUILD", "1") != "0":
            build_local_image(env["NETWORKCLAW_IMAGE"])
        command += ["up", "-d", "--wait"]
    elif action == "down":
        command += ["down"]
    elif action == "status":
        command += ["ps", "--all"]
    else:
        raise SystemExit(f"unsupported action: {action}")
    result = subprocess.run(command, cwd=ROOT, env=runtime, check=False).returncode
    if result == 0 and action == "up":
        bootstrap_models(f"http://127.0.0.1:{env.get('LOBBY_HTTP_PORT', '8080')}", env)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("up", "down", "status"))
    args = parser.parse_args()
    return run(args.action, environment())


if __name__ == "__main__":
    raise SystemExit(main())
