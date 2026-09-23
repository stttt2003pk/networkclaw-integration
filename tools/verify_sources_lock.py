#!/usr/bin/env python3
"""Verify checkout commit/tree identities against sources.lock.yaml."""
from __future__ import annotations
import argparse, json, os, subprocess, sys
from pathlib import Path
import yaml
from jsonschema import Draft202012Validator
from source_tree import tree_hash, included_files

ROOT = Path(__file__).resolve().parents[1]


def normalized_repository(value: str) -> str:
    value = value.strip().removesuffix(".git")
    if value.startswith("git@") and ":" in value:
        return value.split(":", 1)[1]
    for prefix in ("https://", "http://", "ssh://", "git://"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    return value.removeprefix("github.com/")


def origin_repository(root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "remote", "get-url", "origin"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, default=ROOT / "sources.lock.yaml")
    args = parser.parse_args()
    if not args.lock.is_file():
        print(f"sources lock is missing: {args.lock}", file=sys.stderr)
        return 2
    lock = yaml.safe_load(args.lock.read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schemas/sources-lock.schema.json").read_text(encoding="utf-8"))
    schema_errors = sorted(Draft202012Validator(schema).iter_errors(lock), key=lambda error: list(error.absolute_path))
    if schema_errors:
        print(f"sources lock schema validation failed: {schema_errors[0].message}", file=sys.stderr)
        return 1
    if lock.get("protocol", {}).get("version") != "1.0":
        print("sources lock protocol must be 1.0", file=sys.stderr)
        return 1
    target = lock.get("target", {})
    if target != {"os": "ubuntu", "version": "22.04", "architecture": "amd64"}:
        print("sources lock target must be ubuntu 22.04 amd64", file=sys.stderr)
        return 1
    resolved = json.loads(subprocess.check_output([sys.executable, str(ROOT / "tools/resolve_sources.py"), "--json"]))
    resolved["integration"] = {
        "commit": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
        "dirty": bool(subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"], text=True).strip()),
        "tree_sha256": tree_hash(ROOT, included_files(ROOT)),
    }
    errors = []
    allow_dirty = os.environ.get("CI_ALLOW_DIRTY") == "1"
    for name in ("networkclaw", "harness", "integration"):
        expected, actual = lock.get(name, {}), resolved.get(name, {})
        # This repository contains its own lock file, so pinning its commit would
        # require a self-referential commit. Its clean source tree remains pinned.
        if allow_dirty and actual.get("dirty"):
            fields = ()
        elif name == "integration":
            fields = ("tree_sha256",)
        else:
            fields = ("commit", "tree_sha256")
        for field in fields:
            if expected.get(field) != actual.get(field):
                errors.append(f"{name}.{field}: expected {expected.get(field)}, got {actual.get(field)}")
        root = ROOT if name == "integration" else Path(actual.get("path", ""))
        origin = origin_repository(root)
        if origin and not (allow_dirty and actual.get("dirty")) and normalized_repository(origin) != normalized_repository(expected.get("repository", "")):
            errors.append(f"{name}.repository: expected {expected.get('repository')}, got {origin}")
        if os.environ.get("CI_REQUIRE_CLEAN") == "1" and actual.get("dirty") is not False:
            errors.append(f"{name} worktree is dirty")
    if errors:
        print("source lock verification failed:", file=sys.stderr)
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(json.dumps({"status": "passed", "dirty_allowed": allow_dirty}, sort_keys=True))
    return 0

if __name__ == "__main__": raise SystemExit(main())
