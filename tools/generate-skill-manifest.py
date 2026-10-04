#!/usr/bin/env python3
"""Generate release manifests from a Harness checkout without copying its code."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

PROBE = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "src"))
from networkclaw_harness.skills import BUILTIN_SKILLS_ROOT, SkillCatalog
roots = [Path(item) for item in json.loads(sys.argv[2])] or [BUILTIN_SKILLS_ROOT]
policies = json.loads(sys.argv[3])
print(json.dumps({"manifest_version": "skill-release.v1", "skills": [dict(item) for item in SkillCatalog(roots, root_policies=policies).release_manifest()]}, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
'''


def generate(harness: Path, roots: list[Path] | None = None, *, trust_state: str = "unknown", release_status: str = "unavailable") -> dict:
    python = os.environ.get("HARNESS_PYTHON", str(harness / ".venv/bin/python"))
    if not Path(python).is_file():
        python = sys.executable
    root_values = [str(path.resolve()) for path in roots or []]
    policies = {
        str(path): {"trust_state": trust_state, "release_status": release_status}
        for path in root_values
    }
    result = subprocess.run(
        [python, "-c", PROBE, str(harness.resolve()), json.dumps(root_values), json.dumps(policies)],
        cwd=harness,
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr[-4000:] or "Skill release manifest generation failed")
    builtin = json.loads(result.stdout)
    with tempfile.TemporaryDirectory(prefix="networkclaw-hermes-skills-") as directory:
        output = Path(directory) / "vendor-skills.json"
        native = subprocess.run(
            [python, str(harness / "scripts/generate-hermes-skill-manifest.py"), "--output", str(output)],
            cwd=harness,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if native.returncode:
            raise RuntimeError(native.stderr[-4000:] or "Hermes vendor Skill manifest generation failed")
        vendored = json.loads(output.read_text(encoding="utf-8"))
    skills = builtin["skills"] + vendored["skills"]
    ids = [skill["skill_id"] for skill in skills]
    if len(ids) != len(set(ids)):
        raise RuntimeError("duplicate Skill id across Harness builtins and Hermes vendor")
    return {"manifest_version": "skill-release.v1", "skills": sorted(skills, key=lambda skill: skill["skill_id"])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness", type=Path, default=Path(os.environ.get("HARNESS_PATH", ROOT.parent / "networkclaw-harness")))
    parser.add_argument("--root", type=Path, action="append", default=[], help="release root; defaults to Harness built-ins")
    parser.add_argument("--trust-state", choices=("trusted", "quarantined", "unknown"), default="unknown", help="external trust policy for --root values")
    parser.add_argument("--release-status", choices=("available", "unavailable", "revoked"), default="unavailable", help="external release policy for --root values")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/evidence/hermes-skill-release-manifest-v1.json")
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    report = generate(args.harness, args.root, trust_state=args.trust_state, release_status=args.release_status)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "skills": len(report["skills"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
