#!/usr/bin/env python3
"""R-11 cross-repository acceptance; database writes only to an explicit fixture."""

import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    env = os.environ.copy()
    if not env.get("CAPABILITY_MIGRATION_TEST_DSN"):
        print("CAPABILITY_MIGRATION_TEST_DSN must identify a disposable PostgreSQL fixture", file=sys.stderr)
        return 1
    go = Path(env.get("NETWORKCLAW_PATH", ROOT.parent / "NetworkClaw")).resolve()
    harness = Path(env.get("HARNESS_PATH", ROOT.parent / "networkclaw-harness")).resolve()
    env.update(NETWORKCLAW_PATH=str(go), HARNESS_PATH=str(harness), NETWORKCLAW_INTEGRATION_ROOT=str(ROOT), NETWORKCLAW_PYTHON=str(harness / ".venv/bin/python"))
    evidence = ROOT / ".integration-state/evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    report_path = Path(env.get("CAPABILITY_ACCEPTANCE_REPORT", evidence / "capability-release-acceptance.json"))
    report = {"schema_version": "capability-release-acceptance.v1", "status": "failed", "platform": platform.system().lower(), "architecture": platform.machine(), "stages": []}
    with tempfile.TemporaryDirectory(prefix="capability-r11-") as temporary:
        work = Path(temporary)
        env["CAPABILITY_MIGRATION_TEST_REPORT"] = str(work / "sessions.json")
        env["CAPABILITY_ACCEPTANCE_TRANSACTION_REPORT"] = str(work / "compiled-import.json")
        env["CAPABILITY_ACCEPTANCE_MANIFEST"] = str(evidence / "capability-release-v1.json")

        def run(name, command, cwd=ROOT):
            print("R-11: " + name, flush=True)
            result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=1200)
            output = result.stdout + result.stderr
            for value in (env["CAPABILITY_MIGRATION_TEST_DSN"], str(ROOT), str(go), str(harness), temporary):
                output = output.replace(value, "<workspace>")
            (evidence / ("capability-acceptance-" + name + ".log")).write_text(output)
            record = {"name": name, "exit_code": result.returncode}
            report["stages"].append(record)
            if result.returncode:
                raise RuntimeError(name + "_failed")
            return result.stdout

        try:
            run("release_gates", ["make", "capability-release-vendor-check", "capability-release-diff"])
            manifest = json.loads((evidence / "capability-release-v1.json").read_text())
            report.update(release_hash=manifest["release_hash"], sources=manifest["sources"], hermes=manifest["hermes"])
            modules = ["tests.test_capability_release_" + name for name in ("acceptance", "vendor", "discovery", "compile", "check", "diff", "export", "admin")]
            run("release_failures", [sys.executable, "-m", "unittest", *modules, "tests.test_capability_bundle", "-v"])
            run("harness_skills", [str(harness / "scripts/run_tests.sh"), "tests/test_vendor_supply_chain.py", "tests/test_hermes_vendor_skill_manifest.py", "tests/test_skill_release_manifest.py"], harness)
            run("admin_contract", ["make", "capability-release-admin-contract-test", "CAPABILITY_RELEASE_NETWORKCLAW=" + str(go)])
            output = run("transactions_and_sessions", ["go", "test", "-json", "-race", "./tests/integration/harnessinterop", "-run", "^TestCapability(ReleaseAcceptanceAtomicFailures|ReleaseAcceptanceCompiledManifest|MigrationPublishedSessionsAndRollback)$", "-count=1"], go)
            events = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
            required = {"TestCapabilityReleaseAcceptanceAtomicFailures", "TestCapabilityReleaseAcceptanceCompiledManifest", "TestCapabilityMigrationPublishedSessionsAndRollback"}
            passed = {event["Test"] for event in events if event.get("Action") == "pass" and event.get("Test")}
            if not required <= passed or any(event.get("Action") in {"fail", "skip"} for event in events):
                raise RuntimeError("required_database_acceptance_missing")
            sessions = json.loads((work / "sessions.json").read_text())
            if sessions.get("status") != "passed":
                raise RuntimeError("session_evidence_missing")
            report["session_checks"] = sessions["checks"]
            compiled_import = json.loads((work / "compiled-import.json").read_text())
            if compiled_import.get("status") != "passed" or compiled_import.get("release_hash") != report["release_hash"]:
                raise RuntimeError("compiled_import_evidence_missing")
            report["compiled_import"] = compiled_import
            report["database_tests_passed"] = sorted(passed)
            report["status"] = "passed"
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            report["reason_code"] = type(error).__name__ if not isinstance(error, RuntimeError) else str(error)
    report["temporary_workspace_removed"] = not Path(temporary).exists()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": report["status"], "reason_code": report.get("reason_code")}, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
