"""Local Snapshot transport provisioning and first-install admin bootstrap."""

from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path

if __package__:
    from .deployment_smoke import request_json
else:
    from deployment_smoke import request_json


def runtime_environment(env: dict[str, str]) -> dict[str, str]:
    """Provider values are bootstrap input, never child-process configuration."""
    return {key: value for key, value in env.items()
            if not key.startswith(("OPENAI_", "ZHIPU_", "ANTHROPIC_", "GEMINI_"))
            and key not in {"GOOGLE_API_KEY", "NETWORKCLAW_HARNESS_ALLOWED_MODELS"}}


def snapshot_secrets(directory: Path, dns_names: tuple[str, ...] = ("localhost", "lobby"), *, container_readable: bool = False) -> Path:
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    token = directory / "token"
    if not token.exists():
        with os.fdopen(os.open(token, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as stream:
            stream.write(secrets.token_urlsafe(48) + "\n")
    token.chmod(0o600)
    if any(not re.fullmatch(r"[A-Za-z0-9.-]+", name) for name in dns_names):
        raise ValueError("invalid Snapshot certificate DNS name")
    complete = all((directory / name).is_file() for name in ("ca.pem", "cert.pem", "key.pem"))
    if complete and subprocess.run(["openssl", "x509", "-checkend", "86400", "-noout", "-in", str(directory / "cert.pem")],
                                   capture_output=True).returncode == 0:
        for name in ("token", "ca.pem", "cert.pem", "key.pem"):
            (directory / name).chmod(0o444 if container_readable else 0o600)
        return directory
    # OpenSSL is already used by the delivery tools; no crypto dependency required.
    with tempfile.TemporaryDirectory(prefix="tls-", dir=directory) as temporary:
        root = Path(temporary)
        config = root / "openssl.cnf"
        names = ",".join(f"DNS:{name}" for name in dns_names)
        config.write_text("[req]\nprompt=no\ndistinguished_name=dn\nx509_extensions=extensions\n"
                          "[dn]\nCN=NetworkClaw local Snapshot\n[extensions]\n"
                          f"subjectAltName={names},IP:127.0.0.1,IP:::1\n"
                          "basicConstraints=critical,CA:TRUE\nkeyUsage=critical,digitalSignature,keyEncipherment,keyCertSign\n"
                          "extendedKeyUsage=serverAuth\n")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30",
                        "-config", str(config), "-keyout", str(root / "key.pem"), "-out", str(root / "cert.pem")],
                       check=True, capture_output=True)
        for name in ("key.pem", "cert.pem", "ca.pem"):
            source = root / ("cert.pem" if name == "ca.pem" else name)
            source.chmod(0o600)
            shutil.copyfile(source, directory / name)
            (directory / name).chmod(0o444 if container_readable else 0o600)
    # Compose bind-mounted secrets retain host modes. The private 0700 parent
    # protects host access; readable files permit the non-root container UID.
    token.chmod(0o444 if container_readable else 0o600)
    return directory


def bootstrap_models(base: str, env: dict[str, str], *, origin: str | None = None) -> None:
    """Populate an empty store through Lobby, preserving existing administrator choices."""
    configured = []
    for provider, prefix, default_url in (("openai", "OPENAI", "https://api.openai.com/v1"),
                                          ("zhipu", "ZHIPU", "https://open.bigmodel.cn/api/paas/v4")):
        models = list(dict.fromkeys(item.strip() for item in
                      (env.get(prefix + "_MODELS") or env.get(prefix + "_MODEL", "")).split(",") if item.strip()))
        if models:
            if not env.get(prefix + "_API_KEY"):
                raise RuntimeError(f"{prefix}_API_KEY is required for model bootstrap")
            configured.append((provider, prefix, default_url, models))
    if not configured:
        return
    origin = origin or env.get("ONGRID_WEB2_ORIGINS", "http://127.0.0.1:5174").split(",")[0].strip()
    token = None

    def call(path: str, method: str = "GET", body: dict | None = None) -> dict:
        try:
            status, result = request_json(base.rstrip("/") + "/api/v1/" + path, method, body, token, origin, 15)
        except OSError:
            raise RuntimeError("model bootstrap request failed") from None
        if not 200 <= status < 300:
            # Do not propagate response bodies: they may contain provider details.
            raise RuntimeError(f"model bootstrap {method} {path}: HTTP {status}")
        return result

    login = call("auth/login", "POST", {"email": env.get("ONGRID_SEED_ADMIN_EMAIL", "admin"),
                                        "password": env.get("ONGRID_SEED_ADMIN_PASSWORD", "admin")})
    token = login.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("model bootstrap login returned no access token")
    admin = "admin/model-config/"
    if call(admin + "models").get("models"):
        print("model configurations already exist; bootstrap skipped")
        return
    default_id = ""
    for provider, prefix, default_url, models in configured:
        connection = call(admin + "connections", "POST", {
            "name": f"Local {provider}", "provider_id": provider,
            "api_mode": env.get(prefix + "_API_MODE", "chat_completions"),
            "base_url": env.get(prefix + "_BASE_URL") or default_url,
            "api_key": env[prefix + "_API_KEY"], "timeout_seconds": 120, "enabled": True,
        })
        for name in models:
            model = call(admin + "models", "POST", {
                "connection_id": connection["id"], "model_id": name, "display_name": name, "enabled": True,
                "capabilities": {"context_tokens": 128000, "tools": True, "vision": False,
                                 "temperature": not name.lower().startswith(("gpt-5", "o1", "o3", "o4")),
                                 "reasoning_efforts": ["none", "minimal", "low", "medium", "high", "xhigh", "max"]
                                 if name.lower().startswith(("gpt-5", "o1", "o3", "o4")) else []},
                "parameters": {},
            })
            if not default_id or name == env.get("OPENAI_MODEL"):
                default_id = model["id"]
    call(admin + "default", "PUT", {"model_config_id": default_id})
    print("local model configurations created through Lobby administrator API")
