#!/usr/bin/env python3
"""Build a deterministic three-source NetworkClaw bundle and provenance manifest."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import sys
import io
from typing import Any

from source_tree import SKIP_DIRS, included_files, tree_hash, file_sha256, git_diff_hash

ROOT = Path(__file__).resolve().parents[1]
SECRET_NAME = re.compile(r"(^|/)(\.env|\.env\.[^/]+)$", re.IGNORECASE)
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


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL, text=True).strip()


def source_identity(name: str, root: Path, marker: str) -> tuple[dict[str, Any], list[Path]]:
    root = root.resolve()
    if not root.is_dir() or not (root / marker).is_file():
        raise ValueError(f"{name} source is unavailable or missing {marker}: {root}")
    files = included_files(root)
    for path in files:
        if path.is_symlink():
            target = os.readlink(path)
            if Path(target).is_absolute() or ".." in PurePosixPath(target).parts:
                raise ValueError(f"unsafe symlink in source tree: {path.relative_to(root).as_posix()}")
    identity: dict[str, Any] = {
        "path": name,
        "tree_sha256": tree_hash(root, files),
        "commit": None,
        "dirty": None,
        "diff_sha256": None,
        "customized": True,
    }
    try:
        identity["commit"] = git(root, "rev-parse", "HEAD")
        status = git(root, "status", "--porcelain", "--untracked-files=all")
        identity["dirty"] = bool(status)
        identity["customized"] = bool(status)
        identity["diff_sha256"] = git_diff_hash(root)
    except (subprocess.CalledProcessError, FileNotFoundError):
        identity["customized"] = True
    return identity, files


def source_roots(args: argparse.Namespace) -> dict[str, Path]:
    def resolve(path: Path) -> Path:
        return (ROOT / path).resolve() if not path.is_absolute() else path.resolve()

    return {
        "networkclaw": resolve(args.networkclaw),
        "harness": resolve(args.harness),
        "integration": resolve(args.integration),
    }


def validate_release(identities: dict[str, dict[str, Any]], lock_path: Path) -> None:
    if not lock_path.is_file():
        raise ValueError("--release requires sources.lock.yaml")
    try:
        import yaml
        lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"cannot read sources.lock.yaml: {exc}") from exc
    if not isinstance(lock, dict) or lock.get("schema_version") != 1 or lock.get("mode") != "checkout":
        raise ValueError("release lock must use schema_version 1 and mode checkout")
    for name, identity in identities.items():
        expected = lock.get(name)
        if not isinstance(expected, dict):
            raise ValueError(f"release lock is missing source {name}")
        if identity["dirty"] is not False or not identity["commit"]:
            raise ValueError(f"release source {name} must have Git metadata and a clean worktree")
        commit_mismatch = name != "integration" and expected.get("commit") != identity["commit"]
        if commit_mismatch or expected.get("tree_sha256") != identity["tree_sha256"]:
            raise ValueError(f"release source {name} does not match sources.lock.yaml commit/tree hash")
        repository = expected.get("repository")
        if not repository:
            raise ValueError(f"release lock source {name} must declare repository")
        identity["repository"] = repository
        identity["customized"] = False


def verify_harness_vendor(harness_root: Path) -> None:
    verifier = harness_root / "scripts" / "verify-hermes-vendor.py"
    if not verifier.is_file():
        raise ValueError("release source Harness is missing scripts/verify-hermes-vendor.py")
    try:
        subprocess.run([sys.executable, str(verifier)], cwd=harness_root, check=True)
    except subprocess.CalledProcessError as exc:
        raise ValueError("Harness Hermes vendor verification failed; release bundle is blocked") from exc


def hermes_metadata(harness_root: Path) -> dict[str, Any]:
    source_file = harness_root / "upstream" / "hermes-source.json"
    vendor_manifest = harness_root / "upstream" / "hermes-vendor-manifest.json"
    patch_dir = harness_root / "upstream" / "patches"
    if not source_file.is_file() or not vendor_manifest.is_file():
        raise ValueError("Harness Hermes upstream source and vendor manifest are required")
    source = json.loads(source_file.read_text(encoding="utf-8"))
    vendor = json.loads(vendor_manifest.read_text(encoding="utf-8"))
    if not source.get("commit") or not source.get("upstream_repository") or not vendor.get("patches"):
        raise ValueError("Harness Hermes provenance must declare upstream commit/repository and patch metadata")
    actual_patches = {
        path.name: file_sha256(path) for path in sorted(patch_dir.glob("*.patch"))
    } if patch_dir.is_dir() else {}
    declared_patches = vendor.get("patches")
    if not isinstance(declared_patches, list):
        raise ValueError("Harness Hermes vendor manifest patches must be a list")
    patches = sorted(declared_patches, key=lambda patch: patch.get("name", ""))
    expected_patches = [
        {"name": name, "sha256": digest} for name, digest in sorted(actual_patches.items())
    ]
    if patches != expected_patches:
        raise ValueError("Harness Hermes patch files do not match vendor manifest")
    return {
        "upstream_ref": source["commit"],
        "upstream_repository": source["upstream_repository"],
        "patches": patches,
        "vendor_manifest_sha256": file_sha256(vendor_manifest),
    }


def scan_content(rel: str, data: bytes, source_root: Path) -> None:
    if SECRET_NAME.search(rel):
        raise ValueError(f"secret-like file is not permitted in bundle: {rel}")
    if data.startswith((b"\x7fELF", b"MZ", b"\xcf\xfa\xed\xfe", b"PK\x03\x04")):
        return
    searchable = data.replace(b"\0", b"")
    if SECRET_CONTENT.search(searchable):
        raise ValueError(f"possible credential or private key found in bundle file: {rel}")
    if any(match.group(1).lower() not in HOME_PLACEHOLDERS for match in ABSOLUTE_HOME.finditer(searchable)):
        raise ValueError(f"local absolute home path found in bundle file: {rel}")


def source_date_epoch(roots: dict[str, Path]) -> int:
    override = os.environ.get("SOURCE_DATE_EPOCH")
    if override:
        return int(override)
    for root in (roots["integration"], roots["networkclaw"], roots["harness"]):
        try:
            return int(git(root, "show", "-s", "--format=%ct", "HEAD"))
        except (subprocess.CalledProcessError, ValueError):
            continue
    return 0


def file_records(roots: dict[str, Path], file_sets: dict[str, list[Path]]) -> dict[str, str]:
    records: dict[str, str] = {}
    for name, files in file_sets.items():
        prefix = {"networkclaw": "networkclaw", "harness": "networkclaw-harness", "integration": "integration"}[name]
        for path in files:
            rel = f"{prefix}/{path.relative_to(roots[name]).as_posix()}"
            if path.is_symlink():
                content = os.readlink(path).encode()
                scan_content(rel, content, roots[name])
                records[rel] = sha256(content)
            else:
                data = path.read_bytes()
                scan_content(rel, data, roots[name])
                records[rel] = sha256(data)
    return dict(sorted(records.items()))


def add_bytes(archive: tarfile.TarFile, name: str, data: bytes, epoch: int) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o644
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mtime = epoch
    archive.addfile(info, io.BytesIO(data))


def write_archive(output: Path, roots: dict[str, Path], file_sets: dict[str, list[Path]], manifest: dict[str, Any], epoch: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + ".tmp")
    try:
        with temp.open("wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0, compresslevel=9) as compressed:
                with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                    for name, files in file_sets.items():
                        prefix = {"networkclaw": "networkclaw", "harness": "networkclaw-harness", "integration": "integration"}[name]
                        for path in files:
                            rel = f"networkclaw-bundle/{prefix}/{path.relative_to(roots[name]).as_posix()}"
                            if path.is_symlink():
                                info = tarfile.TarInfo(rel)
                                info.type = tarfile.SYMTYPE
                                info.linkname = os.readlink(path)
                                info.mode = 0o777
                                info.uid = info.gid = 0
                                info.uname = info.gname = ""
                                info.mtime = epoch
                                archive.addfile(info)
                            else:
                                info = archive.gettarinfo(str(path), arcname=rel)
                                info.uid = info.gid = 0
                                info.uname = info.gname = ""
                                info.mtime = epoch
                                info.mode = 0o755 if os.access(path, os.X_OK) else 0o644
                                with path.open("rb") as stream:
                                    archive.addfile(info, stream)
                    add_bytes(archive, "networkclaw-bundle/manifest/bundle-manifest.json",
                              (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(), epoch)
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)


def sign_archive(output: Path, key: Path | None) -> str | None:
    if key is None:
        return None
    signature = output.with_suffix(output.suffix + ".sig")
    try:
        subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(key), "-out", str(signature), str(output)], check=True, capture_output=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        signature.unlink(missing_ok=True)
        raise ValueError("OpenSSL signing failed; verify openssl and the private key") from exc
    return signature.name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--networkclaw", type=Path, default=ROOT.parent / "NetworkClaw")
    parser.add_argument("--harness", type=Path, default=ROOT.parent / "networkclaw-harness")
    parser.add_argument("--integration", type=Path, default=ROOT)
    parser.add_argument("--sources-lock", type=Path, default=Path("sources.lock.yaml"))
    parser.add_argument("--output", type=Path, default=Path(".integration-state/artifacts/networkclaw-bundle.tar.gz"))
    parser.add_argument("--bundle-version", default="0.1.0-local")
    parser.add_argument("--target-os", default="ubuntu")
    parser.add_argument("--target-version", default="22.04")
    parser.add_argument("--target-architecture", default="amd64")
    parser.add_argument("--release", action="store_true", help="require clean sources matching sources.lock.yaml")
    parser.add_argument("--signing-key", type=Path, help="optional PEM private key for detached OpenSSL signature")
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    try:
        roots = source_roots(args)
        output_resolved = output.resolve()
        for root in roots.values():
            if output_resolved == root or root in output_resolved.parents:
                relative_parts = output_resolved.relative_to(root).parts
                if not any(part in SKIP_DIRS for part in relative_parts):
                    raise ValueError("bundle output inside a source tree must be under an excluded build/cache directory")
        markers = {"networkclaw": "go.mod", "harness": "pyproject.toml", "integration": "pyproject.toml"}
        identities: dict[str, dict[str, Any]] = {}
        file_sets: dict[str, list[Path]] = {}
        for name, root in roots.items():
            identities[name], file_sets[name] = source_identity(name, root, markers[name])
        if args.release:
            verify_harness_vendor(roots["harness"])
            lock_path = args.sources_lock
            if not lock_path.is_absolute():
                lock_path = roots["integration"] / lock_path
            validate_release(identities, lock_path)
        vendor_root = roots["harness"] / "vendor" / "hermes"
        vendor_files = [path for path in file_sets["harness"] if vendor_root in path.parents]
        identities["harness"]["vendor_tree_sha256"] = tree_hash(vendor_root, vendor_files) if vendor_root.is_dir() else None
        if identities["harness"]["vendor_tree_sha256"] is None:
            raise ValueError("Harness vendor/hermes tree is required")
        for name in ("networkclaw", "integration"):
            identities[name]["vendor_tree_sha256"] = None
        customized = not args.release
        epoch = source_date_epoch(roots)
        records = file_records(roots, file_sets)
        manifest = {
            "schema_version": 1,
            "bundle_version": args.bundle_version,
            "source_date_epoch": epoch,
            "customized": customized,
            "sources": identities,
            "hermes": hermes_metadata(roots["harness"]),
            "protocol": {"version": "1.0"},
            "target": {"os": args.target_os, "version": args.target_version, "architecture": args.target_architecture},
            "artifacts": {"files": records},
        }
        manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
        scan_content("manifest/bundle-manifest.json", manifest_bytes, roots["integration"])
        write_archive(output, roots, file_sets, manifest, epoch)
        archive_hash = file_sha256(output)
        checksum = output.with_suffix(output.suffix + ".sha256")
        checksum.write_text(f"{archive_hash}  {output.name}\n", encoding="ascii")
        output.with_suffix(output.suffix + ".sig").unlink(missing_ok=True)
        signature = sign_archive(output, args.signing_key)
        print(json.dumps({"archive": str(output), "sha256": archive_hash, "customized": customized,
                          "manifest": manifest, "checksum": str(checksum), "signature": signature},
                         ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"build-bundle: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
