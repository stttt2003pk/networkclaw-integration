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
            if SECRET_NAME.search(name):
                raise ValueError(f"secret-like file is present in bundle: {member_name}")
            searchable = data.replace(b"\0", b"")
            if SECRET_CONTENT.search(searchable):
                raise ValueError(f"possible credential or private key found in bundle file: {member_name}")
            if any(
                match.group(1).lower() not in HOME_PLACEHOLDERS for match in ABSOLUTE_HOME.finditer(searchable)
            ):
                raise ValueError(f"local absolute home path found in bundle file: {member_name}")

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
