"""Tokenizer and syntax parser for configured keyword expressions."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum, auto
from typing import TypeAlias


class KeywordSyntaxError(ValueError):
    def __init__(self, message: str, position: int) -> None:
        self.position = position
        super().__init__(f"{message} at column {position + 1}")


@dataclass(frozen=True)
class Term:
    value: str


@dataclass(frozen=True)
class Phrase:
    value: str


@dataclass(frozen=True)
class Prefix:
    value: str


@dataclass(frozen=True)
class Proximity:
    value: str
    distance: int


@dataclass(frozen=True)
class And:
    left: KeywordExpression
    right: KeywordExpression


@dataclass(frozen=True)
class Or:
    left: KeywordExpression
    right: KeywordExpression


KeywordExpression: TypeAlias = Term | Phrase | Prefix | Proximity | And | Or


class _TokenKind(Enum):
    WORD = auto()
    PHRASE = auto()
    PREFIX = auto()
    PROXIMITY = auto()
    AND = auto()
    OR = auto()
    LPAREN = auto()
    RPAREN = auto()
    END = auto()


@dataclass(frozen=True)
class _Token:
    kind: _TokenKind
    value: str
    position: int
    distance: int | None = None


_OPERATORS = {
    "and": _TokenKind.AND,
    "or": _TokenKind.OR,
}

_WHITESPACE_PATTERN = re.compile(r"\s+")
_DECIMAL_INTEGER = re.compile(r"[0-9]+")


def validate_prefix_base(value: str, position: int = 0) -> str:
    """Return the prefix sent to search engines, enforcing the shared minimum."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    if len(normalized) < 4:
        raise KeywordSyntaxError(
            "prefix base must contain at least 4 lexical characters", position
        )
    if not all(character.isalpha() or character.isdigit() for character in normalized):
        raise KeywordSyntaxError(
            "prefix base must contain only letters or digits", position
        )
    return normalized


def _prefix_error_position(value: str, start: int) -> int:
    first = value.find("*")
    second = value.find("*", first + 1)
    if second >= 0:
        return start + second
    return start + first


def _prefix_token(value: str, start: int) -> _Token:
    if value.count("*") != 1 or not value.endswith("*"):
        raise KeywordSyntaxError(
            "prefix wildcard must be a single trailing '*'",
            _prefix_error_position(value, start),
        )

    base = value[:-1]
    wildcard_position = start + len(value) - 1
    validate_prefix_base(base, wildcard_position)
    return _Token(_TokenKind.PREFIX, base, start)


def _tokenize(text: str) -> tuple[_Token, ...]:
    tokens: list[_Token] = []
    position = 0
    while position < len(text):
        character = text[position]
        if character.isspace():
            position += 1
            continue
        if character == "(":
            tokens.append(_Token(_TokenKind.LPAREN, character, position))
            position += 1
            continue
        if character == ")":
            tokens.append(_Token(_TokenKind.RPAREN, character, position))
            position += 1
            continue
        if character == '"':
            start = position
            position += 1
            phrase: list[str] = []
            while position < len(text) and text[position] != '"':
                if text[position] == "\\":
                    escape_position = position
                    position += 1
                    if position >= len(text):
                        raise KeywordSyntaxError("unfinished escape sequence", escape_position)
                    if text[position] not in {'"', "\\"}:
                        raise KeywordSyntaxError("unsupported escape sequence", escape_position)
                phrase.append(text[position])
                position += 1
            if position >= len(text):
                raise KeywordSyntaxError("unterminated phrase", start)
            if any(c in "*?~" for c in phrase):
                raise KeywordSyntaxError("wildcard or proximity operators are not supported inside phrases", start)
            if not phrase:
                raise KeywordSyntaxError("phrase must not be empty", start)
            position += 1

            suffix_position = position
            while suffix_position < len(text) and text[suffix_position].isspace():
                suffix_position += 1
            if suffix_position < len(text) and text[suffix_position] == "~":
                raise KeywordSyntaxError("proximity search is no longer supported", suffix_position)
            else:
                tokens.append(_Token(_TokenKind.PHRASE, "".join(phrase), start))
            continue

        start = position
        while (
            position < len(text)
            and not text[position].isspace()
            and text[position] not in {'(', ')', '"'}
        ):
            position += 1
        value = text[start:position]
        if "?" in value or "~" in value:
            raise KeywordSyntaxError("unsupported wildcard or proximity operator", start)
        if "*" in value:
            tokens.append(_prefix_token(value, start))
            continue
        if value.casefold() == "not":
            raise KeywordSyntaxError("NOT operator is no longer supported; edit the keyword expression", start)
        kind = _OPERATORS.get(value.casefold(), _TokenKind.WORD)
        tokens.append(_Token(kind, value, start))

    tokens.append(_Token(_TokenKind.END, "", len(text)))
    return tuple(tokens)


class _Parser:
    def __init__(self, text: str) -> None:
        self.tokens = _tokenize(text)
        self.index = 0

    @property
    def current(self) -> _Token:
        return self.tokens[self.index]

    def advance(self) -> _Token:
        token = self.current
        self.index += 1
        return token

    def parse(self) -> KeywordExpression:
        if self.current.kind is _TokenKind.END:
            raise KeywordSyntaxError("expression must not be empty", self.current.position)
        expression = self.parse_or()
        if self.current.kind is not _TokenKind.END:
            raise KeywordSyntaxError(
                f"expected an operator, found {self.current.value!r}",
                self.current.position,
            )
        return expression

    def parse_or(self) -> KeywordExpression:
        expression = self.parse_and()
        while self.current.kind is _TokenKind.OR:
            self.advance()
            expression = Or(expression, self.parse_and())
        return expression

    def parse_and(self) -> KeywordExpression:
        expression = self.parse_primary()
        while self.current.kind is _TokenKind.AND:
            self.advance()
            expression = And(expression, self.parse_primary())
        return expression

    def parse_primary(self) -> KeywordExpression:
        token = self.current
        if token.kind is _TokenKind.WORD:
            self.advance()
            return Term(token.value)
        if token.kind is _TokenKind.PHRASE:
            self.advance()
            return Phrase(token.value)
        if token.kind is _TokenKind.PREFIX:
            self.advance()
            return Prefix(token.value)
        if token.kind is _TokenKind.PROXIMITY:
            self.advance()
            assert token.distance is not None
            return Proximity(token.value, token.distance)
        if token.kind is _TokenKind.LPAREN:
            self.advance()
            expression = self.parse_or()
            if self.current.kind is not _TokenKind.RPAREN:
                raise KeywordSyntaxError("expected closing parenthesis", self.current.position)
            self.advance()
            return expression
        if token.kind is _TokenKind.RPAREN:
            raise KeywordSyntaxError("unexpected closing parenthesis", token.position)
        if token.kind is _TokenKind.END:
            raise KeywordSyntaxError("expected a word, phrase, or parenthesized expression", token.position)
        raise KeywordSyntaxError(f"unexpected operator {token.value!r}", token.position)


def parse_keyword_expression(text: str) -> KeywordExpression:
    return _Parser(text).parse()


def compile_native_expression(expression: KeywordExpression, *, provider: str) -> str:
    """Serialize the shared language for the independent WoS Topic path."""
    if provider != "wos":
        raise ValueError("Unsupported native query Provider")
    def operand(node):
        if isinstance(node, (And, Or)):
            operator = "AND" if isinstance(node, And) else "OR"
            return f"({operand(node.left)} {operator} {operand(node.right)})"
        if isinstance(node, Proximity):
            raise ValueError("proximity search is no longer supported")
        value = validate_prefix_base(node.value) if isinstance(node, Prefix) else unicodedata.normalize("NFKC",node.value)
        words = value.split()
        if not words or any(not word.isalnum() for word in words):
            raise ValueError("wos: this operand cannot be converted without changing its meaning")
        if isinstance(node, Prefix):
            return value + "*"
        if isinstance(node, Phrase) or len(words)>1 or value.upper() in {"NEAR","SAME","NOT"}:
            return '"' + " ".join(words) + '"'
        return value
    return f"TS=({operand(expression)})"


def lexical_tokens(text: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKD", text).casefold()
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    return tuple(re.findall(r"[^\W_]+", normalized, re.UNICODE))


def matches_fields(expression: KeywordExpression, fields) -> bool:
    """Evaluate candidates in memory; phrases never span field boundaries."""
    token_fields = tuple(lexical_tokens(str(value)) for value in fields if value)
    def visit(node):
        if isinstance(node, And):
            return visit(node.left) and visit(node.right)
        if isinstance(node, Or):
            return visit(node.left) or visit(node.right)
        if isinstance(node, Proximity):
            raise ValueError("proximity search is no longer supported")
        words = lexical_tokens(node.value)
        if not words:
            return False
        if isinstance(node, Prefix):
            return any(word.startswith(words[0]) for field in token_fields for word in field)
        return any(field[i:i + len(words)] == words for field in token_fields for i in range(len(field)))
    return visit(expression)
