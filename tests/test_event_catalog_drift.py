from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "tools/check_event_catalog.py"
CATALOG = ROOT / "schemas/events/event-catalog-v1.json"
REPORT = ROOT / "schemas/events/event-catalog-consumer-report-v1.json"


class EventCatalogDriftTests(unittest.TestCase):
    def run_checker(self, catalog: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECKER), "--catalog", str(catalog)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_current_catalog_matches_harness_transport_and_consumers(self) -> None:
        result = self.run_checker(CATALOG)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["drift"]["status"], "ok")
        self.assertEqual(report["canonical_event_count"], 56)
        self.assertEqual(report["consumers"]["go_lobby"]["unknown_bucket"], "opaque canonical_event")
        self.assertIn("finalizer.fallback", report["consumers"]["web2"]["unhandled_by_explicit_projection"])
        self.assertEqual(report, json.loads(REPORT.read_text(encoding="utf-8")))

    def test_added_or_removed_catalog_event_fails_the_gate(self) -> None:
        original = json.loads(CATALOG.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "catalog.json"
            added = json.loads(json.dumps(original))
            added["process_extensions"].append({"name": "drift.added"})
            path.write_text(json.dumps(added), encoding="utf-8")
            self.assertNotEqual(self.run_checker(path).returncode, 0)

            removed = json.loads(json.dumps(original))
            removed["baseline_events"].pop()
            path.write_text(json.dumps(removed), encoding="utf-8")
            self.assertNotEqual(self.run_checker(path).returncode, 0)

    def test_checker_uses_resolved_checkout_instead_of_case_specific_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            checkout = Path(temp_dir) / 'renamed-go-source'
            checkout.mkdir()
            (checkout / 'go.mod').write_text('module contract-probe\n', encoding='utf-8')
            result = subprocess.run(
                [sys.executable, str(CHECKER)], cwd=ROOT, text=True, capture_output=True,
                env=os.environ | {'NETWORKCLAW_PATH': str(checkout)}, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('renamed-go-source', result.stderr)



if __name__ == "__main__":
    unittest.main()
