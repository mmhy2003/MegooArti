"""Content selectors' expressions (spec 10, D2): which content of a repository a selector
permission reaches, by its format and its path.

    format == "maven" and (path =^ "/com/acme/" or path =~ "^/org/[^/]+/1\\.0/.*$")

`==` is equal to, `=^` starts with, `=~` matches as a whole (Python's `re.fullmatch`);
`and`, `or`, `not` and parentheses combine them. A string is in double quotes, with
`\\"` and `\\\\` in it. A path starts with `/`.

An expression is parsed once, when it is saved and when it is first used (`parse`, kept
by its text), and says three things: whether a path matches (`matches`); whether any
path under a folder could (`under`), for listing folders without their files; and a
condition a database can test that every matching path meets (`narrowing`), for
listing only what may match before each is checked.
"""

import enum
import functools
import re
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import ColumnElement, and_, false, not_, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.security.models import ContentSelector

MAX_LENGTH = 4000
MAX_PATTERN = 1000
MAX_DEPTH = 32
FIELDS = ("format", "path")
OPERATORS = ("==", "=^", "=~")


class SelectorError(ValueError):
    """An expression that does not parse: what is wrong, and where (from 1)."""

    def __init__(self, message: str, position: int) -> None:
        super().__init__(f"{message} (at character {position})")
        self.message = message
        self.position = position


class Reach(enum.Enum):
    """How much of a folder an expression may match."""

    NONE = "none"  # no path under it
    SOME = "some"  # some may: each must be checked
    ALL = "all"  # every path under it


@dataclass(frozen=True)
class _Token:
    kind: str  # word, operator, string, open, close, end
    text: str
    at: int  # from 1


_WORD = re.compile(r"[A-Za-z_]+")


def _tokens(text: str) -> list[_Token]:
    found: list[_Token] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character.isspace():
            index += 1
        elif character in "()":
            found.append(_Token("open" if character == "(" else "close", character, index + 1))
            index += 1
        elif text.startswith(OPERATORS, index):
            found.append(_Token("operator", text[index : index + 2], index + 1))
            index += 2
        elif character == '"':
            start, index, value = index, index + 1, []
            while True:
                if index >= len(text):
                    raise SelectorError("A string is not closed", start + 1)
                if text[index] == "\\":
                    if index + 1 >= len(text) or text[index + 1] not in '"\\':
                        raise SelectorError('Only \\" and \\\\ are written so', index + 1)
                    value.append(text[index + 1])
                    index += 2
                elif text[index] == '"':
                    index += 1
                    break
                else:
                    value.append(text[index])
                    index += 1
            found.append(_Token("string", "".join(value), start + 1))
        elif matched := _WORD.match(text, index):
            found.append(_Token("word", matched.group(), index + 1))
            index = matched.end()
        else:
            raise SelectorError(f"Unexpected {character!r}", index + 1)
    found.append(_Token("end", "", len(text) + 1))
    return found


class Expression:
    """A parsed expression. Use `parse`."""

    def matches(self, format: str, path: str) -> bool:
        raise NotImplementedError

    def under(self, format: str, folder: str) -> Reach:
        """How many of the paths under `folder` (`/com/acme/`; `/` for all) may match."""
        raise NotImplementedError

    def narrowing(self, format: str, path: ColumnElement[str]) -> tuple[ColumnElement[bool], bool]:
        """A condition every matching path meets, on `path` (the path with its leading
        `/`), and whether it is exact: only a pattern's match cannot be said so."""
        raise NotImplementedError


@dataclass(frozen=True)
class _Compare(Expression):
    field: str
    operator: str
    value: str
    pattern: re.Pattern[str] | None = None

    def _subject(self, format: str, path: str) -> str:
        return format if self.field == "format" else path

    def matches(self, format: str, path: str) -> bool:
        subject = self._subject(format, path)
        if self.operator == "==":
            return subject == self.value
        if self.operator == "=^":
            return subject.startswith(self.value)
        assert self.pattern is not None
        return self.pattern.fullmatch(subject) is not None

    def under(self, format: str, folder: str) -> Reach:
        if self.field == "format":
            return Reach.ALL if self.matches(format, "") else Reach.NONE
        if self.operator == "==":
            return Reach.SOME if self.value.startswith(folder) else Reach.NONE
        if self.operator == "=^":
            if folder.startswith(self.value):
                return Reach.ALL
            return Reach.SOME if self.value.startswith(folder) else Reach.NONE
        return Reach.SOME  # what a pattern matches under a folder cannot be told

    def narrowing(self, format: str, path: ColumnElement[str]) -> tuple[ColumnElement[bool], bool]:
        if self.field == "format":
            return (true() if self.matches(format, "") else false()), True
        if self.operator == "==":
            return path == self.value, True
        if self.operator == "=^":
            return path.startswith(self.value, autoescape=True), True
        return true(), False


@dataclass(frozen=True)
class _Not(Expression):
    inner: Expression

    def matches(self, format: str, path: str) -> bool:
        return not self.inner.matches(format, path)

    def under(self, format: str, folder: str) -> Reach:
        inner = self.inner.under(format, folder)
        return {Reach.ALL: Reach.NONE, Reach.NONE: Reach.ALL}.get(inner, Reach.SOME)

    def narrowing(self, format: str, path: ColumnElement[str]) -> tuple[ColumnElement[bool], bool]:
        condition, exact = self.inner.narrowing(format, path)
        # The opposite of a wider condition is a narrower one: only an exact one turns.
        return (not_(condition), True) if exact else (true(), False)


@dataclass(frozen=True)
class _Both(Expression):
    left: Expression
    right: Expression

    def matches(self, format: str, path: str) -> bool:
        return self.left.matches(format, path) and self.right.matches(format, path)

    def under(self, format: str, folder: str) -> Reach:
        left, right = self.left.under(format, folder), self.right.under(format, folder)
        if Reach.NONE in (left, right):
            return Reach.NONE
        return Reach.ALL if left is right is Reach.ALL else Reach.SOME

    def narrowing(self, format: str, path: ColumnElement[str]) -> tuple[ColumnElement[bool], bool]:
        (left, exact_left), (right, exact_right) = (
            self.left.narrowing(format, path),
            self.right.narrowing(format, path),
        )
        return and_(left, right), exact_left and exact_right


@dataclass(frozen=True)
class _Either(Expression):
    left: Expression
    right: Expression

    def matches(self, format: str, path: str) -> bool:
        return self.left.matches(format, path) or self.right.matches(format, path)

    def under(self, format: str, folder: str) -> Reach:
        left, right = self.left.under(format, folder), self.right.under(format, folder)
        if Reach.ALL in (left, right):
            return Reach.ALL
        return Reach.NONE if left is right is Reach.NONE else Reach.SOME

    def narrowing(self, format: str, path: ColumnElement[str]) -> tuple[ColumnElement[bool], bool]:
        (left, exact_left), (right, exact_right) = (
            self.left.narrowing(format, path),
            self.right.narrowing(format, path),
        )
        return or_(left, right), exact_left and exact_right


class _Parser:
    def __init__(self, text: str) -> None:
        self.tokens = _tokens(text)
        self.index = 0
        self.depth = 0

    def peek(self) -> _Token:
        return self.tokens[self.index]

    def take(self) -> _Token:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def word(self, text: str) -> bool:
        token = self.peek()
        if token.kind == "word" and token.text == text:
            self.index += 1
            return True
        return False

    def either(self) -> Expression:
        found = self.both()
        while self.word("or"):
            found = _Either(found, self.both())
        return found

    def both(self) -> Expression:
        found = self.negated()
        while self.word("and"):
            found = _Both(found, self.negated())
        return found

    def negated(self) -> Expression:
        at = self.peek().at
        if self.word("not"):
            self.depth += 1
            if self.depth > MAX_DEPTH:
                raise SelectorError("Too deeply nested", at)
            found: Expression = _Not(self.negated())
            self.depth -= 1
            return found
        return self.primary()

    def primary(self) -> Expression:
        token = self.take()
        if token.kind == "open":
            self.depth += 1
            if self.depth > MAX_DEPTH:
                raise SelectorError("Too deeply nested", token.at)
            found = self.either()
            closing = self.take()
            if closing.kind != "close":
                raise SelectorError("Expected )", closing.at)
            self.depth -= 1
            return found
        if token.kind != "word" or token.text not in FIELDS:
            raise SelectorError("Expected format, path or (", token.at)
        operator = self.take()
        if operator.kind != "operator":
            raise SelectorError("Expected ==, =^ or =~", operator.at)
        value = self.take()
        if value.kind != "string":
            raise SelectorError("Expected a string in double quotes", value.at)
        if operator.text != "=~":
            return _Compare(token.text, operator.text, value.text)
        if len(value.text) > MAX_PATTERN:
            raise SelectorError(f"A pattern is at most {MAX_PATTERN} characters", value.at)
        try:
            compiled = re.compile(value.text)
        except re.error as error:
            raise SelectorError(f"Not a pattern: {error.msg}", value.at) from None
        return _Compare(token.text, operator.text, value.text, compiled)


@functools.lru_cache(maxsize=1024)
def parse(text: str) -> Expression:
    """The expression a text says. Raises SelectorError, saying where."""
    if len(text) > MAX_LENGTH:
        raise SelectorError(f"An expression is at most {MAX_LENGTH} characters", MAX_LENGTH + 1)
    parser = _Parser(text)
    if parser.peek().kind == "end":
        raise SelectorError("An expression is needed", 1)
    found = parser.either()
    rest = parser.peek()
    if rest.kind != "end":
        raise SelectorError(f"Unexpected {rest.text!r}", rest.at)
    return found


async def held(db: AsyncSession, patterns: Iterable[str]) -> dict[str, str]:
    """The selectors these patterns can name, each by its name with its expression: none
    for whoever holds no selector permission, which is most callers, at no cost."""
    named: set[str] = set()
    every = False
    for pattern in patterns:
        parts = pattern.split(":")
        if parts[0] not in ("selector", "*") or len(parts) == 1:
            continue  # not a selector's, or `*`, which reaches every repository whole
        if parts[1] == "*":
            every = True
        else:
            named.add(parts[1])
    if not every and not named:
        return {}
    query = select(ContentSelector.name, ContentSelector.expression)
    if not every:
        query = query.where(ContentSelector.name.in_(named))
    return dict((await db.execute(query)).all())
