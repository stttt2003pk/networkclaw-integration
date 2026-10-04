"""Shared delivery content checks; these also run in exported artifacts."""

import re
from pathlib import Path

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
    b"alice", b"bob", b"charlie", b"ubuntu", b"root", b"ci", b"demo", b"u", b"x", b"me", b"dashboard",
    b"<username>", b"<user>", b"<me>", b"cwd", b"explicit",
}


def scan_content(rel: str, data: bytes, source_root: Path) -> None:
    if SECRET_NAME.search(rel):
        raise ValueError(f"secret-like file is not permitted in bundle: {rel}")
    if data.startswith((b"\x7fELF", b"MZ", b"\xcf\xfa\xed\xfe", b"PK\x03\x04")):
        return
    # Hermes documentation uses GitHub's deliberately invalid placeholder token.
    # Keep scanning every other credential-shaped value.
    searchable = data.replace(b"\0", b"").replace(
        b'ACCESS_TOKEN: "ghp_xxxxxxxxxxxxxxxxxxxx"', b'ACCESS_TOKEN: ""'
    )
    if SECRET_CONTENT.search(searchable):
        raise ValueError(f"possible credential or private key found in bundle file: {rel}")
    if any(match.group(1).lower() not in HOME_PLACEHOLDERS for match in ABSOLUTE_HOME.finditer(searchable)):
        raise ValueError(f"local absolute home path found in bundle file: {rel}")
