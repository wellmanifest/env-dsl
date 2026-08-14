#!/usr/bin/env python3
"""Dependency-free deterministic conformance checker for Env DSL 1."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Iterable, Sequence


SYNTAX = "ENV-SYNTAX-001"
SEMANTIC = "ENV-SEMANTIC-001"
LAYER = "ENV-LAYER-001"
SECURITY = "ENV-SECURITY-001"

VERSION = "ENV_DSL_VERSION"
NAMESPACE = "ENV_DSL_NAMESPACE"
ENVIRONMENT = "ENV_DSL_ENVIRONMENT"
EXTENDS = "ENV_DSL_EXTENDS"
REQUIRED_HEADERS = (VERSION, NAMESPACE, ENVIRONMENT)
RESERVED_HEADERS = frozenset((*REQUIRED_HEADERS, EXTENDS))

SECRET_NAMES = frozenset(
    {
        "PASSWORD",
        "TOKEN",
        "SECRET",
        "PRIVATE_KEY",
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
        location = self.path if self.line == 0 else f"{self.path}:{self.line}"
        return f"{self.code} ERROR: {self.message} [{location}] help={self.help_path}"


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


def is_name(value: str) -> bool:
    if not value or not ("A" <= value[0] <= "Z"):
        return False
    if value[-1] == "_" or "__" in value:
        return False
    return all("A" <= char <= "Z" or "0" <= char <= "9" or char == "_" for char in value)


def has_interpolation(value: str) -> bool:
    for index, char in enumerate(value[:-1]):
        if char != "$":
            continue
        following = value[index + 1]
        if following in "({" or following == "_" or following.isalpha():
            return True
    return False


def secret_name(name: str) -> bool:
    return name in SECRET_NAMES or name.endswith(SECRET_SUFFIXES)


def secret_value(value: str) -> bool:
    lowered = value.lower()
    if "private-key" in lowered or "private_key" in lowered:
        return True
    if lowered.startswith(("ghp_", "github_pat_", "sk-")):
        return True
    return value.startswith("AKIA") and len(value) >= 16


def value_problem(value: str) -> str | None:
    if not value:
        return "value must not be empty"
    if any(ord(char) < 0x21 or ord(char) > 0x7E for char in value):
        return "value must contain only printable non-space ASCII"
    if "\"" in value or "'" in value:
        return "quotes are not portable literal syntax"
    if "`" in value or "$(" in value or has_interpolation(value):
        return "evaluation, interpolation and command substitution are forbidden"
    lowered = value.lower()
    if any(marker in lowered for marker in HOST_CALL_MARKERS):
        return "host-language constructors and evaluators are forbidden"
    return None


def parse_text(text: str, path: str = "<memory>") -> tuple[Document | None, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    if text.startswith("\ufeff"):
        diagnostics.append(Diagnostic(SYNTAX, "UTF-8 byte-order mark is forbidden", path, 1))
    if "\r" in text:
        diagnostics.append(Diagnostic(SYNTAX, "only LF line endings are canonical", path))
    if text and not text.endswith("\n"):
        diagnostics.append(Diagnostic(SYNTAX, "document must end with LF", path))

    records: list[Record] = []
    seen: dict[str, int] = {}
    for line_number, line in enumerate(text.split("\n")[:-1] if text.endswith("\n") else text.split("\n"), 1):
        if not line.strip(" ") or line.lstrip(" ").startswith("#"):
            if "\t" in line or any(ord(char) < 0x20 or ord(char) > 0x7E for char in line):
                diagnostics.append(Diagnostic(SYNTAX, "blank and comment lines must be printable ASCII without tabs", path, line_number))
            continue
        if line != line.strip() or "=" not in line:
            diagnostics.append(Diagnostic(SYNTAX, "expected exact SNAKE_CASE=value assignment", path, line_number))
            continue
        name, value = line.split("=", 1)
        if not is_name(name):
            diagnostics.append(Diagnostic(SYNTAX, f"invalid SNAKE_CASE name: {name or '<empty>'}", path, line_number))
            continue
        if name in seen:
            diagnostics.append(Diagnostic(SEMANTIC, f"duplicate name {name}; first declared on line {seen[name]}", path, line_number))
            continue
        seen[name] = line_number
        problem = value_problem(value)
        if problem:
            diagnostics.append(Diagnostic(SEMANTIC, f"{name}: {problem}", path, line_number))
        if secret_name(name) or secret_value(value):
            diagnostics.append(Diagnostic(SECURITY, f"secret material is forbidden: {name}", path, line_number))
        records.append(Record(name, value, line_number))

    names = [record.name for record in records]
    for index, required in enumerate(REQUIRED_HEADERS):
        if index >= len(records) or records[index].name != required:
            diagnostics.append(Diagnostic(SEMANTIC, f"header record {index + 1} must be {required}", path, records[index].line if index < len(records) else 0))

    by_name = {record.name: record for record in records}
    for name, record in by_name.items():
        if name.startswith("ENV_DSL_") and name not in RESERVED_HEADERS:
            diagnostics.append(Diagnostic(SEMANTIC, f"unknown reserved metadata name {name}", path, record.line))

    version = by_name.get(VERSION)
    namespace = by_name.get(NAMESPACE)
    environment = by_name.get(ENVIRONMENT)
    extends = by_name.get(EXTENDS)
    if version and version.value != "1":
        diagnostics.append(Diagnostic(SEMANTIC, "ENV_DSL_VERSION must equal 1", path, version.line))
    if namespace and not is_name(namespace.value):
        diagnostics.append(Diagnostic(SEMANTIC, "ENV_DSL_NAMESPACE value must be a valid name", path, namespace.line))
    if environment and not is_name(environment.value):
        diagnostics.append(Diagnostic(SEMANTIC, "ENV_DSL_ENVIRONMENT value must be a valid name", path, environment.line))
    if extends and not is_name(extends.value):
        diagnostics.append(Diagnostic(SEMANTIC, "ENV_DSL_EXTENDS value must be a valid name", path, extends.line))

    if environment:
        if environment.value == "BASE":
            if extends:
                diagnostics.append(Diagnostic(SEMANTIC, "BASE must not declare ENV_DSL_EXTENDS", path, extends.line))
        elif not extends:
            diagnostics.append(Diagnostic(SEMANTIC, "non-BASE environment must declare ENV_DSL_EXTENDS as record 4", path, environment.line))
        elif len(records) < 4 or records[3].name != EXTENDS:
            diagnostics.append(Diagnostic(SEMANTIC, "ENV_DSL_EXTENDS must be header record 4", path, extends.line))
        elif extends.value == environment.value:
            diagnostics.append(Diagnostic(SEMANTIC, "environment cannot extend itself", path, extends.line))

    if not version or not namespace or not environment:
        return None, diagnostics
    constants = {
        record.name: record.value
        for record in records
        if record.name not in RESERVED_HEADERS
    }
    document = Document(
        path=path,
        version=version.value,
        namespace=namespace.value,
        environment=environment.value,
        extends=extends.value if extends else None,
        constants=constants,
    )
    return document, diagnostics


def parse_file(path: Path) -> tuple[Document | None, list[Diagnostic]]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        return None, [Diagnostic(SYNTAX, f"cannot read document: {error}", path.as_posix())]
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        return None, [Diagnostic(SYNTAX, f"document is not UTF-8: {error}", path.as_posix())]
    return parse_text(text, path.as_posix())


def merge_documents(documents: Sequence[Document]) -> tuple[dict[str, str], list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    if not documents:
        return {}, [Diagnostic(LAYER, "at least one document is required", "<chain>")]
    base = documents[0]
    if base.environment != "BASE" or base.extends is not None:
        diagnostics.append(Diagnostic(LAYER, "first document must be BASE without ENV_DSL_EXTENDS", base.path))
    environments: set[str] = set()
    merged: dict[str, str] = {}
    previous: Document | None = None
    for document in documents:
        if document.environment in environments:
            diagnostics.append(Diagnostic(LAYER, f"environment appears more than once: {document.environment}", document.path))
        environments.add(document.environment)
        if document.version != base.version or document.namespace != base.namespace:
            diagnostics.append(Diagnostic(LAYER, "all layers must share version and namespace", document.path))
        if previous is not None and document.extends != previous.environment:
            diagnostics.append(Diagnostic(LAYER, f"{document.environment} must extend immediate parent {previous.environment}", document.path))
        merged.update(document.constants)
        previous = document
    return merged, diagnostics


def render_diagnostics(diagnostics: Iterable[Diagnostic]) -> None:
    for diagnostic in diagnostics:
        print(diagnostic.render())


def command_validate(paths: Sequence[Path]) -> int:
    diagnostics: list[Diagnostic] = []
    for path in paths:
        _, current = parse_file(path)
        diagnostics.extend(current)
    if diagnostics:
        render_diagnostics(diagnostics)
        print(f"ENV-FAIL: failed ({len(diagnostics)} errors)")
        return 1
    print(f"ENV-PASS: passed ({len(paths)} documents, 0 errors)")
    return 0


def command_merge(paths: Sequence[Path]) -> int:
    documents: list[Document] = []
    diagnostics: list[Diagnostic] = []
    for path in paths:
        document, current = parse_file(path)
        diagnostics.extend(current)
        if document:
            documents.append(document)
    if not diagnostics:
        merged, current = merge_documents(documents)
        diagnostics.extend(current)
    else:
        merged = {}
    if diagnostics:
        render_diagnostics(diagnostics)
        print(f"ENV-FAIL: failed ({len(diagnostics)} errors)")
        return 1
    for name in sorted(merged):
        print(f"{name}={merged[name]}")
    return 0


def command_self_test() -> int:
    valid = "ENV_DSL_VERSION=1\nENV_DSL_NAMESPACE=SELF_TEST\nENV_DSL_ENVIRONMENT=BASE\nDIGEST_PATTERN=^sha256:([a-f0-9]{64})$\n"
    _, diagnostics = parse_text(valid)
    invalid = valid + "HOME_VALUE=${HOME}\n"
    _, rejected = parse_text(invalid)
    if diagnostics or not any(item.code == SEMANTIC for item in rejected):
        print("ENV-SELF-TEST-FAIL")
        return 1
    print("ENV-SELF-TEST-PASS")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate Env DSL documents")
    validate.add_argument("paths", nargs="+", type=Path)
    merge = subparsers.add_parser("merge", help="validate and merge an explicit environment chain")
    merge.add_argument("paths", nargs="+", type=Path)
    subparsers.add_parser("self-test", help="run an embedded deterministic smoke test")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "validate":
        return command_validate(arguments.paths)
    if arguments.command == "merge":
        return command_merge(arguments.paths)
    return command_self_test()


if __name__ == "__main__":
    sys.exit(main())
