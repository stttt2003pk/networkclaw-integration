"""R-11 failures and revision changes against real Harness discovery."""

import copy
import os
import runpy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
release = runpy.run_path(str(ROOT / "tools/capability-release.py"))
HARNESS = Path(os.environ.get("HARNESS_PATH", ROOT.parent / "networkclaw-harness"))
NETWORKCLAW = Path(os.environ.get("NETWORKCLAW_PATH", ROOT.parent / "NetworkClaw"))


class ReleaseAcceptanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate = release["vendor_check"](HARNESS)
        cls.discovery = release["discovery"](HARNESS, NETWORKCLAW, ROOT / "tests/fixtures/capability-release/agent-discovery-v1.json")
        cls.manifest = cls.compile(cls.discovery)

    @classmethod
    def compile(cls, discovery):
        return release["compile_release"](discovery, cls.gate, release_id="cap-r11", target_os="ubuntu", target_version="22.04", architecture="amd64", session_platform="linux-amd64")

    def test_fixed_inputs_are_deterministic_and_traceable(self):
        again = release["discovery"](HARNESS, NETWORKCLAW, ROOT / "tests/fixtures/capability-release/agent-discovery-v1.json")
        self.assertEqual(self.discovery, again)
        self.assertEqual(self.manifest, self.compile(again))
        for collection, key in (("toolsets", "name"), ("tools", "name"), ("skills", "skill_id"), ("agents", "agent_id")):
            self.assertEqual(self.manifest[collection], sorted(self.manifest[collection], key=lambda item: (item[key], item["revision"])))
        report = release["check_release"](self.manifest, HARNESS)
        self.assertEqual(report["status"], "passed", report)
        self.assertTrue(all(report["checks"].values()))
        registry = self.gate["inventory"]["registry_tool_sources"]
        self.assertTrue(registry)
        for tool in self.manifest["tools"]:
            self.assertTrue(tool["source"])
            self.assertRegex(tool["schema_hash"], r"^sha256:[0-9a-f]{64}$")
        for skill in self.manifest["skills"]:
            self.assertTrue(skill["source"])
            for key in ("content_hash", "metadata_hash", "manifest_hash"):
                self.assertRegex(skill[key], r"^sha256:[0-9a-f]{64}$")

    def test_missing_dependencies_and_untrusted_skills_fail_closed(self):
        mutations = (
            ("tools", lambda m: m["tools"].clear(), "stale_revision"),
            ("toolsets", lambda m: m["toolsets"].clear(), "dependency_unavailable"),
            ("skills", lambda m: m["skills"].clear(), "stale_revision"),
            ("agent", lambda m: m["agents"][0]["allowed_tool_revisions"].append({"name": "absent", "revision": 1}), "stale_revision"),
            ("trust", lambda m: m["skills"][0].update(trust_state="quarantined"), "dependency_unavailable"),
        )
        for label, mutate, reason in mutations:
            with self.subTest(label=label):
                manifest = copy.deepcopy(self.manifest)
                mutate(manifest)
                manifest["release_hash"] = release["release_hash"](manifest)
                report = release["check_release"](manifest, HARNESS)
                self.assertEqual(report["status"], "failed", report)
                self.assertIn(reason, {error["reason"] for error in report["errors"]}, report)

    def test_toolset_and_agent_binding_changes_are_visible(self):
        changed = copy.deepcopy(self.manifest)
        changed["toolsets"][0]["member_tool_revisions"] = [{"name": "read_file", "revision": 1}]
        changed["agents"][0]["allowed_tool_revisions"] = []
        changed["agents"][0]["skill_revisions"] = []
        changed["release_hash"] = release["release_hash"](changed)
        diff = release["diff_releases"](self.manifest, changed)
        self.assertTrue(diff["changes"]["toolsets"]["changed"])
        self.assertEqual(set(diff["binding_changes"][0]["fields"]), {"allowed_tool_revisions", "skill_revisions"})
        self.assertNotEqual(changed["release_hash"], self.manifest["release_hash"])


if __name__ == "__main__":
    unittest.main()
