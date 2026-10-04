"""Validate dev-up/down in an isolated database, ports, state and provider."""
from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import time
import uuid

from deployment_smoke import request_json

ROOT = Path(__file__).resolve().parents[1]
helpers = runpy.run_path(str(ROOT / "tools/run-model-snapshot-acceptance.py"))


def main() -> int:
    report = {"status": "failed", "checks": []}
    database = "session_dev_" + uuid.uuid4().hex
    env = dict(os.environ, PGPASSWORD=os.environ.get("PGPASSWORD", "ongrid"))
    psql = ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1", "-U",
            os.environ.get("MODEL_ACCEPTANCE_PGADMIN", os.environ.get("PGUSER", "ongrid")), "-d", "postgres"]
    processes = []
    created = False
    try:
        subprocess.run(psql, input=f'CREATE DATABASE "{database}" OWNER "{os.environ.get("PGUSER", "ongrid")}";',
                       env=env, check=True, capture_output=True, text=True)
        created = True
        with tempfile.TemporaryDirectory(prefix="session-dev-", dir="/tmp") as temporary:
            work = Path(temporary)
            (work / "fixture.env").write_text("")
            ports = {key: helpers["port"]() for key in ("http", "tls", "grpc", "lm", "mm", "web", "redis", "provider")}
            origin = f"http://127.0.0.1:{ports['web']}"
            base = f"http://127.0.0.1:{ports['http']}"
            env.update(NETWORKCLAW_STATE_DIR=str(work / "state"), NETWORKCLAW_PROVIDER_ENV_FILE=str(work / "fixture.env"),
                       POSTGRES_DB=database, POSTGRES_USER=os.environ.get("PGUSER", "ongrid"),
                       ONGRID_HTTP_ADDR=f"127.0.0.1:{ports['http']}", ONGRID_MODEL_CONFIG_TLS_ADDR=f"127.0.0.1:{ports['tls']}",
                       CHATRTMGR_GRPC_ADDR=f"127.0.0.1:{ports['grpc']}", ONGRID_METRICS_ADDR=f"127.0.0.1:{ports['lm']}",
                       CHATRTMGR_METRICS_ADDR=f"127.0.0.1:{ports['mm']}", NETWORKCLAW_WEB2_PORT=str(ports['web']),
                       ONGRID_WEB2_ORIGINS=origin, ONGRID_REDIS_ADDR=f"127.0.0.1:{ports['redis']}",
                       ONGRID_HARNESS_WORKSPACE_ROOT=str(work / "workspace"), ONGRID_GRPC_ADDR="127.0.0.1:0",
                       ONGRID_SEED_ADMIN_EMAIL="session-dev-admin", ONGRID_SEED_ADMIN_PASSWORD="session-dev-fixture-password",
                       OPENAI_API_KEY="session-dev-fixture-key", OPENAI_MODEL="fixture-model", OPENAI_MODELS="fixture-model",
                       OPENAI_BASE_URL=f"http://127.0.0.1:{ports['provider']}/v1", NETWORKCLAW_HARNESS_ALLOWED_EGRESS_HOSTS="127.0.0.1",
                       ONGRID_HARNESS_ALLOWED_TOOLS="networkclaw_workspace_read,skills_list,skill_view,delegate_task",
                       ONGRID_HARNESS_ALLOWED_SKILLS="workspace-inspection")
            for command in (["redis-server", "--bind", "127.0.0.1", "--port", str(ports['redis']), "--save", "", "--appendonly", "no"],
                            ["python3.12", str(ROOT / "tests/fixtures/provider_stub/server.py"), "--mode", "session-execution", "--port", str(ports['provider'])]):
                processes.append(subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True))
            try:
                result = subprocess.run(["make", "dev-up"], cwd=ROOT, env=env, capture_output=True, timeout=300)
                if result.returncode:
                    report["dev_up_diagnostic"] = result.stderr.decode("utf-8", "replace")[-800:]
                    raise RuntimeError("isolated_dev_up_failed")
                status, login = request_json(base + "/api/v1/auth/login", "POST", {"email": "session-dev-admin", "password": "session-dev-fixture-password"}, None, origin, 10)
                if status != 200:
                    raise RuntimeError("dev_login_failed")
                token = login["access_token"]
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    status, models = request_json(base + "/api/v1/models", "GET", None, token, origin, 10)
                    if status == 200 and models.get("models"):
                        break
                    time.sleep(.2)
                helpers["wait_for"](lambda: helpers["read_json"](f"http://127.0.0.1:{ports['mm']}/model-config/status")[1]['snapshot_revision'] >= models['snapshot_revision'], "dev_broker_not_converged", timeout=45)
                status, session = request_json(base + "/api/v1/sessions", "POST", {}, token, origin, 10)
                if status != 201:
                    raise RuntimeError("dev_no_profile_create_failed")
                status, reply = request_json(base + f"/api/v1/sessions/{session['session']['id']}/messages", "POST",
                    {"message": "ordinary-dev-up-turn", "model_config_id": models["models"][0]["id"]}, token, origin, 120)
                if status != 200 or "interop-ok" not in reply.get("reply", ""):
                    report["failed_turn"] = {"status": status, "code": reply.get("code"), "reason": reply.get("message")}
                    raise RuntimeError("dev_native_send_failed")
                report["checks"] = ["isolated_dev_up", "dev_no_profile_session", "dev_native_ordinary_turn", "dev_vite_ready"]
            finally:
                down = subprocess.run(["make", "dev-down"], cwd=ROOT, env=env, capture_output=True, timeout=60)
                if down.returncode:
                    report["dev_down_diagnostic"] = down.stderr.decode("utf-8", "replace")[-800:]
                    raise RuntimeError("isolated_dev_down_failed")
                if list((work / "state/pids").glob("*.pid")):
                    raise RuntimeError("dev_pid_residue")
                report["checks"].append("isolated_dev_down_clean")
        report["status"] = "passed"
    except (OSError, RuntimeError, subprocess.SubprocessError, KeyError) as error:
        report["reason_code"] = str(error) if isinstance(error, RuntimeError) else type(error).__name__
    finally:
        for process in processes:
            helpers["stop"](process)
        if created:
            subprocess.run(psql, input=f'DROP DATABASE "{database}" WITH (FORCE);', env=env, check=True, capture_output=True, text=True)
            report["database_removed"] = True
        path = ROOT / ".integration-state/evidence/session-dev-lifecycle.json"
        path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
