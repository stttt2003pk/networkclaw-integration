#!/usr/bin/env python3
"""Fail when the canonical event catalog drifts from its three consumers."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

from resolve_sources import resolve


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def harness_sets(path: Path) -> tuple[set[str], set[str]]:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assignments: dict[str, ast.AST] = {}
    for node in module.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in {"EVENTS", "PROCESS_EXTENSIONS"}:
            assignments[target.id] = node.value

    def read(name: str) -> set[str]:
        value = assignments.get(name)
        if not isinstance(value, ast.Call) or ast.unparse(value.func) != "frozenset" or not value.args:
            raise ValueError(f"Harness catalog assignment {name} is not a frozen literal")
        parsed = ast.literal_eval(value.args[0])
        if not isinstance(parsed, set) or not all(isinstance(item, str) for item in parsed):
            raise ValueError(f"Harness catalog assignment {name} is not a string set")
        return set(parsed)

    return read("EVENTS"), read("PROCESS_EXTENSIONS")


def source_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def handled_types(*paths: Path) -> set[str]:
    found: set[str] = set()
    for path in paths:
        text = source_text(path)
        found.update(re.findall(r"case ['\"]([A-Za-z0-9_.-]+)['\"]\s*:", text))
    return found


def check(args: argparse.Namespace) -> dict[str, Any]:
    catalog = load_json(args.catalog)
    baseline = {item["name"] for item in catalog["baseline_events"]}
    extensions = {item["name"] for item in catalog["process_extensions"]}
    canonical = baseline | extensions
    harness_baseline, harness_extensions = harness_sets(
        args.harness / "src/networkclaw_harness/protocol/catalog.py"
    )

    errors: list[str] = []
    if baseline != harness_baseline:
        errors.append(f"Harness baseline drift: missing={sorted(baseline - harness_baseline)}, extra={sorted(harness_baseline - baseline)}")
    if extensions != harness_extensions:
        errors.append(f"Harness extension drift: missing={sorted(extensions - harness_extensions)}, extra={sorted(harness_extensions - extensions)}")

    harness_server = source_text(args.harness / "src/networkclaw_harness/host/server.py")
    harness_catalog = source_text(args.harness / "src/networkclaw_harness/protocol/catalog.py")
    if "ALL_EVENTS = EVENTS | PROCESS_EXTENSIONS" not in harness_catalog:
        errors.append("Harness ALL_EVENTS is not the union of EVENTS and PROCESS_EXTENSIONS")
    if '"events": sorted(ALL_EVENTS)' not in harness_server:
        errors.append("capabilities.report does not advertise sorted(ALL_EVENTS)")

    go_response = source_text(args.networkclaw / "internal/lobby/model/response.go")
    go_forwarder = source_text(args.networkclaw / "internal/lobby/usecase/grpc_forwarder.go")
    if 'json:"canonical_event,omitempty"' not in go_response:
        errors.append("Go lobby response has no canonical_event carrier")
    if "GetCanonicalEvent" not in go_forwarder or "validateCanonicalEvent" not in go_forwarder:
        errors.append("Go lobby does not validate and forward canonical_event")

    projection = args.networkclaw / "web2/src/api/canonicalProjection.ts"
    semantic = args.networkclaw / "web2/src/api/semanticProjection.ts"
    handled = handled_types(projection, semantic)
    projection_text = source_text(projection)
    unknown_bucket = "unknownEvents" in projection_text and "default:" in projection_text
    if not unknown_bucket:
        errors.append("web2 canonical reducer has no explicit unknownEvents bucket")
    # turn.* is handled by the reducer's prefix branch; all other names must be
    # explicit cases or enter the unknown bucket by policy.
    handled_with_prefix = handled | {name for name in canonical if name.startswith("turn.")}
    unhandled = sorted(canonical - handled_with_prefix)

    report: dict[str, Any] = {
        "report_version": "1.0",
        "catalog_version": catalog.get("catalog_version"),
        "canonical_event_count": len(canonical),
        "baseline_event_count": len(baseline),
        "extension_event_count": len(extensions),
        "harness": {
            "baseline_event_count": len(harness_baseline),
            "extension_event_count": len(harness_extensions),
            "capabilities_source": "host/server.py:capabilities.report",
        },
        "transport": {
            "lobby": "opaque canonical_event carrier with identity and size validation",
            "unknown_events": "preserve-and-observe",
        },
        "consumers": {
            "web2": {
                "explicit_handlers": sorted(handled_with_prefix & canonical),
                "unknown_bucket": "process.unknownEvents",
                "unhandled_by_explicit_projection": unhandled,
            },
            "go_lobby": {"explicit_handlers": [], "unknown_bucket": "opaque canonical_event"},
        },
        "drift": {"errors": errors, "status": "failed" if errors else "ok"},
    }
    if errors:
        raise CatalogDriftError(errors, report)
    return report


class CatalogDriftError(ValueError):
    def __init__(self, errors: list[str], report: dict[str, Any]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors
        self.report = report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=ROOT / "schemas/events/event-catalog-v1.json")
    parser.add_argument("--harness", type=Path)
    parser.add_argument("--networkclaw", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.harness is None or args.networkclaw is None:
            sources = resolve()
            args.harness = args.harness or Path(sources['harness']['path'])
            args.networkclaw = args.networkclaw or Path(sources['networkclaw']['path'])
        report = check(args)
    except CatalogDriftError as exc:
        report = exc.report
        print(f"event catalog drift: {exc}", file=sys.stderr)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"event catalog check: {exc}", file=sys.stderr)
        return 1
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
