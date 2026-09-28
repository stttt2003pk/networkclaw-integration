#!/usr/bin/env python3
"""Exercise a source bundle after extraction, without using source worktrees."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time


SOURCE_ROOTS = ("networkclaw", "networkclaw-harness", "integration")
SOURCE_BASENAMES = {b"networkclaw", b"networkclaw-harness", b"networkclaw-integration"}
ALLOWED_RUNTIME_PATHS = (b"/opt/networkclaw", b"/opt/networkclaw-harness", b"/opt/bin")
MAX_ARCHIVE_MEMBERS = 200_000
MAX_MEMBER_SIZE = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_SIZE = 8 * 1024 * 1024 * 1024
STAGES = ("archive_safety", "dependencies", "doctor", "source_tests", "combination_matrix", "manifest_verify", "rebuild")
SECRET_VALUE = re.compile(r"(?i)((?:api[_-]?key|access[_-]?token|client[_-]?secret|authorization)[\"']?\s*[:=]\s*[\"']?)([^\s\"']{8,})")


def redact_text(value: str, roots: tuple[Path, ...]) -> str:
    redacted = value
    for root in roots:
        root_text = str(root)
        redacted = redacted.replace(root_text, "<workspace>")
    redacted = redacted.replace(str(Path(sys.executable).resolve()), "<python3.12>")
    return redacted


def run(
    name: str,
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    report: dict[str, object],
    redacted_roots: tuple[Path, ...] = (),
) -> bool:
    started = time.monotonic()
    output_tail = ""
    try:
        result = subprocess.run(command, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output_tail = SECRET_VALUE.sub(r"\1[REDACTED]", result.stdout[-2000:]) if result.returncode else ""
        output_tail = redact_text(output_tail, redacted_roots)
        detail = None if result.returncode == 0 else "command failed; see sanitized output tail"
        code = result.returncode
    except OSError as exc:
        code = 127
        detail = redact_text(f"cannot start command: {exc.strerror or exc.__class__.__name__}", redacted_roots)
    report["steps"].append({
        "name": name,
        "command": [redact_text(str(item), redacted_roots) for item in command],
        "exit_code": code,
        "duration_seconds": round(time.monotonic() - started, 3),
        "detail": detail,
        "output_tail": output_tail,
    })
    return code == 0


def check_snapshot(root: Path) -> list[str]:
    problems: list[str] = []
    for name in SOURCE_ROOTS:
        source = root / name
        if not source.is_dir():
            problems.append(f"missing bundle source directory: {name}")
    for current, dirs, files in os.walk(root, followlinks=False):
        base = Path(current)
        excluded = {".git", ".venv", "venv", "__pycache__", ".integration-state"}
        for name in dirs:
            if name in excluded:
                problems.append(f"development metadata included: {(base / name).relative_to(root)}")
        dirs[:] = [name for name in dirs if name not in excluded]
        for name in files:
            path = base / name
            if path.is_symlink():
                target = os.readlink(path)
                if Path(target).is_absolute() or ".." in Path(target).parts:
                    problems.append(f"unsafe symlink: {path.relative_to(root)}")
                continue
            try:
                data = path.read_bytes()
            except OSError as exc:
                problems.append(f"cannot read {path.relative_to(root)}: {exc.strerror}")
                continue
            rel = path.relative_to(root).as_posix()
            absolute_tokens = (
                token.strip(b"\"'`<>()[]{};,:")
                for token in data.split()
                if token.startswith(b"/")
            )
            if any(
                len(token.split(b"/")) >= 4
                and not any(token.lower().startswith(prefix) for prefix in ALLOWED_RUNTIME_PATHS)
                and any(part.lower() in SOURCE_BASENAMES for part in token.split(b"/"))
                for token in absolute_tokens
            ):
                problems.append(f"original workspace path found: {rel}")
    return problems


def check_archive_input(archive: Path, checksum: Path) -> list[str]:
    problems: list[str] = []
    if not checksum.is_file():
        return [f"missing checksum sidecar: {checksum}"]
    fields = checksum.read_text(encoding="ascii").strip().split()
    if len(fields) != 2 or fields[1] != archive.name:
        return ["checksum sidecar has invalid format or filename"]
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if fields[0] != digest.hexdigest():
        return ["archive checksum does not match sidecar"]
    total_size = 0
    with tarfile.open(archive, "r|gz") as tar:
        member_count = 0
        for member in tar:
            member_count += 1
            if member_count > MAX_ARCHIVE_MEMBERS:
                problems.append(f"archive has too many members: {member_count}")
                break
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or "\\" in member.name:
                problems.append(f"unsafe archive path: {member.name}")
            if not (member.isfile() or member.isdir() or member.issym()):
                problems.append(f"unsupported archive entry: {member.name}")
            if member.issym():
                target = PurePosixPath(member.linkname)
                if target.is_absolute() or ".." in target.parts or "\\" in member.linkname:
                    problems.append(f"unsafe archive symlink: {member.name}")
            if member.isfile():
                if member.size > MAX_MEMBER_SIZE:
                    problems.append(f"archive member is too large: {member.name}")
                total_size += member.size
            if total_size > MAX_ARCHIVE_SIZE:
                problems.append(f"archive expands beyond limit: {total_size} bytes")
                break
    return problems


def bootstrap(
    integration: Path,
    harness: Path,
    env: dict[str, str],
    report: dict[str, object],
    wheelhouse: Path | None,
    redacted_roots: tuple[Path, ...],
) -> bool:
    python = shutil.which("python3.12", path=env.get("PATH"))
    if python is None:
        report["missing_inputs"].append("CPython 3.12")
        return False
    harness_venv = harness / ".venv"
    integration_venv = integration / ".venv"
    if not run("create_harness_venv", [python, "-m", "venv", str(harness_venv)], harness, env, report, redacted_roots):
        return False
    harness_python = harness_venv / "bin" / "python"
    pip_args = [str(harness_python), "-m", "pip", "install"]
    if wheelhouse:
        pip_args.extend(["--no-index", "--find-links", str(wheelhouse)])
    pip_args.extend(["--require-hashes", "-r", "requirements.lock", "-r", "requirements-dev.lock", "-r", "requirements-build.lock"])
    if not run("install_harness_locked_dependencies", pip_args, harness, env, report, redacted_roots):
        report["missing_inputs"].append("Harness requirements.lock / requirements-dev.lock wheels (see failed dependency step)")
        return False
    pip_args = [str(harness_python), "-m", "pip", "install", "--no-build-isolation", "-e", ".[dev]"]
    if wheelhouse:
        pip_args.extend(["--no-index", "--find-links", str(wheelhouse)])
    if not run("install_harness_project", pip_args, harness, env, report, redacted_roots):
        report["missing_inputs"].append("Harness local package build dependencies (see failed dependency step)")
        return False
    if not run("create_integration_venv", [python, "-m", "venv", str(integration_venv)], integration, env, report, redacted_roots):
        return False
    integration_python = integration_venv / "bin" / "python"
    pip_args = [str(integration_python), "-m", "pip", "install"]
    if wheelhouse:
        pip_args.extend(["--no-index", "--find-links", str(wheelhouse)])
    pip_args.extend(["-e", str(integration)])
    if not run("install_integration_dependencies", pip_args, integration, env, report, redacted_roots):
        report["missing_inputs"].append("Integration pyproject dependencies (see failed dependency step)")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--report", type=Path, help="write the machine-readable report here")
    parser.add_argument("--wheelhouse", type=Path, help="optional directory of wheels; disables package-index access")
    parser.add_argument("--keep-workspace", action="store_true", help="retain the isolated extracted workspace for diagnosis")
    args = parser.parse_args()
    archive = args.archive.resolve()
    report_path = args.report.resolve() if args.report else None
    report: dict[str, object] = {
        "schema_version": 1,
        "archive": archive.name,
        "status": "failed",
        "steps": [],
        "missing_inputs": [],
        "failures": [],
    }
    temp = tempfile.TemporaryDirectory(prefix="networkclaw-bundle-self-test-")
    workspace = Path(temp.name).resolve()
    isolated_archive = workspace / archive.name
    isolated_checksum = isolated_archive.with_name(isolated_archive.name + ".sha256")
    retain_workspace = False
    try:
        shutil.copyfile(archive, isolated_archive)
        checksum = archive.with_name(archive.name + ".sha256")
        if checksum.is_file():
            shutil.copyfile(checksum, isolated_checksum)
        else:
            report["missing_inputs"].append("bundle checksum sidecar: " + str(checksum))
        archive_problems = check_archive_input(isolated_archive, isolated_checksum)
        if archive_problems:
            report["steps"].append({"name": "archive_safety", "exit_code": 1, "problems": archive_problems})
            report["failures"].extend(archive_problems)
            report["missing_inputs"].extend(problem for problem in archive_problems if "missing" in problem)
            return 1
        with tarfile.open(isolated_archive, "r:gz") as tar:
            tar.extractall(workspace, filter="data")
        bundle = workspace / "networkclaw-bundle"
        integration = bundle / "integration"
        networkclaw = bundle / "networkclaw"
        harness = bundle / "networkclaw-harness"
        problems = check_snapshot(bundle)
        bundled_self_test = integration / "tests" / "bundle" / "self_test.py"
        if not bundled_self_test.is_file():
            problems.append("missing bundle self-test driver: integration/tests/bundle/self_test.py")
        report["steps"].append({"name": "archive_safety", "exit_code": 0 if not problems else 1, "problems": problems})
        if problems:
            report["failures"].extend(problems)
            report["missing_inputs"].extend(name for name in SOURCE_ROOTS if not (bundle / name).is_dir())
        else:
            env = os.environ.copy()
            for key in list(env):
                if (key.startswith("NETWORKCLAW_") and key != "NETWORKCLAW_CHILD_DATABASE_URL") or key == "HARNESS_PATH":
                    env.pop(key)
            env["NETWORKCLAW_PATH"] = str(networkclaw)
            env["HARNESS_PATH"] = str(harness)
            env["NETWORKCLAW_INTEGRATION_PATH"] = str(integration)
            env["NETWORKCLAW_WORKSPACE_FILE"] = str(integration / "workspace.local.yaml")
            env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
            wheelhouse = args.wheelhouse.resolve() if args.wheelhouse else None
            if wheelhouse and not wheelhouse.is_dir():
                report["missing_inputs"].append(f"wheelhouse directory: {wheelhouse}")
            elif bootstrap(integration, harness, env, report, wheelhouse, (workspace,)):
                integration_python = integration / ".venv" / "bin" / "python"
                harness_python = harness / ".venv" / "bin" / "python"
                env["NETWORKCLAW_PYTHON"] = str(harness_python)
                stages = [
                    ("doctor", ["make", "doctor"], integration),
                    ("source_tests", [str(harness / "scripts" / "run_tests.sh")], harness),
                    ("integration_tests", ["make", "test"], integration),
                    ("combination_matrix", [str(integration_python), str(integration / "tools" / "run-combination-matrix.py")], integration),
                    ("manifest_verify", [str(integration_python), str(integration / "tools" / "verify-bundle.py"), str(isolated_archive)], integration),
                    ("rebuild", [str(integration_python), str(integration / "tools" / "build-bundle.py"), "--networkclaw", str(networkclaw), "--harness", str(harness), "--integration", str(integration), "--output", str(workspace / "rebuilt.tar.gz")], integration),
                    ("verify_rebuild", [str(integration_python), str(integration / "tools" / "verify-bundle.py"), str(workspace / "rebuilt.tar.gz")], integration),
                ]
                for name, command, cwd in stages:
                    if not run(name, command, cwd, env, report, (workspace,)):
                        report["failures"].append(name)
                        if name in {"doctor", "source_tests", "integration_tests", "combination_matrix"}:
                            report["missing_inputs"].append(f"see failed {name} stage; required source/tool/platform input may be unavailable")
                        break
                if not report["failures"]:
                    report["status"] = "passed"
            else:
                if not report["missing_inputs"]:
                    report["failures"].append("dependency bootstrap failed")
        report["workspace_retained"] = args.keep_workspace
        if args.keep_workspace:
            report["workspace"] = str(workspace)
            retain_workspace = True
    except (OSError, tarfile.TarError, ValueError) as exc:
        report["failures"].append(f"self-test could not continue: {exc}")
    finally:
        if report_path:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        if not retain_workspace:
            temp.cleanup()
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
