#!/usr/bin/env python3
"""Offline Capability Release gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from capability_contract import canonical_json, release_hash
from jsonschema import Draft202012Validator, ValidationError
from verify_capability_export import scan_document, verify as verify_export

ROOT = Path(__file__).resolve().parents[1]
LEGACY_TOOLS = (
    "host_netns_inspect",
    "probe_dns",
    "probe_http",
    "probe_tcp",
    "read_journal",
    "restart_service",
    "tail_file",
    "web_search",
)

sys.path.insert(0, str(ROOT / "tools"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def vendor_files(vendor: Path) -> dict[str, str]:
    return {
        path.relative_to(vendor).as_posix(): sha256_file(path)
        for path in sorted(vendor.rglob("*"))
        if path.is_file()
        and "__pycache__" not in path.relative_to(vendor).parts
        and path.suffix not in {".pyc", ".pyo"}
        and path.name != ".gitkeep"
    }


def vendor_tree_hash(vendor: Path, files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for relative, content_hash in sorted(files.items()):
        path = vendor / relative
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(b"755\0" if os.access(path, os.X_OK) else b"644\0")
        digest.update(bytes.fromhex(content_hash))
    return digest.hexdigest()


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)


def verify_harness(harness: Path) -> dict[str, Any]:
    required = {
        "vendor": harness / "vendor/hermes",
        "manifest": harness / "upstream/hermes-vendor-manifest.json",
        "source": harness / "upstream/hermes-source.json",
        "allowlist": harness / "upstream/hermes-runtime-files.txt",
        "verifier": harness / "scripts/verify-hermes-vendor.py",
    }
    missing = [name for name, path in required.items() if not path.exists()]
    if missing:
        raise RuntimeError(f"vendor_missing: {','.join(missing)}")

    result = run([sys.executable, str(required["verifier"])], harness)
    if result.returncode:
        raise RuntimeError(f"vendor_hash_mismatch: {result.stdout[-4000:].strip()}")

    manifest = json.loads(required["manifest"].read_text(encoding="utf-8"))
    source = json.loads(required["source"].read_text(encoding="utf-8"))
    files = vendor_files(required["vendor"])
    expected = manifest.get("files", {})
    if files != expected:
        raise RuntimeError("vendor_hash_mismatch: manifest file set differs from vendor tree")
    if manifest.get("source_commit") != source.get("commit"):
        raise RuntimeError("vendor_hash_mismatch: vendor source commit differs from pinned source")

    return {
        "source_repository": source.get("upstream_repository"),
        "source_ref": source.get("commit"),
        "vendor_manifest_sha256": sha256_file(required["manifest"]),
        "vendor_tree_sha256": vendor_tree_hash(required["vendor"], files),
        "vendor_file_count": len(files),
        "allowlist_sha256": manifest.get("allowlist_sha256"),
        "patch_series_sha256": manifest.get("patch_series_sha256"),
        "patches": manifest.get("patches", []),
        "capability_manifest": manifest.get("capability_manifest"),
        "verifier_output": result.stdout.strip(),
    }


def skill_manifest(harness: Path) -> dict[str, Any]:
    generator = ROOT / "tools/generate-skill-manifest.py"
    with tempfile.TemporaryDirectory(prefix="networkclaw-skill-gate-") as directory:
        output = Path(directory) / "skill-release.json"
        result = run(
            [sys.executable, str(generator), "--harness", str(harness), "--output", str(output)],
            ROOT,
        )
        if result.returncode:
            raise RuntimeError(f"vendor_missing: skill manifest generation failed: {result.stdout[-4000:].strip()}")
        document = json.loads(output.read_text(encoding="utf-8"))

    for skill in document.get("skills", []):
        for field in ("content_hash", "metadata_hash", "manifest_hash"):
            value = skill.get(field, "")
            if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:"):
                raise RuntimeError(f"vendor_hash_mismatch: skill {skill.get('skill_id')} has invalid {field}")
        for support_file in skill.get("support_files", []):
            value = support_file.get("sha256", "")
            if not isinstance(value, str) or len(value) != 64:
                raise RuntimeError(f"vendor_hash_mismatch: skill {skill.get('skill_id')} has invalid support file hash")
            path = support_file.get("path", "")
            if not isinstance(path, str) or not path or Path(path).is_absolute() or ".." in Path(path).parts:
                raise RuntimeError(f"vendor_hash_mismatch: skill {skill.get('skill_id')} has unsafe support file path")
            if any(item in LEGACY_TOOLS for item in skill.get("required_tools", [])):
                raise RuntimeError(f"dependency_unavailable: skill {skill.get('skill_id')} requires an excluded legacy tool")
    return {"manifest_version": document.get("manifest_version"), "skill_count": len(document.get("skills", [])), "skills": document.get("skills", [])}


def capability_inventory(harness: Path) -> dict[str, Any]:
    generator = ROOT / "tools/generate-hermes-inventory.py"
    with tempfile.TemporaryDirectory(prefix="networkclaw-inventory-gate-") as directory:
        output = Path(directory) / "inventory.json"
        result = run(
            [sys.executable, str(generator), "--harness", str(harness), "--output", str(output)],
            ROOT,
        )
        if result.returncode:
            raise RuntimeError(f"vendor_missing: Hermes inventory generation failed: {result.stdout[-4000:].strip()}")
        document = json.loads(output.read_text(encoding="utf-8"))

    registry_tools = document.get("registry_tools", [])
    static_toolsets = document.get("static_toolsets", [])
    if any(not isinstance(item.get("source"), str) or not item["source"] for item in registry_tools):
        raise RuntimeError("vendor_hash_mismatch: registry Tool handler provenance is incomplete")
    if any(not isinstance(item.get("name"), str) or not isinstance(item.get("resolved_tools"), list) for item in static_toolsets):
        raise RuntimeError("vendor_hash_mismatch: Toolset membership provenance is incomplete")
    return {
        "counts": document.get("counts", {}),
        "toolset_source": "hermes.toolsets",
        "registry_tool_sources": {item["name"]: item["source"] for item in registry_tools},
        "excluded_legacy_tools_observed": sorted(
            set(LEGACY_TOOLS) & {item.get("name") for item in document.get("tools", [])}
        ),
    }


def generated_inputs(harness: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Run the existing inventory, catalog, and Skill generators in a temp dir."""
    inventory_generator = ROOT / "tools/generate-hermes-inventory.py"
    catalog_generator = ROOT / "tools/project-hermes-catalog.py"
    skill_generator = ROOT / "tools/generate-skill-manifest.py"
    with tempfile.TemporaryDirectory(prefix="networkclaw-discovery-") as directory:
        root = Path(directory)
        inventory_path = root / "inventory.json"
        catalog_path = root / "catalog.json"
        skills_path = root / "skills.json"
        inventory_result = run(
            [sys.executable, str(inventory_generator), "--harness", str(harness), "--output", str(inventory_path)],
            ROOT,
        )
        if inventory_result.returncode:
            raise RuntimeError(f"vendor_missing: Hermes inventory generation failed: {inventory_result.stdout[-4000:].strip()}")
        catalog_result = run(
            [sys.executable, str(catalog_generator), "--input", str(inventory_path), "--output", str(catalog_path)],
            ROOT,
        )
        if catalog_result.returncode:
            raise RuntimeError(f"vendor_missing: Hermes catalog projection failed: {catalog_result.stdout[-4000:].strip()}")
        skill_result = run(
            [sys.executable, str(skill_generator), "--harness", str(harness), "--output", str(skills_path)],
            ROOT,
        )
        if skill_result.returncode:
            raise RuntimeError(f"vendor_missing: Skill manifest generation failed: {skill_result.stdout[-4000:].strip()}")
        return (
            json.loads(inventory_path.read_text(encoding="utf-8")),
            json.loads(catalog_path.read_text(encoding="utf-8")),
            json.loads(skills_path.read_text(encoding="utf-8")),
        )


def load_agent_export(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"unknown_agent: cannot read Agent export: {path.name}") from exc
    if document.get("schema_version") != "networkclaw.agent-revision-export.v1":
        raise RuntimeError("unknown_agent: unsupported Agent export schema")
    profiles = document.get("profiles")
    if not isinstance(profiles, list):
        raise RuntimeError("unknown_agent: Agent export profiles must be an array")
    return document


def source_provenance(networkclaw: Path, harness: Path) -> dict[str, Any]:
    from vendor_status import git_identity
    from source_tree import git_diff_hash
    roots = {"networkclaw": networkclaw, "harness": harness, "integration": ROOT}
    lock = {name: git_identity(root) | {"diff_hash": git_diff_hash(root)} for name, root in roots.items()}
    return {
        name: {
            "commit": identity.get("commit"),
            "tree_hash": "sha256:" + str(identity["tree_sha256"]),
            "dirty": identity.get("dirty"),
            "diff_hash": "sha256:" + identity["diff_hash"] if identity.get("diff_hash") else None,
        }
        for name, identity in lock.items()
    }


def discovery(harness: Path, networkclaw: Path, agent_path: Path) -> dict[str, Any]:
    gate = vendor_check(harness)
    report: dict[str, Any] = {
        "schema_version": "capability-discovery.v1",
        "status": "failed",
        "sources": source_provenance(networkclaw, harness),
        "resolution_errors": [],
    }
    if gate["status"] != "passed":
        report["reason_code"] = gate.get("reason_code") or "vendor_missing"
        report["vendor_gate"] = gate
        return report

    inventory, catalog, skills_manifest = generated_inputs(harness)
    agents = load_agent_export(agent_path)
    toolsets_by_name = {item["name"]: item for item in catalog.get("toolsets", [])}
    tools_by_name = {item["name"]: item for item in catalog.get("tools", [])}
    skills_by_id = {item["skill_id"]: item for item in skills_manifest.get("skills", [])}
    memberships_by_toolset: dict[str, list[dict[str, Any]]] = {}
    for membership in catalog.get("memberships", []):
        memberships_by_toolset.setdefault(membership["toolset_name"], []).append({
            "name": membership["tool_name"],
            "revision": membership["tool_revision"],
        })

    report["catalog"] = catalog.get("catalog", {}) | {"catalog_hash": catalog.get("catalog_hash")}
    report["hermes"] = gate["hermes"]
    report["inputs"] = {
        "inventory_version": inventory.get("inventory_version"),
        "catalog_hash": catalog.get("catalog_hash"),
        "skill_manifest_version": skills_manifest.get("manifest_version"),
        "agent_export_schema": agents.get("schema_version"),
        "agent_export_hash": "sha256:" + sha256_bytes(canonical_json(agents)),
    }
    report["toolsets"] = [
        {
            **{key: value for key, value in item.items() if key in {"name", "revision", "description", "source", "status", "runtime_injection"}},
            "member_tool_revisions": sorted(memberships_by_toolset.get(item["name"], []), key=lambda value: (value["name"], value["revision"])),
        }
        for item in sorted(catalog.get("toolsets", []), key=lambda value: value["name"])
    ]
    report["tools"] = [
        {key: value for key, value in item.items() if key in {"name", "revision", "version", "schema_hash", "source", "availability", "status", "required_capabilities"}}
        for item in sorted(catalog.get("tools", []), key=lambda value: value["name"])
    ]
    report["skills"] = []
    report["agents"] = []
    for skill in sorted(skills_manifest.get("skills", []), key=lambda value: value["skill_id"]):
        missing_toolsets = [name for name in skill.get("required_toolsets", []) if name not in toolsets_by_name]
        missing_tools = [name for name in skill.get("required_tools", []) if name not in tools_by_name]
        for name in missing_toolsets:
            report["resolution_errors"].append({"kind": "toolset", "name": name, "reason": "unknown_toolset", "skill_id": skill["skill_id"]})
        for name in missing_tools:
            report["resolution_errors"].append({"kind": "tool", "name": name, "reason": "unknown_tool", "skill_id": skill["skill_id"]})
        report["skills"].append({
            **skill,
            "revision": 1,
            "required_toolsets": [{"name": name, "revision": toolsets_by_name.get(name, {}).get("revision")} for name in skill.get("required_toolsets", [])],
            "required_tools": [{"name": name, "revision": tools_by_name.get(name, {}).get("revision")} for name in skill.get("required_tools", [])],
        })

    for profile in sorted(agents.get("profiles", []), key=lambda value: value.get("profile_id", "")):
        profile_id = profile.get("profile_id")
        agent_id = profile.get("name") or profile_id
        if not isinstance(profile_id, str) or not isinstance(agent_id, str) or not agent_id:
            report["resolution_errors"].append({"kind": "agent", "name": str(profile_id), "reason": "unknown_agent"})
            continue
        for revision in sorted(profile.get("revisions", []), key=lambda value: value.get("revision", 0)):
            requested = list(revision.get("requested_toolsets", []))
            requested_refs = []
            for name in requested:
                catalog_toolset = toolsets_by_name.get(name)
                if catalog_toolset is None:
                    report["resolution_errors"].append({"kind": "toolset", "name": name, "reason": "unknown_toolset", "agent_id": agent_id})
                requested_refs.append({"name": name, "revision": catalog_toolset.get("revision") if catalog_toolset else None})
            allowed_refs = []
            denied = []
            for binding in revision.get("tools", []):
                name = binding.get("tool_name")
                catalog_tool = tools_by_name.get(name)
                if catalog_tool is None:
                    report["resolution_errors"].append({"kind": "tool", "name": name, "reason": "unknown_tool", "agent_id": agent_id})
                ref = {"name": name, "revision": binding.get("tool_revision")}
                if binding.get("decision") == "allowed":
                    allowed_refs.append(ref)
                elif binding.get("decision") == "denied":
                    denied.append(name)
            skill_refs = []
            for binding in revision.get("skills", []):
                skill_id = binding.get("skill_id")
                skill = skills_by_id.get(skill_id)
                if skill is None or skill.get("version") != binding.get("skill_version"):
                    report["resolution_errors"].append({"kind": "skill", "name": skill_id, "reason": "unknown_skill", "agent_id": agent_id})
                skill_refs.append({"name": skill_id, "revision": 1, "version": binding.get("skill_version"), "mode": binding.get("mode")})
            report.setdefault("agents", []).append({
                "agent_id": agent_id,
                "profile_id": profile_id,
                "display_name": profile.get("display_name", agent_id),
                "enabled": bool(profile.get("enabled", True)),
                "revision": revision.get("revision"),
                "revision_hash": revision.get("revision_hash"),
                "status": revision.get("status", "draft"),
                "catalog_version": revision.get("catalog_version", catalog.get("catalog", {}).get("version")),
                "requested_toolsets": requested_refs,
                "allowed_tool_revisions": sorted(allowed_refs, key=lambda value: value["name"]),
                "denied_tools": sorted(set(denied)),
                "skill_revisions": sorted(skill_refs, key=lambda value: value["name"]),
                "source": "networkclaw.agent-revision-export.v1",
            })

    if report["resolution_errors"]:
        report["reason_code"] = report["resolution_errors"][0]["reason"]
        return report
    report["status"] = "passed"
    return report


def prefixed_hash(value: str) -> str:
    return value if value.startswith("sha256:") else "sha256:" + value


def release_source(name: str, source: dict[str, Any]) -> dict[str, Any]:
    repositories = {
        "networkclaw": "NetworkClaw",
        "harness": "networkclaw-harness",
        "integration": "networkclaw-integration",
    }
    commit = source.get("commit")
    return {
        "repository": repositories[name],
        "ref": commit or "workspace",
        "commit": commit,
        "tree_hash": prefixed_hash(source["tree_hash"]),
        "dirty": bool(source.get("dirty")),
        "diff_hash": source.get("diff_hash"),
    }


def compile_release(
    discovery_document: dict[str, Any],
    gate: dict[str, Any],
    *,
    release_id: str,
    target_os: str,
    target_version: str,
    architecture: str,
    session_platform: str,
) -> dict[str, Any]:
    if discovery_document.get("status") != "passed":
        raise RuntimeError(f"{discovery_document.get('reason_code', 'discovery_failed')}: discovery did not pass")
    if gate.get("status") != "passed":
        raise RuntimeError(f"{gate.get('reason_code', 'vendor_missing')}: vendor gate did not pass")
    if not release_id.startswith("cap-"):
        raise RuntimeError("invalid_release_id: release id must start with cap-")

    toolsets = [{
        "name": item["name"], "revision": item["revision"], "version": str(item["revision"]),
        "member_tool_revisions": item["member_tool_revisions"], "source": item["source"], "status": item["status"],
    } for item in discovery_document["toolsets"]]
    tools = [{key: item[key] for key in ("name", "revision", "version", "schema_hash", "source", "availability", "status")} for item in discovery_document["tools"]]
    skills = [{key: item[key] for key in (
        "skill_id", "revision", "version", "content_hash", "metadata_hash", "manifest_hash", "source",
        "release_ref", "release_status", "trust_state", "required_toolsets", "required_tools", "support_files",
    )} for item in discovery_document["skills"]]
    agents = [{key: item[key] for key in (
        "agent_id", "revision", "revision_hash", "catalog_version", "requested_toolsets",
        "allowed_tool_revisions", "denied_tools", "skill_revisions",
    )} for item in discovery_document["agents"]]
    for agent in agents:
        agent["requested_toolsets"] = [{"name": ref["name"], "revision": ref["revision"]} for ref in agent["requested_toolsets"]]
        agent["allowed_tool_revisions"] = [{"name": ref["name"], "revision": ref["revision"]} for ref in agent["allowed_tool_revisions"]]
        agent["skill_revisions"] = [{"name": ref["name"], "revision": ref["revision"]} for ref in agent["skill_revisions"]]
    manifest: dict[str, Any] = {
        "schema_version": "capability-release.v1",
        "release_id": release_id,
        "release_hash": "sha256:" + "0" * 64,
        "sources": {name: release_source(name, value) for name, value in discovery_document["sources"].items()},
        "hermes": {
            "source_ref": gate["hermes"]["source_ref"], "source_repository": gate["hermes"]["source_repository"],
            "vendor_manifest_hash": prefixed_hash(gate["hermes"]["vendor_manifest_sha256"]),
            "vendor_tree_hash": prefixed_hash(gate["hermes"]["vendor_tree_sha256"]),
        },
        "protocol": {"host_protocol_version": "1.0", "capability_schema_version": "capability.v1"},
        "target": {"os": target_os, "version": target_version, "architecture": architecture, "session_platform": session_platform},
        "catalog": {"version": discovery_document["catalog"]["version"], "status": "draft", "source": "composite"},
        "toolsets": sorted(toolsets, key=lambda item: (item["name"], item["revision"])),
        "tools": sorted(tools, key=lambda item: (item["name"], item["revision"])),
        "skills": sorted(skills, key=lambda item: (item["skill_id"], item["revision"])),
        "agents": sorted(agents, key=lambda item: (item["agent_id"], item["revision"])),
        "migration": {"source": "none", "legacy_inputs": [], "unresolved": []},
    }
    manifest["release_hash"] = release_hash(manifest)
    return manifest


def check_release(manifest: dict[str, Any], harness: Path) -> dict[str, Any]:
    report: dict[str, Any] = {"schema_version": "capability-release-check.v1", "status": "failed", "reason_code": None, "errors": [], "checks": {}}
    schema = json.loads((ROOT / "schemas/capability-release-v1.schema.json").read_text(encoding="utf-8"))
    duplicate_fields = (("toolsets", "name"), ("tools", "name"), ("skills", "skill_id"), ("agents", "agent_id"))
    for collection, identity in duplicate_fields:
        seen: set[tuple[Any, Any]] = set()
        for item in manifest.get(collection, []):
            key = (item.get(identity), item.get("revision"))
            if key in seen:
                report["errors"].append({"reason": "duplicate_revision", "collection": collection, "name": key[0], "revision": key[1]})
            seen.add(key)
    schema_errors = sorted(Draft202012Validator(schema).iter_errors(manifest), key=lambda error: list(map(str, error.absolute_path)))
    if schema_errors:
        report["errors"].extend({"reason": "schema_invalid", "path": list(error.absolute_path), "message": error.message} for error in schema_errors)
    if report["errors"]:
        report["reason_code"] = report["errors"][0]["reason"]
        return report

    expected_hash = release_hash(manifest)
    report["checks"]["release_hash"] = expected_hash == manifest["release_hash"]
    if not report["checks"]["release_hash"]:
        report["errors"].append({"reason": "release_hash_invalid", "expected": expected_hash})

    gate = vendor_check(harness)
    report["checks"]["vendor_gate"] = gate.get("status") == "passed"
    if gate.get("status") != "passed":
        report["errors"].append({"reason": gate.get("reason_code") or "vendor_missing"})
    elif manifest["hermes"]["source_ref"] != gate["hermes"]["source_ref"] or manifest["hermes"]["source_repository"] != gate["hermes"]["source_repository"]:
        report["errors"].append({"reason": "vendor_provenance_mismatch"})
    elif manifest["hermes"]["vendor_manifest_hash"] != prefixed_hash(gate["hermes"]["vendor_manifest_sha256"]) or manifest["hermes"]["vendor_tree_hash"] != prefixed_hash(gate["hermes"]["vendor_tree_sha256"]):
        report["errors"].append({"reason": "vendor_provenance_mismatch"})

    toolsets = {(item["name"], item["revision"]): item for item in manifest["toolsets"]}
    tools = {(item["name"], item["revision"]): item for item in manifest["tools"]}
    skills = {(item["skill_id"], item["revision"]): item for item in manifest["skills"]}
    report["checks"]["toolset_membership"] = True
    for toolset in manifest["toolsets"]:
        for ref in toolset["member_tool_revisions"]:
            tool = tools.get((ref["name"], ref["revision"]))
            if tool is None:
                report["errors"].append({"reason": "stale_revision", "kind": "tool", "name": ref["name"], "revision": ref["revision"], "toolset": toolset["name"]})
                report["checks"]["toolset_membership"] = False

    report["checks"]["skill_dependencies"] = True
    for skill in manifest["skills"]:
        if skill["release_status"] != "available" or skill["trust_state"] != "trusted":
            report["errors"].append({"reason": "dependency_unavailable", "kind": "skill", "name": skill["skill_id"]})
            report["checks"]["skill_dependencies"] = False
        for kind, refs, table in (("toolset", skill["required_toolsets"], toolsets), ("tool", skill["required_tools"], tools)):
            for ref in refs:
                item = table.get((ref["name"], ref["revision"]))
                if item is None:
                    report["errors"].append({"reason": "dependency_unavailable", "kind": kind, "name": ref["name"], "revision": ref["revision"], "skill": skill["skill_id"]})
                    report["checks"]["skill_dependencies"] = False
                elif kind == "tool" and (item["availability"] != "available" or item["status"] != "active"):
                    report["errors"].append({"reason": "dependency_unavailable", "kind": kind, "name": ref["name"], "skill": skill["skill_id"]})
                    report["checks"]["skill_dependencies"] = False

    report["checks"]["agent_references"] = True
    catalog_version = manifest["catalog"]["version"]
    for agent in manifest["agents"]:
        if agent["catalog_version"] != catalog_version:
            report["errors"].append({"reason": "catalog_conflict", "agent": agent["agent_id"], "catalog_version": agent["catalog_version"]})
            report["checks"]["agent_references"] = False
        requested = {(ref["name"], ref["revision"]) for ref in agent["requested_toolsets"]}
        expanded = {ref["name"] for key in requested for ref in toolsets.get(key, {}).get("member_tool_revisions", [])}
        denied = set(agent["denied_tools"])
        for ref in agent["requested_toolsets"]:
            if (ref["name"], ref["revision"]) not in toolsets:
                report["errors"].append({"reason": "stale_revision", "kind": "toolset", "name": ref["name"], "revision": ref["revision"], "agent": agent["agent_id"]})
                report["checks"]["agent_references"] = False
        for ref in agent["allowed_tool_revisions"]:
            tool = tools.get((ref["name"], ref["revision"]))
            if tool is None:
                report["errors"].append({"reason": "stale_revision", "kind": "tool", "name": ref["name"], "revision": ref["revision"], "agent": agent["agent_id"]})
                report["checks"]["agent_references"] = False
            elif ref["name"] not in expanded or ref["name"] in denied or tool["availability"] != "available" or tool["status"] != "active":
                report["errors"].append({"reason": "agent_reference_invalid", "kind": "tool", "name": ref["name"], "agent": agent["agent_id"]})
                report["checks"]["agent_references"] = False
        for ref in agent["skill_revisions"]:
            skill = skills.get((ref["name"], ref["revision"]))
            if skill is None:
                report["errors"].append({"reason": "stale_revision", "kind": "skill", "name": ref["name"], "revision": ref["revision"], "agent": agent["agent_id"]})
                report["checks"]["agent_references"] = False
            elif skill["release_status"] != "available" or skill["trust_state"] != "trusted":
                report["errors"].append({"reason": "dependency_unavailable", "kind": "skill", "name": ref["name"], "agent": agent["agent_id"]})
                report["checks"]["agent_references"] = False

    if report["errors"]:
        report["reason_code"] = report["errors"][0]["reason"]
        return report
    report["status"] = "passed"
    report["manifest_hash"] = manifest["release_hash"]
    return report


def diff_identity(collection: str, item: dict[str, Any]) -> tuple[str, int]:
    return (item.get("skill_id") if collection == "skills" else item.get("name") or item.get("agent_id"), item.get("revision"))


def diff_collection(collection: str, published: list[dict[str, Any]], candidate: list[dict[str, Any]]) -> dict[str, Any]:
    old = {diff_identity(collection, item): item for item in published}
    new = {diff_identity(collection, item): item for item in candidate}
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = [
        {"identity": {"name": key[0], "revision": key[1]}, "before": old[key], "after": new[key]}
        for key in sorted(set(old) & set(new))
        if old[key] != new[key]
    ]
    return {
        "added": [{"name": name, "revision": revision} for name, revision in added],
        "removed": [{"name": name, "revision": revision} for name, revision in removed],
        "changed": changed,
    }


def same_name_index(collection: str, items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        (item.get("skill_id") if collection == "skills" else item.get("name") or item.get("agent_id")): item
        for item in items
    }


def migration_candidates(collection: str, published: list[dict[str, Any]], candidate: list[dict[str, Any]], removed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = same_name_index(collection, candidate)
    result = []
    for identity in removed:
        old_name = identity["name"]
        target = candidates.get(old_name)
        if target is not None:
            result.append({
                "kind": collection[:-1], "old": identity,
                "candidate": {"name": old_name, "revision": target["revision"]},
                "status": "mapped",
            })
            continue
        old = next(item for item in published if diff_identity(collection, item) == (old_name, identity["revision"]))
        status = "unavailable" if old.get("availability") == "unavailable" or old.get("release_status") == "unavailable" else "retired"
        result.append({"kind": collection[:-1], "old": identity, "candidate": None, "status": status})
    return result


def diff_releases(published: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    collections = ("toolsets", "tools", "skills", "agents")
    changes = {collection: diff_collection(collection, published.get(collection, []), candidate.get(collection, [])) for collection in collections}
    binding_changes = []
    for entry in changes["agents"]["changed"]:
        before, after = entry["before"], entry["after"]
        fields = ("requested_toolsets", "allowed_tool_revisions", "denied_tools", "skill_revisions")
        changed_fields = [field for field in fields if before.get(field) != after.get(field)]
        if changed_fields:
            binding_changes.append({"identity": entry["identity"], "fields": changed_fields})
    dependency_changes = []
    for entry in changes["skills"]["changed"]:
        before, after = entry["before"], entry["after"]
        if before.get("required_toolsets") != after.get("required_toolsets") or before.get("required_tools") != after.get("required_tools"):
            dependency_changes.append({"identity": entry["identity"], "before": {"required_toolsets": before.get("required_toolsets", []), "required_tools": before.get("required_tools", [])}, "after": {"required_toolsets": after.get("required_toolsets", []), "required_tools": after.get("required_tools", [])}})
    status_changes = []
    for collection in collections:
        for entry in changes[collection]["changed"]:
            before, after = entry["before"], entry["after"]
            for field in ("status", "availability", "release_status", "trust_state"):
                if before.get(field) != after.get(field):
                    status_changes.append({"kind": collection[:-1], "identity": entry["identity"], "field": field, "before": before.get(field), "after": after.get(field)})
    migration = []
    for collection in collections:
        migration.extend(migration_candidates(collection, published.get(collection, []), candidate.get(collection, []), changes[collection]["removed"]))
    unresolved = [item for item in migration if item["status"] != "mapped"]
    return {
        "schema_version": "capability-release-diff.v1",
        "status": "passed",
        "published": {"release_id": published.get("release_id"), "release_hash": published.get("release_hash")},
        "candidate": {"release_id": candidate.get("release_id"), "release_hash": candidate.get("release_hash")},
        "changes": changes,
        "binding_changes": binding_changes,
        "dependency_changes": dependency_changes,
        "status_changes": status_changes,
        "migration": {
            "source": "published_release",
            "phases": [
                {"id": "M0", "action": "inventory", "status": "ready"},
                {"id": "M1", "action": "first_import", "status": "ready"},
                {"id": "M2", "action": "new_session", "status": "ready"},
                {"id": "M3", "action": "close_old_release", "status": "review_required" if unresolved else "ready"},
            ],
            "candidates": migration,
            "unresolved": unresolved,
        },
        "summary": {
            "added": sum(len(changes[c]["added"]) for c in collections),
            "removed": sum(len(changes[c]["removed"]) for c in collections),
            "changed": sum(len(changes[c]["changed"]) for c in collections),
            "binding_changes": len(binding_changes),
            "dependency_changes": len(dependency_changes),
            "unresolved_migrations": len(unresolved),
        },
    }


def export_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def export_checksums(root: Path) -> str:
    records = []
    for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name != "checksums.sha256"):
        relative = path.relative_to(root).as_posix()
        records.append(f"{sha256_file(path)}  {relative}")
    data = "\n".join(records) + "\n"
    (root / "checksums.sha256").write_text(data, encoding="ascii")
    return sha256_bytes(data.encode("ascii"))


def audit_record(operation: str, manifest: dict[str, Any], operator: str, job_id: str, reason: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": "capability-release-audit.v1", "operation": operation,
        "release_id": manifest.get("release_id"), "manifest_hash": manifest.get("release_hash"),
        "sources": manifest.get("sources", {}), "operator": operator, "job_id": job_id,
        "status": "failed" if reason else "passed", "reason_code": reason,
        "result": "failed" if reason else {"compile": "compiled", "diff": "compared", "export": "exported"}[operation],
    }


def audit_path(output: Path) -> Path:
    return output.with_name(output.name + ".audit.json")


def save_audit(args: argparse.Namespace, manifest: dict[str, Any], reason: str | None = None) -> dict[str, Any]:
    audit = audit_record(args.command, manifest, args.operator, args.job_id, reason)
    try:
        scan_document(audit)
    except ValueError:
        audit = audit_record(args.command, {}, args.operator, args.job_id, reason or "audit_invalid")
    path = args.audit or audit_path(args.output)
    export_json(path, audit)
    return audit


def export_release(
    manifest: dict[str, Any], check_report: dict[str, Any], diff_report: dict[str, Any],
    published: dict[str, Any], gate: dict[str, Any], compile_audit: dict[str, Any], diff_audit: dict[str, Any],
    *, output: Path, operator: str, job_id: str,
) -> dict[str, Any]:
    if output.is_symlink() or output.exists():
        raise RuntimeError("export_output_exists")
    if gate.get("status") != "passed":
        raise RuntimeError(gate.get("reason_code") or "vendor_missing")
    audit = audit_record("export", manifest, operator, job_id)
    documents = {
        "manifest/capability-release.v1.json": manifest,
        "reports/check.json": check_report, "reports/diff.json": diff_report,
        "migration/migration-plan.json": diff_report["migration"],
        "provenance/source-lock.json": {"schema_version": "capability-release-sources.v1", "sources": manifest["sources"], "protocol": manifest["protocol"], "target": manifest["target"]},
        "provenance/published-release.json": published,
        "provenance/vendor.json": {
            **manifest["hermes"], "vendor_file_count": gate["hermes"]["vendor_file_count"],
            "allowlist_hash": gate["hermes"].get("allowlist_sha256"),
            "patch_series_hash": gate["hermes"].get("patch_series_sha256"),
            "patches": gate["hermes"].get("patches", []),
        },
        "audit/compile.json": compile_audit, "audit/diff.json": diff_audit, "audit/export.json": audit,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    # Validate the complete staging directory before making the artifact visible.
    with tempfile.TemporaryDirectory(prefix="capability-export-", dir=output.parent) as directory:
        staging = Path(directory) / "artifact"
        for relative, value in documents.items():
            scan_document(value)
            export_json(staging / relative, value)
        for source, relative in (
            (ROOT / "schemas/capability-release-v1.schema.json", "schemas/capability-release-v1.schema.json"),
            (ROOT / "tools/verify_capability_export.py", "verify.py"),
            (ROOT / "tools/artifact_scan.py", "artifact_scan.py"),
            (ROOT / "tools/capability_contract.py", "capability_contract.py"),
        ):
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        export_checksums(staging)
        verification = verify_export(staging)
        staging.rename(output)
    return verification


def read_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise RuntimeError("input_invalid")
    return document


def audit_identity(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}", value):
        raise argparse.ArgumentTypeError("identity must contain only letters, digits, . _ : @ -")
    return value


def failure_reason(exc: Exception) -> str:
    if isinstance(exc, (OSError, json.JSONDecodeError)):
        return "input_unreadable"
    if isinstance(exc, (KeyError, TypeError, AttributeError)):
        return "input_invalid"
    reason = str(exc).split(":", 1)[0]
    return reason if re.fullmatch(r"[a-z][a-z0-9_]+", reason) else "artifact_invalid"


def tamper_fixture(harness: Path) -> dict[str, bool]:
    with tempfile.TemporaryDirectory(prefix="networkclaw-vendor-gate-") as directory:
        fixture = Path(directory) / "harness"
        shutil.copytree(harness, fixture, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", "*.pyc"))
        vendor_file = fixture / "vendor/hermes/hermes_constants.py"
        original = vendor_file.read_bytes()
        verifier = [sys.executable, str(fixture / "scripts/verify-hermes-vendor.py")]

        vendor_file.write_bytes(original + b"\n# capability-release tamper fixture\n")
        changed = run(verifier, fixture)
        vendor_file.write_bytes(original)

        unexpected_path = fixture / "vendor/hermes/capability-release-unexpected.py"
        unexpected_path.write_text("unexpected = True\n", encoding="utf-8")
        unexpected = run(verifier, fixture)
        unexpected_path.unlink()

        vendor_file.unlink()
        missing = run(verifier, fixture)
        return {
            "changed_file_rejected": changed.returncode != 0 and "verification failed" in changed.stdout,
            "unexpected_file_rejected": unexpected.returncode != 0 and "verification failed" in unexpected.stdout,
            "missing_file_rejected": missing.returncode != 0 and "verification failed" in missing.stdout,
        }


def vendor_check(harness: Path, *, tamper: bool = False) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "failed",
        "reason_code": None,
        "harness": "networkclaw-harness",
        "legacy_tool_exclusions": list(LEGACY_TOOLS),
    }
    try:
        report["hermes"] = verify_harness(harness)
        report["inventory"] = capability_inventory(harness)
        report["skills"] = skill_manifest(harness)
        if tamper:
            report["tamper_fixture"] = tamper_fixture(harness)
            if not all(report["tamper_fixture"].values()):
                raise RuntimeError("vendor_hash_mismatch: tamper fixture was accepted")
        report["status"] = "passed"
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        message = str(exc)
        report["reason_code"] = message.split(":", 1)[0]
        report["error"] = message
    return report


def main() -> int:
    # Reuse the controlled admin client; no network call occurs before its
    # explicit --execute, endpoint, schema and token checks.
    if len(sys.argv) > 1 and sys.argv[1] == "import":
        import runpy
        sys.argv = [str(ROOT / "tools/capability-release-admin.py"), *sys.argv[1:]]
        runpy.run_path(sys.argv[0], run_name="__main__")
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    vendor = subparsers.add_parser("vendor-check", help="verify the pinned Harness vendor and Skill release inputs")
    vendor.add_argument("--harness", type=Path, default=Path(os.environ.get("HARNESS_PATH", ROOT.parent / "networkclaw-harness")))
    vendor.add_argument("--report", type=Path, default=None)
    vendor.add_argument("--tamper-fixture", action="store_true", help="run a temporary vendor tamper rejection check")
    discover_parser = subparsers.add_parser("discover", help="compile deterministic Tool/Toolset/Skill/Agent discovery")
    discover_parser.add_argument("--harness", type=Path, default=Path(os.environ.get("HARNESS_PATH", ROOT.parent / "networkclaw-harness")))
    discover_parser.add_argument("--networkclaw", type=Path, default=Path(os.environ.get("NETWORKCLAW_PATH", ROOT.parent / "NetworkClaw")))
    discover_parser.add_argument("--agents", type=Path, default=ROOT / "tests/fixtures/capability-release/agent-discovery-v1.json", help="explicit Agent/profile revision export; defaults to the local test fixture")
    discover_parser.add_argument("--output", type=Path, default=ROOT / "docs/evidence/capability-discovery-v1.json")
    compile_parser = subparsers.add_parser("compile", help="compile capability-discovery.v1 into capability-release.v1")
    compile_parser.add_argument("--discovery", type=Path, default=ROOT / "docs/evidence/capability-discovery-v1.json")
    compile_parser.add_argument("--harness", type=Path, default=Path(os.environ.get("HARNESS_PATH", ROOT.parent / "networkclaw-harness")))
    compile_parser.add_argument("--release-id", default="cap-local")
    compile_parser.add_argument("--target-os", choices=("ubuntu", "macos"), default="ubuntu")
    compile_parser.add_argument("--target-version", default="22.04")
    compile_parser.add_argument("--architecture", choices=("amd64", "arm64"), default="amd64")
    compile_parser.add_argument("--session-platform", default="linux-amd64")
    compile_parser.add_argument("--output", type=Path, default=ROOT / "docs/evidence/capability-release-v1.json")
    check_parser = subparsers.add_parser("check", help="validate a capability-release.v1 manifest")
    check_parser.add_argument("--manifest", type=Path, default=ROOT / "docs/evidence/capability-release-v1.json")
    check_parser.add_argument("--harness", type=Path, default=Path(os.environ.get("HARNESS_PATH", ROOT.parent / "networkclaw-harness")))
    check_parser.add_argument("--report", type=Path, default=ROOT / "docs/evidence/capability-release-check-v1.json")
    diff_parser = subparsers.add_parser("diff", help="compare a candidate release with a published snapshot")
    diff_parser.add_argument("--published", type=Path, default=ROOT / "tests/fixtures/capability-release/valid-release-v1.json")
    diff_parser.add_argument("--candidate", type=Path, default=ROOT / "docs/evidence/capability-release-v1.json")
    diff_parser.add_argument("--harness", type=Path, default=Path(os.environ.get("HARNESS_PATH", ROOT.parent / "networkclaw-harness")))
    diff_parser.add_argument("--output", type=Path, default=ROOT / "docs/evidence/capability-release-diff-v1.json")
    export_parser = subparsers.add_parser("export", help="export an audited capability release directory")
    export_parser.add_argument("--manifest", type=Path, default=ROOT / "docs/evidence/capability-release-v1.json")
    export_parser.add_argument("--check", type=Path, default=ROOT / "docs/evidence/capability-release-check-v1.json")
    export_parser.add_argument("--diff", type=Path, default=ROOT / "docs/evidence/capability-release-diff-v1.json")
    export_parser.add_argument("--published", type=Path, default=ROOT / "tests/fixtures/capability-release/valid-release-v1.json")
    export_parser.add_argument("--compile-audit", type=Path)
    export_parser.add_argument("--diff-audit", type=Path)
    export_parser.add_argument("--harness", type=Path, default=Path(os.environ.get("HARNESS_PATH", ROOT.parent / "networkclaw-harness")))
    export_parser.add_argument("--output", type=Path, default=ROOT / ".integration-state/artifacts/capability-release")
    for command_parser in (compile_parser, diff_parser, export_parser):
        command_parser.add_argument("--operator", type=audit_identity, default="local")
        command_parser.add_argument("--job-id", type=audit_identity, default="manual")
        command_parser.add_argument("--audit", type=Path)
    verify_parser = subparsers.add_parser("verify-export", help="verify a relocated release artifact without source worktrees")
    verify_parser.add_argument("artifact", type=Path)
    subparsers.add_parser("import", help="controlled admin import; requires --execute (see import --help)")
    args = parser.parse_args()
    if args.command in {"compile", "diff", "export"}:
        args.output = args.output if args.output.is_absolute() else ROOT / args.output
        if args.audit and (args.audit.resolve() == args.output.resolve() or args.output.resolve() in args.audit.resolve().parents):
            parser.error("audit must be outside the artifact output")

    if args.command == "vendor-check":
        report = vendor_check(args.harness.resolve(), tamper=args.tamper_fixture)
        if args.report:
            report_path = args.report if args.report.is_absolute() else ROOT / args.report
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"status": report["status"], "reason_code": report["reason_code"], "report": str(args.report) if args.report else None}, sort_keys=True))
        return 0 if report["status"] == "passed" else 1
    if args.command == "discover":
        try:
            report = discovery(args.harness.resolve(), args.networkclaw.resolve(), args.agents.resolve())
        except (OSError, RuntimeError, json.JSONDecodeError) as exc:
            report = {"schema_version": "capability-discovery.v1", "status": "failed", "reason_code": str(exc).split(":", 1)[0], "error": str(exc)}
        output = args.output if args.output.is_absolute() else ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"status": report["status"], "reason_code": report.get("reason_code"), "output": str(output)}, sort_keys=True))
        return 0 if report["status"] == "passed" else 1
    if args.command == "compile":
        report = {"release_id": args.release_id}
        try:
            discovery_document = read_json(args.discovery)
            report = compile_release(
                discovery_document,
                vendor_check(args.harness.resolve()),
                release_id=args.release_id,
                target_os=args.target_os,
                target_version=args.target_version,
                architecture=args.architecture,
                session_platform=args.session_platform,
            )
            scan_document(report)
            export_json(args.output, report)
            save_audit(args, report)
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError) as exc:
            reason = failure_reason(exc)
            save_audit(args, report, reason)
            print(json.dumps({"status": "failed", "reason_code": reason}, sort_keys=True))
            return 1
        print(json.dumps({"status": "passed", "release_hash": report["release_hash"], "output": args.output.name}, sort_keys=True))
        return 0
    if args.command == "check":
        try:
            manifest = json.loads(args.manifest.resolve().read_text(encoding="utf-8"))
            report = check_release(manifest, args.harness.resolve())
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            report = {"schema_version": "capability-release-check.v1", "status": "failed", "reason_code": "manifest_unreadable", "errors": [{"reason": "manifest_unreadable", "error": str(exc)}]}
        report_path = args.report if args.report.is_absolute() else ROOT / args.report
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"status": report["status"], "reason_code": report.get("reason_code"), "report": str(report_path)}, sort_keys=True))
        return 0 if report["status"] == "passed" else 1
    if args.command == "diff":
        candidate = {}
        try:
            published = read_json(args.published)
            candidate = read_json(args.candidate)
            candidate_check = check_release(candidate, args.harness.resolve())
            if candidate_check["status"] != "passed":
                raise RuntimeError(f"{candidate_check.get('reason_code', 'candidate_invalid')}: candidate release did not pass check")
            report = diff_releases(published, candidate)
            scan_document(report)
        except (OSError, ValueError, KeyError, RuntimeError, TypeError, AttributeError) as exc:
            report = {"schema_version": "capability-release-diff.v1", "status": "failed", "reason_code": failure_reason(exc)}
        export_json(args.output, report)
        save_audit(args, candidate, report.get("reason_code"))
        print(json.dumps({"status": report["status"], "reason_code": report.get("reason_code"), "output": args.output.name}, sort_keys=True))
        return 0 if report["status"] == "passed" else 1
    if args.command == "export":
        manifest = {}
        try:
            manifest = read_json(args.manifest)
            check = read_json(args.check)
            diff = read_json(args.diff)
            published = read_json(args.published)
            current_check = check_release(manifest, args.harness.resolve())
            if current_check["status"] != "passed":
                raise RuntimeError(current_check["reason_code"])
            if check != current_check:
                raise RuntimeError("check_report_mismatch")
            if diff != diff_releases(published, manifest):
                raise RuntimeError("diff_report_mismatch")
            result = export_release(
                manifest, check, diff, published, vendor_check(args.harness.resolve()),
                read_json(args.compile_audit or audit_path(args.manifest)),
                read_json(args.diff_audit or audit_path(args.diff)),
                output=args.output, operator=args.operator, job_id=args.job_id,
            )
            save_audit(args, manifest)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, AttributeError, ValidationError) as exc:
            reason = failure_reason(exc)
            save_audit(args, manifest, reason)
            print(json.dumps({"status": "failed", "reason_code": reason}, sort_keys=True))
            return 1
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.command == "verify-export":
        try:
            print(json.dumps(verify_export(args.artifact), sort_keys=True))
            return 0
        except (OSError, ValueError, KeyError, ValidationError) as exc:
            print(json.dumps({"status": "failed", "reason_code": failure_reason(exc)}, sort_keys=True))
            return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
