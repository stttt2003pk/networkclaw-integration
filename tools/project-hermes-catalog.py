#!/usr/bin/env python3
"""Project a Hermes inventory into the T-02 Lobby capability catalog payload."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def project(inventory: dict, version: str = "hermes-tool-inventory-v1") -> dict:
    toolsets: dict[str, dict] = {}
    memberships: set[tuple[str, str]] = set()

    for item in inventory.get("static_toolsets", []):
        name = item["name"]
        toolsets[name] = {
            "name": name,
            "revision": 1,
            "description": item.get("description", ""),
            "source": "hermes.toolsets",
            "status": "active",
            "runtime_injection": bool(item.get("runtime_injection", False)),
        }
        for tool in item.get("resolved_tools", []):
            memberships.add((name, tool))

    registry_by_toolset: dict[str, list[dict]] = {}
    for item in inventory.get("registry_tools", []):
        registry_by_toolset.setdefault(item["toolset"], []).append(item)
    for name in inventory.get("registered_toolsets", []):
        toolsets.setdefault(name, {
            "name": name,
            "revision": 1,
            "description": "",
            "source": "hermes.registry",
            "status": "active",
            "runtime_injection": False,
        })
    for name, items in registry_by_toolset.items():
        for item in items:
            memberships.add((name, item["name"]))

    registry_tools = {item["name"]: item for item in inventory.get("registry_tools", [])}
    tools = []
    for item in sorted(inventory.get("tools", []), key=lambda row: row["name"]):
        name = item["name"]
        registry = registry_tools.get(name)
        availability = item.get("availability", "registered")
        source = registry.get("source") if registry else "hermes.toolsets"
        check = registry.get("check_capability", {}) if registry else {}
        reason = registry.get("availability_reason") if registry else None
        tools.append({
            "name": name,
            "revision": 1,
            "version": inventory.get("inventory_version", "unknown"),
            "schema_hash": item.get("schema_hash") or "sha256:" + "0" * 64,
            "source": source,
            "availability": availability,
            "grant_policy": "host_grant",
            "required_capabilities": sorted(check.get("requires_env", [])),
            "status": "active" if availability != "unavailable" else "retired",
            "kind": item.get("registry_kind") or "static",
            "check_capability": check,
            "availability_reason": reason,
        })

    membership_rows = [
        {"toolset_name": toolset, "toolset_revision": 1, "tool_name": tool, "tool_revision": 1}
        for toolset, tool in sorted(memberships)
        if tool in {item["name"] for item in tools}
    ]
    payload = {
        "catalog": {"version": version, "source": "hermes", "status": "published"},
        "inventory_version": inventory.get("inventory_version"),
        "tools": tools,
        "toolsets": [toolsets[name] for name in sorted(toolsets)],
        "memberships": membership_rows,
        "resolution_errors": inventory.get("resolution_errors", []),
    }
    payload["catalog_hash"] = "sha256:" + hashlib.sha256(canonical(payload)).hexdigest()
    return payload


def drift_errors(inventory: dict, catalog: dict, version: str = "hermes-tool-inventory-v1") -> list[str]:
    """Return fail-closed drift diagnostics for a previously projected catalog."""
    expected = project(inventory, version)
    errors = []
    for key in ("catalog", "tools", "toolsets", "memberships", "resolution_errors"):
        if expected.get(key) != catalog.get(key):
            errors.append(key)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "docs/evidence/hermes-tool-inventory.json")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/evidence/hermes-capability-catalog-v1.json")
    parser.add_argument("--version", default="hermes-tool-inventory-v1")
    args = parser.parse_args()
    inventory = json.loads(args.input.read_text(encoding="utf-8"))
    output = project(inventory, args.version)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "tools": len(output["tools"]), "toolsets": len(output["toolsets"]), "memberships": len(output["memberships"]), "catalog_hash": output["catalog_hash"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
