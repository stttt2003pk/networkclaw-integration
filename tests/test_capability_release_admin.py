import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location("capability_release_admin", ROOT / "tools/capability-release-admin.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class CapabilityReleaseAdminContractTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / "tests/fixtures/capability-release/valid-release-v1.json").read_text())
        self.schema = json.loads((ROOT / "schemas/capability-release-admin-v1.schema.json").read_text())
        self.validator = Draft202012Validator(self.schema)

    def test_import_request_matches_admin_schema(self):
        request = MODULE.build_request("import", "r07-contract", self.manifest)
        self.assertEqual(list(self.validator.iter_errors(request)), [])

    def test_publish_and_rollback_require_identity_and_cas(self):
        for operation in ("publish", "rollback"):
            request = MODULE.build_request(operation, "r07-contract", release_id=self.manifest["release_id"], release_hash=self.manifest["release_hash"], expected_published_hash=None)
            self.assertEqual(list(self.validator.iter_errors(request)), [])
        with self.assertRaises(ValueError) as error:
            MODULE.build_request("publish", "r07-contract")
        self.assertEqual(str(error.exception), "request_invalid")

    def test_client_does_not_add_import_to_ci_targets(self):
        makefile = (ROOT / "Makefile").read_text()
        ci = (ROOT / "ci/ubuntu-22.04/ci-test.sh").read_text()
        self.assertNotIn("capability-release-admin.py", makefile + ci)

    def test_go_responses_match_schema_and_rejections_do_not_write(self):
        report = json.loads((ROOT / "tests/fixtures/capability-release/admin-contract-v1.json").read_text())
        response_schema = {**self.schema, "oneOf": [{"$ref": "#/$defs/response"}]}
        validator = Draft202012Validator(response_schema)
        self.assertTrue(report["client_round_trip"])
        self.assertTrue(report["compiled_manifest"])
        self.assertEqual(report["storage"], "in_memory_contract_fixture")
        self.assertGreaterEqual(len(report["cases"]), 27)
        names = set()
        for case in report["cases"]:
            names.add(case["name"])
            validator.validate(case["response"])
            receipt = case["response"]["data"]
            if receipt["reason_code"]:
                self.assertEqual(case["write_delta"], 0, case["name"])
                self.assertIn(receipt["result"], {"rejected", "failed"})
            else:
                self.assertEqual(case["response"]["code"], "SUCCESS")
            self.assertNotIn("database detail", json.dumps(case["response"]))
        self.assertTrue({"draft-created", "same-hash-existing", "release-identity-conflict", "stale-revision", "invalid-schema", "unauthorized", "rolled-back"} <= names)

    def test_explicit_execute_guard_and_error_sanitization(self):
        result = subprocess.run([sys.executable, str(ROOT / "tools/capability-release-admin.py"), "import", "--base-url", "http://127.0.0.1:1", "--job-id", "test"], capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout)["reason_code"], "controlled_release_required")
        self.assertNotEqual(result.returncode, 0)
        result = subprocess.run([sys.executable, str(ROOT / "tools/capability-release-admin.py"), "import", "--execute", "--base-url", "http://127.0.0.1:1", "--job-id", "test", "--manifest", "/missing/private-input.json"], capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout)["reason_code"], "release_admin_input_invalid")
        self.assertNotIn("/missing", result.stdout + result.stderr)

    def test_client_blocks_unsafe_endpoint_and_does_not_follow_redirect(self):
        for endpoint in ("http://example.com", "https://user:secret@example.com", "https://example.com?key=secret", "file:///tmp/request"):
            with self.assertRaises(ValueError):
                MODULE.validate_endpoint(endpoint)
        self.assertIsNone(MODULE.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://other.example.com"))
        with patch.object(MODULE, "build_opener") as opener:
            payload = MODULE.build_request("import", "test", {**self.manifest, "release_hash": "sha256:" + "0" * 64})
            with self.assertRaises(ValueError):
                MODULE.send("http://127.0.0.1:1", "fixture-token", payload)
            opener.assert_not_called()

    def test_client_sends_explicit_csrf_origin(self):
        report = json.loads((ROOT / "tests/fixtures/capability-release/admin-contract-v1.json").read_text())
        response = next(case["response"] for case in report["cases"] if case["name"] == "draft-created")
        http_response = MagicMock(status=201)
        http_response.read.return_value = json.dumps(response).encode()
        http_response.__enter__.return_value = http_response
        with patch.object(MODULE, "build_opener") as opener:
            opener.return_value.open.return_value = http_response
            MODULE.send("http://127.0.0.1:8080", "private-token", MODULE.build_request("import", "origin-check", self.manifest), origin="http://127.0.0.1:5174")
            request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.get_header("Origin"), "http://127.0.0.1:5174")

    def test_mirrored_schemas_and_fixtures_match_source_when_available(self):
        source = Path(os.environ.get("NETWORKCLAW_PATH", ROOT.parent / "NetworkClaw"))
        if not (source / "api/lobby/v1").exists():
            self.skipTest("NetworkClaw checkout unavailable; parity is checked by the contract acceptance target")
        self.assertEqual((ROOT / "schemas/capability-release-admin-v1.schema.json").read_bytes(), (source / "api/lobby/v1/capability-release-admin-v1.schema.json").read_bytes())
        self.assertEqual((ROOT / "schemas/capability-release-v1.schema.json").read_bytes(), (source / "api/lobby/v1/capability-release-v1.schema.json").read_bytes())
        self.assertEqual((ROOT / "tests/fixtures/capability-release/valid-release-v1.json").read_bytes(), (source / "api/lobby/v1/testdata/capability-release-v1.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
