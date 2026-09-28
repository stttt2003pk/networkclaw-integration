"""Shared source snapshot selection and hashing for doctor and bundle tools."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import subprocess


SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "node_modules", "dist", "build", "target", ".next", "bin",
    ".integration-state", "artifacts", "tmp", "htmlcov", ".cache",
    ".codebase-memory",
}
SKIP_FILES = {".DS_Store"}
SKIP_PATHS = {
    "sources.lock.yaml",
    ".claude/ecc/install-state.json",
    ".codebuddy/ecc-install-state.json",
    ".codebuddy/hooks/hooks.json",
}
SKIP_SUFFIXES = (".delivery.json", ".visual-check.json")
SECRET_NAME = re.compile(r"(^|/)\.env(?:\.[^/]+)?$", re.IGNORECASE)


def is_included_path(name: str) -> bool:
    rel = PurePosixPath(name)
    return not (
        any(part in SKIP_DIRS for part in rel.parts)
        or name in SKIP_FILES
        or name in SKIP_PATHS
        or name.endswith(SKIP_SUFFIXES)
        or SECRET_NAME.search(name)
    )


def included_files(root: Path) -> list[Path]:
    """Return tracked and non-ignored files, or a filtered source snapshot without Git."""
    root = root.resolve()
    try:
        repo = Path(subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip())
        rel_root = root.relative_to(repo).as_posix()
        args = ["git", "-C", str(repo), "ls-files", "-z", "-co", "--exclude-standard", "--"]
        if rel_root != ".":
            args.append(rel_root)
        raw_names = subprocess.check_output(args, stderr=subprocess.DEVNULL).split(b"\0")
        prefix = "" if rel_root == "." else rel_root + "/"
        result = []
        for raw_name in raw_names:
            if not raw_name:
                continue
            name = os.fsdecode(raw_name)
            if prefix:
                if not name.startswith(prefix):
                    continue
                name = name[len(prefix):]
            if not is_included_path(name):
                continue
            rel = PurePosixPath(name)
            path = root.joinpath(*rel.parts)
            if path.is_file() or path.is_symlink():
                result.append(path)
        return sorted(result, key=lambda item: item.relative_to(root).as_posix())
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        result = []
        for current, dirs, names in os.walk(root, followlinks=False):
            base = Path(current)
            dirs[:] = sorted(name for name in dirs if name not in SKIP_DIRS and not name.startswith(".codex-tmp"))
            for name in sorted(names):
                path = base / name
                rel = path.relative_to(root).as_posix()
                if not is_included_path(rel):
                    continue
                if path.is_symlink() or path.is_file():
                    result.append(path)
        return result


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hash(root: Path, files: list[Path] | None = None) -> str:
    root = root.resolve()
    digest = hashlib.sha256()
    for path in files if files is not None else included_files(root):
        rel = path.relative_to(root).as_posix().encode()
        digest.update(rel + b"\0")
        if path.is_symlink():
            digest.update(b"symlink\0" + os.readlink(path).encode() + b"\0")
        else:
            digest.update(b"755\0" if os.access(path, os.X_OK) else b"644\0")
            digest.update(bytes.fromhex(file_sha256(path)))
    return digest.hexdigest()


def git_diff_hash(root: Path) -> str | None:
    """Hash changed included files, excluding generated and secret paths."""
    try:
        changed = subprocess.check_output(
            ["git", "-C", str(root), "diff", "--name-only", "-z", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).split(b"\0")
        untracked = subprocess.check_output(
            ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard", "-z"],
            stderr=subprocess.DEVNULL,
        ).split(b"\0")
        names = sorted({name for name in (*changed, *untracked) if name and is_included_path(os.fsdecode(name))})
        if not names:
            return None
        digest = hashlib.sha256()
        for raw_name in names:
            name = os.fsdecode(raw_name)
            path = root / name
            digest.update(raw_name + b"\0")
            if path.is_file():
                digest.update(b"755\0" if os.access(path, os.X_OK) else b"644\0")
                digest.update(bytes.fromhex(file_sha256(path)))
            elif path.is_symlink():
                digest.update(b"symlink\0" + os.readlink(path).encode() + b"\0")
            else:
                digest.update(b"deleted\0")
        return digest.hexdigest()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
