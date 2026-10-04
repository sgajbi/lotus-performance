"""Bounded expression identity for mapped durable CHECK predicates.

This is not a general SQL optimizer. Unsupported grammar refuses verification.
Only source-safe PostgreSQL representation differences are normalized; arithmetic
precedence, boolean grouping and literal contents remain in the expression tree.
"""

from __future__ import annotations

import re
from typing import Any

_TOKEN = re.compile(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|\d+(?:\.\d+)?|[a-zA-Z_][\w$]*|>=|<=|<>|!=|::|\|\||[^\s]")
_PRECEDENCE = {
    "or": 1,
    "and": 2,
    "=": 3,
    "!=": 3,
    "<>": 3,
    "<": 3,
    ">": 3,
    "<=": 3,
    ">=": 3,
    "in": 3,
    "between": 3,
    "is": 3,
    "glob": 3,
    "||": 4,
    "+": 5,
    "-": 5,
    "*": 6,
    "/": 6,
}
_TEXT_FUNCTIONS = frozenset({"upper", "lower", "trim", "btrim", "substr", "chr", "char"})


def predicate_identity(
    sql: str,
    *,
    text_columns: set[str] | None = None,
    integer_columns: set[str] | None = None,
    date_columns: set[str] | None = None,
) -> Any:
    if len(sql) > 16_384:
        raise ValueError("Unsupported durable check expression")
    try:
        parser = _Expression(sql, text_columns or set(), integer_columns or set(), date_columns or set())
        result = parser.parse()
        if parser.peek():
            raise ValueError("Unsupported durable check expression")
        return result
    except (RecursionError, IndexError) as exc:
        raise ValueError("Unsupported durable check expression") from exc


class _Expression:
    def __init__(self, sql: str, text_columns: set[str], integer_columns: set[str], date_columns: set[str]):
        self.tokens = [token if token[0] in "'\"" else token.lower() for token in _TOKEN.findall(sql)]
        self.position = 0
        self.text_columns = text_columns
        self.integer_columns = integer_columns
        self.date_columns = date_columns

    def peek(self) -> str:
        return self.tokens[self.position] if self.position < len(self.tokens) else ""

    def take(self, expected: str | None = None) -> str:
        token = self.peek()
        if not token or (expected is not None and token != expected):
            raise ValueError("Unsupported durable check expression")
        self.position += 1
        return token

    def parse(self, minimum: int = 0) -> Any:
        left = self.atom()
        while self.peek():
            if self.peek() == "::":
                left = self.cast(left)
                continue
            negated = self.peek() == "not"
            operator = self.tokens[self.position + 1] if negated else self.peek()
            precedence = _PRECEDENCE.get(operator, -1)
            if precedence < minimum:
                break
            if negated:
                self.take("not")
            self.take(operator)
            left = self.operator(left, operator, precedence)
            if negated:
                left = ("not", left)
        return left

    def atom(self) -> Any:
        lexeme = self.take()
        if lexeme == "(":
            node = self.parse()
            self.take(")")
            return node
        if lexeme in ("not", "+", "-"):
            return (lexeme, self.parse(3 if lexeme == "not" else 7))
        if lexeme == "array":
            return ("array", *self.list("[", "]"))
        if _is_literal(lexeme):
            return ("literal", lexeme)
        return self.reference(lexeme)

    def reference(self, token: str) -> Any:
        if not re.fullmatch(r"[a-zA-Z_][\w$]*|\"(?:\"\"|[^\"])*\"", token):
            raise ValueError("Unsupported durable check expression")
        if self.peek() == "(":
            return ("call", token, *self.list("(", ")"))
        return ("column", token)

    def list(self, opening: str, closing: str) -> tuple[Any, ...]:
        self.take(opening)
        values = []
        if self.peek() != closing:
            values.append(self.parse())
            while self.peek() == ",":
                self.take(",")
                values.append(self.parse())
        self.take(closing)
        return tuple(values)

    def operator(self, left: Any, operator: str, precedence: int) -> Any:
        if operator == "between":
            lower = self.parse(precedence + 1)
            self.take("and")
            upper = self.parse(precedence + 1)
            return _combine("and", (">=", left, lower), ("<=", left, upper))
        if operator == "in":
            return ("in", left, self.list("(", ")"))
        if operator == "is" and self.peek() == "not":
            self.take("not")
            return ("is_not", left, self.parse(precedence + 1))
        right = self.parse(precedence + 1)
        if operator == "=" and _is_array_membership(right):
            return ("in", left, right[2][1:])
        return _combine(operator, left, right)

    def cast(self, node: Any) -> Any:
        self.take("::")
        kind = self.take()
        if kind == "character":
            self.take("varying")
            kind = "varchar"
        if self.peek() == "[":
            self.take("[")
            self.take("]")
            return self.array_cast(node, kind)
        if self.transparent_cast(node, kind):
            return node
        return ("cast", node, kind)

    def transparent_cast(self, node: Any, kind: str) -> bool:
        if kind in ("text", "varchar"):
            return self.is_text(node)
        if kind in ("integer", "bigint"):
            return self.is_integer(node)
        return kind == "date" and self.is_date(node)

    def array_cast(self, node: Any, kind: str) -> Any:
        if kind in ("text", "varchar") and node[0] == "array" and all(self.is_text(item) for item in node[1:]):
            return node
        return ("cast_array", node, kind)

    def is_text(self, node: Any) -> bool:
        if node[0] == "literal":
            return node[1].startswith("'")
        if node[0] == "column":
            return node[1] in self.text_columns
        return node[0] == "call" and node[1] in _TEXT_FUNCTIONS

    def is_integer(self, node: Any) -> bool:
        if node[0] == "literal":
            return bool(re.fullmatch(r"\d+", node[1]))
        return node[0] == "column" and node[1] in self.integer_columns

    def is_date(self, node: Any) -> bool:
        if node[0] == "literal":
            return node[1].startswith("'")
        return node[0] == "column" and node[1] in self.date_columns


def _is_literal(token: str) -> bool:
    return token.startswith("'") or bool(re.fullmatch(r"\d+(?:\.\d+)?", token)) or token in ("null", "true", "false")


def _is_array_membership(node: Any) -> bool:
    return node[:2] == ("call", "any") and len(node) == 3 and node[2][0] == "array"


def _combine(operator: str, left: Any, right: Any) -> Any:
    if operator in ("and", "or"):
        operands: list[Any] = []
        for node in (left, right):
            operands.extend(node[1:] if node[0] == operator else (node,))
        return (operator, *operands)
    return (operator, left, right)
