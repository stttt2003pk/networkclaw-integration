import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/capability-release.py"
HARNESS = ROOT.parent / "networkclaw-harness"
PUBLISHED = ROOT / "tests/fixtures/capability-release/valid-release-v1.json"
DISCOVERY = ROOT / ".integration-state/evidence/capability-discovery-v1.json" if (ROOT / ".integration-state/evidence/capability-discovery-v1.json").is_file() else ROOT / "docs/evidence/capability-discovery-v1.json"


class CapabilityReleaseExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.inputs = Path(cls.temporary.name)
        cls.manifest = cls.inputs / "manifest.json"
        cls.check = cls.inputs / "check.json"
        cls.diff = cls.inputs / "diff.json"
        cls.base_args = ["--operator", "test-operator", "--job-id", "r06-test"]
        for args in (
            ["compile", "--discovery", str(DISCOVERY), "--output", str(cls.manifest), *cls.base_args],
            ["check", "--manifest", str(cls.manifest), "--report", str(cls.check)],
            ["diff", "--published", str(PUBLISHED), "--candidate", str(cls.manifest), "--output", str(cls.diff), *cls.base_args],
        ):
            result = cls.run_tool(*args)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)

    @staticmethod
    def run_tool(*args):
        return subprocess.run([sys.executable, str(TOOL), *args, "--harness", str(HARNESS)], capture_output=True, text=True)

    def export(self, output, *extra):
        return self.run_tool("export", "--manifest", str(self.manifest), "--check", str(self.check), "--diff", str(self.diff), "--published", str(PUBLISHED), "--output", str(output), *self.base_args, *extra)

    def test_relocated_export_verifies_without_workspace_and_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "first", Path(directory) / "second"
            for output in (first, second):
                result = self.export(output)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((first / "checksums.sha256").read_bytes(), (second / "checksums.sha256").read_bytes())
            before = (first / "manifest/capability-release.v1.json").read_bytes()
            first.rename(Path(directory) / "relocated")
            relocated = Path(directory) / "relocated"
            env = dict(os.environ)
            env.pop("PYTHONPATH", None)
            for unused in range(2):
                verified = subprocess.run([sys.executable, "-B", str(relocated / "verify.py")], cwd=directory, env=env, capture_output=True, text=True)
                self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
                report = json.loads(verified.stdout)
                self.assertEqual(report["file_count"], 14)
            self.assertEqual(before, (relocated / "manifest/capability-release.v1.json").read_bytes())
            audit = json.loads((relocated / "audit/export.json").read_text())
            self.assertEqual(audit["operator"], "test-operator")
            self.assertEqual(audit["job_id"], "r06-test")
            self.assertEqual(audit["result"], "exported")
            for name in ("compile", "diff"):
                self.assertEqual(json.loads((relocated / f"audit/{name}.json").read_text())["manifest_hash"], audit["manifest_hash"])

    def test_tamper_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "artifact"
            self.assertEqual(self.export(output).returncode, 0)
            manifest = output / "manifest/capability-release.v1.json"
            original = manifest.read_bytes()
            manifest.write_bytes(original + b" ")
            result = subprocess.run([sys.executable, "-B", str(output / "verify.py")], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)["reason_code"], "checksum_mismatch")
            manifest.unlink()
            external = Path(directory) / "external.json"
            external.write_bytes(original)
            manifest.symlink_to(external)
            result = subprocess.run([sys.executable, "-B", str(output / "verify.py")], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)["reason_code"], "artifact_unsafe_path")

    def test_stale_or_failed_reports_never_produce_an_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            for report_type, change, reason in (
                ("check", {"manifest_hash": "sha256:" + "0" * 64}, "check_report_mismatch"),
                ("diff", {"status": "failed"}, "diff_report_mismatch"),
                ("diff", {"candidate": {"release_id": "cap-other", "release_hash": "sha256:" + "0" * 64}}, "diff_report_mismatch"),
            ):
                report = json.loads((self.check if report_type == "check" else self.diff).read_text())
                report.update(change)
                invalid = Path(directory) / "invalid.json"
                invalid.write_text(json.dumps(report))
                output = Path(directory) / "artifact"
                result = self.export(output, f"--{report_type}", str(invalid))
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stdout)["reason_code"], reason)
                self.assertFalse(output.exists())
                audit = json.loads(output.with_name("artifact.audit.json").read_text())
                self.assertEqual(audit["status"], "failed")
                self.assertEqual(audit["reason_code"], reason)
                self.assertNotIn("published", json.dumps(audit))

    def test_sensitive_data_and_invalid_audits_fail_before_visibility(self):
        with tempfile.TemporaryDirectory() as directory:
            for extra, reason in (
                ({"skill_body": "private Skill instruction"}, "artifact_sensitive_content"),
                ({"api_key": "sk-test-credential"}, "artifact_sensitive_content"),
                ({"notes": "-----BEGIN PRIVATE KEY-----\n" + "a" * 64 + "\n-----END PRIVATE KEY-----"}, "artifact_invalid"),
                ({"notes": "/opt/private-runtime"}, "artifact_absolute_path"),
                ({"manifest_hash": "sha256:" + "0" * 64}, "audit_mismatch"),
            ):
                receipt = json.loads(self.manifest.with_name("manifest.json.audit.json").read_text())
                receipt.update(extra)
                invalid = Path(directory) / "receipt.json"
                invalid.write_text(json.dumps(receipt))
                output = Path(directory) / "artifact"
                result = self.export(output, "--compile-audit", str(invalid))
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)["reason_code"], reason)
                self.assertFalse(output.exists())
                self.assertNotIn("private Skill instruction", result.stdout)
                self.assertNotIn("sk-test-credential", result.stdout)
                self.assertEqual(list(Path(directory).glob("capability-export-*")), [])

    def test_existing_artifact_preserved_and_failure_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "artifact"
            self.assertEqual(self.export(output).returncode, 0)
            before = (output / "checksums.sha256").read_bytes()
            result = self.export(output)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)["reason_code"], "export_output_exists")
            self.assertEqual(before, (output / "checksums.sha256").read_bytes())
            self.assertEqual(json.loads(output.with_name("artifact.audit.json").read_text())["status"], "failed")

    def test_compile_and_diff_failure_audits_are_sanitized(self):
        with tempfile.TemporaryDirectory() as directory:
            compile_output = Path(directory) / "manifest.json"
            result = self.run_tool("compile", "--discovery", str(Path(directory) / "absent.json"), "--output", str(compile_output), *self.base_args)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(compile_output.exists())
            compile_audit = json.loads(compile_output.with_name("manifest.json.audit.json").read_text())
            self.assertEqual(compile_audit["status"], "failed")
            diff_output = Path(directory) / "diff.json"
            result = self.run_tool("diff", "--candidate", str(Path(directory) / "missing.json"), "--output", str(diff_output), *self.base_args)
            self.assertNotEqual(result.returncode, 0)
            diff_audit = json.loads(diff_output.with_name("diff.json.audit.json").read_text())
            self.assertEqual(diff_audit["status"], "failed")
            self.assertEqual(diff_audit["reason_code"], "input_unreadable")
            self.assertNotIn(directory, result.stdout + json.dumps(diff_audit))


if __name__ == "__main__":
    unittest.main()
