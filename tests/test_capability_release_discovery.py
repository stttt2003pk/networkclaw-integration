import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT.parent / "networkclaw-harness"
NETWORKCLAW = Path(os.environ.get("NETWORKCLAW_PATH", ROOT.parent / "NetworkClaw"))
TOOL = ROOT / "tools/capability-release.py"
AGENTS = ROOT / "tests/fixtures/capability-release/agent-discovery-v1.json"


class CapabilityReleaseDiscoveryTest(unittest.TestCase):
    def test_no_agent_profiles_produces_an_explicit_empty_collection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agents = Path(directory) / "agents.json"
            agents.write_text(json.dumps({"schema_version": "networkclaw.agent-revision-export.v1", "profiles": []}))
            output = Path(directory) / "discovery.json"
            result = self.run_discovery(agents, output)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(output.read_text())
            self.assertEqual(report["agents"], [])
            self.assertEqual(len(report["tools"]), 101)

    def run_discovery(self, agents: Path, output: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOL), "discover", "--harness", str(HARNESS), "--networkclaw", str(NETWORKCLAW), "--agents", str(agents), "--output", str(output)],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_discovery_is_deterministic_and_resolves_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first_path = Path(directory) / "first.json"
            second_path = Path(directory) / "second.json"
            first = self.run_discovery(AGENTS, first_path)
            second = self.run_discovery(AGENTS, second_path)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            first_document = json.loads(first_path.read_text(encoding="utf-8"))
            second_document = json.loads(second_path.read_text(encoding="utf-8"))
        self.assertEqual(first_document, second_document)
        self.assertEqual(first_document["status"], "passed")
        self.assertEqual(len(first_document["toolsets"]), 64)
        self.assertEqual(len(first_document["tools"]), 101)
        self.assertEqual(len(first_document["skills"]), 59)
        self.assertEqual(len(first_document["agents"]), 1)
        self.assertEqual(first_document["inputs"]["skill_manifest_version"], "skill-release.v1")
        agent_export = json.loads(AGENTS.read_text(encoding="utf-8"))
        canonical = json.dumps(agent_export, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.assertEqual(first_document["inputs"]["agent_export_hash"], "sha256:" + hashlib.sha256(canonical).hexdigest())
        self.assertEqual(first_document["hermes"]["vendor_file_count"], 1104)
        for key in ("vendor_tree_sha256", "vendor_manifest_sha256"):
            self.assertRegex(first_document["hermes"][key], r"^[0-9a-f]{64}$")
        self.assertEqual(first_document["catalog"]["catalog_hash"][:7], "sha256:")
        self.assertEqual(first_document["agents"][0]["requested_toolsets"], [{"name": "coding", "revision": 1}])
        self.assertEqual(first_document["agents"][0]["allowed_tool_revisions"], [{"name": "read_file", "revision": 1}, {"name": "search_files", "revision": 1}])
        self.assertEqual(first_document["agents"][0]["denied_tools"], ["terminal"])
        tools = {tool["name"]: tool for tool in first_document["tools"]}
        for toolset in first_document["toolsets"]:
            self.assertTrue(toolset["source"])
            for member in toolset["member_tool_revisions"]:
                self.assertEqual(member["revision"], tools[member["name"]]["revision"])
        for skill in first_document["skills"]:
            self.assertTrue(skill["source"])
            for key in ("content_hash", "metadata_hash", "manifest_hash"):
                self.assertRegex(skill[key], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(first_document["skills"][0]["required_toolsets"], [])
        skills = {skill["skill_id"]: skill for skill in first_document["skills"]}
        self.assertEqual(skills["maps"]["required_toolsets"], [{"name": "terminal", "revision": 1}])
        self.assertEqual(skills["sdlc-review"]["required_toolsets"], [{"name": "kanban", "revision": 1}])

    def test_unknown_agent_dependencies_fail_closed(self) -> None:
        cases = (
            ("requested_toolsets", ["missing-toolset"], "unknown_toolset"),
            ("tools", [{"tool_name": "missing-tool", "tool_revision": 1, "decision": "allowed"}], "unknown_tool"),
            ("skills", [{"skill_id": "missing-skill", "skill_version": "1.0.0", "mode": "auto_load"}], "unknown_skill"),
        )
        for field, value, reason in cases:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                invalid = Path(directory) / "invalid.json"
                document = json.loads(AGENTS.read_text(encoding="utf-8"))
                document["profiles"][0]["revisions"][0][field] = value
                invalid.write_text(json.dumps(document), encoding="utf-8")
                output = Path(directory) / "discovery.json"
                result = self.run_discovery(invalid, output)
                report = json.loads(output.read_text(encoding="utf-8"))
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(report["status"], "failed")
                self.assertEqual(report["reason_code"], reason)
                self.assertEqual(report["resolution_errors"][0]["reason"], reason)


if __name__ == "__main__":
    unittest.main()
