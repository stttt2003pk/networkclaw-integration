from __future__ import annotations

import json
import hashlib
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import dev  # noqa: E402
import compose  # noqa: E402
import model_setup  # noqa: E402
import resolve_sources  # noqa: E402
import deployment_smoke  # noqa: E402


class DeploymentRequestTests(unittest.TestCase):
    def test_optional_origin_is_omitted_from_http_headers(self) -> None:
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'{}'
        with patch("deployment_smoke.urllib.request.urlopen", return_value=response) as send:
            deployment_smoke.request_json("http://127.0.0.1/models", "GET", None, "fixture", None, 5)
        self.assertIsNone(send.call_args.args[0].get_header("Origin"))


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
    def test_wait_exit_reaps_an_exited_managed_child(self) -> None:
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        try:
            self.assertTrue(dev.wait_exit(child.pid, 3))
        finally:
            child.wait(timeout=3)

    def test_local_migrations_skip_recorded_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            migration_dir = Path(temp_dir) / "internal/lobby/database/migrations"
            migration_dir.mkdir(parents=True)
            migration = migration_dir / "001_test.up.sql"
            migration.write_text("SELECT 1;\n", encoding="utf-8")
            digest = hashlib.sha256(migration.read_bytes()).hexdigest()
            responses = iter([
                MagicMock(returncode=0),
                MagicMock(returncode=0, stdout="f\n"),
                MagicMock(returncode=0, stdout=f"001_test.up.sql:{digest}\n"),
            ])
            with patch("dev.subprocess.run", side_effect=lambda *args, **kwargs: next(responses)) as run:
                dev.run_local_migrations({"networkclaw": {"path": temp_dir}}, {"POSTGRES_USER": "u", "POSTGRES_DB": "d"})
            self.assertEqual(run.call_count, 3)

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

    def test_pre_ledger_baseline_does_not_skip_model_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "internal/lobby/database/migrations"
            root.mkdir(parents=True)
            old = root / "029_legacy_capability_readonly.up.sql"
            new = root / "030_model_configuration.up.sql"
            old.write_text("SELECT 29;")
            new.write_text("SELECT 30;")
            digest = hashlib.sha256(old.read_bytes()).hexdigest()
            responses = [MagicMock(returncode=0, stdout=value) for value in
                         ("", "t", "", "t", "", f"{old.name}:{digest}", "", "")]
            with patch("dev.subprocess.run", side_effect=responses) as run:
                dev.run_local_migrations({"networkclaw": {"path": directory}}, {})
            baseline = run.call_args_list[4].args[0][-1]
            self.assertNotIn("030_", baseline)
            self.assertIn(str(new), run.call_args_list[6].args[0])


class ModelSetupTests(unittest.TestCase):
    def test_provider_credentials_are_first_install_input_only(self) -> None:
        env = {"OPENAI_API_KEY": "private", "ZHIPU_BASE_URL": "private", "ANTHROPIC_API_KEY": "private",
               "NETWORKCLAW_HARNESS_ALLOWED_MODELS": "obsolete", "PATH": "/bin",
               "NETWORKCLAW_HARNESS_ALLOWED_EGRESS_HOSTS": "example.test"}
        self.assertEqual(model_setup.runtime_environment(env), {"PATH": "/bin", "NETWORKCLAW_HARNESS_ALLOWED_EGRESS_HOSTS": "example.test"})

    def test_existing_model_configuration_is_preserved(self) -> None:
        with patch("model_setup.request_json", side_effect=[(200, {"access_token": "test-token"}),
                                                             (200, {"models": [{"id": "administrator-model"}]})]) as request:
            model_setup.bootstrap_models("http://127.0.0.1", {"OPENAI_MODEL": "fixture", "OPENAI_API_KEY": "private"})
        self.assertEqual(request.call_count, 2)

    def test_empty_configuration_uses_admin_api_and_sets_default(self) -> None:
        with patch("model_setup.request_json", side_effect=[(200, {"access_token": "test-token"}), (200, {"models": []}),
                                                             (201, {"id": "connection"}), (201, {"id": "model"}), (200, {})]) as request:
            model_setup.bootstrap_models("http://127.0.0.1", {"OPENAI_MODEL": "fixture", "OPENAI_API_KEY": "private"})
        self.assertEqual(request.call_args_list[2].args[2]["api_key"], "private")
        self.assertEqual(request.call_args_list[-1].args[2], {"model_config_id": "model"})

    def test_failed_requests_do_not_expose_provider_details(self) -> None:
        with patch("model_setup.request_json", side_effect=OSError("private-provider-value")):
            with self.assertRaisesRegex(RuntimeError, "^model bootstrap request failed$"):
                model_setup.bootstrap_models("http://127.0.0.1", {"OPENAI_MODEL": "fixture", "OPENAI_API_KEY": "private"})

    def test_transport_files_are_protected_and_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = model_setup.snapshot_secrets(Path(directory) / "secrets", ("lobby",))
            token = (root / "token").read_bytes()
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            self.assertEqual((root / "token").stat().st_mode & 0o777, 0o600)
            model_setup.snapshot_secrets(root, ("lobby",), container_readable=True)
            self.assertEqual((root / "token").read_bytes(), token)
            self.assertEqual((root / "key.pem").stat().st_mode & 0o777, 0o444)


class FrontendStartupTests(unittest.TestCase):
    def test_existing_capability_release_is_never_replaced_by_dev_up(self) -> None:
        with patch("dev.local_release_records", return_value=[{"status": "published"}]), \
                patch("dev.runpy.run_path") as compiler:
            dev.seed_local_capabilities({}, {}, {})
        compiler.assert_not_called()

    def test_empty_local_catalog_uses_compiler_and_admin_import_publish(self) -> None:
        manifest = {"release_id": "cap-dev-hermes", "release_hash": "sha256:local", "catalog": {"version": "actual-version"}, "toolsets": [1], "tools": [1], "skills": [1], "agents": []}
        def discover(harness, networkclaw, path):
            self.assertEqual(json.loads(path.read_text())["profiles"], [])
            return {"agents": []}
        compiler = {"discovery": discover, "vendor_check": lambda _: {"status": "passed"}, "compile_release": lambda *a, **k: manifest,
                    "check_release": lambda *a: {"status": "passed"}}
        payloads = []
        def send(base, token, payload, *, origin):
            self.assertEqual(base, "http://127.0.0.1:8080")
            self.assertEqual(token, "private-token")
            self.assertEqual(origin, "http://127.0.0.1:5174")
            payloads.append(payload)
            return 200, {"data": {"result": "ok"}}
        admin = {"build_request": lambda operation, job, manifest, **k: {"operation": operation, "manifest": manifest, **k}, "send": send}
        with tempfile.TemporaryDirectory() as directory, \
                patch("dev.local_release_records", return_value=[]), \
                patch("dev.runpy.run_path", side_effect=[compiler, admin]), \
                patch("deployment_smoke.request_json", return_value=(200, {"access_token": "private-token"})):
            dev.seed_local_capabilities({"harness": {"path": "/harness"}, "networkclaw": {"path": "/go"}}, {"root": Path(directory)}, {})
            evidence = "".join(p.read_text() for p in Path(directory).rglob("*.json"))
            self.assertNotIn("private-token", evidence)
        self.assertEqual([p["operation"] for p in payloads], ["import", "publish"])
        self.assertEqual(payloads[0]["manifest"]["agents"], [])
        self.assertIsNone(payloads[1]["expected_published_hash"])

    def test_existing_releases_are_materialized_and_checked_without_recompile(self) -> None:
        rows = [{"status": "published", "ever_published": True, "manifest": {"release_id": "current"}},
                {"status": "retired", "ever_published": True, "manifest": {"release_id": "old"}}]
        with tempfile.TemporaryDirectory() as directory, \
                patch("dev.local_release_records", return_value=rows), \
                patch("dev.runpy.run_path", return_value={"check_release": lambda *args: {"status": "passed"}}):
            declarations = json.loads(dev.prepare_local_capability_deployment(
                {"harness": {"path": "/harness"}}, {"root": Path(directory)}, {}))
            self.assertEqual([json.loads(Path(row["manifest"]).read_text())["release_id"] for row in declarations], ["current", "old"])
            self.assertTrue(all(row["asset_root"] == "/harness" for row in declarations))

    def test_existing_release_missing_assets_fails_before_starting_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory, \
                patch("dev.local_release_records", return_value=[{"status": "published", "ever_published": True, "manifest": {}}]), \
                patch("dev.runpy.run_path", return_value={"check_release": lambda *args: {"status": "failed", "reason_code": "vendor_provenance_mismatch"}}):
            with self.assertRaisesRegex(RuntimeError, "vendor_provenance_mismatch"):
                dev.prepare_local_capability_deployment({"harness": {"path": "/harness"}}, {"root": Path(directory)}, {})

    def test_build_frontend_runs_the_web2_production_build(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, \
                patch("dev.shutil.which", return_value="/usr/bin/npm"), \
                patch("dev.subprocess.run") as run:
            frontend = Path(temp_dir) / "NetworkClaw" / "web2"
            frontend.mkdir(parents=True)
            dev.build_frontend({"networkclaw": {"path": str(Path(temp_dir) / "NetworkClaw")}})

        run.assert_called_once_with(
            ["/usr/bin/npm", "run", "build"],
            cwd=frontend,
            env=os.environ.copy(),
            check=True,
        )

    def test_starts_web2_and_records_the_managed_process(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "NetworkClaw"
            vite = source / "web2/node_modules/vite/bin/vite.js"
            vite.parent.mkdir(parents=True)
            vite.touch()
            paths = dev.state_paths({"state_dir": str(Path(temp_dir) / "state")})
            dev.ensure_dirs(paths)
            process = MagicMock(pid=1234)
            process.poll.return_value = None
            response = MagicMock()
            response.__enter__.return_value.status = 200

            with patch("dev.shutil.which", return_value="/usr/bin/node"), \
                    patch("dev.subprocess.Popen", return_value=process) as popen, \
                    patch("dev.urlopen", return_value=response):
                dev.start_frontend({"networkclaw": {"path": str(source)}}, paths)

            command = popen.call_args.args[0]
            self.assertEqual(command, ["/usr/bin/node", str(vite), "--host", "127.0.0.1", "--strictPort"])
            self.assertEqual(popen.call_args.kwargs["cwd"], str(source / "web2"))
            self.assertEqual(json.loads((paths["pids"] / "frontend.pid").read_text())["pid"], 1234)


class ComposeLifecycleTests(unittest.TestCase):
    def test_compose_up_stops_before_rebuild_and_start(self) -> None:
        events: list[tuple[str, object]] = []

        def docker(command, **kwargs):
            events.append(("docker", command))
            return MagicMock(returncode=0)

        with patch("compose.subprocess.run", side_effect=docker), \
                patch("compose.build_local_image", side_effect=lambda image: events.append(("build", image))), \
                patch("compose.snapshot_secrets"), patch("compose.bootstrap_models"):
            result = compose.run("up", {"NETWORKCLAW_IMAGE": "networkclaw:test", "NETWORKCLAW_REBUILD": "1"})

        self.assertEqual(result, 0)
        self.assertEqual([kind for kind, _ in events], ["docker", "build", "docker"])
        self.assertIn("down", events[0][1])
        self.assertEqual(events[1][1], "networkclaw:test")
        self.assertIn("up", events[2][1])

    def test_compose_up_can_explicitly_reuse_image(self) -> None:
        with patch("compose.subprocess.run", return_value=MagicMock(returncode=0)) as run, \
                patch("compose.build_local_image") as build, \
                patch("compose.snapshot_secrets"), patch("compose.bootstrap_models"):
            self.assertEqual(
                compose.run("up", {"NETWORKCLAW_IMAGE": "networkclaw:test", "NETWORKCLAW_REBUILD": "0"}),
                0,
            )
        build.assert_not_called()
        self.assertIn("down", run.call_args_list[0].args[0])


if __name__ == "__main__":
    unittest.main()
