from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import dev  # noqa: E402
import resolve_sources  # noqa: E402


class SourceResolutionTests(unittest.TestCase):
    def test_relative_config_paths_are_anchored_at_integration_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "workspace.yaml"
            config_file.write_text(
                "schema_version: 1\nmode: local\n"
                "networkclaw_path: ../NetworkClaw\n"
                "harness_path: ../networkclaw-harness\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"NETWORKCLAW_WORKSPACE_FILE": str(config_file)}, clear=False):
                for key in ("NETWORKCLAW_PATH", "HARNESS_PATH"):
                    os.environ.pop(key, None)
                result = resolve_sources.resolve()
        self.assertEqual(result["networkclaw"]["path"], str((ROOT / ".." / "NetworkClaw").resolve()))
        self.assertEqual(result["harness"]["path"], str((ROOT / ".." / "networkclaw-harness").resolve()))

    def test_source_package_without_git_metadata_gets_tree_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            go = root / "go"
            harness = root / "harness"
            go.mkdir()
            harness.mkdir()
            (go / "go.mod").write_text("module example\n", encoding="utf-8")
            (harness / "pyproject.toml").write_text("[project]\nname='example'\n", encoding="utf-8")
            config_file = root / "workspace.yaml"
            config_file.write_text(
                f"schema_version: 1\nmode: local\nnetworkclaw_path: {go}\nharness_path: {harness}\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"NETWORKCLAW_WORKSPACE_FILE": str(config_file)}, clear=False):
                for key in ("NETWORKCLAW_PATH", "HARNESS_PATH", "NETWORKCLAW_PYTHON", "NETWORKCLAW_GO", "NETWORKCLAW_STATE_DIR"):
                    os.environ.pop(key, None)
                result = resolve_sources.resolve()
            self.assertIsNone(result["networkclaw"]["commit"])
            self.assertIsNone(result["networkclaw"]["dirty"])
            self.assertEqual(len(result["networkclaw"]["tree_sha256"]), 64)
            self.assertEqual(result["networkclaw"]["path"], str(go.resolve()))
            self.assertEqual(result["harness"]["path"], str(harness.resolve()))

    def test_missing_source_has_nonzero_cli_result(self) -> None:
        with patch.dict(os.environ, {"NETWORKCLAW_PATH": "/definitely/missing/networkclaw"}, clear=False):
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "resolve_sources.py"), "--json"],
                text=True, capture_output=True, check=False,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("repository is unavailable", result.stderr)


class ChatsvcReadinessTests(unittest.TestCase):
    def test_health_probe_uses_chatsvc_uds_health_frame(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            socket_path = Path(temp_dir) / "chatsvc.sock"
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(socket_path))
            listener.listen(1)

            def serve_once() -> None:
                conn, _ = listener.accept()
                with conn:
                    request = conn.recv(8)
                    self.assertEqual(request, struct.pack(">II", 3, 0))
                    payload = json.dumps({"status": "active", "service_id": "test"}).encode()
                    conn.sendall(struct.pack(">II", 3, len(payload)) + payload)
                listener.close()

            worker = threading.Thread(target=serve_once)
            worker.start()
            self.assertTrue(dev.health_check(socket_path, timeout=2))
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())

    def test_provider_env_file_is_overridden_by_exported_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text("OPENAI_API_KEY=file-secret\nOPENAI_BASE_URL=http://127.0.0.1:9123/v1\n", encoding="utf-8")
            env = dev.provider_environment({"provider_env_file": str(env_file)}, {"OPENAI_API_KEY": "shell-secret"})
        self.assertEqual(env["OPENAI_API_KEY"], "shell-secret")
        self.assertEqual(env["OPENAI_BASE_URL"], "http://127.0.0.1:9123/v1")
        self.assertNotIn("file-secret", json.dumps(env))


if __name__ == "__main__":
    unittest.main()
