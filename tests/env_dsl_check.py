#!/usr/bin/env python3
"""Dependency-free deterministic conformance checker for Env DSL 1."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from env_dsl_expr import (
    ExpressionError,
    ExpressionNode,
    ExpressionParser,
    Scalar,
    Token,
    analyze_equation_graph,
    coerce_constant,
    dependency_cycle,
    evaluate_node,
    expression_references,
    is_atom_char,
    is_equation,
    is_name,
    parse_expression,
    render_scalar,
    require_type,
    scalar_type,
    tokenize_expression,
)
from env_dsl_io import (
    ENVIRONMENT,
    EXPRESSION,
    EXTENDS,
    HOST_CALL_MARKERS,
    LAYER,
    NAMESPACE,
    REQUIRED_HEADERS,
    RESERVED_HEADERS,
    SECRET_NAMES,
    SECRET_SUFFIXES,
    SECURITY,
    SEMANTIC,
    SYNTAX,
    VERSION,
    Diagnostic,
    Document,
    Record,
    has_interpolation,
    merge_documents,
    read_regular_bytes,
    sanitize_diagnostic_text,
    secret_name,
    secret_value,
    value_problem,
)

__all__ = [
    "ENVIRONMENT",
    "EXPRESSION",
    "EXTENDS",
    "HOST_CALL_MARKERS",
    "LAYER",
    "NAMESPACE",
    "SECRET_NAMES",
    "SECRET_SUFFIXES",
    "SECURITY",
    "SEMANTIC",
    "SYNTAX",
    "VERSION",
    "Diagnostic",
    "Document",
    "ExpressionError",
    "ExpressionNode",
    "ExpressionParser",
    "Record",
    "Scalar",
    "Token",
    "coerce_constant",
    "dependency_cycle",
    "evaluate_constants",
    "evaluate_node",
    "expression_references",
    "has_interpolation",
    "is_atom_char",
    "is_equation",
    "is_name",
    "main",
    "merge_documents",
    "parse_expression",
    "parse_file",
    "parse_text",
    "read_regular_bytes",
    "render_scalar",
    "require_type",
    "scalar_type",
    "secret_name",
    "secret_value",
    "tokenize_expression",
    "value_problem",
]


def parse_text(
    text: str, path: str = "<memory>"
) -> tuple[Document | None, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    if text.startswith("\ufeff"):
        diagnostics.append(
            Diagnostic(SYNTAX, "UTF-8 byte-order mark is forbidden", path, 1)
        )
    if "\r" in text:
        diagnostics.append(
            Diagnostic(SYNTAX, "only LF line endings are canonical", path)
        )
    if text and not text.endswith("\n"):
        diagnostics.append(Diagnostic(SYNTAX, "document must end with LF", path))

    records: list[Record] = []
    seen: dict[str, int] = {}
    raw_lines = text.split("\n")[:-1] if text.endswith("\n") else text.split("\n")
    for line_number, line in enumerate(raw_lines, 1):
        if not line.strip(" ") or line.lstrip(" ").startswith("#"):
            if "\t" in line or any(
                ord(char) < 0x20 or ord(char) > 0x7E for char in line
            ):
                diagnostics.append(
                    Diagnostic(
                        SYNTAX,
                        "blank and comment lines must be printable ASCII without tabs",
                        path,
                        line_number,
                    )
                )
            continue
        if line != line.strip() or "=" not in line:
            diagnostics.append(
                Diagnostic(
                    SYNTAX,
                    "expected exact SNAKE_CASE=value assignment",
                    path,
                    line_number,
                )
            )
            continue
        name, value = line.split("=", 1)
        if not is_name(name):
            display_name = (
                sanitize_diagnostic_text(name, max_len=64) if name else "<empty>"
            )
            diagnostics.append(
                Diagnostic(
                    SYNTAX,
                    f"invalid SNAKE_CASE name: {display_name}",
                    path,
                    line_number,
                )
            )
            continue
        if name in seen:
            diagnostics.append(
                Diagnostic(
                    SEMANTIC,
                    f"duplicate name {name}; first declared on line {seen[name]}",
                    path,
                    line_number,
                )
            )
            continue
        seen[name] = line_number
        problem = value_problem(value)
        if problem:
            diagnostics.append(
                Diagnostic(SEMANTIC, f"{name}: {problem}", path, line_number)
            )
        elif is_equation(name):
            try:
                parse_expression(value)
            except ExpressionError as error:
                diagnostics.append(
                    Diagnostic(EXPRESSION, f"{name}: {error}", path, line_number)
                )
        if secret_name(name) or secret_value(value):
            diagnostics.append(
                Diagnostic(
                    SECURITY, f"secret material is forbidden: {name}", path, line_number
                )
            )
        records.append(Record(name, value, line_number))

    for index, required in enumerate(REQUIRED_HEADERS):
        if index >= len(records) or records[index].name != required:
            line_ref = records[index].line if index < len(records) else 0
            diagnostics.append(
                Diagnostic(
                    SEMANTIC,
                    f"header record {index + 1} must be {required}",
                    path,
                    line_ref,
                )
            )

    by_name = {record.name: record for record in records}
    for name, record in by_name.items():
        if name.startswith("ENV_DSL_") and name not in RESERVED_HEADERS:
            diagnostics.append(
                Diagnostic(
                    SEMANTIC,
                    f"unknown reserved metadata name {name}",
                    path,
                    record.line,
                )
            )

    version = by_name.get(VERSION)
    namespace = by_name.get(NAMESPACE)
    environment = by_name.get(ENVIRONMENT)
    extends = by_name.get(EXTENDS)
    if version and version.value != "1":
        diagnostics.append(
            Diagnostic(SEMANTIC, "ENV_DSL_VERSION must equal 1", path, version.line)
        )
    for hdr, label in (
        (namespace, "ENV_DSL_NAMESPACE"),
        (environment, "ENV_DSL_ENVIRONMENT"),
        (extends, "ENV_DSL_EXTENDS"),
    ):
        if hdr and not is_name(hdr.value):
            diagnostics.append(
                Diagnostic(
                    SEMANTIC, f"{label} value must be a valid name", path, hdr.line
                )
            )

    if environment:
        if environment.value == "BASE":
            if extends:
                diagnostics.append(
                    Diagnostic(
                        SEMANTIC,
                        "BASE must not declare ENV_DSL_EXTENDS",
                        path,
                        extends.line,
                    )
                )
        elif not extends:
            diagnostics.append(
                Diagnostic(
                    SEMANTIC,
                    "non-BASE environment must declare ENV_DSL_EXTENDS as record 4",
                    path,
                    environment.line,
                )
            )
        elif len(records) < 4 or records[3].name != EXTENDS:
            diagnostics.append(
                Diagnostic(
                    SEMANTIC,
                    "ENV_DSL_EXTENDS must be header record 4",
                    path,
                    extends.line,
                )
            )
        elif extends.value == environment.value:
            diagnostics.append(
                Diagnostic(
                    SEMANTIC, "environment cannot extend itself", path, extends.line
                )
            )

    if not version or not namespace or not environment:
        return None, diagnostics
    constants = {r.name: r.value for r in records if r.name not in RESERVED_HEADERS}
    return (
        Document(
            path=path,
            version=version.value,
            namespace=namespace.value,
            environment=environment.value,
            extends=extends.value if extends else None,
            constants=constants,
        ),
        diagnostics,
    )


def parse_file(path: Path) -> tuple[Document | None, list[Diagnostic]]:
    try:
        raw = read_regular_bytes(path)
    except OSError as error:
        return None, [
            Diagnostic(SYNTAX, f"cannot read document: {error}", path.as_posix())
        ]
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        return None, [
            Diagnostic(SYNTAX, f"document is not UTF-8: {error}", path.as_posix())
        ]
    return parse_text(text, path.as_posix())


def evaluate_constants(
    constants: dict[str, str],
    metadata: dict[str, str] | None = None,
    path: str = "<evaluation>",
) -> tuple[dict[str, Scalar], list[Diagnostic]]:
    sources = {**(metadata or {}), **constants}
    nodes: dict[str, ExpressionNode] = {}
    diagnostics: list[Diagnostic] = []
    for name, source in constants.items():
        if not is_equation(name):
            continue
        try:
            nodes[name] = parse_expression(source)
        except ExpressionError as error:
            diagnostics.append(Diagnostic(EXPRESSION, f"{name}: {error}", path))
    for name, node in nodes.items():
        for reference in sorted(expression_references(node)):
            if reference not in sources:
                msg = f"{name}: reference @{reference} is undefined after layering"
                diagnostics.append(Diagnostic(EXPRESSION, msg, path))
    cycle, topo_order = analyze_equation_graph(nodes)
    if cycle:
        diagnostics.append(
            Diagnostic(
                EXPRESSION, f"cyclic equation reference: {' -> '.join(cycle)}", path
            )
        )
    if diagnostics:
        return {}, diagnostics

    evaluated: dict[str, Scalar] = {}
    failed_equations: set[str] = set()

    def resolve_ready(name: str) -> Scalar:
        if name in evaluated:
            return evaluated[name]
        if name in failed_equations:
            raise ExpressionError(f"referenced equation @{name} failed evaluation")
        if name not in sources:
            raise ExpressionError(f"reference @{name} is undefined after layering")
        evaluated[name] = coerce_constant(sources[name])
        return evaluated[name]

    for name in topo_order:
        try:
            value = evaluate_node(nodes[name], resolve_ready)
            if name.endswith("_CONDITION") and type(value) is not bool:
                raise ExpressionError(
                    f"{name} must produce boolean, got {scalar_type(value)}"
                )
            evaluated[name] = value
        except ExpressionError as error:
            failed_equations.add(name)
            diagnostics.append(Diagnostic(EXPRESSION, f"{name}: {error}", path))

    for name in constants:
        if name not in evaluated and name not in failed_equations:
            try:
                evaluated[name] = coerce_constant(sources[name])
            except ExpressionError as error:
                diagnostics.append(Diagnostic(EXPRESSION, f"{name}: {error}", path))

    return {
        name: evaluated[name] for name in constants if name in evaluated
    }, diagnostics


def render_diagnostics(diagnostics: Iterable[Diagnostic]) -> None:
    for diagnostic in diagnostics:
        print(diagnostic.render())


def _load_chain(
    paths: Sequence[Path],
) -> tuple[list[Document], dict[str, str], list[Diagnostic]]:
    documents: list[Document] = []
    diagnostics: list[Diagnostic] = []
    for path in paths:
        document, current = parse_file(path)
        diagnostics.extend(current)
        if document:
            documents.append(document)
    if diagnostics:
        return documents, {}, diagnostics
    merged, layer_diags = merge_documents(documents)
    diagnostics.extend(layer_diags)
    return documents, merged, diagnostics


def command_validate(paths: Sequence[Path]) -> int:
    diagnostics = [diag for path in paths for diag in parse_file(path)[1]]
    if diagnostics:
        render_diagnostics(diagnostics)
        print(f"ENV-FAIL: failed ({len(diagnostics)} errors)")
        return 1
    print(f"ENV-PASS: passed ({len(paths)} documents, 0 errors)")
    return 0


def command_merge(paths: Sequence[Path]) -> int:
    _, merged, diagnostics = _load_chain(paths)
    if diagnostics:
        render_diagnostics(diagnostics)
        print(f"ENV-FAIL: failed ({len(diagnostics)} errors)")
        return 1
    for name in sorted(merged):
        print(f"{name}={merged[name]}")
    return 0


def command_evaluate(paths: Sequence[Path]) -> int:
    documents, merged, diagnostics = _load_chain(paths)
    evaluated: dict[str, Scalar] = {}
    if not diagnostics and documents:
        final = documents[-1]
        metadata = {
            VERSION: final.version,
            NAMESPACE: final.namespace,
            ENVIRONMENT: final.environment,
        }
        if final.extends:
            metadata[EXTENDS] = final.extends
        evaluated, eval_diags = evaluate_constants(merged, metadata, final.path)
        diagnostics.extend(eval_diags)
    if diagnostics:
        render_diagnostics(diagnostics)
        print(f"ENV-FAIL: failed ({len(diagnostics)} errors)")
        return 1
    for name in sorted(evaluated):
        print(f"{name}={render_scalar(evaluated[name])}")
    return 0


def command_self_test() -> int:
    valid = (
        "ENV_DSL_VERSION=1\nENV_DSL_NAMESPACE=SELF_TEST\n"
        "ENV_DSL_ENVIRONMENT=BASE\nLIMIT=3\n"
        "DOUBLE_EXPRESSION=@LIMIT*2\n"
        "READY_CONDITION=@DOUBLE_EXPRESSION==6&&@ENV_DSL_ENVIRONMENT==:BASE\n"
    )
    document, diagnostics = parse_text(valid)
    assert document is not None
    evaluated, expression_diagnostics = evaluate_constants(
        document.constants, {VERSION: "1", NAMESPACE: "SELF_TEST", ENVIRONMENT: "BASE"}
    )
    _, rejected = parse_text(valid + "HOME_VALUE=${HOME}\n")
    if (
        diagnostics
        or expression_diagnostics
        or evaluated.get("READY_CONDITION") is not True
        or not any(item.code == SEMANTIC for item in rejected)
    ):
        print("ENV-SELF-TEST-FAIL")
        return 1
    print("ENV-SELF-TEST-PASS")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for cmd, help_text in (
        ("validate", "validate Env DSL documents"),
        ("merge", "validate and merge an explicit environment chain"),
        ("evaluate", "validate, layer and evaluate portable equations"),
    ):
        sub = subparsers.add_parser(cmd, help=help_text)
        sub.add_argument("paths", nargs="+", type=Path)
    subparsers.add_parser("self-test", help="run an embedded deterministic smoke test")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "validate":
        return command_validate(arguments.paths)
    if arguments.command == "merge":
        return command_merge(arguments.paths)
    if arguments.command == "evaluate":
        return command_evaluate(arguments.paths)
    return command_self_test()


if __name__ == "__main__":
    sys.exit(main())
