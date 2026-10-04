import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CapabilityVerticalSliceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = json.loads((ROOT / "docs/evidence/hermes-capability-catalog-v1.json").read_text())
        self.snapshot = json.loads((ROOT / "tests/fixtures/capabilities/session-capability-snapshot-v1.json").read_text())
        self.tools = {item["name"]: item for item in self.catalog["tools"]}

    def test_lobby_snapshot_tools_exist_in_harness_catalog(self) -> None:
        allowed = set(self.snapshot["snapshot"]["allowed_tools"])
        self.assertTrue(allowed)
        self.assertTrue(allowed <= self.tools.keys())
        self.assertEqual(set(self.snapshot["agent"]["allowed_tools"]), allowed)
        self.assertNotIn("terminal", allowed)

    def test_vertical_slice_matrix_tools_are_projected(self) -> None:
        required = {"read_file", "search_files", "write_file", "patch", "terminal", "todo_list", "delegate_task", "networkclaw_workspace_read"}
        self.assertTrue(required <= self.tools.keys())
        for name in required:
            self.assertRegex(self.tools[name]["schema_hash"], r"^sha256:[0-9a-f]{64}$")
        memberships = {(row["toolset_name"], row["tool_name"]) for row in self.catalog["memberships"]}
        self.assertTrue(any(tool == "terminal" for _, tool in memberships))
        self.assertTrue(any(tool == "todo_list" for _, tool in memberships))

    def test_projection_command_is_reproducible(self) -> None:
        output = ROOT / ".integration-state" / "evidence" / "t07-capability-catalog-check.json"
        result = subprocess.run([sys.executable, str(ROOT / "tools/project-hermes-catalog.py"), "--output", str(output)], cwd=ROOT, capture_output=True, text=True, check=True)
        report = json.loads(result.stdout)
        self.assertEqual(report["tools"], 101)
        self.assertEqual(report["toolsets"], 64)
        self.assertEqual(report["memberships"], 1499)


if __name__ == "__main__":
    unittest.main()
