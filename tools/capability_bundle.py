"""Validate the capability payload against its containing source bundle."""

import json

from jsonschema import Draft202012Validator

try:
    from capability_contract import release_hash
except ModuleNotFoundError:  # package import from tests
    from tools.capability_contract import release_hash

PREFIX = "integration/release/"
FILES = {
    "schemas/capability-release-v1.schema.json", "manifests/capability-release.v1.json",
    "reports/check.json", "reports/diff.json", "provenance/vendor-gate.json",
    "migration/plan.json", "migration/session-runbook.md",
}


def validate(payload: dict[str, bytes], bundle: dict, schema: bytes, go_schema: bytes) -> dict:
    if set(payload) != {PREFIX + name for name in FILES}:
        raise ValueError("capability_payload_incomplete")
    if payload[PREFIX + "schemas/capability-release-v1.schema.json"] != schema or schema != go_schema:
        raise ValueError("capability_schema_drift")

    def read(name: str) -> dict:
        return json.loads(payload[PREFIX + name])

    manifest = read("manifests/capability-release.v1.json")
    Draft202012Validator(json.loads(schema)).validate(manifest)
    if manifest["release_hash"] != release_hash(manifest):
        raise ValueError("release_hash_invalid")
    check, diff, gate = read("reports/check.json"), read("reports/diff.json"), read("provenance/vendor-gate.json")
    identity = {"release_id": manifest["release_id"], "release_hash": manifest["release_hash"]}
    if check.get("status") != "passed" or check.get("manifest_hash") != manifest["release_hash"] or check.get("errors") != [] or not check.get("checks") or not all(value is True for value in check["checks"].values()):
        raise ValueError("capability_check_drift")
    if diff.get("status") != "passed" or diff.get("candidate") != identity or read("migration/plan.json") != diff.get("migration"):
        raise ValueError("capability_diff_drift")
    for name, source in bundle["sources"].items():
        release_source = manifest["sources"][name]
        if any(release_source[field] != value for field, value in {
            "tree_hash": "sha256:" + source["tree_sha256"], "commit": source["commit"],
            "dirty": bool(source["dirty"]), "diff_hash": "sha256:" + source["diff_sha256"] if source["diff_sha256"] else None,
        }.items()):
            raise ValueError("capability_source_drift:" + name)
    hermes = manifest["hermes"]
    expected = {
        "source_ref": bundle["hermes"]["upstream_ref"], "source_repository": bundle["hermes"]["upstream_repository"],
        "vendor_manifest_hash": "sha256:" + bundle["hermes"]["vendor_manifest_sha256"],
        "vendor_tree_hash": "sha256:" + bundle["sources"]["harness"]["vendor_tree_sha256"],
    }
    if hermes != expected or gate.get("status") != "passed" or any(
        gate["hermes"].get(key) != value for key, value in {
            "source_ref": hermes["source_ref"], "source_repository": hermes["source_repository"],
            "vendor_manifest_sha256": hermes["vendor_manifest_hash"][7:], "vendor_tree_sha256": hermes["vendor_tree_hash"][7:],
        }.items()
    ):
        raise ValueError("capability_vendor_drift")
    if manifest["protocol"]["host_protocol_version"] != bundle["protocol"]["version"] or any(manifest["target"].get(key) != value for key, value in bundle["target"].items()):
        raise ValueError("capability_target_drift")
    return {"manifest_hash": manifest["release_hash"], "files": sorted(payload)}
