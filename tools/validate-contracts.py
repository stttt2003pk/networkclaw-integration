#!/usr/bin/env python3
"""Validate repository configuration examples against their JSON Schemas."""

from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from capability_contract import release_hash, snapshot_hash
from session_execution import validate as validate_execution, validate_mirrors
from resolve_sources import resolve


ROOT = Path(__file__).resolve().parents[1]


def load_document(path: Path) -> object:
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def validate(schema_name: str, example_path: Path) -> None:
    schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(load_document(example_path)), key=lambda error: list(map(str, error.absolute_path)))
    if errors:
        details = "; ".join(f"{'.'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}" for error in errors)
        raise ValueError(f"{example_path.relative_to(ROOT)}: {details}")
    print(f"OK {example_path.relative_to(ROOT)} matches {schema_name}")


def main() -> int:
    try:
        sources = resolve()
        validate_mirrors(ROOT, Path(sources['networkclaw']['path']), Path(sources['harness']['path']))
        print('OK session-execution.v1 schema and fixture mirrors')
        for path in sorted((ROOT / "tests/fixtures/session-execution").glob("*.json")):
            validate_execution(load_document(path))
            print(f"OK {path.relative_to(ROOT)} session-execution.v1")
        validate("workspace-local.schema.json", ROOT / "workspace.local.example.yaml")
        local_config = ROOT / "workspace.local.yaml"
        if local_config.is_file():
            validate("workspace-local.schema.json", local_config)
        validate("sources-lock.schema.json", ROOT / "sources.lock.example.yaml")
        validate("bundle-manifest.schema.json", ROOT / "schemas/examples/bundle-manifest.example.json")
        validate("host-protocol-v1-terminal.schema.json", ROOT / "schemas/examples/host-protocol-v1-terminal.example.json")
        capability_fixture = ROOT / "tests/fixtures/capabilities/session-capability-snapshot-v1.json"
        validate("capability-snapshot-v1.schema.json", capability_fixture)
        capability = load_document(capability_fixture)
        expected = snapshot_hash(capability["snapshot"])
        if capability["snapshot"]["snapshot_hash"] != expected:
            raise ValueError(f"{capability_fixture.relative_to(ROOT)}: snapshot_hash does not match canonical snapshot ({expected})")
        print(f"OK {capability_fixture.relative_to(ROOT)} snapshot_hash={expected}")
        skill_manifest = ROOT / "docs/evidence/hermes-skill-release-manifest-v1.json"
        validate("skill-release-manifest-v1.schema.json", skill_manifest)
        manifest_document = load_document(skill_manifest)
        for skill in manifest_document["skills"]:
            unsigned = {key: value for key, value in skill.items() if key != "manifest_hash"}
            actual = "sha256:" + hashlib.sha256(json.dumps(unsigned, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            if skill["manifest_hash"] != actual:
                raise ValueError(f"{skill_manifest.relative_to(ROOT)}: {skill['skill_id']} manifest_hash does not match canonical manifest ({actual})")
        print(f"OK {skill_manifest.relative_to(ROOT)} manifests={len(manifest_document['skills'])}")
        release_fixture = ROOT / "tests/fixtures/capability-release/valid-release-v1.json"
        validate("capability-release-v1.schema.json", release_fixture)
        release_document = load_document(release_fixture)
        expected_release_hash = release_hash(release_document)
        if release_document["release_hash"] != expected_release_hash:
            raise ValueError(f"{release_fixture.relative_to(ROOT)}: release_hash does not match canonical release ({expected_release_hash})")
        print(f"OK {release_fixture.relative_to(ROOT)} release_hash={expected_release_hash}")
        release_schema = ROOT / "schemas/capability-release-v1.schema.json"
        invalid_fixture = load_document(ROOT / "tests/fixtures/capability-release/invalid-release-hash.json")
        invalid_errors = list(Draft202012Validator(json.loads(release_schema.read_text(encoding="utf-8"))).iter_errors(invalid_fixture["manifest"]))
        if not invalid_errors:
            raise ValueError("tests/fixtures/capability-release/invalid-release-hash.json: expected release_hash_invalid")
        if invalid_fixture["expected_reason_code"] != "release_hash_invalid":
            raise ValueError("tests/fixtures/capability-release/invalid-release-hash.json: unexpected reason code")
        print(f"OK tests/fixtures/capability-release/invalid-release-hash.json reason={invalid_fixture['expected_reason_code']}")
        compiled_release = ROOT / "docs/evidence/capability-release-v1.json"
        if compiled_release.is_file():
            validate("capability-release-v1.schema.json", compiled_release)
            compiled_document = load_document(compiled_release)
            expected_compiled_hash = release_hash(compiled_document)
            if compiled_document["release_hash"] != expected_compiled_hash:
                raise ValueError(f"{compiled_release.relative_to(ROOT)}: release_hash does not match canonical release ({expected_compiled_hash})")
            print(f"OK {compiled_release.relative_to(ROOT)} release_hash={expected_compiled_hash}")
    except (OSError, json.JSONDecodeError, yaml.YAMLError, ValueError) as exc:
        print(f"validate-contracts: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
