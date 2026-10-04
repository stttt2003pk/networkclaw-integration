import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("combination_cleanup_runner", Path(__file__).resolve().parents[1] / "tools/run-combination-matrix.py")
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)


class CombinationCleanupTest(unittest.TestCase):
    def test_scopes_leaks_without_exporting_environment(self):
        normal = subprocess.CompletedProcess([], 0, "1 python networkclaw-harness own\n2 python networkclaw-harness other\n", "")
        environment = subprocess.CompletedProcess([], 0, "1 python NETWORKCLAW_COMBINATION_RUN_ID=current PRIVATE_VALUE=must-not-export\n2 python NETWORKCLAW_COMBINATION_RUN_ID=other\n", "")
        with patch.object(runner.subprocess, "run", side_effect=[normal, environment]):
            report = runner.cleanup_evidence(run_id="current")
        self.assertEqual(report["status"], "leaks_detected")
        self.assertEqual([row["pid"] for row in report["active_gateway_or_provider_processes"]], ["1"])
        self.assertNotIn("must-not-export", str(report))

    def test_foreign_job_is_not_a_leak(self):
        normal = subprocess.CompletedProcess([], 0, "2 python networkclaw-harness other\n", "")
        environment = subprocess.CompletedProcess([], 0, "2 python NETWORKCLAW_COMBINATION_RUN_ID=other\n", "")
        with patch.object(runner.subprocess, "run", side_effect=[normal, environment]):
            report = runner.cleanup_evidence(run_id="current")
        self.assertEqual(report["status"], "clean")


if __name__ == "__main__":
    unittest.main()
