#!/usr/bin/env python3
"""Explicit NetworkClaw admin release client; never used by ci-test."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


def contract_validator(fragment: str = "") -> Draft202012Validator:
    schema = json.loads((ROOT / "schemas/capability-release-admin-v1.schema.json").read_text(encoding="utf-8"))
    if fragment:
        schema = {**schema, "oneOf": [{"$ref": fragment}]}
    return Draft202012Validator(schema)


def validate_request(payload: dict) -> None:
    if not contract_validator().is_valid(payload):
        raise ValueError("request_invalid")
    if payload["operation"] == "import":
        schema = json.loads((ROOT / "schemas/capability-release-v1.schema.json").read_text(encoding="utf-8"))
        if not Draft202012Validator(schema).is_valid(payload["manifest"]):
            raise ValueError("release_schema_invalid")
        from capability_contract import release_hash
        if release_hash(payload["manifest"]) != payload["manifest"]["release_hash"]:
            raise ValueError("release_hash_invalid")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_endpoint(base_url: str) -> None:
    url = urlsplit(base_url)
    if url.username or url.password or url.query or url.fragment or url.path not in ("", "/"):
        raise ValueError("release_admin_endpoint_invalid")
    if not url.hostname or (url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"127.0.0.1", "::1", "localhost"})):
        raise ValueError("release_admin_endpoint_invalid")


def load_manifest(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != "capability-release.v1":
        raise ValueError("release_schema_invalid")
    if not isinstance(document.get("release_hash"), str):
        raise ValueError("release_hash_invalid")
    return document


def build_request(operation: str, job_id: str, manifest: dict | None = None, *, release_id: str = "", release_hash: str = "", expected_published_hash: str | None = None) -> dict:
    if operation == "import":
        if manifest is None:
            raise ValueError("request_invalid")
        return {"operation": operation, "job_id": job_id, "manifest": manifest}
    if operation not in {"publish", "rollback"} or not release_id or not release_hash:
        raise ValueError("request_invalid")
    return {"operation": operation, "job_id": job_id, "release_id": release_id, "release_hash": release_hash, "expected_published_hash": expected_published_hash}


def send(base_url: str, token: str, payload: dict, *, origin: str | None = None) -> tuple[int, dict]:
    validate_endpoint(base_url)
    validate_request(payload)
    if not token or any(char.isspace() for char in token):
        raise ValueError("release_admin_token_invalid")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if origin is not None:
        validate_endpoint(origin)
        headers["Origin"] = origin.rstrip("/")
    request = Request(base_url.rstrip("/") + "/api/v1/admin/capability-releases/actions", data=json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8"), headers=headers, method="POST")
    opener = build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=30) as response:
            status, body = response.status, response.read(1 << 20)
    except HTTPError as error:
        status, body = error.code, error.read(1 << 20)
    except URLError as error:
        raise RuntimeError("release_admin_unavailable") from error
    try:
        result = json.loads(body)
    except (ValueError, UnicodeError) as error:
        raise RuntimeError("release_admin_invalid_response") from error
    if not contract_validator("#/$defs/response").is_valid(result):
        raise RuntimeError("release_admin_invalid_response")
    receipt = result["data"]
    if receipt["operation"] != payload["operation"]:
        # Auth/schema failures have no trusted operation or manifest identity.
        if receipt["reason_code"] not in {"unauthorized", "forbidden", "request_invalid"}:
            raise RuntimeError("release_admin_invalid_response")
    expected = payload.get("manifest", payload)
    if result["code"] == "SUCCESS" and (
        not 200 <= status < 300 or receipt["reason_code"] is not None
        or receipt["release_id"] != expected["release_id"]
        or receipt["manifest_hash"] != expected["release_hash"]
    ):
        raise RuntimeError("release_admin_invalid_response")
    if result["code"] != "SUCCESS" and (200 <= status < 300 or receipt["reason_code"] is None):
        raise RuntimeError("release_admin_invalid_response")
    return status, result


def main() -> int:
    parser = argparse.ArgumentParser(description="explicit NetworkClaw capability release admin action")
    parser.add_argument("operation", choices=("import", "publish", "rollback"))
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token-env", default="NETWORKCLAW_ADMIN_TOKEN", help="environment variable holding a verified admin access token")
    parser.add_argument("--origin", default=os.environ.get("NETWORKCLAW_ADMIN_ORIGIN"), help="Origin allowed by Lobby CSRF configuration")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--release-id")
    parser.add_argument("--release-hash")
    parser.add_argument("--expected-published-hash")
    parser.add_argument("--execute", action="store_true", help="explicitly authorize this admin operation")
    args = parser.parse_args()
    try:
        if not args.execute:
            raise ValueError("controlled_release_required")
        manifest = load_manifest(args.manifest) if args.manifest else None
        if args.operation == "import" and (args.release_id or args.release_hash or args.expected_published_hash):
            raise ValueError("request_invalid")
        if args.operation != "import" and args.manifest:
            raise ValueError("request_invalid")
        payload = build_request(args.operation, args.job_id, manifest, release_id=args.release_id or "", release_hash=args.release_hash or "", expected_published_hash=args.expected_published_hash)
        status, response = send(args.base_url, os.environ.get(args.token_env, ""), payload, origin=args.origin)
    except (OSError, ValueError, RuntimeError) as error:
        allowed = {"controlled_release_required", "request_invalid", "release_schema_invalid", "release_hash_invalid", "release_admin_endpoint_invalid", "release_admin_token_invalid", "release_admin_invalid_response", "release_admin_unavailable"}
        reason = str(error) if str(error) in allowed else "release_admin_input_invalid"
        print(json.dumps({"status": "failed", "reason_code": reason}, sort_keys=True))
        return 2
    print(json.dumps(response, ensure_ascii=True, sort_keys=True))
    return 0 if 200 <= status < 300 else 1


if __name__ == "__main__":
    raise SystemExit(main())
