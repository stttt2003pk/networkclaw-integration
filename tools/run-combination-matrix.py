#!/usr/bin/env python3
"""Run the three-repository acceptance matrix and write bounded evidence."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / ".integration-state" / "evidence"


@dataclass
class CommandResult:
    name: str
    cwd: str
    command: list[str]
    returncode: int
    duration_seconds: float
    tests: dict[str, str]
    output_tail: str

    @property
    def passed(self) -> bool:
        return self.returncode == 0


def resolve_source(name: str) -> Path:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "resolve_sources.py"), "--get", name],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    return Path(result.stdout.strip())


def parse_go_tests(output: str) -> dict[str, str]:
    results: dict[str, str] = {}
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("Action") != "pass" and event.get("Action") != "fail" and event.get("Action") != "skip":
            continue
        test = event.get("Test")
        if isinstance(test, str):
            results[test] = str(event["Action"])
    return results


def run_command(name: str, command: list[str], cwd: Path, *, parse_go: bool = False) -> CommandResult:
    started = time.monotonic()
    completed = subprocess.run(command, cwd=cwd, check=False, capture_output=True, text=True)
    output = completed.stdout + completed.stderr
    tests = parse_go_tests(output) if parse_go else {}
    return CommandResult(
        name=name,
        cwd=str(cwd),
        command=command,
        returncode=completed.returncode,
        duration_seconds=round(time.monotonic() - started, 3),
        tests=tests,
        output_tail=output[-2000:],
    )


def command_record(result: CommandResult) -> dict[str, Any]:
    return {
        "name": result.name,
        "cwd": result.cwd,
        "command": result.command,
        "returncode": result.returncode,
        "duration_seconds": result.duration_seconds,
        "tests": result.tests,
        "output_tail": result.output_tail,
    }


def main() -> int:
    skip_real = os.environ.get("NETWORKCLAW_SKIP_REAL_INTEROP") == "1"
    REPORT_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    networkclaw = resolve_source("networkclaw")
    harness = resolve_source("harness")

    commands: list[CommandResult] = []
    fixture = run_command(
        "integration-fixtures",
        [sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-v"],
        ROOT,
    )
    commands.append(fixture)

    if not skip_real:
        commands.append(run_command(
            "go-cross-repository",
            ["go", "test", "-json", "-race", "./tests/integration/harnessinterop", "-count=1"],
            networkclaw,
            parse_go=True,
        ))
        commands.append(run_command(
            "go-process-recovery",
            [
                "go", "test", "-json", "-race", "./internal/chatsvc/harness",
                "-run=TestPythonHarness_(TakeoverFencesOldOwner|SigkillThenReplacementEpoch|ParallelSessionsKeepResponsesCorrelated|KillDuringProviderThenReplacementResumesSameWorkspace)",
                "-count=1",
            ],
            networkclaw,
            parse_go=True,
        ))
        commands.append(run_command(
            "go-client-transport-support",
            [
                "go", "test", "-json", "-race", "./internal/chatsvc/harness",
                "-run=Test(Client_ChildEOFFailsAllPendingCalls|ClientPending_BoundsBufferedFrames)",
                "-count=1",
            ],
            networkclaw,
            parse_go=True,
        ))
        commands.append(run_command(
            "go-lifecycle-fencing-support",
            [
                "go", "test", "-json", "-race", "./internal/chatsvc/session",
                "-run=TestHarnessHandler_(LeaseVersionAdvancesButOldEpochCannotRevoke|RevokeRejectsLateControl|TakeoverFencesLateEpochFrames|ReducesToFirstTerminalAndDropsLateEvents)",
                "-count=1",
            ],
            networkclaw,
            parse_go=True,
        ))
        commands.append(run_command(
            "harness-recovery-delegation",
            [
                str(harness / "scripts" / "run_tests.sh"), "-q",
                "tests/test_recovery.py", "tests/test_recovery_subprocess.py",
                "tests/test_delegation.py", "tests/test_host.py",
                "tests/test_hermes_host_adapter.py", "tests/test_interaction_control.py",
                "tests/test_session_runtime.py", "tests/test_projection.py",
            ],
            harness,
        ))

    command_by_name = {item.name: item for item in commands}
    cross = command_by_name.get("go-cross-repository")
    recovery = command_by_name.get("go-process-recovery")
    transport = command_by_name.get("go-client-transport-support")
    harness_support = command_by_name.get("harness-recovery-delegation")

    def test_passed(result: CommandResult | None, test: str) -> bool:
        return result is not None and result.tests.get(test) == "pass"

    scenarios = [
        {"id": "single_session_vertical_flow", "kind": "cross_repository", "command": "go-cross-repository", "tests": ["TestSingleSessionVerticalFlow"], "reason_codes": ["completed", "provider_succeeded"]},
        {"id": "multi_session_multiplexing", "kind": "cross_repository", "command": "go-cross-repository", "tests": ["TestProviderBackedSessionsMultiplexWithoutCrossTalk"], "reason_codes": ["completed"]},
        {"id": "same_session_admission_cancel_steer", "kind": "cross_repository", "command": "go-cross-repository", "tests": ["TestSameSessionAdmissionAndActiveControl"], "reason_codes": ["turn_already_active", "user_cancel"]},
        {"id": "lease_takeover_and_stale_control", "kind": "cross_repository", "command": "go-cross-repository", "tests": ["TestLeaseTakeoverFencesOldOwnerAcrossProcess"], "reason_codes": ["stale_epoch", "epoch_takeover"]},
        {"id": "provider_and_transport_interruption", "kind": "cross_repository", "command": "go-cross-repository", "tests": ["TestProviderStreamingDropIsNotCompleted", "TestProviderStreamAndTransportFaultCombination", "TestReasonCodesEndToEndThroughClient"], "reason_codes": ["provider_interrupted", "provider_stream_interrupted", "provider_transport_reset"]},
        {"id": "request_replay_and_hash_conflict", "kind": "cross_repository", "command": "go-cross-repository", "tests": ["TestRequestReplayAndHashConflictAcrossProcess"], "reason_codes": ["request_id_conflict"]},
        {"id": "sigkill_replacement_same_workspace", "kind": "cross_repository", "command": "go-process-recovery", "tests": ["TestPythonHarness_SigkillThenReplacementEpoch", "TestPythonHarness_KillDuringProviderThenReplacementResumesSameWorkspace"], "reason_codes": ["harness_unavailable", "epoch_takeover"]},
        {"id": "eof_fanout_and_pending_backpressure", "kind": "cross_process_support", "command": "go-client-transport-support", "tests": ["TestClient_ChildEOFFailsAllPendingCalls", "TestClientPending_BoundsBufferedFrames"], "reason_codes": ["harness_unavailable", "backpressure"]},
        {"id": "lease_revoke_and_late_frame_fencing", "kind": "go_lifecycle_support", "command": "go-lifecycle-fencing-support", "tests": ["TestHarnessHandler_LeaseVersionAdvancesButOldEpochCannotRevoke", "TestHarnessHandler_RevokeRejectsLateControl", "TestHarnessHandler_TakeoverFencesLateEpochFrames", "TestHarnessHandler_ReducesToFirstTerminalAndDropsLateEvents"], "reason_codes": []},
        {"id": "parent_child_interrupt_scope", "kind": "cross_repository", "command": "go-cross-repository", "tests": ["TestParentChildInterruptScopeIsSessionLocal"], "reason_codes": ["user_cancel"]},
        {"id": "unknown_side_effect_no_replay_and_exactly_once_release", "kind": "harness_supporting", "command": "harness-recovery-delegation", "tests": [], "reason_codes": ["unknown_side_effect", "delegation_broker_closed"]},
    ]

    for scenario in scenarios:
        result = command_by_name.get(scenario["command"])
        if skip_real:
            scenario["status"] = "skipped"
        elif result is None:
            scenario["status"] = "missing"
        elif scenario["tests"]:
            scenario["status"] = "passed" if all(test_passed(result, test) for test in scenario["tests"]) else "failed"
        else:
            scenario["status"] = "passed" if result.passed else "failed"

    report = {
        "schema_version": "1",
        "matrix": "networkclaw-go-harness-v1",
        "platform": {"system": sys.platform, "python": sys.version.split()[0]},
        "skip_real_interop": skip_real,
        "commands": [command_record(item) for item in commands],
        "scenarios": scenarios,
        "status": "passed" if all(item.passed for item in commands) and all(item["status"] == "passed" for item in scenarios if not skip_real) else ("skipped" if skip_real else "failed"),
    }
    json_path = REPORT_DIR / "combination-matrix.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(json_path, 0o600)

    markdown = ["# Combination Matrix", "", f"Status: **{report['status']}**", "", "| Scenario | Evidence | Status | Reason codes |", "|---|---|---|---|"]
    for scenario in scenarios:
        markdown.append(f"| `{scenario['id']}` | {scenario['kind']} | **{scenario['status']}** | {', '.join(f'`{code}`' for code in scenario['reason_codes'])} |")
    markdown.extend(["", "Command evidence:", ""])
    for item in commands:
        markdown.append(f"- `{item.name}`: exit `{item.returncode}`, {item.duration_seconds:.3f}s")
    md_path = REPORT_DIR / "combination-matrix.md"
    md_path.write_text("\n".join(markdown) + "\n", encoding="utf-8")
    os.chmod(md_path, 0o600)

    if report["status"] == "failed":
        for item in commands:
            if not item.passed:
                print(f"matrix: {item.name} failed (exit {item.returncode})", file=sys.stderr)
                print(item.output_tail, file=sys.stderr)
        return 1
    print(f"matrix: {report['status']} ({json_path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
