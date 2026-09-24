#!/usr/bin/env python3
"""Report the pinned Hermes vendor and three-source compatibility identity."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from source_tree import included_files, tree_hash  # noqa: E402


def command(args: list[str], *, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.PIPE).strip()


def git_identity(root: Path) -> dict[str, object]:
    try:
        commit = command(["git", "-C", str(root), "rev-parse", "HEAD"])
        dirty = bool(command(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"]))
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = None, None
    return {"commit": commit, "dirty": dirty, "tree_sha256": tree_hash(root, included_files(root))}


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_status(networkclaw: Path, harness: Path, lock_path: Path) -> dict[str, object]:
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    source = json.loads((harness / "upstream/hermes-source.json").read_text(encoding="utf-8"))
    vendor_manifest_path = harness / "upstream/hermes-vendor-manifest.json"
    vendor_root = harness / "vendor/hermes"
    sources = {
        "networkclaw": git_identity(networkclaw),
        "harness": git_identity(harness),
        "integration": git_identity(ROOT),
    }
    vendor_files = [path for path in included_files(harness) if vendor_root in path.parents]
    vendor_tree = tree_hash(vendor_root, vendor_files) if vendor_root.is_dir() else None
    lock_matches = all(
        lock.get(name, {}).get("tree_sha256") == identity["tree_sha256"]
        and (name == "integration" or lock.get(name, {}).get("commit") == identity["commit"])
        for name, identity in sources.items()
    )
    return {
        "schema_version": 1,
        "sources": sources,
        "source_lock_matches": lock_matches,
        "hermes": {
            "upstream_repository": source.get("upstream_repository"),
            "upstream_commit": source.get("commit"),
            "vendor_manifest_sha256": sha256(vendor_manifest_path),
            "vendor_tree_sha256": vendor_tree,
            "patch_series_sha256": json.loads(vendor_manifest_path.read_text(encoding="utf-8")).get("patch_series_sha256"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--networkclaw", type=Path, default=Path(os.environ.get("NETWORKCLAW_PATH", ROOT.parent / "NetworkClaw")))
    parser.add_argument("--harness", type=Path, default=Path(os.environ.get("HARNESS_PATH", ROOT.parent / "networkclaw-harness")))
    parser.add_argument("--lock", type=Path, default=ROOT / "sources.lock.yaml")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args()
    try:
        status = collect_status(args.networkclaw.resolve(), args.harness.resolve(), args.lock.resolve())
    except (OSError, KeyError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"vendor-status: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        hermes = status["hermes"]
        print(f"Hermes upstream: {hermes['upstream_repository']} @ {hermes['upstream_commit']}")
        print(f"Vendor tree SHA-256: {hermes['vendor_tree_sha256']}")
        print(f"Patch series SHA-256: {hermes['patch_series_sha256']}")
        for name, identity in status["sources"].items():
            print(f"{name}: commit={identity['commit']} dirty={identity['dirty']} tree={identity['tree_sha256']}")
        print(f"Source lock matches: {status['source_lock_matches']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
