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
            if not phrase:
                raise KeywordSyntaxError("phrase must not be empty", start)
            position += 1

            suffix_position = position
            while suffix_position < len(text) and text[suffix_position].isspace():
                suffix_position += 1
            if suffix_position < len(text) and text[suffix_position] == "~":
                wildcard_position = text.find("*", start + 1, position - 1)
                if wildcard_position >= 0:
                    raise KeywordSyntaxError(
                        "wildcard '*' cannot be combined with proximity search",
                        wildcard_position,
                    )
                distance_position = suffix_position + 1
                distance_end = distance_position
                while (
                    distance_end < len(text)
                    and not text[distance_end].isspace()
                    and text[distance_end] not in {'(', ')', '"'}
                ):
                    distance_end += 1
                distance_text = text[distance_position:distance_end]
                if not distance_text:
                    raise KeywordSyntaxError(
                        "proximity distance is required", suffix_position
                    )
                if _DECIMAL_INTEGER.fullmatch(distance_text) is None:
                    raise KeywordSyntaxError(
                        "proximity distance must be a decimal integer",
                        distance_position,
                    )
                distance = int(distance_text)
                if distance > 50:
                    raise KeywordSyntaxError(
                        "proximity distance must be between 0 and 50",
                        distance_position,
                    )

                # S1 只校验语法和距离范围；真实 unicode61 token 数量必须由
                # S2 复用 FTS5 tokenizer 校验，避免在 parser 里维护第二套分词规则。
                tokens.append(
                    _Token(
                        _TokenKind.PROXIMITY,
                        "".join(phrase),
                        start,
                        distance=distance,
                    )
                )
                position = distance_end
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


def compile_native_expression(expression: KeywordExpression, *, provider: str, mode: str = "title_abstract") -> str:
    """Serialize the shared AST, never reinterpreting text as native query syntax."""
    if provider not in {"pubmed", "wos"}:
        raise ValueError("Unsupported native query Provider")
    if provider == "pubmed" and mode not in {"title_abstract", "broad"}:
        raise ValueError("Choose title_abstract or broad mode")

    def operand(node):
        if isinstance(node, (And, Or)):
            operator = "AND" if isinstance(node, And) else "OR"
            return f"({operand(node.left)} {operator} {operand(node.right)})"
        value = (validate_prefix_base(node.value) if isinstance(node, Prefix)
                 else unicodedata.normalize("NFKC", node.value))
        if isinstance(node, Proximity) and "*" in value:
            raise ValueError(f"{provider}: wildcard '*' cannot be combined with proximity search")
        # Local FTS treats punctuation as lexical boundaries. Native engines have
        # different punctuation/field rules, so do not guess at their meaning.
        words = value.split()
        if not words or any(not word.isalnum() for word in words):
            raise ValueError(f"{provider}: this operand cannot be converted without changing its meaning")
        if isinstance(node, Proximity):
            if len(words) < 2:
                raise ValueError(f"{provider}: proximity requires at least two lexical terms")
            if not 0 <= node.distance <= 50:
                raise ValueError(f"{provider}: proximity distance must be between 0 and 50")
            if provider == "pubmed":
                return '"' + " ".join(words) + f'"[tiab:~{node.distance}]'
            result = f'"{words[0]}"'
            for word in words[1:]:
                result = f'({result} NEAR/{node.distance} "{word}")'
            return result
        if isinstance(node, Prefix):
            result = value + "*"
        elif isinstance(node, Phrase) or len(words) > 1 or (provider == "wos" and value.upper() in {"NEAR", "SAME", "NOT"}):
            result = '"' + " ".join(words) + '"'
        else:
            result = value
        return result + ("[tiab]" if provider == "pubmed" and mode == "title_abstract" else "")

    content = operand(expression)
    return f"TS=({content})" if provider == "wos" else content
