"""Bounded portable expression lexer, parser, cycle analyzer, and evaluator for Env DSL 1."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

Scalar = bool | int | str
MAX_ENV_FILE_BYTES = 4 * 1024 * 1024


def read_regular_bytes(path: Path, max_bytes: int = MAX_ENV_FILE_BYTES) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(os.fspath(path), flags)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise OSError("input must be a regular file")
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
MAX_EXPRESSION_DEPTH = 64
MAX_EXPRESSION_OPERATORS = 512
MAX_INTEGER_DIGITS = 64
MAX_INTEGER_BITS = 256


def is_atom_char(char: str) -> bool:
    code = ord(char)
    return (
        0x23 <= code <= 0x24
        or code == 0x2C
        or code == 0x2E
        or 0x30 <= code <= 0x3B
        or 0x3F <= code <= 0x5F
        or 0x61 <= code <= 0x7B
        or 0x7D <= code <= 0x7E
    )


def is_name(value: str) -> bool:
    if not value or not ("A" <= value[0] <= "Z"):
        return False
    if value[-1] == "_" or "__" in value:
        return False
    return all(
        "A" <= char <= "Z" or "0" <= char <= "9" or char == "_" for char in value
    )


def is_equation(name: str) -> bool:
    return name.endswith(("_EXPRESSION", "_CONDITION"))


def tokenize_expression(source: str) -> list[Token]:
    tokens: list[Token] = []
    index = 0
    while index < len(source):
        position = index + 1
        matched = next(
            (item for item in MULTI_OPERATORS if source.startswith(item, index)), None
        )
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
            name = source[index + 1 : end]
            if not is_name(name):
                raise ExpressionError(
                    f"invalid reference at column {position}; expected @SNAKE_CASE"
                )
            tokens.append(Token("REF", name, position))
            index = end
            continue
        if char == ":":
            end = index + 1
            while end < len(source) and is_atom_char(source[end]):
                end += 1
            value = source[index + 1 : end]
            if not value:
                raise ExpressionError(f"empty string atom at column {position}")
            if end < len(source) and source[end] not in STRING_DELIMITERS:
                raise ExpressionError(
                    f"invalid string-atom character {source[end]!r} at column {end + 1}"
                )
            tokens.append(Token("STRING", value, position))
            index = end
            continue
        if char.isdigit():
            end = index + 1
            while end < len(source) and source[end].isdigit():
                end += 1
            value = source[index:end]
            if len(value) > 1 and value.startswith("0"):
                raise ExpressionError(
                    f"integer has a leading zero at column {position}"
                )
            if len(value) > MAX_INTEGER_DIGITS:
                raise ExpressionError(
                    f"integer literal exceeds maximum {MAX_INTEGER_DIGITS} digits at column {position}"
                )
            tokens.append(Token("INT", value, position))
            index = end
            continue
        if "A" <= char <= "Z":
            end = index + 1
            while end < len(source) and (source[end].isalnum() or source[end] == "_"):
                end += 1
            value = source[index:end]
            if value not in {"TRUE", "FALSE"}:
                raise ExpressionError(
                    f"bare atom {value} at column {position}; use :{value} for a string"
                )
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
        self.depth = 0
        self.operators = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def take(self) -> Token:
        lexeme = self.current
        self.index += 1
        return lexeme

    def _count_operator(self) -> None:
        self.operators += 1
        if self.operators > MAX_EXPRESSION_OPERATORS:
            raise ExpressionError(
                f"expression exceeds maximum operator count {MAX_EXPRESSION_OPERATORS}"
            )

    def parse(self) -> ExpressionNode:
        node = self.parse_binary(1)
        if self.current.kind != "EOF":
            raise ExpressionError(
                f"unexpected token {self.current.value!r} at column {self.current.position}"
            )
        return node

    def parse_binary(self, minimum: int) -> ExpressionNode:
        left = self.parse_unary()
        while (
            self.current.kind == "OP"
            and PRECEDENCE.get(self.current.value, 0) >= minimum
        ):
            self._count_operator()
            operator = self.take()
            precedence = PRECEDENCE[operator.value]
            right = self.parse_binary(precedence + 1)
            left = ExpressionNode("binary", operator.value, left, right)
        return left

    def parse_unary(self) -> ExpressionNode:
        if self.current.kind == "OP" and self.current.value in {"!", "-"}:
            self._count_operator()
            self.depth += 1
            if self.depth > MAX_EXPRESSION_DEPTH:
                raise ExpressionError(
                    f"expression nesting exceeds maximum depth {MAX_EXPRESSION_DEPTH}"
                )
            try:
                operator = self.take()
                return ExpressionNode("unary", operator.value, self.parse_unary())
            finally:
                self.depth -= 1
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
            self.depth += 1
            if self.depth > MAX_EXPRESSION_DEPTH:
                raise ExpressionError(
                    f"expression nesting exceeds maximum depth {MAX_EXPRESSION_DEPTH}"
                )
            try:
                node = self.parse_binary(1)
                if self.current.kind != "RPAREN":
                    raise ExpressionError(
                        f"missing closing parenthesis at column {lexeme.position}"
                    )
                self.take()
                return node
            finally:
                self.depth -= 1
        raise ExpressionError(f"expected operand at column {lexeme.position}")


def parse_expression(source: str) -> ExpressionNode:
    return ExpressionParser(source).parse()


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
    unsigned = value.removeprefix("-")
    if unsigned.isdigit() and not unsigned.startswith("0"):
        if len(unsigned) > MAX_INTEGER_DIGITS:
            raise ExpressionError(
                f"integer constant exceeds maximum {MAX_INTEGER_DIGITS} digits"
            )
        return int(value)
    return value


def require_type(value: Scalar, expected: type, operator: str) -> None:
    if type(value) is not expected:
        raise ExpressionError(
            f"operator {operator} requires {expected.__name__}, got {scalar_type(value)}"
        )


def _check_int_bounds(value: int, operator: str) -> int:
    if value.bit_length() > MAX_INTEGER_BITS:
        raise ExpressionError(
            f"operator {operator} integer overflow exceeds {MAX_INTEGER_BITS} bits"
        )
    return value


def evaluate_node(node: ExpressionNode, resolve: Callable[[str], Scalar]) -> Scalar:
    if node.kind == "literal":
        return node.value
    if node.kind == "reference":
        return resolve(str(node.value))
    if node.kind == "unary":
        if node.left is None:
            raise ExpressionError("unary operator has no operand")
        operand = evaluate_node(node.left, resolve)
        if node.value == "!":
            require_type(operand, bool, "!")
            return not operand
        require_type(operand, int, "-")
        assert type(operand) is int
        return _check_int_bounds(-operand, "-")
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
                f"operator {operator} requires equal operand types, "
                f"got {scalar_type(left)} and {scalar_type(right)}"
            )
        return left == right if operator == "==" else left != right
    if operator in {"<", "<=", ">", ">="}:
        if type(left) is not type(right) or type(left) not in {int, str}:
            raise ExpressionError(
                f"operator {operator} requires two integers or two strings of the same type"
            )
        if operator == "<":
            return left < right  # type: ignore[operator]
        if operator == "<=":
            return left <= right  # type: ignore[operator]
        if operator == ">":
            return left > right  # type: ignore[operator]
        return left >= right  # type: ignore[operator]
    require_type(left, int, str(operator))
    require_type(right, int, str(operator))
    assert type(left) is int and type(right) is int
    if operator == "+":
        return _check_int_bounds(left + right, "+")
    if operator == "-":
        return _check_int_bounds(left - right, "-")
    if operator == "*":
        return _check_int_bounds(left * right, "*")
    if right == 0:
        raise ExpressionError(f"operator {operator} cannot divide by zero")
    quotient = abs(left) // abs(right)
    if (left < 0) != (right < 0):
        quotient = -quotient
    if operator == "/":
        return _check_int_bounds(quotient, "/")
    if operator == "%":
        return _check_int_bounds(left - quotient * right, "%")
    raise ExpressionError(f"unsupported operator {operator}")


def expression_references(node: ExpressionNode) -> set[str]:
    references: set[str] = set()
    stack: list[ExpressionNode] = [node]
    while stack:
        current = stack.pop()
        if current.kind == "reference":
            references.add(str(current.value))
        if current.left is not None:
            stack.append(current.left)
        if current.right is not None:
            stack.append(current.right)
    return references


def analyze_equation_graph(
    nodes: dict[str, ExpressionNode],
) -> tuple[list[str], list[str]]:
    """Return `(cycle, topological_order)` iteratively without Python recursion."""
    deps_map = {
        name: sorted(dep for dep in expression_references(node) if dep in nodes)
        for name, node in nodes.items()
    }
    state: dict[str, int] = {}
    order: list[str] = []

    for start_name in sorted(nodes):
        if state.get(start_name, 0) != 0:
            continue
        path_stack: list[str] = [start_name]
        path_index: dict[str, int] = {start_name: 0}
        frames: list[tuple[str, list[str], int]] = [
            (start_name, deps_map[start_name], 0)
        ]
        state[start_name] = 1
        while frames:
            name, deps, idx = frames[-1]
            if idx < len(deps):
                frames[-1] = (name, deps, idx + 1)
                dep = deps[idx]
                dep_state = state.get(dep, 0)
                if dep_state == 1:
                    cycle_start = path_index[dep]
                    return [*path_stack[cycle_start:], dep], []
                if dep_state == 0:
                    state[dep] = 1
                    path_index[dep] = len(path_stack)
                    path_stack.append(dep)
                    frames.append((dep, deps_map[dep], 0))
            else:
                frames.pop()
                popped = path_stack.pop()
                path_index.pop(popped, None)
                state[name] = 2
                order.append(name)
    return [], order


def dependency_cycle(nodes: dict[str, ExpressionNode]) -> list[str]:
    cycle, _ = analyze_equation_graph(nodes)
    return cycle


def render_scalar(value: Scalar) -> str:
    if type(value) is bool:
        return "TRUE" if value else "FALSE"
    return str(value)
