import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("project_catalog", ROOT / "tools/project-hermes-catalog.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class CapabilityCatalogProjectionTests(unittest.TestCase):
    def test_inventory_projects_deterministically_and_deduplicates(self):
        inventory = json.loads((ROOT / "docs/evidence/hermes-tool-inventory.json").read_text())
        first = MODULE.project(inventory)
        second = MODULE.project(json.loads(json.dumps(inventory)))
        self.assertEqual(first, second)
        self.assertEqual(len({item["name"] for item in first["tools"]}), len(first["tools"]))
        self.assertEqual(len({(item["toolset_name"], item["tool_name"]) for item in first["memberships"]}), len(first["memberships"]))
        self.assertEqual(first["catalog"]["status"], "published")

    def test_unavailable_and_dynamic_provenance_are_preserved(self):
        inventory = {"inventory_version": "test", "registered_toolsets": ["mcp-demo"], "static_toolsets": [], "registry_tools": [{"name": "dynamic", "toolset": "mcp-demo", "kind": "mcp", "source": "mcp.server", "availability": "unavailable", "check_capability": {"has_check_fn": True, "requires_env": ["TOKEN"]}, "availability_reason": "check_failed"}], "tools": [{"name": "dynamic", "registry_toolset": "mcp-demo", "registry_kind": "mcp", "schema_hash": "sha256:" + "1" * 64, "availability": "unavailable"}]}
        output = MODULE.project(inventory)
        self.assertEqual(output["tools"][0]["kind"], "mcp")
        self.assertEqual(output["tools"][0]["availability_reason"], "check_failed")
        self.assertEqual(output["tools"][0]["status"], "retired")

    def test_drift_rejects_added_tool_and_schema_change(self):
        inventory = json.loads((ROOT / "docs/evidence/hermes-tool-inventory.json").read_text())
        catalog = MODULE.project(inventory)
        self.assertEqual(MODULE.drift_errors(inventory, catalog), [])
        catalog["tools"][0]["schema_hash"] = "sha256:" + "f" * 64
        self.assertIn("tools", MODULE.drift_errors(inventory, catalog))


if __name__ == "__main__":
    unittest.main()
