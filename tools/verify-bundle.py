#!/usr/bin/env python3
"""Verify a NetworkClaw source bundle without consulting source worktrees."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile

from artifact_scan import scan_content
from capability_bundle import PREFIX, validate as validate_capability_bundle

ROOT = Path(__file__).resolve().parents[1]
SECRET_NAME = re.compile(r"(^|/)\.env(?:\.[^/]+)?$", re.IGNORECASE)
SECRET_CONTENT = re.compile(
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[ \t]*\r?\n"
    rb"(?:[A-Za-z0-9+/=]{40,}\r?\n)+"
    rb"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    rb"(?:api[_-]?key|access[_-]?token|client[_-]?secret)[ \t]*[:=][ \t]*"
    rb"(?:[\"'][A-Za-z0-9_+/=-]{24,}[\"']|(?=[A-Za-z0-9_+/=-]{24,}(?:[ \t\r\n]|$))"
    rb"(?=[A-Za-z0-9_+/=-]*[0-9+/=-])[A-Za-z0-9_+/=-]{24,})",
    re.IGNORECASE,
)
ABSOLUTE_HOME = re.compile(rb"/(?:Users|home)/([A-Za-z0-9_][A-Za-z0-9_.-]*)(?=/|[^A-Za-z0-9_.-]|$)")
HOME_PLACEHOLDERS = {
    b"user", b"you", b"example", b"test", b"runner", b"developer", b"username", b"yourname",
    b"alice", b"bob", b"charlie", b"ubuntu", b"root", b"ci", b"demo", b"u", b"x",
    b"<username>", b"<user>", b"<me>", b"cwd", b"explicit",
}
ABSOLUTE_HOME = re.compile(rb"/(?:Users|home)/([A-Za-z0-9_][A-Za-z0-9_.-]*)(?=/|[^A-Za-z0-9_.-]|$)")
MANIFEST_PATH = "networkclaw-bundle/manifest/bundle-manifest.json"
SCHEMA_PATH = "networkclaw-bundle/integration/schemas/bundle-manifest.schema.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def archive_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_archive_path(name: str) -> str:
    if "\\" in name:
        raise ValueError(f"archive contains a Windows-style path: {name}")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "networkclaw-bundle":
        raise ValueError(f"archive contains an unsafe or unexpected path: {name}")
    return path.as_posix()


def verify_signature(archive: Path, public_key: Path, signature: Path) -> None:
    if not signature.is_file():
        raise ValueError(f"signature file is missing: {signature}")
    try:
        subprocess.run(
            ["openssl", "dgst", "-sha256", "-verify", str(public_key), "-signature", str(signature), str(archive)],
            check=True, capture_output=True,
        )
    except FileNotFoundError as exc:
        raise ValueError("OpenSSL is required to verify a detached signature") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode(errors="replace").strip()
        raise ValueError(f"bundle signature verification failed: {detail or 'invalid signature'}") from exc


def verify(archive_path: Path, public_key: Path | None) -> dict[str, object]:
    archive_path = archive_path.resolve()
    checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    if not checksum_path.is_file():
        raise ValueError(f"checksum sidecar is missing: {checksum_path}")
    fields = checksum_path.read_text(encoding="ascii").strip().split()
    if len(fields) != 2 or fields[1] != archive_path.name:
        raise ValueError("checksum sidecar must contain the archive SHA-256 and matching filename")
    actual_archive_hash = archive_digest(archive_path)
    if fields[0] != actual_archive_hash:
        raise ValueError("archive checksum does not match sidecar")

    signature_path = archive_path.with_suffix(archive_path.suffix + ".sig")
    if public_key is not None:
        verify_signature(archive_path, public_key.resolve(), signature_path)

    try:
        import jsonschema
    except ImportError as exc:
        raise ValueError("jsonschema is required; run make bootstrap") from exc

    with tarfile.open(archive_path, "r:gz") as tar:
        members = tar.getmembers()
        by_name: dict[str, tarfile.TarInfo] = {}
        for member in members:
            name = validate_archive_path(member.name)
            if name in by_name:
                raise ValueError(f"archive contains duplicate path: {name}")
            if not (member.isfile() or member.isdir() or member.issym()):
                raise ValueError(f"archive contains unsupported entry type: {name}")
            if member.issym():
                target = PurePosixPath(member.linkname)
                if target.is_absolute() or ".." in target.parts or "\\" in member.linkname:
                    raise ValueError(f"archive contains an unsafe symlink: {name}")
            by_name[name] = member

        if MANIFEST_PATH not in by_name or SCHEMA_PATH not in by_name:
            raise ValueError("archive is missing its manifest or bundle schema")
        manifest_stream = tar.extractfile(by_name[MANIFEST_PATH])
        schema_stream = tar.extractfile(by_name[SCHEMA_PATH])
        if manifest_stream is None or schema_stream is None:
            raise ValueError("manifest and schema must be regular files")
        manifest = json.load(manifest_stream)
        manifest_data = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode()
        if SECRET_CONTENT.search(manifest_data.replace(b"\0", b"")):
            raise ValueError("possible credential or private key found in bundle manifest")
        if any(
            match.group(1).lower() not in HOME_PLACEHOLDERS
            for match in ABSOLUTE_HOME.finditer(manifest_data.replace(b"\0", b""))
        ):
            raise ValueError("local absolute home path found in bundle manifest")
        schema = json.load(schema_stream)
        jsonschema.Draft202012Validator.check_schema(schema)
        errors = sorted(
            jsonschema.Draft202012Validator(schema).iter_errors(manifest),
            key=lambda error: list(map(str, error.absolute_path)),
        )
        if errors:
            detail = "; ".join(
                f"{'.'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
                for error in errors
            )
            raise ValueError(f"bundle manifest does not match schema: {detail}")

        for source, marker in (("networkclaw", "go.mod"), ("harness", "pyproject.toml"), ("integration", "pyproject.toml")):
            relative = manifest["sources"][source]["path"]
            if Path(relative).is_absolute() or ".." in Path(relative).parts or f"networkclaw-bundle/{relative}/{marker}" not in by_name:
                raise ValueError(f"bundle source path does not locate {source}/{marker}")

        expected: dict[str, str] = manifest["artifacts"]["files"]
        actual_names = {
            name.removeprefix("networkclaw-bundle/")
            for name, member in by_name.items()
            if (member.isfile() or member.issym()) and name != MANIFEST_PATH
        }
        if actual_names != set(expected):
            missing = sorted(set(expected) - actual_names)
            extra = sorted(actual_names - set(expected))
            raise ValueError(f"manifest file list differs from archive (missing={missing}, extra={extra})")

        for name, expected_hash in expected.items():
            member_name = "networkclaw-bundle/" + name
            member = by_name[member_name]
            if member.issym():
                data = member.linkname.encode()
            else:
                stream = tar.extractfile(member)
                if stream is None:
                    raise ValueError(f"cannot read archive member: {member_name}")
                data = stream.read()
            if sha256(data) != expected_hash:
                raise ValueError(f"payload checksum mismatch: {member_name}")
            scan_content(member_name, data, Path("."))

        if "capability_release" in manifest:
            def read_payload(relative: str) -> bytes:
                stream = tar.extractfile("networkclaw-bundle/" + relative)
                if stream is None:
                    raise ValueError("capability_payload_incomplete")
                return stream.read()
            payload = {name: read_payload(name) for name in expected if name.startswith(PREFIX)}
            identity = validate_capability_bundle(payload, manifest,
                read_payload("integration/schemas/capability-release-v1.schema.json"),
                read_payload("networkclaw/api/lobby/v1/capability-release-v1.schema.json"))
            if identity != manifest["capability_release"]:
                raise ValueError("capability_bundle_identity_drift")

    return {
        "archive": str(archive_path),
        "sha256": actual_archive_hash,
        "customized": manifest["customized"],
        "bundle_version": manifest["bundle_version"],
        "sources": manifest["sources"],
        "signature_verified": public_key is not None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--public-key", type=Path, help="verify the adjacent .sig detached OpenSSL signature")
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.archive, args.public_key), ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError, tarfile.TarError) as exc:
        print(f"verify-bundle: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
