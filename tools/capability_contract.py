"""Shared canonicalization helpers for capability contract v1."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    payload = {key: value for key, value in snapshot.items() if key != "snapshot_hash"}
    return "sha256:" + hashlib.sha256(canonical_json(payload)).hexdigest()


def release_hash(release: dict[str, Any]) -> str:
    payload = {key: value for key, value in release.items() if key != "release_hash"}
    return "sha256:" + hashlib.sha256(canonical_json(payload)).hexdigest()
