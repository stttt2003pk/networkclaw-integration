#!/usr/bin/env python3
"""Validate repository configuration examples against their JSON Schemas."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


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
        validate("workspace-local.schema.json", ROOT / "workspace.local.example.yaml")
        local_config = ROOT / "workspace.local.yaml"
        if local_config.is_file():
            validate("workspace-local.schema.json", local_config)
        validate("sources-lock.schema.json", ROOT / "sources.lock.example.yaml")
        validate("bundle-manifest.schema.json", ROOT / "schemas/examples/bundle-manifest.example.json")
        validate("host-protocol-v1-terminal.schema.json", ROOT / "schemas/examples/host-protocol-v1-terminal.example.json")
    except (OSError, json.JSONDecodeError, yaml.YAMLError, ValueError) as exc:
        print(f"validate-contracts: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
