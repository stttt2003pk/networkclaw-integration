import hashlib
import importlib.util
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT.parent / "networkclaw-harness"
SPEC = importlib.util.spec_from_file_location("generate_skill_manifest", ROOT / "tools/generate-skill-manifest.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


class SkillManifestContractTests(unittest.TestCase):
    def test_harness_release_manifest_matches_schema_and_is_reproducible(self):
        generated = MODULE.generate(HARNESS)
        recorded = json.loads((ROOT / "docs/evidence/hermes-skill-release-manifest-v1.json").read_text())
        schema = json.loads((ROOT / "schemas/skill-release-manifest-v1.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(generated)), [])
        self.assertEqual(generated, recorded)
        for skill in generated["skills"]:
            unsigned = {key: value for key, value in skill.items() if key != "manifest_hash"}
            self.assertEqual(skill["manifest_hash"], "sha256:" + hashlib.sha256(canonical(unsigned)).hexdigest())

    def test_capability_and_release_skill_schemas_stay_aligned(self):
        capability = json.loads((ROOT / "schemas/capability-snapshot-v1.schema.json").read_text())
        release = json.loads((ROOT / "schemas/skill-release-manifest-v1.schema.json").read_text())
        self.assertEqual(capability["$defs"]["skill"], release["$defs"]["skill"])


if __name__ == "__main__":
    unittest.main()
