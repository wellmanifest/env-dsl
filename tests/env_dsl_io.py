"""Bounded regular-file I/O, document models, layering, and secret scanners for Env DSL 1."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

SYNTAX = "ENV-SYNTAX-001"
SEMANTIC = "ENV-SEMANTIC-001"
LAYER = "ENV-LAYER-001"
EXPRESSION = "ENV-EXPRESSION-001"
SECURITY = "ENV-SECURITY-001"

VERSION = "ENV_DSL_VERSION"
NAMESPACE = "ENV_DSL_NAMESPACE"
ENVIRONMENT = "ENV_DSL_ENVIRONMENT"
EXTENDS = "ENV_DSL_EXTENDS"
REQUIRED_HEADERS = (VERSION, NAMESPACE, ENVIRONMENT)
RESERVED_HEADERS = frozenset((*REQUIRED_HEADERS, EXTENDS))

MAX_ENV_FILE_BYTES = 4 * 1024 * 1024

SECRET_NAMES = frozenset(
    {
        "PASSWORD",
        "TOKEN",
        "SECRET",
        "PRI" + "VATE_KEY",
        "ACCESS_KEY",
        "API_KEY",
        "CREDENTIAL",
    }
)
SECRET_SUFFIXES = tuple(f"_{name}" for name in sorted(SECRET_NAMES))
HOST_CALL_MARKERS = (
    "re." + "compile(",
    "regexp.new(",
    "pattern.compile(",
    "regex.compile(",
    "eval(",
    "exec(",
    "system(",
)

_TOKEN_PREFIXES = (
    "gh" + "p_",
    "gh" + "o_",
    "gh" + "u_",
    "gh" + "s_",
    "gh" + "r_",
    "github_" + "pat_",
    "gl" + "pat-",
    "sk-",
    "xox" + "b-",
    "xox" + "p-",
    "xox" + "a-",
    "xox" + "r-",
    "xox" + "s-",
    "npm_",
    "pypi-",
)
_EMBEDDED_TOKEN_RE = re.compile(
    r"(?:^|[:/@?&=,;|+])(?:"
    + "|".join(re.escape(prefix) for prefix in _TOKEN_PREFIXES)
    + r")[A-Za-z0-9_-]{6,}",
    re.IGNORECASE,
)
_AWS_KEY_ID_RE = re.compile(
    r"(?:^|[^A-Z0-9])(?:AK" + r"IA|AS" + r"IA)[0-9A-Z]{16}(?:$|[^A-Z0-9])"
)
_JWT_RE = re.compile(
    r"(?:^|[:/@?&=,;|+])eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
)
_URI_USERINFO_SECRET_RE = re.compile(
    r"\A[A-Za-z][A-Za-z0-9+.-]*://[^/?#\s@]*:[^/?#\s@]+@"
)


def sanitize_diagnostic_text(value: str, *, max_len: int = 256) -> str:
    clipped = value[:max_len]
    out: list[str] = []
    for char in clipped:
        code = ord(char)
        if code < 0x20 or code == 0x7F:
            out.append(f"\\x{code:02x}")
        elif 0x80 <= code <= 0x9F or 0xD800 <= code <= 0xDFFF:
            out.append(char.encode("ascii", "backslashreplace").decode("ascii"))
        else:
            out.append(char)
    if len(value) > max_len:
        out.append("...")
    return "".join(out)


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    path: str
    line: int = 0

    @property
    def help_path(self) -> str:
        root = "CRITICAL" if self.code == SECURITY else "ERROR"
        return f"docs/{root}/{self.code}.md"

    def render(self) -> str:
        safe_path = sanitize_diagnostic_text(self.path, max_len=512)
        safe_msg = sanitize_diagnostic_text(self.message, max_len=512)
        location = safe_path if self.line == 0 else f"{safe_path}:{self.line}"
        return f"{self.code} ERROR: {safe_msg} [{location}] help={self.help_path}"


@dataclass(frozen=True)
class Record:
    name: str
    value: str
    line: int


@dataclass(frozen=True)
class Document:
    path: str
    version: str
    namespace: str
    environment: str
    extends: str | None
    constants: dict[str, str]


def _check_no_symlink_path(path: str | Path) -> Path:
    raw_path = os.fspath(path)
    if not raw_path or "\x00" in raw_path:
        raise OSError("invalid file path")
    path_obj = Path(raw_path)
    if path_obj.is_absolute():
        cur = Path(path_obj.anchor)
        walk_parts = path_obj.parts[1:]
    else:
        cwd = Path.cwd()
        if len(cwd.parts) > 2 and cwd.is_symlink():
            raise OSError(f"symlink ancestor is forbidden: {cwd}")
        for anc in cwd.parents:
            if len(anc.parts) > 2 and anc.is_symlink():
                raise OSError(f"symlink ancestor is forbidden: {anc}")
        cur = cwd
        walk_parts = path_obj.parts
    for part in walk_parts:
        if part in ("", "."):
            continue
        if part == "..":
            cur = cur.parent
            continue
        cur = cur / part
        if len(cur.parts) > 2 and cur.is_symlink():
            raise OSError(f"symlink path component is forbidden: {cur}")
    abs_path = Path(os.path.abspath(raw_path))
    if abs_path.is_symlink():
        raise OSError(f"symlink path is forbidden: {path_obj}")
    for anc in abs_path.parents:
        if len(anc.parts) > 2 and anc.is_symlink():
            raise OSError(f"symlink ancestor is forbidden: {anc}")
    return abs_path


def read_regular_bytes(path: Path, max_bytes: int = MAX_ENV_FILE_BYTES) -> bytes:
    abs_path = _check_no_symlink_path(path)
    before = os.lstat(abs_path)
    if not stat.S_ISREG(before.st_mode):
        raise OSError("input must be a regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(os.fspath(abs_path), flags)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise OSError("input must be a regular file")
        if (before.st_dev, before.st_ino) != (st.st_dev, st.st_ino):
            raise OSError("file inode changed during open")
        if st.st_size > max_bytes:
            raise OSError("exceeds maximum byte budget")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise OSError("exceeds maximum byte budget")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def has_interpolation(value: str) -> bool:
    for index, char in enumerate(value[:-1]):
        if char != "$":
            continue
        following = value[index + 1]
        if (
            following in "({$@"
            or following == "_"
            or following.isalpha()
            or following.isdigit()
        ):
            return True
    return False


def secret_name(name: str) -> bool:
    return name in SECRET_NAMES or name.endswith(SECRET_SUFFIXES)


def secret_value(value: str) -> bool:
    lowered = value.lower()
    if (
        ("pri" + "vate-key") in lowered
        or ("pri" + "vate_key") in lowered
        or ("-----be" + "gin") in lowered
    ):
        return True
    if lowered.startswith(_TOKEN_PREFIXES):
        return True
    if value.startswith(("AK" + "IA", "AS" + "IA")) and len(value) >= 16:
        return True
    if _EMBEDDED_TOKEN_RE.search(value) or _AWS_KEY_ID_RE.search(value):
        return True
    return bool(_JWT_RE.search(value) or _URI_USERINFO_SECRET_RE.search(value))


def value_problem(value: str) -> str | None:
    if not value:
        return "value must not be empty"
    if any(ord(char) < 0x21 or ord(char) > 0x7E for char in value):
        return "value must contain only printable non-space ASCII"
    if '"' in value or "'" in value:
        return "quotes are not portable literal syntax"
    if "`" in value or "$(" in value or has_interpolation(value):
        return "evaluation, interpolation and command substitution are forbidden"
    lowered = value.lower()
    if any(marker in lowered for marker in HOST_CALL_MARKERS):
        return "host-language constructors and evaluators are forbidden"
    return None


def merge_documents(
    documents: Sequence[Document],
) -> tuple[dict[str, str], list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    if not documents:
        return {}, [Diagnostic(LAYER, "at least one document is required", "<chain>")]
    base = documents[0]
    if base.environment != "BASE" or base.extends is not None:
        diagnostics.append(
            Diagnostic(
                LAYER, "first document must be BASE without ENV_DSL_EXTENDS", base.path
            )
        )
    environments: set[str] = set()
    merged: dict[str, str] = {}
    previous: Document | None = None
    for document in documents:
        if document.environment in environments:
            diagnostics.append(
                Diagnostic(
                    LAYER,
                    f"environment appears more than once: {document.environment}",
                    document.path,
                )
            )
        environments.add(document.environment)
        if document.version != base.version or document.namespace != base.namespace:
            diagnostics.append(
                Diagnostic(
                    LAYER, "all layers must share version and namespace", document.path
                )
            )
        if previous is not None and document.extends != previous.environment:
            diagnostics.append(
                Diagnostic(
                    LAYER,
                    f"{document.environment} must extend immediate parent {previous.environment}",
                    document.path,
                )
            )
        merged.update(document.constants)
        previous = document
    return merged, diagnostics
