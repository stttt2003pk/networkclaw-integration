#!/usr/bin/env python3
"""Generate a deterministic Hermes toolset/registry inventory from one Harness checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

PROBE = r'''
import hashlib, json, os, sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root / "vendor" / "hermes"))
sys.path.insert(0, str(root / "src"))
import model_tools  # noqa: F401 - imports built-in registry modules
import toolsets
from tools.registry import registry
from networkclaw_harness.runtime.hermes_tools import install_hermes_host_tools

install_hermes_host_tools()

def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()

def sha(value):
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()

static_names = sorted(toolsets.TOOLSETS)
static = []
static_membership = {}
for name in static_names:
    definition = toolsets.get_toolset(name, include_registry=False) or {}
    resolved = toolsets.resolve_toolset(name, include_registry=False)
    for item in resolved:
        static_membership.setdefault(item, []).append(name)
    static.append({
        "name": name,
        "description": definition.get("description", ""),
        "direct_tools": sorted(set(definition.get("tools", []))),
        "includes": sorted(set(definition.get("includes", []))),
        "resolved_tools": resolved,
        "runtime_injection": not bool(resolved),
    })

entries = sorted(registry.get_all_entries(), key=lambda item: item.name)
registry_by_name = {entry.name: entry for entry in entries}
registered_toolsets = sorted(registry.get_registered_toolset_names())
registered = []
for entry in entries:
    availability = "available"
    check_error = None
    if entry.check_fn is not None:
        try:
            if not bool(entry.check_fn()):
                availability = "unavailable"
                check_error = "check_returned_false"
        except Exception:
            availability = "unavailable"
            check_error = "check_failed"
    toolset = entry.toolset
    if toolset.startswith("mcp-"):
        kind = "mcp"
    elif entry.handler.__module__.startswith("networkclaw_harness"):
        kind = "runtime_injected"
    elif toolset not in toolsets.TOOLSETS:
        kind = "plugin"
    else:
        kind = "registry"
    record = {
        "name": entry.name,
        "toolset": toolset,
        "kind": kind,
        "schema_hash": sha(entry.schema),
        "source": entry.handler.__module__,
        "availability": availability,
        "check_capability": {
            "has_check_fn": entry.check_fn is not None,
            "requires_env": sorted(set(entry.requires_env or [])),
        },
    }
    if check_error:
        record["availability_reason"] = check_error
    registered.append(record)

all_tool_names = sorted(set(static_membership) | set(registry_by_name))
tools = []
for name in all_tool_names:
    entry = registry_by_name.get(name)
    memberships = sorted(set(static_membership.get(name, [])))
    tools.append({
        "name": name,
        "static_toolsets": memberships,
        "registry_toolset": entry.toolset if entry else None,
        "registry_kind": next((row["kind"] for row in registered if row["name"] == name), None),
        "schema_hash": sha(entry.schema) if entry else None,
        "availability": next((row["availability"] for row in registered if row["name"] == name), "registered"),
    })

requested = json.loads(os.environ.get("HERMES_INVENTORY_REQUESTED_TOOLSETS", "[]"))
resolution_errors = []
for name in requested:
    if not toolsets.validate_toolset(name):
        resolution_errors.append({"toolset": name, "code": "unknown"})

report = {
    "inventory_version": "hermes.tool-inventory.v1",
    "static_toolsets": static,
    "registered_toolsets": registered_toolsets,
    "registry_tools": registered,
    "tools": tools,
    "resolution_errors": resolution_errors,
    "counts": {
        "static_toolsets": len(static),
        "registered_toolsets": len(registered_toolsets),
        "registry_tools": len(registered),
        "unique_tools": len(tools),
    },
}
print(json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
'''


def generate(harness: Path, requested_toolsets: list[str]) -> dict:
    python = os.environ.get("HARNESS_PYTHON", str(harness / ".venv/bin/python"))
    if not Path(python).is_file():
        python = sys.executable
    env = os.environ | {"HERMES_INVENTORY_REQUESTED_TOOLSETS": json.dumps(requested_toolsets)}
    result = subprocess.run(
        [python, "-c", PROBE, str(harness)],
        cwd=harness,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr[-4000:] or "Hermes inventory probe failed")
    return json.loads(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness", type=Path, default=Path(os.environ.get("HARNESS_PATH", ROOT.parent / "networkclaw-harness")))
    parser.add_argument("--output", type=Path, default=ROOT / "docs/evidence/hermes-tool-inventory.json")
    parser.add_argument("--requested-toolset", action="append", default=[])
    args = parser.parse_args()
    report = generate(args.harness.resolve(), args.requested_toolset)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "counts": report["counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
