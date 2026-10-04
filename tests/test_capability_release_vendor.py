import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT.parent / "networkclaw-harness"
TOOL = ROOT / "tools/capability-release.py"


class CapabilityReleaseVendorTest(unittest.TestCase):
    def test_vendor_gate_and_tamper_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "vendor-gate.json"
            result = subprocess.run(
                [sys.executable, str(TOOL), "vendor-check", "--harness", str(HARNESS), "--tamper-fixture", "--report", str(report)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            document = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(document["status"], "passed")
        self.assertEqual(document["hermes"]["vendor_file_count"], 1104)
        self.assertEqual(document["inventory"]["counts"]["registry_tools"], 101)
        self.assertEqual(document["inventory"]["counts"]["registered_toolsets"], 34)
        self.assertEqual(document["inventory"]["counts"]["static_toolsets"], 60)
        self.assertEqual(len(document["inventory"]["registry_tool_sources"]), 101)
        self.assertEqual(document["tamper_fixture"], {
            "changed_file_rejected": True,
            "unexpected_file_rejected": True,
            "missing_file_rejected": True,
        })
        self.assertEqual(document["skills"]["skill_count"], 59)
        skill_ids = {skill["skill_id"] for skill in document["skills"]["skills"]}
        self.assertIn("workspace-inspection", skill_ids)
        self.assertIn("maps", skill_ids)
        self.assertIn("sdlc-review", skill_ids)
        self.assertIn("web_search", document["legacy_tool_exclusions"])

    def test_missing_vendor_fails_closed_with_stable_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "missing.json"
            result = subprocess.run(
                [sys.executable, str(TOOL), "vendor-check", "--harness", str(Path(directory) / "missing"), "--report", str(report)],
                check=False,
                capture_output=True,
                text=True,
            )
            document = json.loads(report.read_text(encoding="utf-8"))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(document["reason_code"], "vendor_missing")


if __name__ == "__main__":
    unittest.main()
