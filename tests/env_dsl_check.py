#!/usr/bin/env python3
"""Dependency-free deterministic conformance checker for Env DSL 1."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Callable, Iterable, Sequence


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


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    position: int


@dataclass(frozen=True)
class ExpressionNode:
    kind: str
    value: str | int | bool
    left: ExpressionNode | None = None
    right: ExpressionNode | None = None


class ExpressionError(ValueError):
    pass


PRECEDENCE = {
    "||": 1,
    "&&": 2,
    "==": 3,
    "!=": 3,
    "<": 4,
    "<=": 4,
    ">": 4,
    ">=": 4,
    "+": 5,
    "-": 5,
    "*": 6,
    "/": 6,
    "%": 6,
}
MULTI_OPERATORS = ("&&", "||", "==", "!=", "<=", ">=")
SINGLE_OPERATORS = frozenset("+-*/%!<>")
STRING_DELIMITERS = frozenset("&|=!<>()+-*/%")


def is_name(value: str) -> bool:
    if not value or not ("A" <= value[0] <= "Z"):
        return False
    if value[-1] == "_" or "__" in value:
        return False
    return all("A" <= char <= "Z" or "0" <= char <= "9" or char == "_" for char in value)


def is_equation(name: str) -> bool:
    return name.endswith("_EXPRESSION") or name.endswith("_CONDITION")


def tokenize_expression(source: str) -> list[Token]:
    tokens: list[Token] = []
    index = 0
    while index < len(source):
        position = index + 1
        matched = next((item for item in MULTI_OPERATORS if source.startswith(item, index)), None)
        if matched:
            tokens.append(Token("OP", matched, position))
            index += len(matched)
            continue
        char = source[index]
        if char == "(":
            tokens.append(Token("LPAREN", char, position))
            index += 1
            continue
        if char == ")":
            tokens.append(Token("RPAREN", char, position))
            index += 1
            continue
        if char in SINGLE_OPERATORS:
            tokens.append(Token("OP", char, position))
            index += 1
            continue
        if char == "@":
            end = index + 1
            while end < len(source) and (source[end].isalnum() or source[end] == "_"):
                end += 1
            name = source[index + 1:end]
            if not is_name(name):
                raise ExpressionError(f"invalid reference at column {position}; expected @SNAKE_CASE")
            tokens.append(Token("REF", name, position))
            index = end
            continue
        if char == ":":
            end = index + 1
            while end < len(source) and source[end] not in STRING_DELIMITERS:
                end += 1
            value = source[index + 1:end]
            if not value:
                raise ExpressionError(f"empty string atom at column {position}")
            tokens.append(Token("STRING", value, position))
            index = end
            continue
        if char.isdigit():
            end = index + 1
            while end < len(source) and source[end].isdigit():
                end += 1
            value = source[index:end]
            if len(value) > 1 and value.startswith("0"):
                raise ExpressionError(f"integer has a leading zero at column {position}")
            tokens.append(Token("INT", value, position))
            index = end
            continue
        if "A" <= char <= "Z":
            end = index + 1
            while end < len(source) and (source[end].isalnum() or source[end] == "_"):
                end += 1
            value = source[index:end]
            if value not in {"TRUE", "FALSE"}:
                raise ExpressionError(f"bare atom {value} at column {position}; use :{value} for a string")
            tokens.append(Token("BOOL", value, position))
            index = end
            continue
        raise ExpressionError(f"unexpected character {char!r} at column {position}")
    tokens.append(Token("EOF", "", len(source) + 1))
    return tokens


class ExpressionParser:
    def __init__(self, source: str) -> None:
        self.tokens = tokenize_expression(source)
        self.index = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def take(self) -> Token:
        lexeme = self.current
        self.index += 1
        return lexeme

    def parse(self) -> ExpressionNode:
        node = self.parse_binary(1)
        if self.current.kind != "EOF":
            raise ExpressionError(
                f"unexpected token {self.current.value!r} at column {self.current.position}"
            )
        return node

    def parse_binary(self, minimum: int) -> ExpressionNode:
        left = self.parse_unary()
        while self.current.kind == "OP" and PRECEDENCE.get(self.current.value, 0) >= minimum:
            operator = self.take()
            precedence = PRECEDENCE[operator.value]
            right = self.parse_binary(precedence + 1)
            left = ExpressionNode("binary", operator.value, left, right)
        return left

    def parse_unary(self) -> ExpressionNode:
        if self.current.kind == "OP" and self.current.value in {"!", "-"}:
            operator = self.take()
            return ExpressionNode("unary", operator.value, self.parse_unary())
        return self.parse_primary()

    def parse_primary(self) -> ExpressionNode:
        lexeme = self.take()
        if lexeme.kind == "REF":
            return ExpressionNode("reference", lexeme.value)
        if lexeme.kind == "STRING":
            return ExpressionNode("literal", lexeme.value)
        if lexeme.kind == "INT":
            return ExpressionNode("literal", int(lexeme.value))
        if lexeme.kind == "BOOL":
            return ExpressionNode("literal", lexeme.value == "TRUE")
        if lexeme.kind == "LPAREN":
            node = self.parse_binary(1)
            if self.current.kind != "RPAREN":
                raise ExpressionError(f"missing closing parenthesis at column {lexeme.position}")
            self.take()
            return node
        raise ExpressionError(f"expected operand at column {lexeme.position}")


def parse_expression(source: str) -> ExpressionNode:
    return ExpressionParser(source).parse()


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
        elif is_equation(name):
            try:
                parse_expression(value)
            except ExpressionError as error:
                diagnostics.append(Diagnostic(EXPRESSION, f"{name}: {error}", path, line_number))
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


Scalar = bool | int | str


def scalar_type(value: Scalar) -> str:
    if type(value) is bool:
        return "boolean"
    if type(value) is int:
        return "integer"
    return "string"


def coerce_constant(value: str) -> Scalar:
    if value == "TRUE":
        return True
    if value == "FALSE":
        return False
    if value == "0":
        return 0
    unsigned = value[1:] if value.startswith("-") else value
    if unsigned.isdigit() and not unsigned.startswith("0"):
        return int(value)
    return value


def require_type(value: Scalar, expected: type, operator: str) -> None:
    if type(value) is not expected:
        raise ExpressionError(
            f"operator {operator} requires {expected.__name__}, got {scalar_type(value)}"
        )


def evaluate_node(node: ExpressionNode, resolve: Callable[[str], Scalar]) -> Scalar:
    if node.kind == "literal":
        return node.value
    if node.kind == "reference":
        return resolve(node.value)
    if node.kind == "unary":
        if node.left is None:
            raise ExpressionError("unary operator has no operand")
        operand = evaluate_node(node.left, resolve)
        if node.value == "!":
            require_type(operand, bool, "!")
            return not operand
        require_type(operand, int, "-")
        return -operand
    if node.left is None or node.right is None:
        raise ExpressionError("binary operator has a missing operand")
    left = evaluate_node(node.left, resolve)
    operator = node.value
    if operator == "&&":
        require_type(left, bool, "&&")
        if not left:
            return False
        right = evaluate_node(node.right, resolve)
        require_type(right, bool, "&&")
        return right
    if operator == "||":
        require_type(left, bool, "||")
        if left:
            return True
        right = evaluate_node(node.right, resolve)
        require_type(right, bool, "||")
        return right
    right = evaluate_node(node.right, resolve)
    if operator in {"==", "!="}:
        if type(left) is not type(right):
            raise ExpressionError(
                f"operator {operator} requires equal operand types, got {scalar_type(left)} and {scalar_type(right)}"
            )
        return left == right if operator == "==" else left != right
    if operator in {"<", "<=", ">", ">="}:
        if type(left) is not type(right) or type(left) not in {int, str}:
            raise ExpressionError(
                f"operator {operator} requires two integers or two strings of the same type"
            )
        if operator == "<":
            return left < right
        if operator == "<=":
            return left <= right
        if operator == ">":
            return left > right
        return left >= right
    require_type(left, int, str(operator))
    require_type(right, int, str(operator))
    if operator == "+":
        return left + right
    if operator == "-":
        return left - right
    if operator == "*":
        return left * right
    if right == 0:
        raise ExpressionError(f"operator {operator} cannot divide by zero")
    quotient = abs(left) // abs(right)
    if (left < 0) != (right < 0):
        quotient = -quotient
    if operator == "/":
        return quotient
    if operator == "%":
        return left - quotient * right
    raise ExpressionError(f"unsupported operator {operator}")


def expression_references(node: ExpressionNode) -> set[str]:
    if node.kind == "reference":
        return {str(node.value)}
    references: set[str] = set()
    if node.left:
        references.update(expression_references(node.left))
    if node.right:
        references.update(expression_references(node.right))
    return references


def dependency_cycle(nodes: dict[str, ExpressionNode]) -> list[str]:
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(name: str) -> list[str]:
        state[name] = 1
        stack.append(name)
        for dependency in sorted(expression_references(nodes[name])):
            if dependency not in nodes:
                continue
            if state.get(dependency) == 1:
                start = stack.index(dependency)
                return [*stack[start:], dependency]
            if state.get(dependency, 0) == 0:
                found = visit(dependency)
                if found:
                    return found
        stack.pop()
        state[name] = 2
        return []

    for name in sorted(nodes):
        if state.get(name, 0) == 0:
            found = visit(name)
            if found:
                return found
    return []


def evaluate_constants(
    constants: dict[str, str],
    metadata: dict[str, str] | None = None,
    path: str = "<evaluation>",
) -> tuple[dict[str, Scalar], list[Diagnostic]]:
    sources = dict(metadata or {})
    sources.update(constants)
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
                diagnostics.append(
                    Diagnostic(
                        EXPRESSION,
                        f"{name}: reference @{reference} is undefined after layering",
                        path,
                    )
                )
    cycle = dependency_cycle(nodes)
    if cycle:
        diagnostics.append(
            Diagnostic(
                EXPRESSION,
                f"cyclic equation reference: {' -> '.join(cycle)}",
                path,
            )
        )
    if diagnostics:
        return {}, diagnostics

    evaluated: dict[str, Scalar] = {}
    active: list[str] = []

    def resolve(name: str) -> Scalar:
        if name in evaluated:
            return evaluated[name]
        if name not in sources:
            raise ExpressionError(f"reference @{name} is undefined after layering")
        if name in active:
            cycle = " -> ".join((*active[active.index(name):], name))
            raise ExpressionError(f"cyclic equation reference: {cycle}")
        active.append(name)
        try:
            source = sources[name]
            if is_equation(name):
                value = evaluate_node(nodes[name], resolve)
                if name.endswith("_CONDITION") and type(value) is not bool:
                    raise ExpressionError(
                        f"{name} must produce boolean, got {scalar_type(value)}"
                    )
            else:
                value = coerce_constant(source)
            evaluated[name] = value
            return value
        finally:
            active.pop()

    for name in constants:
        try:
            resolve(name)
        except ExpressionError as error:
            diagnostics.append(Diagnostic(EXPRESSION, f"{name}: {error}", path))
    return {name: evaluated[name] for name in constants if name in evaluated}, diagnostics


def render_scalar(value: Scalar) -> str:
    if type(value) is bool:
        return "TRUE" if value else "FALSE"
    return str(value)


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


def command_evaluate(paths: Sequence[Path]) -> int:
    documents: list[Document] = []
    diagnostics: list[Diagnostic] = []
    for path in paths:
        document, current = parse_file(path)
        diagnostics.extend(current)
        if document:
            documents.append(document)
    merged: dict[str, str] = {}
    if not diagnostics:
        merged, current = merge_documents(documents)
        diagnostics.extend(current)
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
        evaluated, current = evaluate_constants(merged, metadata, final.path)
        diagnostics.extend(current)
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
    evaluated, expression_diagnostics = evaluate_constants(
        document.constants,
        {VERSION: "1", NAMESPACE: "SELF_TEST", ENVIRONMENT: "BASE"},
    )
    invalid = valid + "HOME_VALUE=${HOME}\n"
    _, rejected = parse_text(invalid)
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
    validate = subparsers.add_parser("validate", help="validate Env DSL documents")
    validate.add_argument("paths", nargs="+", type=Path)
    merge = subparsers.add_parser("merge", help="validate and merge an explicit environment chain")
    merge.add_argument("paths", nargs="+", type=Path)
    evaluate = subparsers.add_parser(
        "evaluate", help="validate, layer and evaluate portable equations"
    )
    evaluate.add_argument("paths", nargs="+", type=Path)
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
