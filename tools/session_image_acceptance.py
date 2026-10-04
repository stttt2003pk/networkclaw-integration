"""Run the delivered amd64 image with isolated PostgreSQL, Redis and provider state.

PostgreSQL and Redis are host dependencies; all application binaries and native
Hermes execution come from the verified image. No source is mounted as runtime code.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import time
import uuid

from deployment_smoke import request_json
from dev import run_local_migrations
from model_setup import bootstrap_models, snapshot_secrets

ROOT = Path(__file__).resolve().parents[1]
helpers = runpy.run_path(str(ROOT / "tools/run-model-snapshot-acceptance.py"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=ROOT / ".integration-state/evidence/session-image-deployment.json")
    args = parser.parse_args()
    database = "session_image_" + uuid.uuid4().hex
    container = "networkclaw-session-image-" + uuid.uuid4().hex[:10]
    report = {"status": "failed", "checks": [], "runtime_platform": "linux/amd64"}
    env = dict(os.environ, PGPASSWORD=os.environ.get("PGPASSWORD", "ongrid"))
    db_user = os.environ.get("PGUSER", "ongrid")
    psql = ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1", "-U",
            os.environ.get("MODEL_ACCEPTANCE_PGADMIN", db_user), "-d", "postgres"]
    created = False
    redis = None
    try:
        identity = json.loads(subprocess.check_output(["docker", "image", "inspect", args.image], text=True))[0]
        if identity["Architecture"] != "amd64" or identity["Config"]["User"] != "65532:65532":
            raise RuntimeError("image_platform_or_user_invalid")
        if "HERMES_DISABLE_LAZY_INSTALLS=1" not in identity["Config"].get("Env", []):
            raise RuntimeError("image_online_install_not_disabled")
        image_hash = identity["Id"]
        builder = runpy.run_path(str(ROOT / "ci/ubuntu-22.04/build-artifacts.py"))
        if identity["Config"].get("Labels", {}).get("io.networkclaw.bundle.sha256") != builder["sha"](args.bundle):
            raise RuntimeError("image_bundle_identity_mismatch")
        report.update(image_id=image_hash, bundle_sha256=builder["sha"](args.bundle))
        with ExitStack() as scope:
            temporary = tempfile.TemporaryDirectory(prefix="session-image-", dir="/tmp")
            scope.callback(temporary.cleanup)
            work = Path(temporary.name)
            bundle, manifest = builder["extract_build_input"](args.bundle, work / "input")
            go = bundle / manifest["sources"]["networkclaw"]["path"]
            subprocess.run(psql, input=f'CREATE DATABASE "{database}" OWNER "{db_user}";', env=env, check=True, capture_output=True, text=True)
            created = True
            run_local_migrations({"networkclaw": {"path": str(go)}}, dict(env, POSTGRES_DB=database, POSTGRES_USER=db_user))
            runtime = work / "runtime"
            runtime.mkdir(mode=0o777)
            runtime.chmod(0o777)
            secrets = snapshot_secrets(work / "secrets", container_readable=True)
            private_values = [env["PGPASSWORD"], "image-disposable-provider", (secrets / "token").read_text().strip()]
            def diagnostics():
                lines = []
                for path in runtime.rglob("*.log"):
                    file_lines = ["--- " + path.name + " ---"]
                    for line in path.read_text(errors="replace").splitlines():
                        if "msg='" not in line:
                            file_lines.append(line)
                    lines.append("\n".join(file_lines)[-6000:])
                value = "\n".join(lines)
                for private in private_values:
                    if private:
                        value = value.replace(private, "<redacted>")
                args.report.with_suffix(".diagnostic.log").write_text(value + "\n")
            scope.callback(diagnostics)
            redis_port, http_port, metrics_port, web_port = (helpers["port"]() for _ in range(4))
            # Disposable instance. Docker Desktop reaches the host loopback listener.
            redis = subprocess.Popen(["redis-server", "--bind", "0.0.0.0", "--port", str(redis_port), "--save", "", "--appendonly", "no"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            log_path = args.report.with_suffix(".log")
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("w") as log:
                run = ["docker", "run", "-d", "--platform=linux/amd64", "--name", container, "--init",
                       "--tmpfs", "/tmp:size=268435456,mode=1777", "-v", f"{runtime}:/tmp/ongrid", "-v", f"{secrets}:/secrets:ro",
                       "-v", f"{ROOT / 'tests'}:/fixtures:ro",
                       "-p", f"127.0.0.1:{http_port}:8080", "-p", f"127.0.0.1:{metrics_port}:9100", "-p", f"127.0.0.1:{web_port}:5174",
                       "--entrypoint", "/bin/sh", args.image, "-c", "exec sleep 3600"]
                subprocess.run(run, check=True, stdout=log, stderr=log)

                def spawn(binary: str, values: dict[str, str], command: str | None = None):
                    cmd = ["docker", "exec", "-d"]
                    for key, value in values.items():
                        cmd += ["-e", f"{key}={value}"]
                    cmd += [container, "/bin/sh", "-c", f"exec {command or '/opt/bin/' + binary} > /tmp/ongrid/{binary}.log 2>&1"]
                    subprocess.run(cmd, check=True, stdout=log, stderr=log)

                origin = f"http://127.0.0.1:{web_port}"
                common = {"HOME": "/tmp/ongrid", "HERMES_HOME": "/tmp/ongrid/hermes", "DEV_ENV": "dev",
                          "NETWORKCLAW_HARNESS_PROFILE": "development", "NETWORKCLAW_HARNESS_PROVIDER_MODE": "live",
                          "NETWORKCLAW_HARNESS_ALLOWED_EGRESS_HOSTS": "127.0.0.1", "ONGRID_HARNESS_WORKSPACE_ROOT": "/tmp/ongrid/workspaces"}
                spawn("provider", {}, "python /fixtures/fixtures/provider_stub/server.py --host 127.0.0.1 --port 18080 --mode session-execution")
                helpers["wait_for"](lambda: subprocess.run(["docker", "exec", container, "python", "-c",
                    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:18080/healthz',timeout=2)"],
                    capture_output=True, timeout=5).returncode == 0, "image_provider_not_ready", timeout=30)
                spawn("chatrtmgr", common | {"CHATRTMGR_PROCESS_TARGET": "gateway", "CHATRTMGR_GRPC_ADDR": "127.0.0.1:50052",
                      "CHATRTMGR_METRICS_ADDR": ":9101", "CHATRTMGR_DISCOVERY_TYPE": "local", "CHATRTMGR_LOCAL_REGISTRY_PATH": "/tmp/ongrid/registry.json",
                      "CHATRTMGR_NODE_ID": "image-node", "CHATRTMGR_SOCKET_DIR": "/tmp/networkclaw-sockets",
                      "CHATRTMGR_LOBBY_URL": "https://localhost:8443", "CHATRTMGR_MODEL_CONFIG_TOKEN_FILE": "/secrets/token", "CHATRTMGR_MODEL_CONFIG_CA_FILE": "/secrets/ca.pem"})
                spawn("lobby", common | {"ONGRID_HTTP_ADDR": ":8080", "ONGRID_GRPC_ADDR": "127.0.0.1:0", "ONGRID_METRICS_ADDR": ":9100",
                      "ONGRID_HTTP_WRITE_TIMEOUT": "180s",
                      "ONGRID_MODEL_CONFIG_TLS_ADDR": ":8443", "ONGRID_MODEL_CONFIG_CERT_FILE": "/secrets/cert.pem", "ONGRID_MODEL_CONFIG_KEY_FILE": "/secrets/key.pem",
                      "LOBBY_MODEL_CONFIG_TOKEN_FILE": "/secrets/token", "ONGRID_DB_HOST": "host.docker.internal", "ONGRID_DB_USER": db_user,
                      "ONGRID_DB_PASSWORD": env["PGPASSWORD"], "ONGRID_DB_NAME": database, "ONGRID_DB_SSLMODE": "disable",
                      "ONGRID_REDIS_ADDR": f"host.docker.internal:{redis_port}", "ONGRID_DISCOVERY_TYPE": "local", "ONGRID_LOCAL_REGISTRY_PATH": "/tmp/ongrid/registry.json",
                      "ONGRID_JWT_SECRET": "image-disposable-jwt", "ONGRID_OIDC_SECRET_KEY": "image-disposable-encryption", "ONGRID_WEB2_ORIGINS": origin,
                      "ONGRID_SEED_ADMIN_EMAIL": "image-admin", "ONGRID_SEED_ADMIN_PASSWORD": "image-disposable-password",
                      "ONGRID_HARNESS_ENABLED": "true", "ONGRID_HARNESS_ROLLOUT_PERCENT": "100",
                      "ONGRID_HARNESS_ALLOWED_TOOLS": "networkclaw_workspace_read,skills_list,skill_view,delegate_task", "ONGRID_HARNESS_ALLOWED_SKILLS": "workspace-inspection"})
                spawn("web2-server", {"NETWORKCLAW_WEB2_LOBBY_URL": "http://127.0.0.1:8080"})
                base = f"http://127.0.0.1:{http_port}"
                report["stage"] = "lobby_ready"
                helpers["wait_for"](lambda: helpers["read_json"](base + "/readyz")[0] == 200, "image_lobby_not_ready", timeout=100)
                bootstrap_models(base, {"OPENAI_API_KEY": "image-disposable-provider", "OPENAI_MODEL": "fixture-model", "OPENAI_MODELS": "fixture-model",
                    "OPENAI_BASE_URL": "http://127.0.0.1:18080/v1", "ONGRID_SEED_ADMIN_EMAIL": "image-admin", "ONGRID_SEED_ADMIN_PASSWORD": "image-disposable-password"}, origin=origin)
                status, login = request_json(base + "/api/v1/auth/login", "POST", {"email": "image-admin", "password": "image-disposable-password"}, None, origin, 10)
                if status != 200:
                    raise RuntimeError("image_login_failed")
                token = login["access_token"]
                private_values.append(token)
                release = json.loads((bundle / "integration/release/manifests/capability-release.v1.json").read_text())
                client = runpy.run_path(str(ROOT / "tools/capability-release-admin.py"))
                for operation in ("import", "publish"):
                    report["stage"] = "release_" + operation
                    payload = client["build_request"](operation, "image-" + operation, release if operation == "import" else None,
                        release_id=release["release_id"], release_hash=release["release_hash"], expected_published_hash=None)
                    status, receipt = client["send"](base, token, payload, origin=origin)
                    if not 200 <= status < 300:
                        report["release_rejection"] = {"http_status": status, "code": receipt.get("code"), "message": receipt.get("message"), "errors": receipt.get("errors")}
                        raise RuntimeError("image_release_" + operation + "_failed")
                time.sleep(32)  # production Broker interval
                report["stage"] = "session_create"
                status, created_session = request_json(base + "/api/v1/sessions", "POST", {}, token, origin, 60)
                if status != 201:
                    raise RuntimeError("image_no_profile_create_failed")
                sid = created_session["session"]["id"]
                for prompt in ("ordinary-image-turn", "session-skill read the frozen skill"):
                    report["stage"] = prompt.split()[0]
                    print("image acceptance stage: " + report["stage"], flush=True)
                    status, reply = request_json(base + f"/api/v1/sessions/{sid}/messages", "POST", {"message": prompt}, token, origin, 180)
                    if status != 200 or "interop-ok" not in reply.get("reply", ""):
                        report["failed_turn"] = {"http_status": status, "code": reply.get("code")}
                        raise RuntimeError("image_native_turn_failed")
                    if "image-disposable-provider" in json.dumps(reply):
                        raise RuntimeError("image_public_credential_leak")
                status, _ = request_json(base + f"/api/v1/sessions/{sid}", "DELETE", None, token, origin, 30)
                if status != 200:
                    raise RuntimeError("image_session_close_failed")
                if helpers["read_json"](f"http://127.0.0.1:{web_port}/readyz")[0] != 200:
                    raise RuntimeError("image_web2_not_ready")
                # Logs are scanned in the disposable directory, never exported with user text.
                for path in runtime.rglob("*.log"):
                    if any(secret in path.read_text(errors="replace") for secret in (token, "image-disposable-provider", (secrets / "token").read_text().strip())):
                        raise RuntimeError("image_diagnostic_credential_leak")
                report["checks"] = ["verified_bundle_image_identity", "amd64_nonroot_image", "isolated_full_migrations", "tls_model_broker",
                                    "no_profile_create", "native_ordinary_turn", "native_frozen_skill", "session_close", "image_web2_ready", "public_and_diagnostic_no_credentials"]
                report["status"] = "passed"
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report["reason_code"] = str(error) if isinstance(error, RuntimeError) else type(error).__name__
    finally:
        removed = subprocess.run(["docker", "rm", "-f", container], capture_output=True).returncode
        if redis is not None:
            helpers["stop"](redis)
        if created:
            subprocess.run(psql, input=f'DROP DATABASE "{database}" WITH (FORCE);', env=env, check=True, capture_output=True, text=True)
        # A still-running registry writer may recreate a file after ExitStack's
        # first cleanup. Remove the disposable directory after the container stops.
        if "temporary" in locals():
            temporary.cleanup()
        report["container_removed"] = removed == 0
        report["isolated_database_removed"] = created
        report["temporary_workspace_removed"] = "temporary" not in locals() or not Path(temporary.name).exists()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    return 0 if report["status"] == "passed" and report["container_removed"] and report["temporary_workspace_removed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
