from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
import tempfile
import tarfile


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "tools" / "build-bundle.py"
VERIFIER = ROOT / "tools" / "verify-bundle.py"


class BundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.networkclaw = self.base / "networkclaw"
        self.harness = self.base / "harness"
        self.integration = self.base / "integration"
        for root in (self.networkclaw, self.harness, self.integration):
            root.mkdir()
        (self.networkclaw / "go.mod").write_text("module example\n", encoding="utf-8")
        (self.harness / "pyproject.toml").write_text("[project]\nname='harness'\n", encoding="utf-8")
        (self.integration / "pyproject.toml").write_text("[project]\nname='integration'\n", encoding="utf-8")
        schema_dir = self.integration / "schemas"
        schema_dir.mkdir()
        shutil.copyfile(ROOT / "schemas" / "bundle-manifest.schema.json", schema_dir / "bundle-manifest.schema.json")
        vendor = self.harness / "vendor" / "hermes"
        vendor.mkdir(parents=True)
        (vendor / "runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
        upstream = self.harness / "upstream"
        upstream.mkdir()
        patch_dir = upstream / "patches"
        patch_dir.mkdir()
        patch_data = b"diff --git a/example.py b/example.py\n"
        (patch_dir / "0001-local.patch").write_bytes(patch_data)
        (upstream / "hermes-source.json").write_text(
            json.dumps({"commit": "a" * 40, "upstream_repository": "https://example.invalid/hermes.git"}),
            encoding="utf-8",
        )
        (upstream / "hermes-vendor-manifest.json").write_text(
            json.dumps({"patches": [{"name": "0001-local.patch", "sha256": hashlib.sha256(patch_data).hexdigest()}]}),
            encoding="utf-8",
        )
        harness_scripts = self.harness / "scripts"
        harness_scripts.mkdir()
        (harness_scripts / "verify-hermes-vendor.py").write_text(
            "raise SystemExit(0)\n", encoding="utf-8"
        )
        self.output = self.base / "networkclaw-bundle.tar.gz"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def build(self, output: Path | None = None, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(BUILDER), "--networkclaw", str(self.networkclaw),
             "--harness", str(self.harness), "--integration", str(self.integration),
             "--output", str(output or self.output), *extra],
            text=True, capture_output=True, check=False,
        )

    def test_gitless_sources_build_deterministically_and_verify(self) -> None:
        first = self.build()
        self.assertEqual(first.returncode, 0, first.stderr)
        first_hash = hashlib.sha256(self.output.read_bytes()).hexdigest()
        second_output = self.base / "second.tar.gz"
        second = self.build(second_output)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first_hash, hashlib.sha256(second_output.read_bytes()).hexdigest())

        verified = subprocess.run(
            [sys.executable, str(VERIFIER), str(self.output)],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(verified.returncode, 0, verified.stderr)
        result = json.loads(verified.stdout)
        self.assertTrue(result["customized"])
        self.assertIsNone(result["sources"]["networkclaw"]["commit"])
        self.assertEqual(result["sources"]["harness"]["path"], "networkclaw-harness")

    def test_generated_code_index_is_excluded_from_bundle(self) -> None:
        index = self.harness / ".codebase-memory"
        index.mkdir()
        (index / "graph.db.zst").write_bytes(b"generated index")
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        with tarfile.open(self.output, "r:gz") as archive:
            self.assertNotIn(
                "networkclaw-bundle/networkclaw-harness/.codebase-memory/graph.db.zst",
                archive.getnames(),
            )

    def test_dirty_git_source_is_marked_customized(self) -> None:
        for root in (self.networkclaw, self.harness, self.integration):
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c",
                            "user.email=test@example.invalid", "commit", "-qm", "baseline"], check=True)
        (self.networkclaw / "change.go").write_text("package main\n", encoding="utf-8")
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(result.stdout)["manifest"]
        self.assertTrue(manifest["customized"])
        identity = manifest["sources"]["networkclaw"]
        self.assertTrue(identity["dirty"])
        self.assertRegex(identity["diff_sha256"], r"^[0-9a-f]{64}$")
        sys.path.insert(0, str(ROOT / "tools"))
        try:
            from resolve_sources import source_metadata
            resolved = source_metadata(self.networkclaw, "go.mod")
        finally:
            sys.path.pop(0)
        self.assertEqual(identity["diff_sha256"], resolved["diff_sha256"])

    def test_excluded_untracked_file_does_not_change_diff_hash(self) -> None:
        root = self.networkclaw
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c",
                        "user.email=test@example.invalid", "commit", "-qm", "baseline"], check=True)
        (root / "change.go").write_text("package main\n", encoding="utf-8")
        sys.path.insert(0, str(ROOT / "tools"))
        try:
            from source_tree import git_diff_hash
            before = git_diff_hash(root)
            generated = root / ".codebase-memory"
            generated.mkdir()
            (generated / "index.db").write_text("generated", encoding="utf-8")
            after = git_diff_hash(root)
        finally:
            sys.path.pop(0)
        self.assertEqual(before, after)

    def test_secret_file_is_rejected(self) -> None:
        (self.integration / ".env.production").write_text("TOKEN=not-a-real-secret\n", encoding="utf-8")
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(".env.production", result.stdout)

    def test_embedded_credential_is_rejected(self) -> None:
        assignment = "api_" + "key" + " = \"" + "123456789012345678901234" + "\"\n"
        (self.integration / "config.py").write_text(
            assignment, encoding="utf-8"
        )
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("possible credential", result.stderr)

    def test_nul_separated_text_is_still_scanned(self) -> None:
        secret = ("api_" + "key = \"" + "123456789012345678901234" + "\"").encode()
        (self.integration / "encoded.bin").write_bytes(b"\0".join((b"prefix", secret, b"suffix")))
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("possible credential", result.stderr)

    def test_generated_manifest_metadata_is_scanned(self) -> None:
        source_path = self.harness / "upstream" / "hermes-source.json"
        source = json.loads(source_path.read_text(encoding="utf-8"))
        source["upstream_repository"] = "/" + "Users/private-user/hermes.git"
        source_path.write_text(json.dumps(source), encoding="utf-8")
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("local absolute home path", result.stderr)

    def test_complete_pem_private_key_is_rejected(self) -> None:
        (self.integration / "private.pem").write_text(
            "-----BEGIN PRIVATE KEY-----\n" + "A" * 64 + "\n-----END PRIVATE KEY-----\n",
            encoding="ascii",
        )
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("possible credential", result.stderr)

    def test_environment_variable_reference_is_not_a_credential(self) -> None:
        (self.integration / "config.py").write_text(
            "api_" + "key = process.env.OPENAI_API_KEY\n", encoding="utf-8"
        )
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unquoted_placeholder_identifier_is_not_a_credential(self) -> None:
        (self.integration / "config.py").write_text(
            "api_" + "key = ACTUAL_LOCAL_NOAUTH_PLACEHOLDER\n", encoding="utf-8"
        )
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_home_path_is_rejected(self) -> None:
        (self.integration / "local.txt").write_text(
            f"machine path: {Path.home()}/private/config\n", encoding="utf-8"
        )
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("local absolute home path", result.stderr)

    def test_home_dot_directory_is_not_treated_as_username(self) -> None:
        (self.integration / "example.md").write_text(
            "Hermes internal path: /home/.hermes/profiles/example\n", encoding="utf-8"
        )
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_hermes_patch_must_match_manifest(self) -> None:
        patches = self.harness / "upstream" / "patches"
        patches.mkdir(exist_ok=True)
        (patches / "0001-example.patch").write_text("diff --git a/a b/a\n", encoding="utf-8")
        manifest_path = self.harness / "upstream" / "hermes-vendor-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["patches"] = [{"name": "0001-example.patch", "sha256": "0" * 64}]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("patch files do not match", result.stderr)

    def test_release_requires_matching_clean_git_sources(self) -> None:
        for root in (self.networkclaw, self.harness, self.integration):
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c",
                            "user.email=test@example.invalid", "commit", "-qm", "baseline"], check=True)

        sys.path.insert(0, str(ROOT / "tools"))
        try:
            from source_tree import tree_hash
        finally:
            sys.path.pop(0)
        lock = self.base / "release-lock.yaml"
        lock_data = ["schema_version: 1", "mode: checkout"]
        for name, root in (("networkclaw", self.networkclaw), ("harness", self.harness), ("integration", self.integration)):
            commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
            lock_data.extend((f"{name}:", "  repository: https://example.invalid/source.git", f"  commit: {commit}", f"  tree_sha256: {tree_hash(root)}"))
        lock.write_text("\n".join(lock_data) + "\n", encoding="utf-8")
        released = self.build(self.output, "--release", "--sources-lock", str(lock))
        self.assertEqual(released.returncode, 0, released.stderr)
        manifest = json.loads(released.stdout)["manifest"]
        self.assertFalse(manifest["customized"])
        self.assertTrue(all(not source["customized"] for source in manifest["sources"].values()))

        (self.networkclaw / "change.go").write_text("package main\n", encoding="utf-8")
        rejected = self.build(self.base / "rejected.tar.gz", "--release", "--sources-lock", str(lock))
        self.assertNotEqual(rejected.returncode, 0)

    def test_release_is_blocked_when_harness_vendor_verifier_fails(self) -> None:
        for root in (self.networkclaw, self.harness, self.integration):
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c",
                            "user.email=test@example.invalid", "commit", "-qm", "baseline"], check=True)

        sys.path.insert(0, str(ROOT / "tools"))
        try:
            from source_tree import tree_hash
        finally:
            sys.path.pop(0)
        lock = self.base / "release-lock.yaml"
        lock_data = ["schema_version: 1", "mode: checkout"]
        for name, root in (("networkclaw", self.networkclaw), ("harness", self.harness), ("integration", self.integration)):
            commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
            lock_data.extend((f"{name}:", "  repository: https://example.invalid/source.git", f"  commit: {commit}", f"  tree_sha256: {tree_hash(root)}"))
        lock.write_text("\n".join(lock_data) + "\n", encoding="utf-8")
        (self.harness / "scripts/verify-hermes-vendor.py").write_text(
            "raise SystemExit('injected vendor verification failure')\n", encoding="utf-8"
        )
        rejected_output = self.base / "blocked-release.tar.gz"
        rejected = self.build(rejected_output, "--release", "--sources-lock", str(lock))
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("vendor verification failed", rejected.stderr)
        self.assertFalse(rejected_output.exists())

    def test_payload_hash_is_checked_after_sidecar_is_updated(self) -> None:
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        rewritten = self.base / "rewritten.tar.gz"
        with tarfile.open(self.output, "r:gz") as source, tarfile.open(rewritten, "w:gz") as target:
            for member in source.getmembers():
                if member.name.endswith("networkclaw/go.mod"):
                    member.size = len(b"tampered")
                    target.addfile(member, io.BytesIO(b"tampered"))
                else:
                    stream = source.extractfile(member) if member.isfile() else None
                    target.addfile(member, stream)
        digest = hashlib.sha256(rewritten.read_bytes()).hexdigest()
        rewritten.with_suffix(rewritten.suffix + ".sha256").write_text(
            f"{digest}  {rewritten.name}\n", encoding="ascii"
        )
        verified = subprocess.run(
            [sys.executable, str(VERIFIER), str(rewritten)], text=True, capture_output=True, check=False
        )
        self.assertNotEqual(verified.returncode, 0)
        self.assertIn("payload checksum mismatch", verified.stderr)

    def test_manifest_source_path_must_locate_the_archived_source(self) -> None:
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        rewritten = self.base / "wrong-source-path.tar.gz"
        with tarfile.open(self.output, "r:gz") as source, tarfile.open(rewritten, "w:gz") as target:
            for member in source.getmembers():
                if member.name == "networkclaw-bundle/manifest/bundle-manifest.json":
                    manifest = json.load(source.extractfile(member))
                    manifest["sources"]["harness"]["path"] = "networkclaw"
                    data = json.dumps(manifest).encode()
                    member.size = len(data)
                    target.addfile(member, io.BytesIO(data))
                else:
                    target.addfile(member, source.extractfile(member) if member.isfile() else None)
        digest = hashlib.sha256(rewritten.read_bytes()).hexdigest()
        rewritten.with_suffix(rewritten.suffix + ".sha256").write_text(f"{digest}  {rewritten.name}\n")
        verified = subprocess.run([sys.executable, str(VERIFIER), str(rewritten)], text=True, capture_output=True)
        self.assertNotEqual(verified.returncode, 0)
        self.assertIn("bundle source path does not locate harness", verified.stderr)

    def test_manifest_metadata_is_scanned_by_verifier(self) -> None:
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        rewritten = self.base / "manifest-path.tar.gz"
        with tarfile.open(self.output, "r:gz") as source, tarfile.open(rewritten, "w:gz") as target:
            for member in source.getmembers():
                if member.name.endswith("manifest/bundle-manifest.json"):
                    manifest = json.load(source.extractfile(member))
                    manifest["hermes"]["upstream_repository"] = "/" + "Users/private-user/hermes.git"
                    data = json.dumps(manifest, sort_keys=True).encode() + b"\n"
                    member.size = len(data)
                    target.addfile(member, io.BytesIO(data))
                else:
                    stream = source.extractfile(member) if member.isfile() else None
                    target.addfile(member, stream)
        digest = hashlib.sha256(rewritten.read_bytes()).hexdigest()
        rewritten.with_suffix(rewritten.suffix + ".sha256").write_text(
            f"{digest}  {rewritten.name}\n", encoding="ascii"
        )
        verified = subprocess.run(
            [sys.executable, str(VERIFIER), str(rewritten)], text=True, capture_output=True, check=False
        )
        self.assertNotEqual(verified.returncode, 0)
        self.assertIn("absolute home path", verified.stderr)

    def test_detached_signature_is_verified(self) -> None:
        if shutil.which("openssl") is None:
            self.skipTest("OpenSSL is unavailable")
        private_key = self.base / "private.pem"
        public_key = self.base / "public.pem"
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048",
             "-out", str(private_key)], check=True, capture_output=True,
        )
        subprocess.run(
            ["openssl", "pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)],
            check=True, capture_output=True,
        )
        built = self.build(self.output, "--signing-key", str(private_key))
        self.assertEqual(built.returncode, 0, built.stderr)
        verified = subprocess.run(
            [sys.executable, str(VERIFIER), str(self.output), "--public-key", str(public_key)],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertTrue(json.loads(verified.stdout)["signature_verified"])

    def test_modified_archive_fails_checksum_verification(self) -> None:
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        with self.output.open("ab") as archive:
            archive.write(b"tampered")
        verified = subprocess.run(
            [sys.executable, str(VERIFIER), str(self.output)],
            text=True, capture_output=True, check=False,
        )
        self.assertNotEqual(verified.returncode, 0)
        self.assertIn("checksum", verified.stderr.lower())


if __name__ == "__main__":
    unittest.main()
