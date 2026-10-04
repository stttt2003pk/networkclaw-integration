import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT.parent / "networkclaw-harness"
TOOL = ROOT / "tools/capability-release.py"
DISCOVERY = ROOT / "docs/evidence/capability-discovery-v1.json"
if (ROOT / ".integration-state/evidence/capability-discovery-v1.json").is_file():
    DISCOVERY = ROOT / ".integration-state/evidence/capability-discovery-v1.json"


class CapabilityReleaseCompileTest(unittest.TestCase):
    def compile(self, discovery: Path, output: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOL), "compile", "--discovery", str(discovery), "--harness", str(HARNESS), "--release-id", "cap-test-001", "--output", str(output)],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_compile_is_deterministic_and_emits_release_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first_path = Path(directory) / "first.json"
            second_path = Path(directory) / "second.json"
            first = self.compile(DISCOVERY, first_path)
            second = self.compile(DISCOVERY, second_path)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            first_document = json.loads(first_path.read_text(encoding="utf-8"))
            second_document = json.loads(second_path.read_text(encoding="utf-8"))
        self.assertEqual(first_document, second_document)
        self.assertTrue(first_document["release_hash"].startswith("sha256:"))
        self.assertEqual(len(first_document["toolsets"]), 64)
        self.assertEqual(len(first_document["tools"]), 101)
        self.assertEqual(len(first_document["skills"]), 59)
        self.assertEqual(len(first_document["agents"]), len(json.loads(DISCOVERY.read_text())["agents"]))
        self.assertEqual(first_document["catalog"]["status"], "draft")

    def test_compile_preserves_explicit_empty_agents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            discovery = Path(directory) / "discovery.json"
            document = json.loads(DISCOVERY.read_text())
            document["agents"] = []
            discovery.write_text(json.dumps(document))
            output = Path(directory) / "release.json"
            result = self.compile(discovery, output)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            release = json.loads(output.read_text())
            self.assertEqual(release["agents"], [])
            self.assertEqual(len(release["tools"]), 101)

    def test_failed_discovery_does_not_emit_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "invalid.json"
            document = json.loads(DISCOVERY.read_text(encoding="utf-8"))
            document["status"] = "failed"
            document["reason_code"] = "unknown_toolset"
            invalid.write_text(json.dumps(document), encoding="utf-8")
            output = Path(directory) / "release.json"
            result = self.compile(invalid, output)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["reason_code"], "unknown_toolset")
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
