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


class CapabilityReleaseDiffTest(unittest.TestCase):
    def run_diff(self, published: Path, candidate: Path, output: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOL), "diff", "--published", str(published), "--candidate", str(candidate), "--harness", str(HARNESS), "--output", str(output)],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_same_manifest_is_empty_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_a, output_b = Path(directory) / "a.json", Path(directory) / "b.json"
            first = self.run_diff(MANIFEST, MANIFEST, output_a)
            second = self.run_diff(MANIFEST, MANIFEST, output_b)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            first_document = json.loads(output_a.read_text(encoding="utf-8"))
            second_document = json.loads(output_b.read_text(encoding="utf-8"))
        self.assertEqual(first_document, second_document)
        self.assertEqual(first_document["summary"], {"added": 0, "removed": 0, "changed": 0, "binding_changes": 0, "dependency_changes": 0, "unresolved_migrations": 0})
        self.assertEqual(first_document["migration"]["unresolved"], [])

    def test_changes_and_unresolved_migration_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            published = Path(directory) / "published.json"
            candidate = Path(directory) / "candidate.json"
            output = Path(directory) / "diff.json"
            current = json.loads(MANIFEST.read_text(encoding="utf-8"))
            current["agents"] = json.loads((ROOT / "tests/fixtures/capability-release/valid-release-v1.json").read_text())["agents"]
            for agent in current["agents"]:
                agent["catalog_version"] = current["catalog"]["version"]
                agent["requested_toolsets"] = [{"name": "coding", "revision": 1}]
                agent["skill_revisions"] = []
            current["release_hash"] = release_hash(current)
            old = json.loads(json.dumps(current))
            old["release_id"] = "cap-published-fixture"
            old["catalog"]["version"] = "old-catalog"
            old["tools"] = [tool for tool in old["tools"] if tool["name"] != "read_file"]
            old["tools"].append({"name": "legacy_tool", "revision": 1, "version": "old", "schema_hash": "sha256:" + "1" * 64, "source": "legacy", "availability": "available", "status": "active"})
            old["skills"].append({"skill_id": "legacy-skill", "revision": 1, "version": "1.0.0", "content_hash": "sha256:" + "2" * 64, "metadata_hash": "sha256:" + "3" * 64, "manifest_hash": "sha256:" + "4" * 64, "source": "legacy", "release_ref": "legacy", "release_status": "available", "trust_state": "trusted", "required_toolsets": [], "required_tools": [], "support_files": []})
            old["skills"][0]["required_tools"] = [{"name": "missing-old-tool", "revision": 1}]
            old["agents"][0]["allowed_tool_revisions"] = []
            old["release_hash"] = release_hash(old)
            published.write_text(json.dumps(old), encoding="utf-8")
            candidate.write_text(json.dumps(current), encoding="utf-8")
            result = self.run_diff(published, candidate, output)
            report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertGreater(report["summary"]["changed"], 0)
        self.assertGreater(report["summary"]["added"], 0)
        self.assertGreater(report["summary"]["unresolved_migrations"], 0)
        self.assertTrue(any(item["status"] in {"retired", "unavailable"} for item in report["migration"]["unresolved"]))
        self.assertTrue(report["binding_changes"])


if __name__ == "__main__":
    unittest.main()
