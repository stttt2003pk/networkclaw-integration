from pathlib import Path
import json
import runpy
import tempfile
import unittest


MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "ci/ubuntu-22.04/build-artifacts.py"))


class PreparedImageContextTests(unittest.TestCase):
    def test_prepared_context_is_bound_to_bundle_and_every_payload_file(self):
        with tempfile.TemporaryDirectory() as directory:
            context = Path(directory) / "context"
            context.mkdir()
            binary = context / "lobby"
            binary.write_bytes(b"compiled-on-ubuntu-fixture")
            identity = {"bundle_sha256": "bundle-a", "builder": {"os": "ubuntu", "version": "22.04"},
                        "files": MODULE["context_files"](context)}
            context.with_suffix(".identity.json").write_text(json.dumps(identity))
            self.assertEqual(MODULE["load_prepared_context"](context, "bundle-a"), identity["builder"])
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                MODULE["load_prepared_context"](context, "bundle-b")
            binary.write_bytes(b"changed-binary")
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                MODULE["load_prepared_context"](context, "bundle-a")
            binary.write_bytes(b"compiled-on-ubuntu-fixture")
            (context / "untracked-secret").write_text("extra-file")
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                MODULE["load_prepared_context"](context, "bundle-a")
