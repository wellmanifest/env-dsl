"""Bounded portable expression lexer, parser, cycle analyzer, and iterative evaluator."""

from __future__ import annotations

import operator as _op
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from env_dsl_io import MAX_ENV_FILE_BYTES, read_regular_bytes

Scalar = bool | int | str
_ = (MAX_ENV_FILE_BYTES, read_regular_bytes)


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
_ORDER_FNS = {"<": _op.lt, "<=": _op.le, ">": _op.gt, ">=": _op.ge}
MULTI_OPERATORS = ("&&", "||", "==", "!=", "<=", ">=")
SINGLE_OPERATORS = frozenset("+-*/%!<>")
STRING_DELIMITERS = frozenset("&|=!<>()+-*/%")
MAX_EXPRESSION_DEPTH = 64
MAX_EXPRESSION_OPERATORS = 512
MAX_EVAL_STEPS = 4096
MAX_INTEGER_DIGITS = 64
MAX_INTEGER_BITS = 256


def _is_ascii_digit(char: str) -> bool:
    return "0" <= char <= "9"


def _is_ascii_ident_char(char: str) -> bool:
    return "A" <= char <= "Z" or "a" <= char <= "z" or "0" <= char <= "9" or char == "_"


def is_atom_char(char: str) -> bool:
    code = ord(char)
    return (
        0x23 <= code <= 0x24
        or code in (0x2C, 0x2E)
        or 0x30 <= code <= 0x3B
        or 0x3F <= code <= 0x5F
        or 0x61 <= code <= 0x7B
        or 0x7D <= code <= 0x7E
    )


def is_name(value: str) -> bool:
    if not value or not ("A" <= value[0] <= "Z") or value[-1] == "_" or "__" in value:
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
            (op for op in MULTI_OPERATORS if source.startswith(op, index)), None
        )
        if matched:
            tokens.append(Token("OP", matched, position))
            index += len(matched)
            continue
        char = source[index]
        if char in ("(", ")"):
            tokens.append(Token("LPAREN" if char == "(" else "RPAREN", char, position))
            index += 1
            continue
        if char in SINGLE_OPERATORS:
            tokens.append(Token("OP", char, position))
            index += 1
            continue
        if char == "@":
            end = index + 1
            while end < len(source) and _is_ascii_ident_char(source[end]):
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
        if _is_ascii_digit(char):
            end = index + 1
            while end < len(source) and _is_ascii_digit(source[end]):
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
            while end < len(source) and _is_ascii_ident_char(source[end]):
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
            right = self.parse_binary(PRECEDENCE[operator.value] + 1)
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
    return "integer" if type(value) is int else "string"


def coerce_constant(value: str) -> Scalar:
    if value in ("TRUE", "FALSE"):
        return value == "TRUE"
    if value == "0":
        return 0
    unsigned = value.removeprefix("-")
    if (
        unsigned
        and all(_is_ascii_digit(ch) for ch in unsigned)
        and not unsigned.startswith("0")
    ):
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


def _apply_binary_operator(operator: str, left: Scalar, right: Scalar) -> Scalar:
    if operator in {"&&", "||"}:
        require_type(right, bool, operator)
        return right
    if operator in {"==", "!="}:
        if type(left) is not type(right):
            raise ExpressionError(
                f"operator {operator} requires equal operand types, "
                f"got {scalar_type(left)} and {scalar_type(right)}"
            )
        return (left == right) if operator == "==" else (left != right)
    if operator in _ORDER_FNS:
        if type(left) is not type(right) or type(left) not in {int, str}:
            raise ExpressionError(
                f"operator {operator} requires two integers or two strings of the same type"
            )
        return bool(_ORDER_FNS[operator](left, right))
    require_type(left, int, operator)
    require_type(right, int, operator)
    assert type(left) is int and type(right) is int
    if operator in {"+", "-", "*"}:
        res = (
            left + right
            if operator == "+"
            else (left - right if operator == "-" else left * right)
        )
        return _check_int_bounds(res, operator)
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


def evaluate_node(node: ExpressionNode, resolve: Callable[[str], Scalar]) -> Scalar:
    """Evaluate `node` iteratively in O(1) Python stack frames with short-circuiting."""
    frames: list[list[object]] = [[node, 0, None]]
    results: list[Scalar] = []
    steps = 0
    while frames:
        frame = frames[-1]
        current = frame[0]
        assert isinstance(current, ExpressionNode)
        stage = frame[1]
        if stage == 0:
            steps += 1
            if steps > MAX_EVAL_STEPS:
                raise ExpressionError(
                    f"expression exceeds maximum evaluation budget {MAX_EVAL_STEPS}"
                )
            if current.kind == "literal":
                frames.pop()
                if type(current.value) is int:
                    _check_int_bounds(current.value, "literal")
                results.append(current.value)
            elif current.kind == "reference":
                frames.pop()
                results.append(resolve(str(current.value)))
            elif current.kind in {"unary", "binary"}:
                if current.left is None or (
                    current.kind == "binary" and current.right is None
                ):
                    raise ExpressionError(
                        f"{current.kind} operator has a missing operand"
                    )
                frame[1] = 1
                frames.append([current.left, 0, None])
            else:
                raise ExpressionError(
                    f"unsupported expression node kind {current.kind!r}"
                )
        elif stage == 1:
            if current.kind == "unary":
                frames.pop()
                operand = results.pop()
                if current.value == "!":
                    require_type(operand, bool, "!")
                    results.append(not operand)
                elif current.value == "-":
                    require_type(operand, int, "-")
                    assert type(operand) is int
                    results.append(_check_int_bounds(-operand, "-"))
                else:
                    raise ExpressionError(f"unsupported unary operator {current.value}")
            else:
                left = results.pop()
                op_name = str(current.value)
                if op_name in {"&&", "||"}:
                    require_type(left, bool, op_name)
                    if (op_name == "&&" and not left) or (op_name == "||" and left):
                        frames.pop()
                        results.append(op_name == "||")
                        continue
                assert current.right is not None
                frame[1] = 2
                frame[2] = left
                frames.append([current.right, 0, None])
        else:
            frames.pop()
            right = results.pop()
            left_val = frame[2]
            assert type(left_val) in (bool, int, str)
            results.append(_apply_binary_operator(str(current.value), left_val, right))
    return results[0]


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
                    return [*path_stack[path_index[dep] :], dep], []
                if dep_state == 0:
                    state[dep] = 1
                    path_index[dep] = len(path_stack)
                    path_stack.append(dep)
                    frames.append((dep, deps_map[dep], 0))
            else:
                frames.pop()
                path_index.pop(path_stack.pop(), None)
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
