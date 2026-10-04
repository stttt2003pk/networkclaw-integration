import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT.parent / "networkclaw-harness"
GENERATOR = ROOT / "tools/generate-hermes-inventory.py"


class HermesInventoryTest(unittest.TestCase):
    def test_inventory_is_repeatable_and_keeps_dynamic_tools(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            outputs = []
            for index in range(2):
                output = Path(directory) / f"inventory-{index}.json"
                subprocess.run(
                    [sys.executable, str(GENERATOR), "--harness", str(HARNESS), "--output", str(output)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                outputs.append(json.loads(output.read_text(encoding="utf-8")))
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0]["inventory_version"], "hermes.tool-inventory.v1")
        self.assertEqual(outputs[0]["counts"]["unique_tools"], len(outputs[0]["tools"]))
        workspace = next(item for item in outputs[0]["registry_tools"] if item["name"] == "networkclaw_workspace_read")
        self.assertEqual(workspace["kind"], "runtime_injected")
        coding = next(item for item in outputs[0]["static_toolsets"] if item["name"] == "coding")
        self.assertEqual(coding["resolved_tools"], sorted(coding["resolved_tools"]))

    def test_unknown_requested_toolset_is_fail_closed_in_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "inventory.json"
            subprocess.run(
                [sys.executable, str(GENERATOR), "--harness", str(HARNESS), "--output", str(output), "--requested-toolset", "missing-toolset"],
                check=True,
                capture_output=True,
                text=True,
            )
            report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["resolution_errors"], [{"code": "unknown", "toolset": "missing-toolset"}])


if __name__ == "__main__":
    unittest.main()
