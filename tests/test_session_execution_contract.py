import copy
import json
import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from session_execution import snapshot_hash, validate, validate_mirrors

FIXTURES = Path(__file__).parent / "fixtures/session-execution"


class SessionExecutionContractTest(unittest.TestCase):
    def test_profile_independent_parent_child_and_empty(self):
        for path in FIXTURES.glob("*.json"):
            with self.subTest(path=path.name):
                snapshot = json.loads(path.read_text())
                validate(snapshot, session_id=snapshot["session_id"])
                self.assertNotIn("profile_source", snapshot)

    def test_negative_authorization_and_private_input(self):
        original = json.loads((FIXTURES / "parent-no-profile.json").read_text())
        cases = [
            ("missing_tools", lambda s: s.pop("tools"), "execution_snapshot_invalid"),
            ("null_tools", lambda s: s.update(tools=None), "execution_snapshot_invalid"),
            ("version", lambda s: s.update(contract_version="session-execution.v2"), "execution_contract_unsupported"),
            ("private_model", lambda s: s.update(model_execution={"api_key": "fixture-only"}), "execution_snapshot_invalid"),
            ("run", lambda s: s.update(run_id="r"), "execution_snapshot_invalid"),
            ("empty_grant", lambda s: s.update(tools=[]), "execution_dependency_denied"),
            ("delegation", lambda s: s["policy"]["delegation_policy"].update(max_depth=0), "execution_delegation_denied"),
            ("duplicate", lambda s: s["tools"].append(dict(s["tools"][0], revision=2)), "execution_asset_duplicate"),
            ("hash_shape", lambda s: s["tools"][0].update(schema_hash="latest"), "execution_snapshot_invalid"),
        ]
        for name, mutate, reason in cases:
            with self.subTest(case=name):
                snapshot = copy.deepcopy(original)
                mutate(snapshot)
                snapshot["snapshot_hash"] = snapshot_hash(snapshot)
                with self.assertRaisesRegex(ValueError, "^" + reason + "$"):
                    validate(snapshot)
        original["policy"]["system_prompt"] += "tampered"
        with self.assertRaisesRegex(ValueError, "^execution_snapshot_hash_invalid$"):
            validate(original)

    def test_identity_and_unicode_hash(self):
        snapshot = json.loads((FIXTURES / "parent-no-profile.json").read_text())
        with self.assertRaisesRegex(ValueError, "^execution_snapshot_identity_invalid$"):
            validate(snapshot, session_id="other")
        self.assertEqual(snapshot_hash(snapshot), snapshot["snapshot_hash"])

    def test_deployed_contract_drift_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            integration, go, harness = root / 'integration', root / 'go', root / 'harness'
            schema_dirs = [integration / 'schemas', go / 'api/chatrtmgr/v1', harness / 'src/networkclaw_harness/protocol/schema/v1']
            fixture_dirs = [integration / 'tests/fixtures/session-execution', go / 'internal/shared/sessionexecution/testdata', harness / 'tests/fixtures/session-execution']
            schema = (FIXTURES.parents[2] / 'schemas/session-execution-v1.schema.json').read_bytes()
            for path in schema_dirs:
                path.mkdir(parents=True)
                (path / 'session-execution-v1.schema.json').write_bytes(schema)
            for path in fixture_dirs:
                path.mkdir(parents=True)
                for fixture in FIXTURES.glob('*.json'):
                    (path / fixture.name).write_bytes(fixture.read_bytes())
            validate_mirrors(integration, go, harness)
            for path in [schema_dirs[1] / 'session-execution-v1.schema.json', fixture_dirs[2] / 'explicit-empty.json']:
                original = path.read_bytes()
                path.write_bytes(original + b'\n')
                with self.assertRaisesRegex(ValueError, '^execution_contract_mirror_drift:'):
                    validate_mirrors(integration, go, harness)
                path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
