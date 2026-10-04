"""Verify a relocated capability export using only files in that directory."""

import sys
sys.dont_write_bytecode = True

import argparse
import hashlib
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator, ValidationError

from artifact_scan import scan_content
from capability_contract import release_hash


PAYLOADS = {
    "manifest/capability-release.v1.json", "reports/check.json", "reports/diff.json",
    "migration/migration-plan.json", "provenance/source-lock.json", "provenance/vendor.json",
    "provenance/published-release.json", "audit/compile.json", "audit/diff.json", "audit/export.json",
    "schemas/capability-release-v1.schema.json", "verify.py", "artifact_scan.py", "capability_contract.py",
}


def scan_document(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in {"body", "skill_body", "content", "transcript", "secret", "token", "password", "authorization", "api_key", "access_token", "client_secret", "provider_credential"}:
                raise ValueError("artifact_sensitive_content")
            if key == "path" and isinstance(child, str) and (".." in Path(child).parts or "\\" in child):
                raise ValueError("artifact_unsafe_path")
            scan_document(child)
    elif isinstance(value, list):
        for child in value:
            scan_document(child)
    elif isinstance(value, str):
        if value.startswith(("/", "file://")) or re.match(r"^[A-Za-z]:[\\/]", value):
            raise ValueError("artifact_absolute_path")
        scan_content("document", value.encode("utf-8"), Path("."))


def verify(root: Path) -> dict:
    if root.is_symlink():
        raise ValueError("artifact_unsafe_path")
    paths = list(root.rglob("*"))
    if any(path.is_symlink() or not (path.is_file() or path.is_dir()) for path in paths):
        raise ValueError("artifact_unsafe_path")
    files = {path.relative_to(root).as_posix() for path in paths if path.is_file()}
    if files != PAYLOADS | {"checksums.sha256"}:
        raise ValueError("artifact_file_set_mismatch")
    records = {}
    for line in (root / "checksums.sha256").read_text(encoding="ascii").splitlines():
        digest, separator, relative = line.partition("  ")
        if not separator or not re.fullmatch(r"[0-9a-f]{64}", digest) or relative not in PAYLOADS or relative in records:
            raise ValueError("checksum_invalid")
        records[relative] = digest
    if set(records) != PAYLOADS:
        raise ValueError("artifact_file_set_mismatch")
    for relative, digest in records.items():
        data = (root / relative).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("checksum_mismatch")
        scan_content(relative, data, root)

    def read(relative: str) -> dict:
        value = json.loads((root / relative).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("artifact_document_invalid")
        scan_document(value)
        return value

    manifest = read("manifest/capability-release.v1.json")
    schema = json.loads((root / "schemas/capability-release-v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(manifest)
    if release_hash(manifest) != manifest["release_hash"]:
        raise ValueError("release_hash_invalid")
    check = read("reports/check.json")
    diff = read("reports/diff.json")
    identity = {"release_id": manifest["release_id"], "release_hash": manifest["release_hash"]}
    if check.get("status") != "passed" or check.get("manifest_hash") != manifest["release_hash"] or check.get("errors") != [] or not check.get("checks") or not all(check["checks"].values()):
        raise ValueError("check_failed")
    if diff.get("status") != "passed" or diff.get("candidate") != identity:
        raise ValueError("diff_failed")
    published = read("provenance/published-release.json")
    Draft202012Validator(schema).validate(published)
    if published["release_hash"] != release_hash(published) or diff.get("published") != {"release_id": published["release_id"], "release_hash": published["release_hash"]}:
        raise ValueError("published_snapshot_invalid")
    if read("migration/migration-plan.json") != diff.get("migration"):
        raise ValueError("migration_mismatch")
    source_lock = read("provenance/source-lock.json")
    if source_lock != {"schema_version": "capability-release-sources.v1", "sources": manifest["sources"], "protocol": manifest["protocol"], "target": manifest["target"]}:
        raise ValueError("source_lock_mismatch")
    vendor = read("provenance/vendor.json")
    if any(vendor.get(key) != value for key, value in manifest["hermes"].items()):
        raise ValueError("vendor_provenance_mismatch")
    for operation in ("compile", "diff", "export"):
        audit = read(f"audit/{operation}.json")
        if set(audit) != {"schema_version", "operation", "release_id", "manifest_hash", "sources", "operator", "job_id", "status", "reason_code", "result"} or audit.get("schema_version") != "capability-release-audit.v1":
            raise ValueError("audit_invalid")
        if audit.get("operation") != operation or audit.get("status") != "passed" or audit.get("reason_code") is not None or audit.get("result") != {"compile": "compiled", "diff": "compared", "export": "exported"}[operation]:
            raise ValueError("audit_invalid")
        if audit.get("release_id") != manifest["release_id"] or audit.get("manifest_hash") != manifest["release_hash"] or audit.get("sources") != manifest["sources"]:
            raise ValueError("audit_mismatch")
        if not all(isinstance(audit.get(field), str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}", audit[field]) for field in ("operator", "job_id")):
            raise ValueError("audit_identity_invalid")
    return {"schema_version": "capability-release-export-verify.v1", "status": "passed", "manifest_hash": manifest["release_hash"], "file_count": len(records), "checksum_hash": "sha256:" + hashlib.sha256((root / "checksums.sha256").read_bytes()).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", nargs="?", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.artifact), sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, ValidationError) as exc:
        print(json.dumps({"status": "failed", "reason_code": str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else "artifact_invalid"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
