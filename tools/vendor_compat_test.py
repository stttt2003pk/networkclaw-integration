#!/usr/bin/env python3
"""Run Harness vendor checks and the cross-repository compatibility gate."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from source_tree import included_files, tree_hash  # noqa: E402
from vendor_status import collect_status  # noqa: E402


def run_stage(name: str, command: list[str], cwd: Path, env: dict[str, str]) -> dict[str, object]:
    started = time.monotonic()
    result = subprocess.run(command, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return {
        "name": name,
        "command": command,
        "returncode": result.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "output_tail": result.stdout[-4000:],
    }


def refresh_lock(lock_path: Path, status: dict[str, object]) -> None:
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    for name in ("networkclaw", "harness"):
        identity = status["sources"][name]
        lock[name]["commit"] = identity["commit"]
        lock[name]["tree_sha256"] = identity["tree_sha256"]
    lock["integration"]["tree_sha256"] = status["sources"]["integration"]["tree_sha256"]
    temp = lock_path.with_suffix(lock_path.suffix + ".tmp")
    temp.write_text(yaml.safe_dump(lock, sort_keys=False, allow_unicode=True), encoding="utf-8")
    os.replace(temp, lock_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--networkclaw", type=Path, default=Path(os.environ.get("NETWORKCLAW_PATH", ROOT.parent / "NetworkClaw")))
    parser.add_argument("--harness", type=Path, default=Path(os.environ.get("HARNESS_PATH", ROOT.parent / "networkclaw-harness")))
    parser.add_argument("--lock", type=Path, default=ROOT / "sources.lock.yaml")
    parser.add_argument("--report", type=Path, default=ROOT / ".integration-state/evidence/vendor-compat-report.json")
    parser.add_argument("--update-lock", action="store_true", help="after all checks pass, advance sources.lock.yaml to tested clean commits")
    parser.add_argument("--vendor-fixture", action="store_true", help="tamper a temporary Harness vendor copy and prove verifier failure blocks formal acceptance")
    args = parser.parse_args()
    networkclaw, harness, lock_path = args.networkclaw.resolve(), args.harness.resolve(), args.lock.resolve()
    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    report = {
        "schema_version": 1,
        "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "failed",
        "source_lock_before": yaml.safe_load(lock_path.read_text(encoding="utf-8")),
        "stages": [],
        "release_bundle_created": False,
    }
    env = os.environ | {"NETWORKCLAW_PATH": str(networkclaw), "HARNESS_PATH": str(harness)}
    env.pop("CI_ALLOW_DIRTY", None)

    try:
        initial = collect_status(networkclaw, harness, lock_path)
        report["source_identity_before"] = initial
        tested_harness = harness
        if args.vendor_fixture:
            temporary = tempfile.TemporaryDirectory(prefix="networkclaw-vendor-fixture-")
            report["fixture_workspace_removed_after_run"] = True
            tested_harness = Path(temporary.name) / "harness"
            import shutil
            shutil.copytree(harness, tested_harness, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", "*.pyc"))
            (tested_harness / ".venv").symlink_to(harness / ".venv", target_is_directory=True)
            vendor_file = tested_harness / "vendor/hermes/hermes_constants.py"
            vendor_file.write_bytes(vendor_file.read_bytes() + b"\n# simulated upstream vendor update\n")
            vendor_manifest = tested_harness / "upstream/hermes-vendor-manifest.json"
            manifest = json.loads(vendor_manifest.read_text(encoding="utf-8"))
            manifest["files"]["hermes_constants.py"] = hashlib.sha256(vendor_file.read_bytes()).hexdigest()
            vendor_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            env["HARNESS_PATH"] = str(tested_harness)

            upgrade_verifier = run_stage("simulated_upgrade_vendor_verifier", [sys.executable, str(tested_harness / "scripts/verify-hermes-vendor.py")], tested_harness, env)
            report["stages"].append(upgrade_verifier)
            if upgrade_verifier["returncode"] == 0:
                upgrade_tests = run_stage("simulated_upgrade_harness_tests", [str(tested_harness / "scripts/run_tests.sh"), "-q"], tested_harness, env)
                report["stages"].append(upgrade_tests)
            else:
                upgrade_tests = {"returncode": 1}
            if upgrade_tests["returncode"] == 0:
                upgrade_matrix = run_stage("simulated_upgrade_combination_matrix", [str(ROOT / ".venv/bin/python"), str(ROOT / "tools/run-combination-matrix.py")], ROOT, env)
                report["stages"].append(upgrade_matrix)
            else:
                upgrade_matrix = {"returncode": 1}

            vendor_file.write_bytes(vendor_file.read_bytes() + b"\n# injected incompatible content\n")
            negative = run_stage("incompatible_vendor_rejected", [sys.executable, str(tested_harness / "scripts/verify-hermes-vendor.py")], tested_harness, env)
            report["stages"].append(negative)
            report["formal_delivery_blocked"] = negative["returncode"] != 0
            report["release_bundle_created"] = False

            env["HARNESS_PATH"] = str(harness)
            baseline_tests = run_stage("restored_baseline_harness_tests", [str(harness / "scripts/run_tests.sh"), "-q"], harness, env)
            report["stages"].append(baseline_tests)
            baseline_matrix = run_stage("restored_baseline_combination_matrix", [str(ROOT / ".venv/bin/python"), str(ROOT / "tools/run-combination-matrix.py")], ROOT, env)
            report["stages"].append(baseline_matrix)
            fixture_ok = all(stage.get("returncode") == 0 for stage in (upgrade_verifier, upgrade_tests, upgrade_matrix, baseline_tests, baseline_matrix)) and negative["returncode"] != 0
            report["vendor_upgrade_fixture"] = {
                "simulated_vendor_change_accepted": upgrade_verifier["returncode"] == 0,
                "incompatible_change_blocked": negative["returncode"] != 0,
                "formal_delivery_blocked": report["formal_delivery_blocked"],
                "baseline_restored_and_retested": baseline_tests["returncode"] == 0 and baseline_matrix["returncode"] == 0,
            }
            report["status"] = "passed" if fixture_ok else "failed"
            report["fixture_expectation"] = "passed" if fixture_ok else "failed"

        if not args.vendor_fixture:
            verifier = run_stage(
                "harness_vendor_verifier",
                [sys.executable, str(tested_harness / "scripts/verify-hermes-vendor.py")],
                tested_harness, env,
            )
            report["stages"].append(verifier)
        else:
            verifier = {"returncode": 1}
        if not args.vendor_fixture and verifier["returncode"] != 0:
            report["blocked_stage"] = "harness_vendor_verifier"
            report["formal_delivery_blocked"] = True
            report["status"] = "failed"
        elif not args.vendor_fixture:
            tests = run_stage("harness_tests", [str(tested_harness / "scripts/run_tests.sh"), "-q"], tested_harness, env)
            report["stages"].append(tests)
            if tests["returncode"] != 0:
                report["blocked_stage"] = "harness_tests"
            else:
                matrix = run_stage("combination_matrix", [str(ROOT / ".venv/bin/python"), str(ROOT / "tools/run-combination-matrix.py")], ROOT, env)
                report["stages"].append(matrix)
                if matrix["returncode"] != 0:
                    report["blocked_stage"] = "combination_matrix"
                else:
                    after = collect_status(networkclaw, harness, lock_path)
                    dirty = [name for name in ("networkclaw", "harness", "integration") if after["sources"][name]["dirty"]]
                    if dirty:
                        report["blocked_stage"] = "clean_source_precondition"
                        report["dirty_sources"] = dirty
                    elif args.update_lock:
                        refresh_lock(lock_path, after)
                        report["source_lock_updated"] = True
                        report["source_lock_after"] = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
                        lock_gate = run_stage("source_lock_after_update", [str(ROOT / ".venv/bin/python"), str(ROOT / "tools/verify_sources_lock.py"), "--lock", str(lock_path)], ROOT, env)
                        report["stages"].append(lock_gate)
                        if lock_gate["returncode"] == 0:
                            report["status"] = "passed"
                        else:
                            report["blocked_stage"] = "source_lock_after_update"
                    else:
                        lock_gate = run_stage("source_lock", [str(ROOT / ".venv/bin/python"), str(ROOT / "tools/verify_sources_lock.py"), "--lock", str(lock_path)], ROOT, env)
                        report["stages"].append(lock_gate)
                        if lock_gate["returncode"] == 0:
                            report["status"] = "passed"
                        else:
                            report["blocked_stage"] = "source_lock"

    except (OSError, ValueError, KeyError, yaml.YAMLError, subprocess.CalledProcessError) as exc:
        report["error"] = str(exc)
        report["status"] = "failed"
    finally:
        if "temporary" in locals():
            temporary.cleanup()
        report["finished_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({"status": report["status"], "report": str(report_path), "blocked_stage": report.get("blocked_stage"), "source_lock_updated": report.get("source_lock_updated", False)}, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
