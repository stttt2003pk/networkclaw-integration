import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.capability_contract import release_hash


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT.parent / "networkclaw-harness"
TOOL = ROOT / "tools/capability-release.py"
MANIFEST = ROOT / "docs/evidence/capability-release-v1.json"
if (ROOT / ".integration-state/evidence/capability-release-v1.json").is_file():
    MANIFEST = ROOT / ".integration-state/evidence/capability-release-v1.json"


class CapabilityReleaseCheckTest(unittest.TestCase):
    def run_check(self, document: dict, directory: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        manifest = Path(directory) / "manifest.json"
        report = Path(directory) / "report.json"
        manifest.write_text(json.dumps(document), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(TOOL), "check", "--manifest", str(manifest), "--harness", str(HARNESS), "--report", str(report)],
            check=False,
            capture_output=True,
            text=True,
        )
        return result, json.loads(report.read_text(encoding="utf-8"))

    def test_valid_manifest_passes_all_checks(self) -> None:
        result = subprocess.run(
            [sys.executable, str(TOOL), "check", "--manifest", str(MANIFEST), "--harness", str(HARNESS), "--report", "/tmp/capability-release-check-test.json"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(Path("/tmp/capability-release-check-test.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "passed")
        self.assertTrue(all(report["checks"].values()))

    def test_stable_reason_codes_cover_hash_dependency_revision_and_duplicate(self) -> None:
        base = json.loads(MANIFEST.read_text(encoding="utf-8"))
        # Agent mutation cases use an explicit test asset. Delivered ordinary
        # releases legitimately contain no Profiles and must remain empty.
        base["agents"] = json.loads((ROOT / "tests/fixtures/capability-release/valid-release-v1.json").read_text())["agents"]
        for agent in base["agents"]:
            agent["catalog_version"] = base["catalog"]["version"]
            agent["requested_toolsets"] = [{"name": "coding", "revision": 1}]
            agent["skill_revisions"] = []
        base["release_hash"] = release_hash(base)
        cases = []

        invalid_hash = json.loads(json.dumps(base))
        invalid_hash["release_hash"] = "sha256:" + "0" * 64
        cases.append(("release_hash_invalid", invalid_hash))

        stale = json.loads(json.dumps(base))
        stale["agents"][0]["allowed_tool_revisions"][0]["revision"] = 99
        stale["release_hash"] = release_hash(stale)
        cases.append(("stale_revision", stale))

        unavailable = json.loads(json.dumps(base))
        unavailable["skills"][0]["required_tools"] = [{"name": "a2a_call", "revision": 1}]
        unavailable["release_hash"] = release_hash(unavailable)
        cases.append(("dependency_unavailable_unavailable_tool", unavailable))

        missing_dependency = json.loads(json.dumps(base))
        missing_dependency["skills"][0]["required_toolsets"] = [{"name": "missing-toolset", "revision": 1}]
        missing_dependency["release_hash"] = release_hash(missing_dependency)
        cases.append(("dependency_unavailable_missing_dependency", missing_dependency))

        duplicate = json.loads(json.dumps(base))
        duplicate["tools"].append(json.loads(json.dumps(duplicate["tools"][0])))
        duplicate["release_hash"] = release_hash(duplicate)
        cases.append(("duplicate_revision", duplicate))

        with tempfile.TemporaryDirectory() as directory:
            for label, document in cases:
                result, report = self.run_check(document, directory)
                self.assertNotEqual(result.returncode, 0, label)
                expected = "dependency_unavailable" if label.startswith("dependency_unavailable") else label
                self.assertEqual(report["reason_code"], expected, report)


if __name__ == "__main__":
    unittest.main()
