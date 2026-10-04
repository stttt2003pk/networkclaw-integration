from __future__ import annotations

import json
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.collect_k8s_diagnostics import redact_text
from tools.source_tree import included_files


ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "deploy" / "helm" / "networkclaw-bundle"


class DeploymentInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        rendered = subprocess.run(
            ["helm", "template", "networkclaw", str(CHART), "--namespace", "test"],
            capture_output=True, text=True, check=True,
        )
        cls.rendered = rendered.stdout

    def test_helm_chart_lints_and_renders(self) -> None:
        result = subprocess.run(["helm", "lint", str(CHART)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rendered_workloads_use_probes_and_non_root(self) -> None:
        self.assertGreaterEqual(self.rendered.count("readinessProbe:"), 3)
        self.assertGreaterEqual(self.rendered.count("livenessProbe:"), 3)
        self.assertIn("runAsNonRoot: true", self.rendered)
        self.assertIn("capabilities:", self.rendered)
        self.assertIn("drop: [ALL]", self.rendered)

    def test_lobby_has_endpoint_reader_and_chatrtmgr_has_no_token(self) -> None:
        lobby = self.rendered.split("kind: Deployment\nmetadata:\n  name: networkclaw-networkclaw-bundle-lobby\n", 1)[1]
        chatrtmgr = self.rendered.split("kind: Deployment\nmetadata:\n  name: networkclaw-networkclaw-bundle-chatrtmgr\n", 1)[1].split("kind: Deployment", 1)[0]
        self.assertIn("serviceAccountName: networkclaw-networkclaw-bundle-lobby", lobby)
        self.assertIn("automountServiceAccountToken: true", lobby)
        self.assertIn("automountServiceAccountToken: false", chatrtmgr)

    def test_secrets_are_references_not_values(self) -> None:
        rendered = subprocess.run(
            ["helm", "template", "networkclaw", str(CHART), "--namespace", "test",
             "--set", "secrets.existingSecret=runtime-secret"],
            capture_output=True, text=True, check=True,
        ).stdout
        self.assertIn("secretKeyRef:", rendered)
        self.assertIn("name: runtime-secret", rendered)
        self.assertNotIn("POSTGRES_PASSWORD: ", rendered)
        self.assertNotIn("OPENAI_API_KEY: ", rendered)

    def test_model_snapshot_settings_are_secret_references(self) -> None:
        self.assertIn("name: CHATRTMGR_LOBBY_URL", self.rendered)
        self.assertIn("name: CHATRTMGR_MODEL_CONFIG_TOKEN_FILE", self.rendered)
        self.assertIn("name: CHATRTMGR_MODEL_CONFIG_CA_FILE", self.rendered)
        self.assertIn("name: ONGRID_MODEL_CONFIG_TLS_ADDR", self.rendered)
        self.assertIn("name: ONGRID_MODEL_CONFIG_CERT_FILE", self.rendered)
        self.assertIn("name: ONGRID_MODEL_CONFIG_KEY_FILE", self.rendered)
        self.assertIn("secretName: \"networkclaw-model-snapshot\"", self.rendered)
        self.assertNotIn("OPENAI_API_KEY", self.rendered)
        self.assertNotIn("OPENAI_MODELS", self.rendered)

    def test_pod_ip_is_defined_before_reference(self) -> None:
        chatrtmgr = self.rendered.split("kind: Deployment\nmetadata:\n  name: networkclaw-networkclaw-bundle-chatrtmgr\n", 1)[1].split("kind: Deployment", 1)[0]
        self.assertLess(chatrtmgr.index("name: CHATRTMGR_POD_IP"), chatrtmgr.index("name: CHATRTMGR_GRPC_ADDR"))

    def test_etcd_rendering_supports_distributed_replicas(self) -> None:
        rendered = subprocess.run(
            ["helm", "template", "networkclaw", str(CHART), "--namespace", "test",
             "--set", "replicas.lobby=2", "--set", "replicas.chatrtmgr=2",
             "--set", "discovery.type=etcd", "--set-string", "discovery.etcdEndpoints=etcd:2379"],
            capture_output=True, text=True, check=True,
        ).stdout
        self.assertIn("replicas: 2", rendered)
        self.assertIn("name: CHATRTMGR_DISCOVERY_TYPE\n              value: \"etcd\"", rendered)
        self.assertIn("name: CHATRTMGR_ETCD_ENDPOINTS", rendered)
        self.assertIn("name: ONGRID_ETCD_ENDPOINTS", rendered)
        self.assertNotIn("name: CHATRTMGR_K8S_NAMESPACE", rendered)

    def test_ingress_routes_to_web2_using_the_combined_image(self) -> None:
        rendered = subprocess.run(
            ["helm", "template", "networkclaw", str(CHART), "--namespace", "test",
             "--set", "ingress.enabled=true"], capture_output=True, text=True, check=True,
        ).stdout
        ingress = rendered.split("kind: Ingress", 1)[1]
        self.assertIn("name: networkclaw-networkclaw-bundle-web2", ingress)
        self.assertIn("path: /", ingress)
        self.assertIn("command: [/opt/bin/web2-server]", rendered)
        self.assertIn("name: NETWORKCLAW_WEB2_LOBBY_URL", rendered)
        self.assertEqual(rendered.count("image: \"networkclaw:dev\""), 3)

    def test_compose_config_is_valid(self) -> None:
        result = subprocess.run(
            ["docker", "compose", "--env-file", str(ROOT / "deploy/compose/compose.env.example"),
             "-f", str(ROOT / "deploy/compose/docker-compose.yml"), "config", "--format", "json"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads(result.stdout)
        self.assertEqual(set(config["services"]), {"postgres", "redis", "etcd", "migrate", "chatrtmgr", "lobby", "web2"})
        self.assertEqual(config["services"]["web2"]["entrypoint"], ["/opt/bin/web2-server"])
        self.assertEqual(config["services"]["web2"]["environment"]["NETWORKCLAW_WEB2_LOBBY_URL"], "http://lobby:8080")
        self.assertEqual(
            config["services"]["lobby"]["depends_on"]["migrate"]["condition"],
            "service_completed_successfully",
        )
        self.assertEqual(config["services"]["chatrtmgr"]["environment"]["CHATRTMGR_GRPC_ADDR"], "chatrtmgr:50052")
        self.assertTrue((ROOT.parent / "networkclaw/internal/lobby/database/migrations").is_dir())
        self.assertIn("ON_ERROR_STOP=1", " ".join(config["services"]["migrate"]["entrypoint"]))
        self.assertEqual(config["services"]["migrate"]["volumes"][0]["target"], "/migrations")
        self.assertIn("networkclaw_compose_migrations", " ".join(config["services"]["migrate"]["entrypoint"]))
        self.assertNotIn("OPENAI_MODELS", config["services"]["migrate"]["environment"])
        for name in ("CHATRTMGR_LOBBY_URL", "CHATRTMGR_MODEL_CONFIG_TOKEN_FILE", "CHATRTMGR_MODEL_CONFIG_CA_FILE"):
            self.assertIn(name, config["services"]["chatrtmgr"]["environment"])
        self.assertEqual(config["services"]["chatrtmgr"]["environment"]["CHATRTMGR_LOBBY_URL"], "https://lobby:8443")
        secret_sources = {item["source"] for item in config["services"]["chatrtmgr"]["secrets"]}
        self.assertIn("model-token", secret_sources)
        self.assertIn("model-ca", secret_sources)

    def test_compose_wrappers_have_up_down_entries(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("compose-up:", makefile)
        self.assertIn("compose-down:", makefile)
        result = subprocess.run([sys.executable, str(ROOT / "tools/compose.py"), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("compose.py", result.stdout)

    def test_compose_example_is_in_bundle_source_set(self) -> None:
        self.assertIn(ROOT / "deploy/compose/compose.env.example", included_files(ROOT))

    def test_smoke_connection_failure_is_json(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/deployment_smoke.py"), "--url", "http://127.0.0.1:1", "--timeout", "0.2"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertFalse(report["passed"])
        self.assertEqual(report["checks"]["readyz"]["status"], None)

    def test_diagnostics_redacts_common_credentials(self) -> None:
        result = redact_text("Authorization: Bearer abc.def\npassword=private\nOPENAI_API_KEY=key123")
        for value in ("abc.def", "private", "key123"):
            self.assertNotIn(value, result)

    def test_kind_tool_has_safe_cleanup_guard(self) -> None:
        tool = ROOT / "tools/kind-up.py"
        help_result = subprocess.run([sys.executable, str(tool), "--help"], capture_output=True, text=True)
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("--context", help_result.stdout)
        cleanup = subprocess.run(
            [sys.executable, str(tool), "down", "--namespace", "default"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(cleanup.returncode, 0)
        self.assertIn("protected namespace", cleanup.stderr)

    def test_kind_tool_rejects_non_kind_context(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/kind-up.py"), "down", "--context", "prod", "--cluster", "ongrid"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("matching --cluster", result.stderr)

    def test_kind_provider_file_is_bootstrap_input_only(self) -> None:
        tool = runpy.run_path(str(ROOT / "tools/kind-up.py"))
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env.kind"
            env_file.write_text(
                "OPENAI_API_KEY='test-only-key'\nOPENAI_MODEL=gpt-5.6-sol\nOPENAI_BASE_URL=https://example.test/v1\n",
                encoding="utf-8",
            )
            values = tool["read_env_file"](env_file)
        self.assertEqual(values["OPENAI_MODEL"], "gpt-5.6-sol")
        self.assertEqual(values["OPENAI_BASE_URL"], "https://example.test/v1")
        self.assertEqual(values["OPENAI_API_KEY"], "test-only-key")
        self.assertNotIn("apply_model_catalog_seed", tool)


if __name__ == "__main__":
    unittest.main()
