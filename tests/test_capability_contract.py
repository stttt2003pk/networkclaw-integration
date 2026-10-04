import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from capability_contract import release_hash, snapshot_hash


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/capabilities/session-capability-snapshot-v1.json"
SCHEMA = ROOT / "schemas/capability-snapshot-v1.schema.json"
RELEASE_FIXTURE = ROOT / "tests/fixtures/capability-release/valid-release-v1.json"
RELEASE_SCHEMA = ROOT / "schemas/capability-release-v1.schema.json"


class CapabilityContractTest(unittest.TestCase):
    def test_fixture_matches_schema_and_hash(self) -> None:
        document = json.loads(FIXTURE.read_text(encoding="utf-8"))
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema).iter_errors(document))
        self.assertEqual(errors, [])
        self.assertEqual(document["snapshot"]["snapshot_hash"], snapshot_hash(document["snapshot"]))

    def test_release_fixture_matches_schema_and_hash(self) -> None:
        document = json.loads(RELEASE_FIXTURE.read_text(encoding="utf-8"))
        schema = json.loads(RELEASE_SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema).iter_errors(document))
        self.assertEqual(errors, [])
        self.assertEqual(document["release_hash"], release_hash(document))

    def test_release_hash_ignores_only_self_field(self) -> None:
        document = json.loads(RELEASE_FIXTURE.read_text(encoding="utf-8"))
        document["release_hash"] = "sha256:" + "f" * 64
        self.assertEqual(release_hash(document), json.loads(RELEASE_FIXTURE.read_text(encoding="utf-8"))["release_hash"])

    def test_invalid_release_fixture_declares_stable_reason(self) -> None:
        invalid = json.loads((ROOT / "tests/fixtures/capability-release/invalid-release-hash.json").read_text(encoding="utf-8"))
        self.assertEqual(invalid["expected_reason_code"], "release_hash_invalid")
        errors = list(Draft202012Validator(json.loads(RELEASE_SCHEMA.read_text(encoding="utf-8"))).iter_errors(invalid["manifest"]))
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
