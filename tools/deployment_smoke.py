#!/usr/bin/env python3
"""Small dependency-free smoke check for a deployed lobby and metrics endpoint."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from urllib.parse import urljoin


def get(url: str, timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "networkclaw-deployment-smoke/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(4096).decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read(4096).decode("utf-8", "replace")


def check_tcp(host: str, port: int, timeout: float) -> bool:
    with socket.create_connection((host, port), timeout=timeout):
        return True


def request_json(url: str, method: str, payload: dict[str, str] | None, token: str | None, origin: str | None, timeout: float) -> tuple[int, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        body = response.read(65536)
        value = json.loads(body) if body else {}
        return response.status, value if isinstance(value, dict) else {}


def check_session(base: str, origin: str, timeout: float) -> dict[str, bool]:
    token = os.environ.get("NETWORKCLAW_SMOKE_ACCESS_TOKEN", "")
    if not token:
        email = os.environ.get("NETWORKCLAW_SMOKE_EMAIL", "")
        password = os.environ.get("NETWORKCLAW_SMOKE_PASSWORD", "")
        if not email or not password:
            raise ValueError("set NETWORKCLAW_SMOKE_ACCESS_TOKEN or both NETWORKCLAW_SMOKE_EMAIL/PASSWORD")
        status, login = request_json(urljoin(base, "api/v1/auth/login"), "POST", {"email": email, "password": password}, None, origin, timeout)
        token = login.get("access_token", "")
        if status != 200 or not isinstance(token, str) or not token:
            raise RuntimeError(f"login returned HTTP {status}")

    session_id = ""
    try:
        status, created = request_json(urljoin(base, "api/v1/sessions"), "POST", {"title": "deployment-smoke"}, token, origin, timeout)
        session = created.get("session", {})
        if isinstance(session, dict):
            session_id = session.get("id", "")
        if status != 201 or not session_id:
            raise RuntimeError(f"session create returned HTTP {status}")
        if not session.get("runtime_manager_id") or not session.get("chat_service_id"):
            raise RuntimeError("session has no runtime manager or chat service binding")
        status, message = request_json(urljoin(base, f"api/v1/sessions/{session_id}/messages"), "POST",
                                      {"message": "Reply with exactly: deployment-smoke-ok"}, token, origin, timeout)
        reply = message.get("reply", "")
        if status != 200 or not isinstance(reply, str) or not reply.strip() or reply.startswith("[ERROR]"):
            raise RuntimeError(f"session message returned HTTP {status} without an assistant reply")
        return {"created": True, "bound": True, "closed": True}
    finally:
        if session_id:
            status, _ = request_json(urljoin(base, f"api/v1/sessions/{session_id}"), "DELETE", None, token, origin, timeout)
            if status != 200:
                raise RuntimeError(f"session cleanup returned HTTP {status}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="lobby base URL, for example http://127.0.0.1:8080")
    parser.add_argument("--metrics-url", help="optional lobby metrics URL")
    parser.add_argument("--chatrtmgr", help="optional host:port TCP check")
    parser.add_argument("--session", action="store_true", help="create and close a session using credentials from NETWORKCLAW_SMOKE_* environment variables")
    parser.add_argument("--origin", default="http://localhost:5174", help="Origin allowed by the lobby CSRF configuration")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    base = args.url.rstrip("/") + "/"
    checks: dict[str, object] = {}
    failures: list[str] = []
    for name, path in (("healthz", "healthz"), ("readyz", "readyz")):
        try:
            status, _ = get(urljoin(base, path), args.timeout)
            checks[name] = {"status": status}
            if status != 200:
                failures.append(f"{name}: expected HTTP 200, got {status}")
        except (OSError, ValueError, urllib.error.URLError):
            checks[name] = {"status": None}
            failures.append(f"{name}: connection failed")

    if args.metrics_url:
        try:
            status, body = get(args.metrics_url.rstrip("/") + "/metrics", args.timeout)
            checks["metrics"] = {"status": status}
            if status != 200 or not body.strip():
                failures.append(f"metrics: expected non-empty HTTP 200, got {status}")
        except (OSError, ValueError, urllib.error.URLError):
            checks["metrics"] = {"status": None}
            failures.append("metrics: connection failed")

    if args.chatrtmgr:
        try:
            host, port_text = args.chatrtmgr.rsplit(":", 1)
            check_tcp(host, int(port_text), args.timeout)
            checks["chatrtmgr"] = {"tcp": "open"}
        except (OSError, ValueError) as error:
            checks["chatrtmgr"] = {"tcp": "closed"}
            failures.append(f"chatrtmgr: {error}")

    if args.session:
        try:
            checks["session"] = check_session(base, args.origin, args.timeout)
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError, urllib.error.URLError) as error:
            checks["session"] = {"passed": False}
            failures.append(f"session: {error}")

    result = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
