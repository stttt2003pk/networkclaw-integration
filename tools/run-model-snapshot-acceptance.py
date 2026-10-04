#!/usr/bin/env python3
"""Real 2 Lobby / 2 chatrtmgr / Gateway acceptance using disposable local fixtures."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import os
from pathlib import Path
import platform
import runpy
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from urllib.parse import urlparse

from deployment_smoke import request_json
from model_setup import runtime_environment, snapshot_secrets
from dev import run_local_migrations

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from support.process import ManagedProcess


def port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_for(check, reason: str, timeout: float = 40) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    raise RuntimeError(reason)


def read_json(url: str, headers: dict | None = None) -> tuple[int, dict | list, dict]:
    try:
        response = urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=5)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read()
        return response.status, json.loads(raw) if raw else {}, {key.lower(): value for key, value in response.headers.items()}


def stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        rows = subprocess.check_output(["ps", "-axo", "pid=,ppid="], text=True)
        parents = {int(pid): int(parent) for pid, parent in (row.split() for row in rows.splitlines())}
        descendants = {process.pid}
        while True:
            children = {pid for pid, parent in parents.items() if parent in descendants}
            if children <= descendants:
                break
            descendants.update(children)
        descendants.remove(process.pid)
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=35)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        def alive(pid):
            try:
                os.kill(pid, 0)
                return True
            except ProcessLookupError:
                return False
        try:
            wait_for(lambda: not any(alive(pid) for pid in descendants), "service_children_not_cleaned", timeout=5)
        except RuntimeError:
            for pid in descendants:
                if alive(pid):
                    os.kill(pid, signal.SIGKILL)
            raise


def acceptance(args, report: dict) -> None:
    go = args.networkclaw.resolve()
    harness = args.harness.resolve()
    environment = runtime_environment(dict(os.environ))
    real_config = None
    if args.real_gpt:
        from dotenv import dotenv_values
        source = dotenv_values(go / ".env")
        model = source.get("OPENAI_MODEL") or (source.get("OPENAI_MODELS") or "").split(",")[0].strip()
        key = source.get("OPENAI_API_KEY")
        endpoint = source.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        if not key or not model:
            raise RuntimeError("real_gpt_configuration_missing")
        real_config = {"model": model, "key": key, "endpoint": endpoint}
    # Only this randomly named database is created/dropped; shared Redis is never touched.
    database = "model_acceptance_" + uuid.uuid4().hex
    db_env = dict(environment, PGPASSWORD=os.environ.get("PGPASSWORD", "ongrid"))
    psql = ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1", "-U", os.environ.get("PGUSER", "ongrid")]

    def sql(statement: str, *, admin: bool = False) -> str:
        command = [*psql, "-At", "-d", "postgres" if admin else database]
        if admin and os.environ.get("MODEL_ACCEPTANCE_PGADMIN"):
            command = [*command, "-U", os.environ["MODEL_ACCEPTANCE_PGADMIN"]]
        result = subprocess.run(command, input=statement,
                                env=db_env, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError("fixture_database_operation_failed")
        return result.stdout.strip()

    sql(f'CREATE DATABASE "{database}" OWNER "{os.environ.get("PGUSER", "ongrid")}";', admin=True)
    try:
        with tempfile.TemporaryDirectory(prefix="ms-", dir="/tmp") as temporary, ExitStack() as stack:
            work = Path(temporary)
            private_values = ["model-fixture-v1", "model-fixture-v2"]
            if real_config:
                private_values.append(real_config["key"])
            secrets_dir = snapshot_secrets(work / "secrets")
            internal_token = (secrets_dir / "token").read_text().strip()
            private_values.append(internal_token)
            config = {"networkclaw": {"path": str(go)}}
            run_local_migrations(config, dict(db_env, POSTGRES_DB=database, POSTGRES_USER=os.environ.get("PGUSER", "ongrid")))
            result = subprocess.run(["make", "build-coordinator", "build-model-snapshot-probe", "GOFLAGS=-race", "BIN_DIR="+str(work)],
                                    cwd=go, env=environment, capture_output=True, timeout=300)
            if result.returncode:
                raise RuntimeError("acceptance_binaries_build_failed")

            processes = []
            def diagnostic(content: str) -> None:
                # Native stderr can contain user input. Keep protocol diagnostics
                # without preserving the turn text in exported evidence.
                content = "\n".join(line for line in content.splitlines() if "msg='" not in line)
                for secret in private_values:
                    content = content.replace(secret, "<redacted>")
                content = content.replace(str(work), "<fixture>")
                path = args.report.with_suffix(".probe.log")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)

            def spawn(name: str, command: list[str], env: dict) -> subprocess.Popen:
                log = stack.enter_context((work / (name + ".log")).open("wb"))
                process = subprocess.Popen(command, cwd=work, env=env, stdout=log, stderr=log, start_new_session=True)
                processes.append(process)
                stack.callback(stop, process)
                return process

            redis_port = port()
            spawn("redis", ["redis-server", "--bind", "127.0.0.1", "--port", str(redis_port),
                            "--save", "", "--appendonly", "no"], environment)
            providers = []
            for index in range(2):
                managed, ready = ManagedProcess.start_ready([sys.executable, str(ROOT / "tests/fixtures/provider_stub/server.py"),
                                                             "--mode", "session-execution" if args.session_execution else "delay", "--delay-ms", "1500" if index else "0"], env=environment)
                stack.callback(managed.close)
                providers.append("http://127.0.0.1:" + ready.decode().split()[1])

            browser_port = port() if args.browser else 5174
            web_origin = f"http://127.0.0.1:{browser_port}"
            lobby_ports = [port(), port()]
            grpc_ports = [port(), port()]
            metrics_ports = [port(), port()]
            # Local manager IDs are hostname based; public routing uses node 0's registry.
            registry = str(work / "manager-0.registry.json")
            common = dict(environment, PYTHONPATH=str(harness / "src"), HERMES_HOME=str(work / "hermes"),
                          NETWORKCLAW_HARNESS_PROFILE="development",
                          NETWORKCLAW_HARNESS_ALLOWED_EGRESS_HOSTS=",".join(["127.0.0.1"] +
                              ([urlparse(real_config["endpoint"]).hostname] if real_config else [])))
            if args.session_execution:
                release_tools = runpy.run_path(str(ROOT / "tools/capability-release.py"))
                agent_export = work / "empty-agents.json"
                agent_export.write_text(json.dumps({"schema_version":"networkclaw.agent-revision-export.v1","profiles":[]}))
                discovered = release_tools["discovery"](harness, go, agent_export)
                manifest = release_tools["compile_release"](discovered,release_tools["vendor_check"](harness),
                    release_id="cap-session-acceptance", target_os="macos" if sys.platform=="darwin" else "ubuntu",
                    target_version=platform.mac_ver()[0] if sys.platform=="darwin" else "22.04",
                    architecture="arm64" if platform.machine() in {"arm64","aarch64"} else "amd64",
                    session_platform="darwin-arm64" if sys.platform=="darwin" else "linux-amd64")
                checked=release_tools["check_release"](manifest,harness)
                if checked["status"]!="passed": raise RuntimeError("execution_release_check_failed")
                release_file=work / "execution-release.json"
                release_file.write_text(json.dumps(manifest))
                common["NETWORKCLAW_CAPABILITY_RELEASES"]=json.dumps([{"manifest":str(release_file),"asset_root":str(harness)}])
                common["ONGRID_HARNESS_ALLOWED_TOOLS"]="networkclaw_workspace_read,skills_list,skill_view,delegate_task"
                common["ONGRID_HARNESS_ALLOWED_SKILLS"]="workspace-inspection"
            manager_envs = []
            managers = []
            for index in range(2):
                (work / f"s{index}").mkdir(mode=0o700)
                env = dict(common, CHATRTMGR_PROCESS_TARGET="gateway", CHATRTMGR_GATEWAY_BINARY_PATH=str(harness / ".venv/bin/networkclaw-harness"),
                           CHATRTMGR_LOBBY_URL=f"http://127.0.0.1:{lobby_ports[index]}", CHATRTMGR_MODEL_CONFIG_TOKEN_FILE=str(secrets_dir / "token"),
                           CHATRTMGR_GRPC_ADDR=f"127.0.0.1:{grpc_ports[index]}", CHATRTMGR_METRICS_ADDR=f"127.0.0.1:{metrics_ports[index]}",
                           CHATRTMGR_SOCKET_DIR=str(work / f"s{index}"), CHATRTMGR_DISCOVERY_TYPE="local",
                           CHATRTMGR_LOCAL_REGISTRY_PATH=registry if args.session_execution else str(work / f"manager-{index}.registry.json"),
                           CHATRTMGR_NODE_ID=f"execution-node-{index}" if args.session_execution else "")
                manager_envs.append(env)
                managers.append(spawn(f"manager{index}", [str(work / "chatrtmgr")], env))
            status_urls = [f"http://127.0.0.1:{value}/model-config/status" for value in metrics_ports]
            for url in status_urls:
                try:
                    wait_for(lambda: read_json(url)[0] == 200, "manager_listener_missing")
                except RuntimeError:
                    diagnostic("\n".join(path.read_text(errors="replace") for path in work.rglob("*.log")))
                    raise
                if read_json(url)[1]["ready"]:
                    raise RuntimeError("manager_ready_without_lobby")
            report["checks"].append("manager_listeners_start_before_lobby")

            lobbies = []
            lobby_envs = []
            for index in range(2):
                env = dict(common, ONGRID_HTTP_ADDR=f"127.0.0.1:{lobby_ports[index]}", ONGRID_GRPC_ADDR=f"127.0.0.1:{port()}",
                           ONGRID_METRICS_ADDR=f"127.0.0.1:{port()}", LOBBY_MODEL_CONFIG_TOKEN_FILE=str(secrets_dir / "token"),
                           ONGRID_DB_HOST="127.0.0.1", ONGRID_DB_USER=os.environ.get("PGUSER", "ongrid"), ONGRID_DB_PASSWORD=db_env["PGPASSWORD"],
                           ONGRID_DB_NAME=database, ONGRID_DB_SSLMODE="disable", ONGRID_REDIS_ADDR=f"127.0.0.1:{redis_port}",
                           ONGRID_DISCOVERY_TYPE="local", ONGRID_LOCAL_REGISTRY_PATH=registry, ONGRID_JWT_SECRET="session-fixture-shared-jwt" if args.session_execution else uuid.uuid4().hex,
                           ONGRID_OIDC_SECRET_KEY="fixture-shared-encryption-key", ONGRID_WEB2_ORIGINS=web_origin,
                           ONGRID_SEED_ADMIN_EMAIL="model-admin", ONGRID_SEED_ADMIN_PASSWORD="model-admin-fixture-password",
                           ONGRID_HARNESS_ENABLED="true", ONGRID_HARNESS_ROLLOUT_PERCENT="100")
                env["ONGRID_HARNESS_WORKSPACE_ROOT"] = str(work / "user-workspaces")
                lobby_envs.append(env)
                lobbies.append(spawn(f"lobby{index}", [str(work / "lobby")], env))
                wait_for(lambda index=index: read_json(f"http://127.0.0.1:{lobby_ports[index]}/readyz")[0] == 200, "lobby_not_ready")

            base = f"http://127.0.0.1:{lobby_ports[0]}"
            status, login = request_json(base + "/api/v1/auth/login", "POST", {"email": "model-admin", "password": "model-admin-fixture-password"}, None, web_origin, 10)
            if status != 200 or not login.get("access_token"):
                raise RuntimeError("admin_login_failed")
            token = login["access_token"]
            private_values.append(token)

            def admin(path: str, method="GET", body=None):
                status, value = request_json(base + "/api/v1/admin/model-config/" + path, method, body, token, web_origin, 10)
                if not 200 <= status < 300:
                    raise RuntimeError("admin_model_configuration_http_" + str(status))
                return value

            connections = []
            models = []
            for index in range(2):
                connection = admin("connections", "POST", {"name": "fixture" + str(index), "provider_id": "openai", "api_mode": "chat_completions",
                                   "base_url": providers[index] + "/v1", "api_key": private_values[0], "timeout_seconds": 120, "enabled": True})
                connections.append(connection)
                models.append(admin("models", "POST", {"connection_id": connection["id"], "model_id": "gpt-5.5" if not index else "gpt-fixture-b", "display_name": "fixture" + str(index),
                              "enabled": True, "capabilities": {"context_tokens": 128000, "tools": True, "vision": False, "temperature": False,
                              "reasoning_efforts": ["low", "high"]}, "parameters": {}}))
            models.append(admin("models", "POST", {"connection_id": connections[1]["id"], "model_id": "gpt-5.5", "display_name": "fixture2",
                          "enabled": True, "capabilities": {"context_tokens": 128000, "tools": True, "vision": False, "temperature": False,
                          "reasoning_efforts": ["low", "high"]}, "parameters": {}}))
            admin("default", "PUT", {"model_config_id": models[0]["id"]})
            models = admin("models")["models"]
            connections = admin("connections")["connections"]
            models.sort(key=lambda item: item["display_name"])
            connections.sort(key=lambda item: item["name"])
            headers = {"Authorization": "Bearer " + internal_token}

            def snapshots():
                values = [read_json(f"http://127.0.0.1:{value}/internal/v1/model-config-snapshot", headers) for value in lobby_ports]
                if values[0][1] != values[1][1] or values[0][0] != 200 or values[1][0] != 200:
                    raise RuntimeError("lobby_snapshots_disagree")
                return values[0]

            _, snapshot, response_headers = snapshots()
            revision = snapshot["snapshot_revision"]
            if response_headers.get("cache-control") != "no-store":
                raise RuntimeError("snapshot_cache_control_missing")
            code, _, _ = read_json(base + "/internal/v1/model-config-snapshot", dict(headers, **{"If-None-Match": response_headers["etag"]}))
            if code != 304:
                raise RuntimeError("snapshot_304_missing")
            report["checks"].append("two_lobbies_consistent_snapshot_and_304")

            def converge():
                print("waiting for production snapshot polling", flush=True)
                started = time.monotonic()
                for url in status_urls:
                    wait_for(lambda url=url: read_json(url)[1]["snapshot_revision"] == revision, "snapshot_convergence_timeout")
                report["convergence_seconds"].append(round(time.monotonic() - started, 3))
            converge()
            report["checks"].append("production_30_second_polling_convergence")

            if args.session_execution:
                if args.browser:
                    spawn("web2", ["node", str(go / "web2/node_modules/vite/bin/vite.js"), str(go / "web2"), "--host", "127.0.0.1", "--strictPort"],
                          dict(common, NETWORKCLAW_WEB2_PORT=str(browser_port), NETWORKCLAW_WEB2_LOBBY_URL=base))
                    wait_for(lambda: read_json(web_origin + "/api/v1/auth/providers")[0] == 200, "browser_proxy_not_ready")
                def restart_manager(index):
                    stop(managers[index])
                    managers[index] = spawn(f"manager{index}-restarted", [str(work / "chatrtmgr")], manager_envs[index])
                    wait_for(lambda: read_json(status_urls[index])[1]['ready'], "restarted_manager_broker_not_ready")

                from session_execution_acceptance import run_public_sessions
                run_public_sessions(args, report, work=work, go=go, common=common, base=base,
                    lobby_ports=lobby_ports,token=token,manifest=manifest,models=models,providers=providers,
                    admin=admin,sql=sql,read_json=read_json,converge=converge,status_urls=status_urls,
                    diagnostic=diagnostic,real_config=real_config,private_values=private_values,origin=web_origin,restart_manager=restart_manager,grpc_ports=grpc_ports)
                for process in processes:
                    stop(process)
                if any(path.exists() for directory in (work / "s0", work / "s1") for path in directory.glob("*.sock")):
                    raise RuntimeError("gateway_socket_not_cleaned")
                for path in work.rglob("*.log"):
                    if any(secret.encode() in path.read_bytes() for secret in private_values):
                        raise RuntimeError("diagnostic_credential_leak")
                report["checks"].extend(["service_descendants_and_sockets_cleaned","diagnostics_no_credentials"])
                report["status"]="passed"
                report["scope"]="Two Lobby and two distinct managers with shared discovery; public no-Profile creation and admission; native deployed Skill, workspace Tool and delegation."
                return
            session = "session-" + uuid.uuid4().hex
            workspace = work / "workspace"
            workspace.mkdir()
            now = time.time()
            stamp = lambda offset: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + offset))
            lease = {"session_id": session, "owner_id": "owner", "lease_id": "lease", "lease_version": 1, "execution_epoch": 1,
                     "issued_at": stamp(0), "renew_by": stamp(1200), "expires_at": stamp(1800), "grace_expires_at": stamp(1860),
                     "ttl_ms": 1800000, "renew_interval_ms": 1200000, "grace_ms": 60000}
            sql(f"INSERT INTO sessions(id,tenant_id,user_id) VALUES('{session}','fixture',1); INSERT INTO harness_session_leases "
                "(tenant_id,session_id,owner_id,lease_id,lease_version,execution_epoch,issued_at,renew_by,expires_at,grace_expires_at) "
                f"VALUES('fixture','{session}','owner','lease',1,1,now(),now()+interval '20 minutes',now()+interval '30 minutes',now()+interval '31 minutes');")

            run_processes = {}

            def probe(index: int, model: dict, label: str, *, new_admission=True, effort="low", maximum=64, user_id="fixture-user", create_only=False):
                run = "run-" + label
                turn = "turn-" + label
                request = {"session_id": session, "message": "Reply with a short fixture response", "execution_path": "harness", "zero_tools": True,
                           "model_config_id": model["id"], "model_config_revision": model["config_revision"], "credential_revision": model["credential_revision"],
                           "model_parameters": {"max_output_tokens": maximum, **({"reasoning_effort": effort} if effort else {})},
                           "harness": {"tenant_id": "fixture", "user_id": user_id, "owner_id": "owner", "execution_epoch": 1,
                           "turn_id": turn, "run_id": run, "process_id": run_processes.get(run, "") if not new_admission else "", "lease": lease, "workspace_root": str(workspace), "profile_id": "development", "agent_id": "fixture-agent",
                           "host_grant": {"session_id": session, "execution_epoch": 1, "workspace": str(workspace), "resource_profile": "development",
                           "turn_budget": {"max_steps": 8, "max_retries": 2, "max_actions": 8, "timeout_seconds": 120}, "allowed_tools": []}}}
                input_path, output_path = work / (label + ".request.json"), work / (label + ".result.json")
                input_path.write_text(json.dumps(request))
                result = subprocess.run([str(work / "probe"), "-test.run=^TestModelSnapshotDistributedProbe$"], cwd=go,
                                        env=dict(common, MODEL_SNAPSHOT_PROBE_ENDPOINT=f"127.0.0.1:{grpc_ports[index]}",
                                        MODEL_SNAPSHOT_PROBE_CREATE_ONLY="1" if create_only else "0",
                                        MODEL_SNAPSHOT_PROBE_INPUT=str(input_path), MODEL_SNAPSHOT_PROBE_OUTPUT=str(output_path)),
                                        capture_output=True, timeout=200)
                if result.returncode:
                    diagnostic((result.stdout + result.stderr).decode("utf-8", "replace"))
                    raise RuntimeError("grpc_probe_failed")
                value = json.loads(output_path.read_text())
                if new_admission and not create_only:
                    run_processes[run] = value["service_id"]
                if any(secret in json.dumps(value) for secret in private_values):
                    raise RuntimeError("public_response_credential_leak")
                return value

            def success(value, reason):
                if value["errors"] or not value["done"] or not value["has_content"]:
                    # Error bodies are private diagnostics; only stable codes leave the fixture.
                    diagnostic(json.dumps(value) + "\n" + "\n".join(path.read_text(errors="replace") for path in work.rglob("*.log")))
                    raise RuntimeError(reason)

            def requests(index):
                return [value for value in read_json(providers[index] + "/__fixture/events")[1] if value["event"] == "provider.request_received"]

            user, tenant = sql("SELECT id,tenant_id FROM users WHERE email='model-admin'").split("|")
            owned_session = "owned-" + uuid.uuid4().hex
            service = probe(0, models[0], "public-service", user_id=user, create_only=True)["service_id"]
            manager_id = next(iter(json.loads(Path(registry).read_text())["services"]))
            sql(f"INSERT INTO sessions(id,tenant_id,user_id,status,runtime_manager_id,chat_service_id,agent_id) "
                f"VALUES('{owned_session}','{tenant}','{user}','running','{manager_id}','{service}','fixture-agent');")

            def public_message(model):
                return request_json(base + f"/api/v1/sessions/{owned_session}/messages", "POST",
                    {"message": "Reply with a short fixture response", "model_config_id": model["id"],
                     "model_parameters": {"max_output_tokens": 64, "reasoning_effort": "low"}},
                    token, "http://127.0.0.1:5174", 120)

            code, value = public_message(models[0])
            if code != 200 or not requests(0):
                diagnostic(json.dumps(value) + "\n" + "\n".join(path.read_text(errors="replace") for path in work.rglob("*.log")))
                raise RuntimeError("public_http_turn_failed")
            ws_input, ws_output = work / "ws.request.json", work / "ws.result.json"
            ws_input.write_text(json.dumps({"session_id": owned_session, "message": "Reply with a short fixture response",
                                           "model_config_id": models[1]["id"], "model_parameters": {"reasoning_effort": "high", "max_output_tokens": 96}}))
            result = subprocess.run([str(work / "probe"), "-test.run=^TestModelSnapshotWebSocketProbe$"], cwd=go,
                env=dict(common, MODEL_SNAPSHOT_PROBE_WS=base.replace("http:", "ws:") + "/ws",
                         MODEL_SNAPSHOT_PROBE_TOKEN=token, MODEL_SNAPSHOT_PROBE_INPUT=str(ws_input),
                         MODEL_SNAPSHOT_PROBE_OUTPUT=str(ws_output)), capture_output=True, timeout=150)
            if result.returncode:
                diagnostic((result.stdout + result.stderr).decode("utf-8", "replace"))
                raise RuntimeError("public_websocket_probe_failed")
            success(json.loads(ws_output.read_text()), "public_websocket_turn_failed")
            if requests(1)[-1]["model"] != models[1]["model_id"]:
                raise RuntimeError("public_model_selection_not_forwarded")
            report["checks"].extend(["user_http_model_selection", "user_websocket_model_switch"])

            success(probe(0, models[0], "a"), "first_turn_failed")
            first = requests(0)[-1]
            success(probe(0, models[1], "b", effort="high", maximum=96), "model_switch_failed")
            second = requests(1)[-1]
            if (first["model"], second["model"], second["credential_revision"], second["reasoning_effort"], second["max_output_tokens"]) != ("gpt-5.5", "gpt-fixture-b", 1, "high", 96):
                diagnostic(json.dumps({"first": first, "second": second}))
                raise RuntimeError("provider_model_parameters_mismatch")
            if second["history_messages"] <= first["history_messages"]:
                raise RuntimeError("session_history_lost_on_model_switch")
            success(probe(1, models[0], "other-node"), "second_manager_turn_failed")
            success(probe(0, models[2], "same-name"), "same_name_connection_switch_failed")
            if requests(1)[-1]["model"] != "gpt-5.5":
                raise RuntimeError("same_name_connection_not_received")
            report["checks"].extend(["same_session_model_a_to_b_different_connection", "same_name_different_connections", "history_preserved", "two_managers_real_gateway_execution", "per_turn_parameters"])

            connection = connections[1]
            before = len(requests(1))
            with ThreadPoolExecutor(max_workers=1) as pool:
                active = pool.submit(probe, 0, models[1], "during-rotation")
                wait_for(lambda: len(requests(1)) > before, "inflight_turn_not_started")
                admin("connections/" + connection["id"], "PUT", {"name": connection["name"], "provider_id": "openai", "api_mode": "chat_completions",
                      "base_url": providers[1] + "/v1", "api_key": private_values[1], "timeout_seconds": 120, "enabled": True})
                success(active.result(), "inflight_turn_interrupted_by_rotation")
            if requests(1)[-1]["credential_revision"] != 1:
                raise RuntimeError("inflight_credential_changed")
            models = admin("models")["models"]
            rotated = next(model for model in models if model["display_name"] == "fixture1")
            _, snapshot, _ = snapshots()
            revision = snapshot["snapshot_revision"]
            rejected = probe(0, rotated, "before-sync")
            if not any("model_config_not_synced" in value for value in rejected["errors"]):
                raise RuntimeError("new_revision_executed_before_sync")
            converge()
            success(probe(0, rotated, "rotation"), "credential_rotation_failed")
            if requests(1)[-1]["credential_revision"] != 2:
                raise RuntimeError("credential_rotation_not_received")
            before = len(requests(1))
            replayed = probe(0, rotated, "during-rotation", new_admission=False)
            if replayed["errors"] or len(requests(1)) != before:
                raise RuntimeError("same_run_retry_reexecuted_after_rotation")
            report["checks"].extend(["inflight_turn_keeps_old_credentials", "same_run_retry_does_not_reexecute", "new_revision_rejected_before_sync", "credential_rotation_rebuild"])

            # A protocol edit must reach the native Hermes adapter, retaining Session history.
            connection = admin("connections/" + connections[0]["id"], "PUT", {
                "name": connections[0]["name"], "provider_id": "openai", "api_mode": "codex_responses",
                "base_url": providers[0] + "/v1", "timeout_seconds": 120, "enabled": True})
            protocol_model = next(value for value in admin("models")["models"] if value["id"] == models[0]["id"])
            _, snapshot, _ = snapshots()
            revision = snapshot["snapshot_revision"]
            converge()
            success(probe(0, protocol_model, "protocol-switch", effort="high", maximum=96), "protocol_switch_failed")
            received = requests(0)[-1]
            if (received["api_mode"], received["model"], received["credential_revision"], received["reasoning_effort"],
                received["max_output_tokens"]) != ("codex_responses", protocol_model["model_id"], 1, "high", 96):
                raise RuntimeError("protocol_parameters_not_received")
            if received["history_messages"] <= first["history_messages"]:
                raise RuntimeError("protocol_switch_lost_history")
            report["checks"].append("native_protocol_switch_with_history_and_parameters")

            stop(managers[0])
            managers[0] = spawn("manager0-restarted", [str(work / "chatrtmgr")], manager_envs[0])
            wait_for(lambda: read_json(status_urls[0])[1]["ready"], "manager_restart_not_ready")
            before = len(requests(1))
            lost = probe(0, rotated, "rotation", new_admission=False)
            if not any("model_config_pin_lost" in value for value in lost["errors"]) or len(requests(1)) != before:
                raise RuntimeError("restart_reexecuted_lost_pin")
            report["checks"].append("manager_restart_lost_pin_fails_closed")

            # Authorized Host turns use the fresh cache even while Lobby is unavailable.
            prior = read_json(status_urls[0])[1]
            stop(lobbies[0])
            success(probe(0, rotated, "snapshot-outage"), "fresh_cache_turn_requires_lobby")
            wait_for(lambda: read_json(status_urls[0])[1]["sync_failures"] > prior["sync_failures"], "sync_failure_not_observed")
            after = read_json(status_urls[0])[1]
            if after["snapshot_revision"] != prior["snapshot_revision"] or after["last_success"] != prior["last_success"]:
                raise RuntimeError("failed_sync_replaced_or_refreshed_snapshot")
            lobbies[0] = spawn("lobby0-recovered", [str(work / "lobby")], lobby_envs[0])
            wait_for(lambda: read_json(base + "/readyz")[0] == 200, "lobby_recovery_failed")
            wait_for(lambda: read_json(status_urls[0])[1]["last_success"] != prior["last_success"], "snapshot_recovery_failed")
            success(probe(0, rotated, "recovery"), "recovered_turn_failed")
            report["checks"].extend(["sync_failure_preserves_cache", "fresh_cache_admits_authorized_turn_without_lobby", "sync_recovery"])

            if real_config:
                print("running bounded real GPT turn through snapshot", flush=True)
                connection = admin("connections", "POST", {"name": "real-gpt-acceptance", "provider_id": "openai", "api_mode": "chat_completions",
                                   "base_url": real_config["endpoint"], "api_key": real_config["key"], "timeout_seconds": 120, "enabled": True})
                model = admin("models", "POST", {"connection_id": connection["id"], "model_id": real_config["model"], "display_name": "real-gpt-acceptance",
                              "enabled": True, "capabilities": {"context_tokens": 128000, "tools": False, "vision": False, "temperature": False, "reasoning_efforts": []}, "parameters": {}})
                real_model = next(value for value in admin("models")["models"] if value["id"] == model["id"])
                _, snapshot, _ = snapshots()
                revision = snapshot["snapshot_revision"]
                converge()
                success(probe(0, real_model, "real-gpt", effort=None, maximum=256), "real_gpt_turn_failed")
                report["checks"].append("real_gpt_snapshot_gateway_turn")

            # Lobby rejects disabled models immediately, before broker convergence.
            current_models = admin("models")["models"]
            before = sum(len(requests(index)) for index in range(2))
            for model in current_models:
                admin("models/" + model["id"], "PUT", {key: model[key] for key in
                      ("connection_id", "model_id", "display_name", "capabilities", "parameters")} | {"enabled": False})
            code, public = request_json(base + "/api/v1/models", "GET", None, token, None, 10)
            if code != 200 or public.get("models"):
                raise RuntimeError("disabled_models_remain_public")
            code, value = public_message(models[0])
            if code != 409 or "model_config_unavailable" not in json.dumps(value):
                raise RuntimeError("disabled_model_not_rejected_immediately")
            _, snapshot, _ = snapshots()
            if snapshot["models"]:
                raise RuntimeError("disabled_models_remain_in_snapshot")
            revision = snapshot["snapshot_revision"]
            converge()
            if any(read_json(url)[1]["ready"] for url in status_urls):
                raise RuntimeError("empty_snapshot_reports_ready")
            rejected = probe(0, models[0], "empty-snapshot")
            if not rejected["errors"] or sum(len(requests(index)) for index in range(2)) != before:
                raise RuntimeError("empty_snapshot_executed_model")
            for model in current_models:
                admin("models/" + model["id"], "DELETE")
            for connection in admin("connections")["connections"]:
                admin("connections/" + connection["id"], "DELETE")
            report["checks"].extend(["disabled_models_removed_from_public_list", "lobby_disable_rejects_before_sync",
                                      "valid_empty_snapshot_not_ready", "empty_snapshot_rejects_execution", "model_connection_delete"])

            for process in processes:
                stop(process)
            if any(path.exists() for directory in (work / "s0", work / "s1") for path in directory.glob("*.sock")):
                raise RuntimeError("gateway_socket_not_cleaned")
            report["checks"].append("service_descendants_and_sockets_cleaned")
            for path in work.rglob("*.log"):
                content = path.read_bytes()
                if any(secret.encode() in content for secret in private_values):
                    raise RuntimeError("diagnostic_credential_leak")
            report["checks"].append("diagnostics_and_public_results_no_credentials")
            report["scope"] = "Two Lobby/two managers/real Gateways; admin HTTP and user HTTP/WS admission. Session creation/ownership uses isolated SQL fixtures. Local node 1 is direct gRPC; shared two-node discovery is not covered."
            report["status"] = "passed"
        report["temporary_workspace_removed"] = not work.exists()
    finally:
        if 'work' in locals():
            report["temporary_workspace_removed"] = not work.exists()
        sql(f'DROP DATABASE "{database}" WITH (FORCE);', admin=True)
        report["isolated_database_removed"] = True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--networkclaw", type=Path, default=Path(os.environ.get("NETWORKCLAW_PATH", ROOT.parent / "NetworkClaw")))
    parser.add_argument("--harness", type=Path, default=Path(os.environ.get("HARNESS_PATH", ROOT.parent / "networkclaw-harness")))
    parser.add_argument("--report", type=Path, default=ROOT / ".integration-state/evidence/model-snapshot-acceptance.json")
    parser.add_argument("--real-gpt", action="store_true", help="Use existing Go .env GPT settings in the disposable database; never pass provider environment to children")
    parser.add_argument("--manager-restart", action="store_true", help="Kill/restart the assigned real manager; reject replay of the old run and recover native history on a new turn")
    parser.add_argument("--browser", action="store_true", help="Run actual Web2 login, no-Profile send and model switching with Playwright")
    parser.add_argument("--session-execution",action="store_true",help="Accept the profile-independent execution contract through public Session APIs")
    args = parser.parse_args()
    args.report.with_suffix(".probe.log").unlink(missing_ok=True)
    report = {"schema_version": "session-execution-acceptance.v1" if args.session_execution else "model-snapshot-acceptance.v1", "status": "failed", "platform": platform.system().lower(),
              "architecture": platform.machine(), "checks": [], "convergence_seconds": []}
    try:
        acceptance(args, report)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report["reason_code"] = str(error) if isinstance(error, RuntimeError) else type(error).__name__
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
