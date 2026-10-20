# External Identity: Content Selectors and `may` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A selector permission (`selector:<selector>:<format>:<repository>:<action>`) gives an action on the paths a content selector's expression matches. One function, `may`, decides every check of content: the content route, groups, writes, deletes, Docker, the content API's listings and files, search, and MCP through its routes.

**Architecture:**
- **Expressions.** `security/selectors.py` parses D2's expressions once and says three things about each: whether a path matches; whether a folder may hold a match; and a condition a database can test first.
- **The selectors themselves.** They are a table with their own API, permissions and audit records, and roles name only selectors that exist.
- **Who may do what.** A principal carries the selectors its permissions name. `security/access.py` (`reach`, `may`, `require`) is the one place that decides access to content.
- **Where it is checked.** The content context, the content route and the registry check each path through it.
- **Listings.** The content API, search and MCP list only what is reached, narrowed in the database (`repositories/reached.py`) and then checked exactly where a pattern is involved.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy and Alembic (PostgreSQL), Python's `re`; the frontend's generated API types.

**Spec:** [docs/superpowers/specs/2026-10-19-identity-audit-selectors-design.md](../specs/2026-10-19-identity-audit-selectors-design.md): section 10, with E6, D2, 11, 12, 14 and the row of plan 15g in 13; the "Settled" tables of 15a to 15f (15f's audit records).

## Decisions this plan settles

Task 5 writes these into the spec, as "Settled while building plan 15g".

| # | Decision | Reason |
| --- | --- | --- |
| G1 | Expressions are `security/selectors.py`'s: a parser of the grammar of D2 (keywords lower case; a string's only escapes `\"` and `\\`), at most 4,000 characters, 32 levels deep, a pattern at most 1,000; refused with `SelectorError`, the message and the character (from 1). `parse` is kept by the expression's text (1,024 at most), which is the selector's version: a changed selector is parsed anew. | D2; section 10; 14: compiled once. |
| G2 | An expression says three things: `matches(format, path)`; `under(format, folder)`, whether no path, some or every path under a folder may match (a pattern: some), for listing folders; and `narrowing(format, path_column)`, a condition a database can test that every match meets, exact unless a pattern is in it, for listing only what may match before each is checked. | Section 10: listings and search leave out what a caller may not see, without reading every path where a prefix says it. |
| G3 | Selectors are `content_selectors` (name unique, as a permission's segment; description; expression; times), at `/api/v1/content-selectors` with `admin:selectors:read` and `write`; the name does not change. A role names only selectors there are, or every one (`selector:*`); one a role names is not deleted (`409 in_use`). Each change is recorded (`selector.created`, `updated`, `deleted`). Preview takes an expression, a format and at most 100 paths, `/` put before a path without one. | Section 10; 15f's audit. |
| G4 | A principal carries the selectors its patterns (and the public's) can name, each by its name with its expression, read with it; none, at no cost, for whoever holds no selector permission. `security/access.py` decides: `reach(principal, repository, action)` is the whole (by a repository permission) or the expressions of the selector permissions that name it; `may` is a path of it; `require` and `require_somewhere` answer 401 or 403 as `authorize` does. | E6; section 14: only a principal holding selector permissions evaluates them. |
| G5 | A token's scopes grant a selector permission if they grant it, or the repository permission it narrows (`selector:s:maven:releases:read` as `repository:maven:releases:read`): a read-only token reads through a selector. The anonymous user's selector permissions are public, as its repository permissions are. | Section 10 is silent: a token that may only read must not lose what a selector gives its user to read. |
| G6 | The content route and the registry check `read` at the path asked, with a `/` before it; a path is never rewritten to be served, and one that is not canonical is refused before it is (`invalid_path`). Each file stored is checked at its path (`add` or `edit`), each deleted at its own (`delete`); an upload whose paths are known only as it is read needs `add` or `edit` somewhere first. A version's attributes (npm's deprecate) need `edit` at its file. A document a format keeps beside what was uploaded (Maven's metadata, npm's package document) is written as part of that upload, not checked again. | Section 10: reads, writes and deletes. |
| G7 | Through a group, the group's permission is checked at the path asked, and its members are not checked again (as `group.py` has it for repository permissions): each member is asked for that path, which is the member's path. | Section 10: "through groups (each member's path checked)". |
| G8 | A repository is listed, and its page and members shown, to a caller whose reach of it for `browse` is something: the whole, or a selector that can match its format. In it: folders that may hold something reached (`under`), files reached, components with a file reached (each with only those files), counted exactly; search likewise. A file or component not reached is `404`, as one that is not there. Deleting a folder deletes what may be deleted, and keeps the rest unsaid. | Section 10: listings, search, `browse some of it`. |
| G9 | Listing through a reach that is not the whole asks the database for the components with a file the narrowing keeps (`repositories/reached.py`), and, where a pattern makes it inexact, checks those files one by one and leaves out the components none of whose files is reached; totals stay exact and paging stays in the database. | Section 14: selectors must not slow every read. |
| G10 | Docker's catalog lists, of the images of a repository reached, those under whose name (`<image>/`) something may be reached. | Section 10: Docker, at the path of the registry's request. |

## Global Constraints

- **An expression (D2):** `format == "maven"`, `path =^ "/com/acme/"`, `path =~ "^/org/[^/]+/[^/]+/1\.0/.*$"`; `and`, `or`, `not`, parentheses; strings in double quotes with `\"` and `\\`. **`path` starts with `/`.** **`=~` matches the whole path (Python's `re.fullmatch`, a pattern of at most 1,000 characters, compiled once).** An expression that does not parse is refused at its field, saying where (section 10).
- **A permission `selector:<selector>:<format>:<repository>:<action>` (each part `*` allowed; the actions are the repository permission's)** (section 10).
- **One function decides access to content, given the repository, the path and the action: `may`** (E6). **Every check of content moves to it** (section 10).
- **A repository is listed to a caller who may browse some of it** (section 10). **`admin:selectors:read` and `write`; a selector a role names cannot be deleted** (section 10).
- **Only a principal holding selector permissions evaluates them** (section 14). **Every new list is paged** (API-5).
- **A table's line under its headings is `| --- | --- |`** (one `---` cell a column). Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Working directories:** run `uv` and `pytest` commands in `backend/`, with `MEGOOARTI_TEST_DATABASE_URL` set to your test database; `pnpm` commands in `frontend/`; `git` commands in the repository root.

## Review Focus

These are the failures that would hurt a person using this most, each with the test in this plan that pins it.

1. **A path written another way to slip past a selector.** A `not path =^ "/secret/"` selector asked for `%2E/secret/x.txt` must not serve the file: the path checked is the one served, and a path that is not canonical is refused. Pinned by Task 4's `test_a_path_written_another_way_is_not_served_past_a_selector`.
2. **A selector changed while people use it.** What it reaches changes at once: no principal or parse cache keeps the old expression. Pinned by Task 4's `test_a_selector_changed_reaches_what_it_says_at_once`.
3. **A read-only token of someone who reads through a selector.** It still reads there, and adds nothing. Pinned by Task 3's `test_a_tokens_scopes_narrow_a_selector_permission_as_its_repository_permission`.
4. **A listing decided by a pattern.** Its folders, files, components and totals show only what the pattern reaches, with exact counts. Pinned by Task 5's `test_through_a_pattern_components_are_those_a_file_of_matches` and `test_components_are_those_with_a_file_reached`.
5. **A permission naming a selector that is gone, or one that no longer parses.** It reaches nothing and fails no request. Pinned by Task 3's `test_may_decides_by_repository_and_selector_permissions` (the `gone` and `broken` rows).

---

### Task 1: Selector expressions

**Files:**
- Create: `backend/src/megooarti/security/selectors.py`
- Test: `backend/tests/security/test_selectors.py`

**Interfaces:**
- Consumes: nothing of this plan; SQLAlchemy's column expressions.
- Produces:
  - Parsing: `selectors.parse(text) -> Expression` (kept by its text), `SelectorError(message, position)`, `Reach` (`NONE`, `SOME`, `ALL`), `MAX_LENGTH`, `MAX_PATTERN`.
  - On an `Expression`: `matches(format, path) -> bool`, `under(format, folder) -> Reach`, `narrowing(format, path_column) -> (condition, exact)`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/security/test_selectors.py`:

```python
"""Content selectors' expressions (spec 10, D2): what they say, what they match, what they
refuse and where, and what they let a listing leave out."""

import pytest
from sqlalchemy import literal, select

from megooarti.security.selectors import Reach, SelectorError, parse

PATHS = [
    "/com/acme/app/1.0/app-1.0.jar",
    "/com/acme/lib/2.0/lib-2.0.pom",
    "/org/example/tool/1.0/tool-1.0.jar",
    "/org/example/tool/1.1/tool-1.1.jar",
    '/odd/"quoted"/a\\b.txt',
]


@pytest.mark.parametrize(
    ("text", "format", "matching"),
    [
        ('format == "maven"', "maven", PATHS),
        ('format == "maven"', "npm", []),
        ('path == "/com/acme/app/1.0/app-1.0.jar"', "maven", PATHS[:1]),
        ('path =^ "/com/acme/"', "maven", PATHS[:2]),
        ('path =~ "^/org/[^/]+/[^/]+/1\\\\.0/.*$"', "maven", PATHS[2:3]),
        ('path =~ "/org/.*"', "maven", PATHS[2:4]),  # the whole path, anchored or not
        ('path =~ "org"', "maven", []),
        ('not path =^ "/com/"', "maven", PATHS[2:]),
        ('format == "maven" and path =^ "/org/"', "maven", PATHS[2:4]),
        ('path =^ "/com/acme/lib/" or path =~ ".*1\\\\.1.*"', "maven", [PATHS[1], PATHS[3]]),
        ('not (path =^ "/com/" or path =^ "/org/")', "maven", PATHS[4:]),
        ('path == "/odd/\\"quoted\\"/a\\\\b.txt"', "raw", PATHS[4:]),
        ('  path=^"/com/acme/app/"and format=="maven"  ', "maven", PATHS[:1]),
    ],
)
def test_an_expression_matches_what_it_says(text, format, matching):
    expression = parse(text)

    assert [path for path in PATHS if expression.matches(format, path)] == matching


def test_and_binds_before_or_and_not_before_both():
    # a or (b and c), and (not a) and b
    either = parse('path =^ "/com/" or path =^ "/org/" and path =^ "/org/none/"')
    negated = parse('not path =^ "/com/" and path =^ "/org/"')

    assert [path for path in PATHS if either.matches("maven", path)] == PATHS[:2]
    assert [path for path in PATHS if negated.matches("maven", path)] == PATHS[2:4]


@pytest.mark.parametrize(
    ("text", "position", "said"),
    [
        ("", 1, "An expression is needed"),
        ('format = "maven"', 8, "Unexpected '='"),
        ('name == "x"', 1, "Expected format, path or ("),
        ('path "x"', 6, "Expected ==, =^ or =~"),
        ("path == maven", 9, "Expected a string in double quotes"),
        ('path == "open', 9, "A string is not closed"),
        ('path == "a\\n"', 11, 'Only \\" and \\\\ are written so'),
        ('(path == "x"', 13, "Expected )"),
        ('path == "x" path == "y"', 13, "Unexpected 'path'"),
        ('path =~ "("', 9, "Not a pattern"),
        ('path == "x" and', 16, "Expected format, path or ("),
        ('Path == "x"', 1, "Expected format, path or ("),
        ('path == "x" AND path == "y"', 13, "Unexpected 'AND'"),
    ],
)
def test_what_does_not_parse_is_refused_saying_where(text, position, said):
    with pytest.raises(SelectorError) as refused:
        parse(text)

    assert refused.value.position == position
    assert refused.value.message.startswith(said)


def test_too_long_a_pattern_or_too_deep_a_nesting_is_refused():
    with pytest.raises(SelectorError, match="at most 1000"):
        parse('path =~ "' + "a" * 1001 + '"')
    with pytest.raises(SelectorError, match="Too deeply nested"):
        parse("(" * 40 + 'path == "x"' + ")" * 40)
    with pytest.raises(SelectorError, match="Too deeply nested"):
        parse("not " * 40 + 'path == "x"')


def test_an_expression_is_parsed_once_for_its_text():
    assert parse('path =^ "/com/"') is parse('path =^ "/com/"')


@pytest.mark.parametrize(
    ("text", "folder", "reach"),
    [
        ('path =^ "/com/acme/"', "/", Reach.SOME),
        ('path =^ "/com/acme/"', "/com/", Reach.SOME),
        ('path =^ "/com/acme/"', "/com/acme/lib/", Reach.ALL),
        ('path =^ "/com/acme/"', "/org/", Reach.NONE),
        ('path == "/com/acme/app/1.0/app-1.0.jar"', "/com/acme/", Reach.SOME),
        ('path == "/com/acme/app/1.0/app-1.0.jar"', "/org/", Reach.NONE),
        ('path =~ "/org/.*"', "/com/", Reach.SOME),  # a pattern's reach cannot be told
        ('format == "npm"', "/", Reach.NONE),
        ('format == "maven"', "/", Reach.ALL),
        ('not path =^ "/com/"', "/com/acme/", Reach.NONE),
        ('not path =^ "/com/"', "/org/", Reach.ALL),
        ('path =^ "/com/" and path =^ "/org/"', "/", Reach.SOME),
        ('path =^ "/com/" and format == "npm"', "/com/", Reach.NONE),
        ('path =^ "/com/" or path =^ "/org/"', "/org/example/", Reach.ALL),
        ('path =^ "/com/" or path =^ "/org/"', "/net/", Reach.NONE),
    ],
)
def test_an_expression_says_how_much_of_a_folder_it_may_match(text, folder, reach):
    assert parse(text).under("maven", folder) is reach


@pytest.mark.parametrize(
    "text",
    [
        'path =^ "/com/acme/"',
        'path == "/org/example/tool/1.0/tool-1.0.jar"',
        'path =~ "/org/.*1\\\\.1.*"',
        'not path =^ "/com/"',
        'not path =~ "/com/.*"',
        'path =^ "/org/" and not path =~ ".*1\\\\.0.*"',
        'path =^ "/com/acme/lib/" or path =~ ".*1\\\\.1.*"',
        'path =^ "/odd/\\"quoted\\"/" or path =^ "/a%_b/"',
        'format == "npm" or path =^ "/org/"',
    ],
)
async def test_what_a_database_is_asked_keeps_every_match_and_is_exact_where_it_says(db, text):
    expression = parse(text)
    paths = [*PATHS, "/a%_b/c", "/aXYb/c"]

    for path in paths:
        condition, exact = expression.narrowing("maven", literal(path))
        kept = await db.scalar(select(condition))
        matched = expression.matches("maven", path)
        assert kept or not matched, (text, path)
        if exact:
            assert kept == matched, (text, path)
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `backend/`): `uv run pytest -q tests/security/test_selectors.py`
Expected: The tests do not load: `ModuleNotFoundError: No module named 'megooarti.security.selectors'`.

- [ ] **Step 3: Write the code**

Create `backend/src/megooarti/security/selectors.py`:

```python
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
from dataclasses import dataclass

from sqlalchemy import ColumnElement, and_, false, not_, or_, true

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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest -q tests/security/test_selectors.py`
Expected: 53 passed.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat(security): content selectors' expressions: parsed once, refused saying where; what they match, under which folders, and what a database can be asked first"
```

---

### Task 2: Content selectors kept, previewed, and named by roles

**Files:**
- Create: `backend/src/megooarti/security/api/selectors.py`, `backend/src/megooarti/migrations/versions/0013_add_content_selectors.py`
- Modify:
  - `backend/src/megooarti/security/models.py` (`ContentSelector`), `backend/src/megooarti/security/roles.py` (a role names only selectors there are), `backend/src/megooarti/main.py`.
  - `docs/administration.md` (the permission's row).
  - `frontend/openapi.json` (written by the snapshot test with `MEGOOARTI_UPDATE_OPENAPI=1`) and `frontend/src/lib/api/schema.d.ts` (written by `pnpm gen:api`).
- Test: `backend/tests/security/test_content_selectors_api.py`

**Interfaces:**
- Consumes: Task 1's `parse`, `SelectorError`, `MAX_LENGTH`; 15f's `audit.record`, `audit.diff`; `names.NewName`; `pagination`.
- Produces:
  - The model `ContentSelector` (`name`, `description`, `expression`).
  - Routes: `GET`/`POST /api/v1/content-selectors`, `GET`/`PUT`/`DELETE /api/v1/content-selectors/{name}`, `POST /api/v1/content-selectors/preview`.
  - The permissions `admin:selectors:read` and `admin:selectors:write`, and the events `selector.created`, `selector.updated`, `selector.deleted`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/security/test_content_selectors_api.py`:

```python
"""Content selectors' API (spec 10): kept with their own permissions, refused at their
expression saying where, previewed against paths, recorded in the audit log, and kept
while a role names them."""

import pytest

from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.audit import last

SELECTORS = "/api/v1/content-selectors"
ACME = {"name": "acme", "description": "Acme's", "expression": 'path =^ "/com/acme/"'}


async def make_role(sessionmaker, name: str, *patterns: str) -> None:
    async with sessionmaker() as db:
        await roles.create_role(db, name, "", list(patterns), [])
        await db.commit()


async def test_a_selector_is_made_listed_changed_and_deleted_with_its_records(
    admin_client, sessionmaker
):
    made = await admin_client.post(SELECTORS, json=ACME)
    listed = await admin_client.get(SELECTORS)
    changed = await admin_client.put(
        f"{SELECTORS}/acme", json={"description": "Acme's", "expression": 'path =^ "/com/"'}
    )
    read = await admin_client.get(f"{SELECTORS}/acme")
    deleted = await admin_client.delete(f"{SELECTORS}/acme")
    gone = await admin_client.get(f"{SELECTORS}/acme")

    assert made.status_code == 201
    assert (made.json()["name"], made.json()["expression"]) == ("acme", 'path =^ "/com/acme/"')
    assert [found["name"] for found in listed.json()["items"]] == ["acme"]
    assert changed.status_code == 200
    assert read.json()["expression"] == 'path =^ "/com/"'
    assert (deleted.status_code, gone.status_code) == (204, 404)
    assert (await last(sessionmaker, "selector.created")).target_name == "acme"
    assert (await last(sessionmaker, "selector.updated")).changes == {
        "expression": {"before": 'path =^ "/com/acme/"', "after": 'path =^ "/com/"'}
    }
    assert (await last(sessionmaker, "selector.deleted")).target_name == "acme"


@pytest.mark.parametrize(
    ("expression", "said"),
    [
        ('path = "/com/"', "Unexpected '=' (at character 6)"),
        (
            'path =~ "(unclosed"',
            "Not a pattern: missing ), unterminated subpattern (at character 9)",
        ),
        ('name == "x"', "Expected format, path or ( (at character 1)"),
    ],
)
async def test_an_expression_that_does_not_parse_is_refused_saying_where(
    admin_client, expression, said
):
    refused = await admin_client.post(SELECTORS, json={**ACME, "expression": expression})
    changed = await admin_client.post(SELECTORS, json=ACME)
    refused_change = await admin_client.put(
        f"{SELECTORS}/acme", json={"description": "", "expression": expression}
    )

    assert changed.status_code == 201
    for answer in (refused, refused_change):
        assert (answer.status_code, error_code(answer)) == (422, "validation_error")
        assert answer.json()["error"]["details"] == [{"field": "expression", "message": said}]


@pytest.mark.parametrize("name", ["with space", "a:b", "..", "x" * 65])
async def test_a_name_a_permission_could_not_hold_is_refused(admin_client, name):
    refused = await admin_client.post(SELECTORS, json={**ACME, "name": name})

    assert refused.status_code == 422


async def test_a_name_taken_is_a_conflict(admin_client):
    await admin_client.post(SELECTORS, json=ACME)

    again = await admin_client.post(SELECTORS, json=ACME)

    assert (again.status_code, error_code(again)) == (409, "conflict")


async def test_a_preview_says_which_paths_match(admin_client):
    said = await admin_client.post(
        f"{SELECTORS}/preview",
        json={
            "expression": 'format == "maven" and path =^ "/com/acme/"',
            "format": "maven",
            "paths": ["/com/acme/app/1.0/app-1.0.jar", "com/acme/lib.pom", "/org/x.jar"],
        },
    )

    assert said.json() == {
        "paths": [
            {"path": "/com/acme/app/1.0/app-1.0.jar", "matches": True},
            {"path": "/com/acme/lib.pom", "matches": True},
            {"path": "/org/x.jar", "matches": False},
        ]
    }


async def test_a_role_names_only_a_selector_there_is_and_keeps_it(admin_client):
    await admin_client.post(SELECTORS, json=ACME)
    unknown = await admin_client.post(
        "/api/v1/roles",
        json={
            "name": "acme-readers",
            "permissions": ["selector:nobody:maven:*:read"],
            "roles": [],
        },
    )
    every = await admin_client.post(
        "/api/v1/roles",
        json={"name": "every-selector", "permissions": ["selector:*:maven:*:read"], "roles": []},
    )
    named = await admin_client.post(
        "/api/v1/roles",
        json={"name": "acme-readers", "permissions": ["selector:acme:maven:*:read"], "roles": []},
    )

    kept = await admin_client.delete(f"{SELECTORS}/acme")

    assert (unknown.status_code, error_code(unknown)) == (422, "validation_error")
    assert unknown.json()["error"]["details"] == [
        {"field": "permissions", "message": "Unknown content selector: nobody"}
    ]
    assert (every.status_code, named.status_code) == (201, 201)
    assert (kept.status_code, error_code(kept)) == (409, "in_use")
    assert "acme-readers" in kept.json()["error"]["message"]
    assert "every-selector" not in kept.json()["error"]["message"]


async def test_selectors_need_their_permissions(client, make_user, sessionmaker):
    await make_role(sessionmaker, "selector-readers", "admin:selectors:read")
    await make_user("rita", roles=["selector-readers"])
    await make_user("sam")
    rita = basic("rita", PASSWORD)

    nobody = await client.get(SELECTORS)
    sam = await client.get(SELECTORS, headers=basic("sam", PASSWORD))
    reads = await client.get(SELECTORS, headers=rita)
    previews = await client.post(
        f"{SELECTORS}/preview", json={"expression": 'path =^ "/"', "paths": []}, headers=rita
    )
    makes = await client.post(SELECTORS, json=ACME, headers=rita)

    assert (nobody.status_code, sam.status_code) == (401, 403)
    assert (reads.status_code, previews.status_code, makes.status_code) == (200, 200, 403)
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `backend/`): `uv run pytest -q tests/security/test_content_selectors_api.py`
Expected: 12 failed: there are no such routes (`404`).

- [ ] **Step 3: Write the code**

Change `backend/src/megooarti/security/models.py`:

```diff
@@ -8,7 +8,7 @@ import uuid
 from datetime import datetime
 from typing import Any
 
-from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
+from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
 from sqlalchemy.dialects.postgresql import JSONB
 from sqlalchemy.orm import Mapped, mapped_column
 
@@ -73,6 +73,22 @@ class Role(Base):
     builtin: Mapped[bool] = mapped_column(default=False)
 
 
+class ContentSelector(Base):
+    """Which content of repositories a selector permission reaches, by an expression of
+    their format and their paths (spec 10): `selector:<name>:<format>:<repository>:<action>`."""
+
+    __tablename__ = "content_selectors"
+
+    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
+    name: Mapped[str] = mapped_column(String(64), unique=True)
+    description: Mapped[str] = mapped_column(String(255), default="")
+    expression: Mapped[str] = mapped_column(Text)
+    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
+    updated_at: Mapped[datetime] = mapped_column(
+        DateTime(timezone=True), default=utcnow, onupdate=utcnow
+    )
+
+
 class RolePermission(Base):
     __tablename__ = "role_permissions"
 
```

Create `backend/src/megooarti/migrations/versions/0013_add_content_selectors.py`:

```python
"""add content selectors, which selector permissions name

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "content_selectors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("expression", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_content_selectors")),
        sa.UniqueConstraint("name", name=op.f("uq_content_selectors_name")),
    )


def downgrade() -> None:
    op.drop_table("content_selectors")
```

Create `backend/src/megooarti/security/api/selectors.py`:

```python
"""Content selectors (spec 10): named expressions of a repository's format and paths, which
selector permissions (`selector:<name>:<format>:<repository>:<action>`) name. Kept with
`admin:selectors:read` and `write`; one a role names is not deleted."""

import uuid
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.names import NewName
from megooarti.pagination import Page, PageParams, page
from megooarti.security.authentication import Principal, require
from megooarti.security.models import ContentSelector, Role, RolePermission
from megooarti.security.selectors import MAX_LENGTH, SelectorError, parse
from megooarti.system import audit

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/content-selectors", tags=["content selectors"])


class SelectorOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    expression: str
    created_at: datetime
    updated_at: datetime


class SelectorContent(BaseModel):
    description: str = Field(default="", max_length=255)
    expression: str = Field(min_length=1, max_length=MAX_LENGTH)


class SelectorCreate(SelectorContent):
    name: NewName


class Preview(BaseModel):
    expression: str = Field(min_length=1, max_length=MAX_LENGTH)
    format: str = Field(default="", max_length=32)
    paths: list[str] = Field(default=[], max_length=100)


class Previewed(BaseModel):
    path: str
    matches: bool


class PreviewOut(BaseModel):
    paths: list[Previewed]


def _parsed(expression: str, field: str = "expression") -> None:
    """Refuse an expression that does not parse, at its field, saying where."""
    try:
        parse(expression)
    except SelectorError as error:
        details = [{"field": field, "message": str(error)}]
        raise ApiError(422, "validation_error", "The request is not valid.", details) from None


def _told(selector: ContentSelector) -> dict:
    return {"description": selector.description, "expression": selector.expression}


async def _load(db: AsyncSession, name: str) -> ContentSelector:
    found = await db.scalar(select(ContentSelector).where(ContentSelector.name == name))
    if found is None:
        raise ApiError(404, "not_found", "No such content selector.")
    return found


@router.get("", response_model=Page[SelectorOut])
async def list_selectors(
    params: PageParams = Depends(),
    _: Principal = Depends(require("admin:selectors:read")),
    db: AsyncSession = Depends(get_session),
) -> dict:
    total = await db.scalar(select(func.count()).select_from(ContentSelector))
    found = await db.scalars(
        select(ContentSelector)
        .order_by(ContentSelector.name)
        .limit(params.limit)
        .offset(params.offset)
    )
    return page(list(found), total or 0, params)


@router.post("", response_model=SelectorOut, status_code=201)
async def create_selector(
    body: SelectorCreate,
    principal: Principal = Depends(require("admin:selectors:write")),
    db: AsyncSession = Depends(get_session),
) -> ContentSelector:
    _parsed(body.expression)
    if await db.scalar(select(ContentSelector.id).where(ContentSelector.name == body.name)):
        raise ApiError(409, "conflict", f"A content selector named {body.name} already exists.")
    selector = ContentSelector(
        name=body.name, description=body.description, expression=body.expression
    )
    db.add(selector)
    await db.flush()
    audit.record(
        db, "selector.created", ("selector", selector.name), audit.diff(None, _told(selector))
    )
    await db.commit()
    log.info("selector_created", selector=selector.name, by=principal.user.username)
    return selector


@router.post("/preview", response_model=PreviewOut)
async def preview(
    body: Preview,
    _: Principal = Depends(require("admin:selectors:read")),
) -> PreviewOut:
    """Which of these paths an expression matches, in a repository of this format. A path
    is taken as starting with `/`."""
    _parsed(body.expression)
    expression = parse(body.expression)
    paths = [path if path.startswith("/") else f"/{path}" for path in body.paths]
    return PreviewOut(
        paths=[
            Previewed(path=path, matches=expression.matches(body.format, path)) for path in paths
        ]
    )


@router.get("/{name}", response_model=SelectorOut)
async def get_selector(
    name: str,
    _: Principal = Depends(require("admin:selectors:read")),
    db: AsyncSession = Depends(get_session),
) -> ContentSelector:
    return await _load(db, name)


@router.put("/{name}", response_model=SelectorOut)
async def update_selector(
    name: str,
    body: SelectorContent,
    principal: Principal = Depends(require("admin:selectors:write")),
    db: AsyncSession = Depends(get_session),
) -> ContentSelector:
    """Change what a selector matches: at once, for every permission that names it."""
    _parsed(body.expression)
    selector = await _load(db, name)
    before = _told(selector)
    selector.description, selector.expression = body.description, body.expression
    await db.flush()
    audit.record(
        db, "selector.updated", ("selector", selector.name), audit.diff(before, _told(selector))
    )
    await db.commit()
    log.info("selector_updated", selector=selector.name, by=principal.user.username)
    return selector


@router.delete("/{name}", status_code=204)
async def delete_selector(
    name: str,
    principal: Principal = Depends(require("admin:selectors:write")),
    db: AsyncSession = Depends(get_session),
) -> None:
    """Delete a selector no role names."""
    selector = await _load(db, name)
    naming = list(
        await db.scalars(
            select(Role.name)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .where(
                or_(
                    RolePermission.pattern == f"selector:{name}",
                    RolePermission.pattern.startswith(f"selector:{name}:", autoescape=True),
                )
            )
            .distinct()
            .order_by(Role.name)
        )
    )
    if naming:
        raise ApiError(409, "in_use", f"Roles name this content selector: {', '.join(naming)}.")
    before = _told(selector)
    await db.delete(selector)
    audit.record(db, "selector.deleted", ("selector", name), audit.diff(before, None))
    await db.commit()
    log.info("selector_deleted", selector=name, by=principal.user.username)
```

Change `backend/src/megooarti/security/roles.py`:

```diff
@@ -8,7 +8,7 @@ from sqlalchemy import delete, func, insert, select
 from sqlalchemy.ext.asyncio import AsyncSession
 
 from megooarti.errors import ApiError
-from megooarti.security.models import Role, RoleMember, RolePermission
+from megooarti.security.models import ContentSelector, Role, RoleMember, RolePermission
 from megooarti.system import audit
 from megooarti.system.settings_store import get_setting
 
@@ -83,9 +83,32 @@ async def list_roles(db: AsyncSession, limit: int, offset: int) -> tuple[list[Ro
     return [await describe(db, role) for role in page], total or 0
 
 
+async def _selectors_named(db: AsyncSession, patterns: Iterable[str]) -> None:
+    """A selector permission names a content selector there is, or every one (`*`)."""
+    named = {
+        parts[1]
+        for pattern in patterns
+        if (parts := pattern.split(":"))[0] == "selector" and len(parts) > 1 and parts[1] != "*"
+    }
+    if not named:
+        return
+    found = set(
+        await db.scalars(select(ContentSelector.name).where(ContentSelector.name.in_(named)))
+    )
+    missing = sorted(named - found)
+    if missing:
+        details = [
+            {"field": "permissions", "message": f"Unknown content selector: {name}"}
+            for name in missing
+        ]
+        raise ApiError(422, "validation_error", "The request is not valid.", details)
+
+
 async def _replace_content(
     db: AsyncSession, role: Role, permissions: Iterable[str], member_names: Iterable[str]
 ) -> None:
+    permissions = list(permissions)
+    await _selectors_named(db, permissions)
     members = await roles_named(db, member_names)
     member_ids = {member.id for member in members}
     if role.id in await reachable_role_ids(db, member_ids):
```

Change `backend/src/megooarti/main.py`:

```diff
@@ -44,6 +44,7 @@ from megooarti.security.api import me as me_api
 from megooarti.security.api import oauth as oauth_api
 from megooarti.security.api import oidc as oidc_api
 from megooarti.security.api import roles as roles_api
+from megooarti.security.api import selectors as selectors_api
 from megooarti.security.api import sources as sources_api
 from megooarti.security.api import users as users_api
 from megooarti.security.bootstrap import ensure_initial_admin_password
@@ -200,6 +201,7 @@ def create_app(settings: Settings | None = None) -> FastAPI:
     app.include_router(me_api.router, prefix=API_PREFIX)
     app.include_router(users_api.router, prefix=API_PREFIX)
     app.include_router(roles_api.router, prefix=API_PREFIX)
+    app.include_router(selectors_api.router, prefix=API_PREFIX)
     app.include_router(sources_api.router, prefix=API_PREFIX)
     app.include_router(settings_router, prefix=API_PREFIX)
     app.include_router(information_router, prefix=API_PREFIX)
```

Change `docs/administration.md`:

```diff
@@ -292,6 +292,7 @@ area's name alone gives both.
 | `admin:security` | How people sign in: the sign-in sources and their order, the default role, and whether MegooArti's own users sign in |
 | `admin:certificates` | The certificates outbound TLS trusts besides the usual authorities; to write, also fetching what a host presents |
 | `admin:audit` | The audit log: to read, its records and their export; to write, how many days they are kept |
+| `admin:selectors` | The content selectors: the expressions that selector permissions name |
 
 What a repository holds is not given by these, but by `repository:` permissions:
 see [Repositories](repositories.md). Whoever may change roles, or the roles a user
```

Change `frontend/openapi.json`:

```diff
@@ -1476,6 +1476,37 @@
         "title": "Page[RoleOut]",
         "type": "object"
       },
+      "Page_SelectorOut_": {
+        "properties": {
+          "items": {
+            "items": {
+              "$ref": "#/components/schemas/SelectorOut"
+            },
+            "title": "Items",
+            "type": "array"
+          },
+          "limit": {
+            "title": "Limit",
+            "type": "integer"
+          },
+          "offset": {
+            "title": "Offset",
+            "type": "integer"
+          },
+          "total": {
+            "title": "Total",
+            "type": "integer"
+          }
+        },
+        "required": [
+          "items",
+          "total",
+          "limit",
+          "offset"
+        ],
+        "title": "Page[SelectorOut]",
+        "type": "object"
+      },
       "Page_SignInSource_": {
         "properties": {
           "items": {
@@ -1639,6 +1670,70 @@
         "title": "PasswordReset",
         "type": "object"
       },
+      "Preview": {
+        "properties": {
+          "expression": {
+            "maxLength": 4000,
+            "minLength": 1,
+            "title": "Expression",
+            "type": "string"
+          },
+          "format": {
+            "default": "",
+            "maxLength": 32,
+            "title": "Format",
+            "type": "string"
+          },
+          "paths": {
+            "default": [],
+            "items": {
+              "type": "string"
+            },
+            "maxItems": 100,
+            "title": "Paths",
+            "type": "array"
+          }
+        },
+        "required": [
+          "expression"
+        ],
+        "title": "Preview",
+        "type": "object"
+      },
+      "PreviewOut": {
+        "properties": {
+          "paths": {
+            "items": {
+              "$ref": "#/components/schemas/Previewed"
+            },
+            "title": "Paths",
+            "type": "array"
+          }
+        },
+        "required": [
+          "paths"
+        ],
+        "title": "PreviewOut",
+        "type": "object"
+      },
+      "Previewed": {
+        "properties": {
+          "matches": {
+            "title": "Matches",
+            "type": "boolean"
+          },
+          "path": {
+            "title": "Path",
+            "type": "string"
+          }
+        },
+        "required": [
+          "path",
+          "matches"
+        ],
+        "title": "Previewed",
+        "type": "object"
+      },
       "ProxyIn": {
         "properties": {
           "auto_block": {
@@ -2379,6 +2474,95 @@
         "title": "SchemaState",
         "type": "object"
       },
+      "SelectorContent": {
+        "properties": {
+          "description": {
+            "default": "",
+            "maxLength": 255,
+            "title": "Description",
+            "type": "string"
+          },
+          "expression": {
+            "maxLength": 4000,
+            "minLength": 1,
+            "title": "Expression",
+            "type": "string"
+          }
+        },
+        "required": [
+          "expression"
+        ],
+        "title": "SelectorContent",
+        "type": "object"
+      },
+      "SelectorCreate": {
+        "properties": {
+          "description": {
+            "default": "",
+            "maxLength": 255,
+            "title": "Description",
+            "type": "string"
+          },
+          "expression": {
+            "maxLength": 4000,
+            "minLength": 1,
+            "title": "Expression",
+            "type": "string"
+          },
+          "name": {
+            "pattern": "^[A-Za-z0-9_.-]{1,64}$",
+            "title": "Name",
+            "type": "string"
+          }
+        },
+        "required": [
+          "expression",
+          "name"
+        ],
+        "title": "SelectorCreate",
+        "type": "object"
+      },
+      "SelectorOut": {
+        "properties": {
+          "created_at": {
+            "format": "date-time",
+            "title": "Created At",
+            "type": "string"
+          },
+          "description": {
+            "title": "Description",
+            "type": "string"
+          },
+          "expression": {
+            "title": "Expression",
+            "type": "string"
+          },
+          "id": {
+            "format": "uuid",
+            "title": "Id",
+            "type": "string"
+          },
+          "name": {
+            "title": "Name",
+            "type": "string"
+          },
+          "updated_at": {
+            "format": "date-time",
+            "title": "Updated At",
+            "type": "string"
+          }
+        },
+        "required": [
+          "id",
+          "name",
+          "description",
+          "expression",
+          "created_at",
+          "updated_at"
+        ],
+        "title": "SelectorOut",
+        "type": "object"
+      },
       "SessionInfo": {
         "properties": {
           "authenticated": {
@@ -4760,6 +4944,270 @@
         ]
       }
     },
+    "/api/v1/content-selectors": {
+      "get": {
+        "operationId": "list_selectors_api_v1_content_selectors_get",
+        "parameters": [
+          {
+            "in": "query",
+            "name": "limit",
+            "required": false,
+            "schema": {
+              "default": 50,
+              "maximum": 200,
+              "minimum": 1,
+              "title": "Limit",
+              "type": "integer"
+            }
+          },
+          {
+            "in": "query",
+            "name": "offset",
+            "required": false,
+            "schema": {
+              "default": 0,
+              "minimum": 0,
+              "title": "Offset",
+              "type": "integer"
+            }
+          }
+        ],
+        "responses": {
+          "200": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/Page_SelectorOut_"
+                }
+              }
+            },
+            "description": "Successful Response"
+          },
+          "default": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/ErrorResponse"
+                }
+              }
+            },
+            "description": "Any error."
+          }
+        },
+        "summary": "List Selectors",
+        "tags": [
+          "content selectors"
+        ]
+      },
+      "post": {
+        "operationId": "create_selector_api_v1_content_selectors_post",
+        "requestBody": {
+          "content": {
+            "application/json": {
+              "schema": {
+                "$ref": "#/components/schemas/SelectorCreate"
+              }
+            }
+          },
+          "required": true
+        },
+        "responses": {
+          "201": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/SelectorOut"
+                }
+              }
+            },
+            "description": "Successful Response"
+          },
+          "default": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/ErrorResponse"
+                }
+              }
+            },
+            "description": "Any error."
+          }
+        },
+        "summary": "Create Selector",
+        "tags": [
+          "content selectors"
+        ]
+      }
+    },
+    "/api/v1/content-selectors/preview": {
+      "post": {
+        "description": "Which of these paths an expression matches, in a repository of this format. A path\nis taken as starting with `/`.",
+        "operationId": "preview_api_v1_content_selectors_preview_post",
+        "requestBody": {
+          "content": {
+            "application/json": {
+              "schema": {
+                "$ref": "#/components/schemas/Preview"
+              }
+            }
+          },
+          "required": true
+        },
+        "responses": {
+          "200": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/PreviewOut"
+                }
+              }
+            },
+            "description": "Successful Response"
+          },
+          "default": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/ErrorResponse"
+                }
+              }
+            },
+            "description": "Any error."
+          }
+        },
+        "summary": "Preview",
+        "tags": [
+          "content selectors"
+        ]
+      }
+    },
+    "/api/v1/content-selectors/{name}": {
+      "delete": {
+        "description": "Delete a selector no role names.",
+        "operationId": "delete_selector_api_v1_content_selectors__name__delete",
+        "parameters": [
+          {
+            "in": "path",
+            "name": "name",
+            "required": true,
+            "schema": {
+              "title": "Name",
+              "type": "string"
+            }
+          }
+        ],
+        "responses": {
+          "204": {
+            "description": "Successful Response"
+          },
+          "default": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/ErrorResponse"
+                }
+              }
+            },
+            "description": "Any error."
+          }
+        },
+        "summary": "Delete Selector",
+        "tags": [
+          "content selectors"
+        ]
+      },
+      "get": {
+        "operationId": "get_selector_api_v1_content_selectors__name__get",
+        "parameters": [
+          {
+            "in": "path",
+            "name": "name",
+            "required": true,
+            "schema": {
+              "title": "Name",
+              "type": "string"
+            }
+          }
+        ],
+        "responses": {
+          "200": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/SelectorOut"
+                }
+              }
+            },
+            "description": "Successful Response"
+          },
+          "default": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/ErrorResponse"
+                }
+              }
+            },
+            "description": "Any error."
+          }
+        },
+        "summary": "Get Selector",
+        "tags": [
+          "content selectors"
+        ]
+      },
+      "put": {
+        "description": "Change what a selector matches: at once, for every permission that names it.",
+        "operationId": "update_selector_api_v1_content_selectors__name__put",
+        "parameters": [
+          {
+            "in": "path",
+            "name": "name",
+            "required": true,
+            "schema": {
+              "title": "Name",
+              "type": "string"
+            }
+          }
+        ],
+        "requestBody": {
+          "content": {
+            "application/json": {
+              "schema": {
+                "$ref": "#/components/schemas/SelectorContent"
+              }
+            }
+          },
+          "required": true
+        },
+        "responses": {
+          "200": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/SelectorOut"
+                }
+              }
+            },
+            "description": "Successful Response"
+          },
+          "default": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/ErrorResponse"
+                }
+              }
+            },
+            "description": "Any error."
+          }
+        },
+        "summary": "Update Selector",
+        "tags": [
+          "content selectors"
+        ]
+      }
+    },
     "/api/v1/content/{repository}": {
       "get": {
         "operationId": "get_repository_api_v1_content__repository__get",
```

Change `frontend/src/lib/api/schema.d.ts`:

```diff
@@ -390,6 +390,70 @@ export interface paths {
         patch?: never;
         trace?: never;
     };
+    "/api/v1/content-selectors": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        /** List Selectors */
+        get: operations["list_selectors_api_v1_content_selectors_get"];
+        put?: never;
+        /** Create Selector */
+        post: operations["create_selector_api_v1_content_selectors_post"];
+        delete?: never;
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
+    "/api/v1/content-selectors/preview": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        get?: never;
+        put?: never;
+        /**
+         * Preview
+         * @description Which of these paths an expression matches, in a repository of this format. A path
+         *     is taken as starting with `/`.
+         */
+        post: operations["preview_api_v1_content_selectors_preview_post"];
+        delete?: never;
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
+    "/api/v1/content-selectors/{name}": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        /** Get Selector */
+        get: operations["get_selector_api_v1_content_selectors__name__get"];
+        /**
+         * Update Selector
+         * @description Change what a selector matches: at once, for every permission that names it.
+         */
+        put: operations["update_selector_api_v1_content_selectors__name__put"];
+        post?: never;
+        /**
+         * Delete Selector
+         * @description Delete a selector no role names.
+         */
+        delete: operations["delete_selector_api_v1_content_selectors__name__delete"];
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
     "/api/v1/content/{repository}": {
         parameters: {
             query?: never;
@@ -1734,6 +1798,17 @@ export interface components {
             /** Total */
             total: number;
         };
+        /** Page[SelectorOut] */
+        Page_SelectorOut_: {
+            /** Items */
+            items: components["schemas"]["SelectorOut"][];
+            /** Limit */
+            limit: number;
+            /** Offset */
+            offset: number;
+            /** Total */
+            total: number;
+        };
         /** Page[SignInSource] */
         Page_SignInSource_: {
             /** Items */
@@ -1795,6 +1870,33 @@ export interface components {
             /** Password */
             password: string;
         };
+        /** Preview */
+        Preview: {
+            /** Expression */
+            expression: string;
+            /**
+             * Format
+             * @default
+             */
+            format: string;
+            /**
+             * Paths
+             * @default []
+             */
+            paths: string[];
+        };
+        /** PreviewOut */
+        PreviewOut: {
+            /** Paths */
+            paths: components["schemas"]["Previewed"][];
+        };
+        /** Previewed */
+        Previewed: {
+            /** Matches */
+            matches: boolean;
+            /** Path */
+            path: string;
+        };
         /** ProxyIn */
         ProxyIn: {
             /**
@@ -2091,6 +2193,52 @@ export interface components {
             /** Revision */
             revision: string | null;
         };
+        /** SelectorContent */
+        SelectorContent: {
+            /**
+             * Description
+             * @default
+             */
+            description: string;
+            /** Expression */
+            expression: string;
+        };
+        /** SelectorCreate */
+        SelectorCreate: {
+            /**
+             * Description
+             * @default
+             */
+            description: string;
+            /** Expression */
+            expression: string;
+            /** Name */
+            name: string;
+        };
+        /** SelectorOut */
+        SelectorOut: {
+            /**
+             * Created At
+             * Format: date-time
+             */
+            created_at: string;
+            /** Description */
+            description: string;
+            /** Expression */
+            expression: string;
+            /**
+             * Id
+             * Format: uuid
+             */
+            id: string;
+            /** Name */
+            name: string;
+            /**
+             * Updated At
+             * Format: date-time
+             */
+            updated_at: string;
+        };
         /** SessionInfo */
         SessionInfo: {
             /** Authenticated */
@@ -3285,6 +3433,199 @@ export interface operations {
             };
         };
     };
+    list_selectors_api_v1_content_selectors_get: {
+        parameters: {
+            query?: {
+                limit?: number;
+                offset?: number;
+            };
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        requestBody?: never;
+        responses: {
+            /** @description Successful Response */
+            200: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["Page_SelectorOut_"];
+                };
+            };
+            /** @description Any error. */
+            default: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["ErrorResponse"];
+                };
+            };
+        };
+    };
+    create_selector_api_v1_content_selectors_post: {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        requestBody: {
+            content: {
+                "application/json": components["schemas"]["SelectorCreate"];
+            };
+        };
+        responses: {
+            /** @description Successful Response */
+            201: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["SelectorOut"];
+                };
+            };
+            /** @description Any error. */
+            default: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["ErrorResponse"];
+                };
+            };
+        };
+    };
+    preview_api_v1_content_selectors_preview_post: {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        requestBody: {
+            content: {
+                "application/json": components["schemas"]["Preview"];
+            };
+        };
+        responses: {
+            /** @description Successful Response */
+            200: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["PreviewOut"];
+                };
+            };
+            /** @description Any error. */
+            default: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["ErrorResponse"];
+                };
+            };
+        };
+    };
+    get_selector_api_v1_content_selectors__name__get: {
+        parameters: {
+            query?: never;
+            header?: never;
+            path: {
+                name: string;
+            };
+            cookie?: never;
+        };
+        requestBody?: never;
+        responses: {
+            /** @description Successful Response */
+            200: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["SelectorOut"];
+                };
+            };
+            /** @description Any error. */
+            default: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["ErrorResponse"];
+                };
+            };
+        };
+    };
+    update_selector_api_v1_content_selectors__name__put: {
+        parameters: {
+            query?: never;
+            header?: never;
+            path: {
+                name: string;
+            };
+            cookie?: never;
+        };
+        requestBody: {
+            content: {
+                "application/json": components["schemas"]["SelectorContent"];
+            };
+        };
+        responses: {
+            /** @description Successful Response */
+            200: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["SelectorOut"];
+                };
+            };
+            /** @description Any error. */
+            default: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["ErrorResponse"];
+                };
+            };
+        };
+    };
+    delete_selector_api_v1_content_selectors__name__delete: {
+        parameters: {
+            query?: never;
+            header?: never;
+            path: {
+                name: string;
+            };
+            cookie?: never;
+        };
+        requestBody?: never;
+        responses: {
+            /** @description Successful Response */
+            204: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content?: never;
+            };
+            /** @description Any error. */
+            default: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["ErrorResponse"];
+                };
+            };
+        };
+    };
     get_repository_api_v1_content__repository__get: {
         parameters: {
             query?: never;
```

Then (in `backend/`): `MEGOOARTI_UPDATE_OPENAPI=1 uv run pytest -q tests/test_openapi_snapshot.py`, which writes `frontend/openapi.json`; and (in `frontend/`) `pnpm gen:api`, which writes `src/lib/api/schema.d.ts`, both as above.

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest -q tests/security/test_content_selectors_api.py tests/security/test_roles_api.py tests/security/test_roles.py tests/test_migrations.py tests/test_db_script.py tests/test_route_guards.py tests/test_openapi_snapshot.py tests/test_documents.py`
Expected: 210 passed.

- [ ] **Step 5: Commit**

```bash
git add backend docs frontend/openapi.json frontend/src/lib/api/schema.d.ts
git commit -m "feat(security): content selectors kept, previewed against paths and recorded; a role names only selectors there are, and one it names is kept"
```

---

### Task 3: `may`

**Files:**
- Create: `backend/src/megooarti/security/access.py`
- Modify: `backend/src/megooarti/security/selectors.py` (`held`), `backend/src/megooarti/security/authentication.py` (a principal's `selectors`; a selector permission's scopes; `refuse_pending_password_change` made public)
- Test: `backend/tests/security/test_access.py`

**Interfaces:**
- Consumes: Task 1's `parse`, `Expression`, `Reach`, `SelectorError`; Task 2's `ContentSelector`; `Principal`, `build_principal`, `unauthorized`, `Scheme`.
- Produces:
  - `selectors.held(db, patterns) -> dict[str, str]`; `Principal.selectors: dict[str, str]`.
  - `access.reach(principal, repository, action) -> Reached`. A `Reached` has `.whole`, `.anything`, `.allows(path)`, `.folder(folder)` and `.narrowing(path_column) -> (condition | None, exact)`.
  - `access.may(principal, repository, path, action)` and `may_somewhere(principal, repository, action)`.
  - `access.require(principal, repository, path, action, *, scheme="Basic")`, `require_somewhere(...)`, and `slashed(path)`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/security/test_access.py`:

```python
"""`may` (spec 10, E6): a repository permission reaches every path; a selector permission,
the paths its selector matches; a token's scopes and the public's patterns as for any
permission. Tested against a table of permissions, selectors, paths and actions."""

import pytest
from sqlalchemy import literal

from megooarti.errors import ApiError
from megooarti.repositories.models import Repository
from megooarti.security import access, roles, selectors
from megooarti.security.authentication import Principal, build_principal
from megooarti.security.models import ContentSelector, User

RELEASES = Repository(name="releases", format="maven", type="hosted", config={})
SNAPSHOTS = Repository(name="snapshots", format="maven", type="hosted", config={})
NPM = Repository(name="npm-hosted", format="npm", type="hosted", config={})
SELECTORS = {
    "acme": 'path =^ "/com/acme/"',
    "jars": 'path =~ ".*\\\\.jar"',
    "npm-only": 'format == "npm"',
    "broken": "path ==",
}
ACME_JAR = "/com/acme/app/1.0/app-1.0.jar"
ACME_POM = "com/acme/app/1.0/app-1.0.pom"  # as content paths are kept, without the slash
OTHER_JAR = "/org/other/1.0/other-1.0.jar"


def caller(
    *patterns: str,
    scopes: list[str] | None = None,
    public: tuple[str, ...] = (),
    method: str = "session",
) -> Principal:
    return Principal(
        User(username="kim", display_name="Kim", status="active"),
        method,
        frozenset(patterns),
        None if scopes is None else frozenset(scopes),
        public=frozenset(public),
        selectors=SELECTORS,
    )


@pytest.mark.parametrize(
    ("patterns", "repository", "path", "action", "allowed"),
    [
        # A repository permission: every path.
        (["repository:maven:releases:read"], RELEASES, OTHER_JAR, "read", True),
        (["repository:maven:releases:read"], SNAPSHOTS, OTHER_JAR, "read", False),
        (["repository:maven:releases:read"], RELEASES, OTHER_JAR, "add", False),
        # A selector permission: the paths its selector matches, and their neighbours not.
        (["selector:acme:maven:releases:read"], RELEASES, ACME_JAR, "read", True),
        (["selector:acme:maven:releases:read"], RELEASES, ACME_POM, "read", True),
        (["selector:acme:maven:releases:read"], RELEASES, OTHER_JAR, "read", False),
        (["selector:acme:maven:releases:read"], RELEASES, ACME_JAR, "delete", False),
        (["selector:acme:maven:releases:read"], SNAPSHOTS, ACME_JAR, "read", False),
        (["selector:acme:maven:*:read"], SNAPSHOTS, ACME_JAR, "read", True),
        (["selector:acme:*:*:*"], NPM, "/com/acme/x.tgz", "delete", True),
        (["selector:acme"], RELEASES, ACME_JAR, "edit", True),
        (["selector:jars:maven:*:read"], RELEASES, OTHER_JAR, "read", True),
        (["selector:jars:maven:*:read"], RELEASES, ACME_POM, "read", False),
        # Every selector, each by what it matches.
        (["selector:*:maven:releases:read"], RELEASES, ACME_POM, "read", True),
        (["selector:*:maven:releases:read"], RELEASES, "/org/other/x.pom", "read", False),
        # One whose format is another reaches nothing; one that no longer parses, nothing.
        (["selector:npm-only:*:*:read"], RELEASES, ACME_JAR, "read", False),
        (["selector:npm-only:*:*:read"], NPM, "/anything", "read", True),
        (["selector:broken:*:*:read"], RELEASES, ACME_JAR, "read", False),
        # A selector permission naming a selector there is none of.
        (["selector:gone:*:*:read"], RELEASES, ACME_JAR, "read", False),
        (["*"], RELEASES, OTHER_JAR, "delete", True),
        ([], RELEASES, ACME_JAR, "read", False),
    ],
)
def test_may_decides_by_repository_and_selector_permissions(
    patterns, repository, path, action, allowed
):
    assert access.may(caller(*patterns), repository, path, action) is allowed


def test_a_tokens_scopes_narrow_a_selector_permission_as_its_repository_permission():
    reader = caller("selector:acme:maven:*:*", scopes=["repository:*:*:read"])
    selector_scoped = caller("selector:acme:maven:*:*", scopes=["selector:acme:*:*:read"])

    assert access.may(reader, RELEASES, ACME_JAR, "read")
    assert not access.may(reader, RELEASES, ACME_JAR, "add")
    assert access.may(selector_scoped, RELEASES, ACME_JAR, "read")
    assert not access.may(selector_scoped, RELEASES, ACME_JAR, "delete")


def test_the_publics_selector_permissions_are_everyones():
    public = ("selector:acme:maven:releases:read",)
    anonymous = caller(*public, public=public, method="anonymous")
    signed_in = caller(public=public)

    assert access.may(anonymous, RELEASES, ACME_JAR, "read")
    assert access.may(signed_in, RELEASES, ACME_JAR, "read")
    assert not access.may(anonymous, RELEASES, OTHER_JAR, "read")


def test_what_of_a_repository_is_reached_says_what_is_listed():
    acme = access.reach(caller("selector:acme:maven:releases:browse"), RELEASES, "browse")
    whole = access.reach(caller("repository:maven:releases:browse"), RELEASES, "browse")
    elsewhere = access.reach(caller("selector:npm-only:*:*:browse"), RELEASES, "browse")

    assert (acme.anything, whole.anything, elsewhere.anything) == (True, True, False)
    assert acme.folder("com") and acme.folder("/com/acme/app")
    assert not acme.folder("org")
    assert whole.folder("org")
    assert whole.narrowing(None) == (None, True)
    jars = access.reach(caller("selector:jars:maven:releases:browse"), RELEASES, "browse")
    assert acme.narrowing(literal("/x"))[1] is True  # a prefix a database can be asked
    assert jars.narrowing(literal("/x"))[1] is False  # a pattern it cannot
    assert access.may_somewhere(caller("selector:acme:maven:releases:browse"), RELEASES, "browse")
    assert not access.may_somewhere(caller("selector:acme:maven:releases:browse"), NPM, "browse")


def test_require_answers_as_authorize_does():
    with pytest.raises(ApiError) as nobody:
        access.require(None, RELEASES, ACME_JAR, "read")
    with pytest.raises(ApiError) as anonymous:
        access.require(caller(method="anonymous"), RELEASES, ACME_JAR, "read")
    with pytest.raises(ApiError) as refused:
        access.require(caller("selector:acme:maven:*:read"), RELEASES, OTHER_JAR, "read")
    with pytest.raises(ApiError) as nowhere:
        access.require_somewhere(caller("selector:acme:maven:*:read"), NPM, "read")

    assert (nobody.value.status_code, anonymous.value.status_code) == (401, 401)
    assert (refused.value.status_code, nowhere.value.status_code) == (403, 403)
    assert access.require(caller("selector:acme:maven:*:read"), RELEASES, ACME_JAR, "read")


async def test_a_principal_holds_the_selectors_its_permissions_name_and_no_others(db, make_user):
    db.add_all(
        [
            ContentSelector(name="acme", expression='path =^ "/com/acme/"'),
            ContentSelector(name="other", expression='path =^ "/org/"'),
        ]
    )
    await roles.create_role(db, "acme-readers", "", ["selector:acme:maven:*:read"], [])
    await roles.create_role(db, "plain", "", ["repository:maven:*:read"], [])
    await db.commit()
    acme = await make_user("ada", roles=["acme-readers"])
    plain = await make_user("pat", roles=["plain"])

    held = await build_principal(db, acme, "session")
    none = await build_principal(db, plain, "session")

    assert held.selectors == {"acme": 'path =^ "/com/acme/"'}
    assert none.selectors == {}
    assert await selectors.held(db, ["selector:*:maven:*:read"]) == {
        "acme": 'path =^ "/com/acme/"',
        "other": 'path =^ "/org/"',
    }
    assert await selectors.held(db, ["*", "repository:*:*:read"]) == {}
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `backend/`): `uv run pytest -q tests/security/test_access.py`
Expected: The tests do not load: `ImportError: cannot import name 'access' from 'megooarti.security'`.

- [ ] **Step 3: Write the code**

Change `backend/src/megooarti/security/selectors.py`:

```diff
@@ -17,9 +17,13 @@ listing only what may match before each is checked.
 import enum
 import functools
 import re
+from collections.abc import Iterable
 from dataclasses import dataclass
 
-from sqlalchemy import ColumnElement, and_, false, not_, or_, true
+from sqlalchemy import ColumnElement, and_, false, not_, or_, select, true
+from sqlalchemy.ext.asyncio import AsyncSession
+
+from megooarti.security.models import ContentSelector
 
 MAX_LENGTH = 4000
 MAX_PATTERN = 1000
@@ -300,3 +304,23 @@ def parse(text: str) -> Expression:
         raise SelectorError(f"Unexpected {rest.text!r}", rest.at)
     return found
 
+
+async def held(db: AsyncSession, patterns: Iterable[str]) -> dict[str, str]:
+    """The selectors these patterns can name, each by its name with its expression: none
+    for whoever holds no selector permission, which is most callers, at no cost."""
+    named: set[str] = set()
+    every = False
+    for pattern in patterns:
+        parts = pattern.split(":")
+        if parts[0] not in ("selector", "*") or len(parts) == 1:
+            continue  # not a selector's, or `*`, which reaches every repository whole
+        if parts[1] == "*":
+            every = True
+        else:
+            named.add(parts[1])
+    if not every and not named:
+        return {}
+    query = select(ContentSelector.name, ContentSelector.expression)
+    if not every:
+        query = query.where(ContentSelector.name.in_(named))
+    return dict((await db.execute(query)).all())
```

Change `backend/src/megooarti/security/authentication.py`:

```diff
@@ -5,7 +5,7 @@ import base64
 import secrets
 import uuid
 from collections.abc import Awaitable, Callable
-from dataclasses import dataclass, replace
+from dataclasses import dataclass, field, replace
 from typing import Literal
 from urllib.parse import urlsplit
 
@@ -20,6 +20,7 @@ from megooarti.security import (
     header,
     oauth,
     registry_tokens,
+    selectors,
     sessions,
     sources,
     throttle,
@@ -63,6 +64,9 @@ class Principal:
     token_id: uuid.UUID | None = None
     # The OAuth approval the caller's access token stands for, if it held one (MCP 7).
     grant_id: uuid.UUID | None = None
+    # The content selectors its patterns (and the public's) can name, each by its name
+    # with its expression (spec 10): none for whoever holds no selector permission.
+    selectors: dict[str, str] = field(default_factory=dict)
 
     @property
     def is_anonymous(self) -> bool:
@@ -77,13 +81,28 @@ class Principal:
     def allows(self, permission: str) -> bool:
         if not is_valid_permission(permission):
             return False  # fail closed on anything that could shift segments
-        if permission.startswith("repository:") and any_grants(self.public, permission):
+        content = permission.startswith(("repository:", "selector:"))
+        if content and any_grants(self.public, permission):
             return True  # public content is public to everyone, whatever a token's scopes
         if self.is_anonymous:
             return False  # whatever roles anonymous holds, nobody administers anonymously
         if not any_grants(self.patterns, permission):
             return False
-        return self.scopes is None or any_grants(self.scopes, permission)
+        return (
+            self.scopes is None
+            or any_grants(self.scopes, permission)
+            or any_grants(self.scopes, _scoped_as(permission))
+        )
+
+
+def _scoped_as(permission: str) -> str:
+    """What else a token's scopes may grant for a permission. A selector permission is
+    scoped as the repository permission it narrows, too: a token that may only read reads
+    through a selector (`selector:s:maven:releases:read` as `repository:maven:releases:read`)."""
+    parts = permission.split(":")
+    if parts[0] == "selector" and len(parts) == 5:
+        return ":".join(["repository", *parts[2:]])
+    return permission
 
 
 def unauthorized(
@@ -119,14 +138,16 @@ async def build_principal(
     anonymous = await _anonymous_access(db)
     public = frozenset() if anonymous is None else anonymous[1]
     scopes = None if token is None or token.scopes is None else frozenset(token.scopes)
+    patterns = await users.signed_in_patterns(db, user)
     return Principal(
         user,
         method,
-        await users.signed_in_patterns(db, user),
+        patterns,
         scopes,
         session,
         public,
         None if token is None else token.id,
+        selectors=await selectors.held(db, patterns | public),
     )
 
 
@@ -324,7 +345,13 @@ async def _from_registry_token(db: AsyncSession, request: Request, value: str) -
         if anonymous is None:
             raise refused
         user, patterns = anonymous
-        return Principal(user, "anonymous", patterns, public=patterns)
+        return Principal(
+            user,
+            "anonymous",
+            patterns,
+            public=patterns,
+            selectors=await selectors.held(db, patterns),
+        )
     user = await users.get_user(db, claims.user_id)
     if user is None or not await users.can_act(db, user) or claims.method == "anonymous":
         raise refused
@@ -434,7 +461,13 @@ async def resolve_principal(
     anonymous = await _anonymous_access(db)
     if anonymous is not None:
         user, patterns = anonymous
-        return Principal(user, "anonymous", patterns, public=patterns)
+        return Principal(
+            user,
+            "anonymous",
+            patterns,
+            public=patterns,
+            selectors=await selectors.held(db, patterns),
+        )
     return None
 
 
@@ -650,7 +683,7 @@ AUTHENTICATION_DEPENDENCIES = frozenset(
 )
 
 
-def _refuse_pending_password_change(principal: Principal) -> None:
+def refuse_pending_password_change(principal: Principal) -> None:
     if principal.is_interactive and principal.user.must_change_password:
         raise ApiError(
             403, "password_change_required", "Change your password before doing anything else."
@@ -663,7 +696,7 @@ def authorize(
     """The one place that decides whether a caller may do something."""
     if principal is None:
         raise unauthorized(scheme=scheme)
-    _refuse_pending_password_change(principal)
+    refuse_pending_password_change(principal)
     if not principal.allows(permission):
         if principal.is_anonymous:
             raise unauthorized(scheme=scheme)
@@ -692,7 +725,7 @@ async def require_caller(
     """
     if principal is None:
         raise unauthorized()
-    _refuse_pending_password_change(principal)
+    refuse_pending_password_change(principal)
     return principal
 
 
@@ -713,7 +746,7 @@ def require_interactive(
                 "Sign in with your password to do this; an API token is not enough.",
             )
         if not allow_pending_password_change:
-            _refuse_pending_password_change(principal)
+            refuse_pending_password_change(principal)
         return principal
 
     return dependency
```

Create `backend/src/megooarti/security/access.py`:

```python
"""Who may do what to a repository's content (spec 10, E6): the one place that decides.

A caller reaches a repository's content for an action by a repository permission
(`repository:<format>:<repository>:<action>`), which is every path of it; or by
selector permissions (`selector:<selector>:<format>:<repository>:<action>`), each the
paths its selector's expression matches. `may` asks for one path; `reach` says it all,
for listing what a caller may see: whether the whole, which paths, which folders, and
what a database can be asked to leave out first.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import ColumnElement, or_

from megooarti.errors import ApiError
from megooarti.repositories.models import Repository
from megooarti.security.authentication import (
    Principal,
    Scheme,
    refuse_pending_password_change,
    unauthorized,
)
from megooarti.security.selectors import Expression, Reach, SelectorError, parse


def slashed(path: str) -> str:
    """A path as an expression sees it: from `/`."""
    return path if path.startswith("/") else f"/{path}"


@dataclass(frozen=True)
class Reached:
    """What of one repository a caller reaches for one action."""

    format: str
    whole: bool  # by a repository permission: every path
    expressions: Sequence[Expression]  # else, the paths any of these match

    @property
    def anything(self) -> bool:
        """Whether the caller reaches any of it: what a repository is listed by."""
        return self.whole or any(
            expression.under(self.format, "/") is not Reach.NONE for expression in self.expressions
        )

    def allows(self, path: str) -> bool:
        path = slashed(path)
        return self.whole or any(e.matches(self.format, path) for e in self.expressions)

    def folder(self, folder: str) -> bool:
        """Whether a folder may hold anything reached: what a folder is listed by."""
        if self.whole:
            return True
        folder = slashed(folder.rstrip("/") + "/")
        return any(e.under(self.format, folder) is not Reach.NONE for e in self.expressions)

    def narrowing(self, path: ColumnElement[str]) -> tuple[ColumnElement[bool] | None, bool]:
        """A condition on a path (from `/`) every reached path meets, None for the whole;
        and whether it is exact. What an inexact one keeps is still to be checked by
        `allows`: a pattern's matches cannot be asked of a database."""
        if self.whole:
            return None, True
        said = [e.narrowing(self.format, path) for e in self.expressions]
        return or_(*(condition for condition, _ in said)), all(exact for _, exact in said)


def reach(principal: Principal | None, repository: Repository, action: str) -> Reached:
    """What of a repository a caller reaches for an action."""
    if principal is None:
        return Reached(repository.format, False, ())
    named = f"{repository.format}:{repository.name}:{action}"
    if principal.allows(f"repository:{named}"):
        return Reached(repository.format, True, ())
    found = []
    for selector, text in sorted(principal.selectors.items()):
        if not principal.allows(f"selector:{selector}:{named}"):
            continue
        try:
            found.append(parse(text))
        except SelectorError:
            continue  # kept before it was checked as it is now: it reaches nothing
    return Reached(repository.format, False, tuple(found))


def may(principal: Principal | None, repository: Repository, path: str, action: str) -> bool:
    """Whether a caller may do this to what is at this path of a repository (E6)."""
    return reach(principal, repository, action).allows(path)


def may_somewhere(principal: Principal | None, repository: Repository, action: str) -> bool:
    """Whether a caller may do this to some of a repository: it is listed to them so."""
    return reach(principal, repository, action).anything


def _refuse(principal: Principal | None, scheme: Scheme) -> None:
    if principal is None or principal.is_anonymous:
        raise unauthorized(scheme=scheme)
    raise ApiError(403, "forbidden", "You do not have permission to do this.")


def require(
    principal: Principal | None,
    repository: Repository,
    path: str,
    action: str,
    *,
    scheme: Scheme = "Basic",
) -> Principal:
    """The caller, if they may do this at this path; else 401 (nobody, or anonymous) or
    403, as `authorize` answers."""
    if principal is not None:
        refuse_pending_password_change(principal)
    if not may(principal, repository, path, action):
        _refuse(principal, scheme)
    assert principal is not None
    return principal


def require_somewhere(
    principal: Principal | None, repository: Repository, action: str, *, scheme: Scheme = "Basic"
) -> Principal:
    """The caller, if they may do this to some of the repository; else 401 or 403. For a
    request whose paths are known only as it is served: each is checked then too."""
    if principal is not None:
        refuse_pending_password_change(principal)
    if not may_somewhere(principal, repository, action):
        _refuse(principal, scheme)
    assert principal is not None
    return principal
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest -q tests/security tests/mcp`
Expected: 671 passed.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat(security): may: a repository permission reaches every path, a selector permission the paths its selector matches; a principal carries the selectors it can name"
```

---

### Task 4: Reading, writing and deleting by `may`

**Files:**
- Modify:
  - `backend/src/megooarti/repositories/content.py` (each path stored, maintained or deleted, and a version's attributes, by `may`; an upload by `require_somewhere`; `permission` removed).
  - `backend/src/megooarti/repositories/routes.py`, `backend/src/megooarti/repositories/npm/format.py`, `backend/src/megooarti/repositories/docker/routes.py`.
- Test: `backend/tests/repositories/test_selector_content.py`, `backend/tests/repositories/docker/test_selectors.py`; modify `backend/tests/repositories/test_content_components.py` and `backend/tests/repositories/test_search_text.py` (`annotate` names its file)

**Interfaces:**
- Consumes: Task 3's `access.require`, `require_somewhere`, `reach`; Task 2's `ContentSelector`.
- Produces: `RepositoryContext.annotate(namespace, name, version, attributes, *, path)`. `RepositoryContext.permission` is gone.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/repositories/test_selector_content.py`:

```python
"""Content by selector permissions (spec 10): the content route reads, writes and deletes
the paths a selector allows and refuses their neighbours, through a group as directly;
and a component's attributes are changed only where its file may be."""

from dataclasses import replace

import pytest

from megooarti.errors import ApiError
from megooarti.repositories import service
from megooarti.security import roles
from megooarti.security.models import ContentSelector
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.conftest import someone
from tests.repositories.test_content_components import Packaged, store

FILES = "/repository/files"


@pytest.fixture
async def kim(db, files, make_user) -> dict[str, str]:
    """Someone who may read, add and delete under /allowed/ in `files` and its group, and
    nothing else; with a file there, and one beside it, put by an administrator."""
    db.add(ContentSelector(name="allowed", expression='path =^ "/allowed/"'))
    await service.create_repository(
        db,
        name="files-group",
        format="raw",
        type="group",
        online=True,
        blob_store=None,
        group={"members": ["files"]},
    )
    await roles.create_role(
        db,
        "allowed-files",
        "",
        ["selector:allowed:raw:files:*", "selector:allowed:raw:files-group:read"],
        [],
    )
    await db.commit()
    root = basic("root", PASSWORD)
    await make_user("root", roles=["admin"])
    await make_user("kim", roles=["allowed-files"])
    return basic("kim", PASSWORD), root


async def test_a_selector_reads_the_paths_it_matches_and_not_their_neighbours(client, kim):
    kim, root = kim
    await client.put(f"{FILES}/allowed/a.txt", content=b"a", headers=root)
    await client.put(f"{FILES}/denied/b.txt", content=b"b", headers=root)

    allowed = await client.get(f"{FILES}/allowed/a.txt", headers=kim)
    denied = await client.get(f"{FILES}/denied/b.txt", headers=kim)
    nobody = await client.get(f"{FILES}/allowed/a.txt")

    assert (allowed.status_code, allowed.content) == (200, b"a")
    assert (denied.status_code, error_code(denied)) == (403, "forbidden")
    assert nobody.status_code == 401


async def test_a_selector_writes_and_deletes_the_paths_it_matches_only(client, kim):
    kim, root = kim
    await client.put(f"{FILES}/denied/b.txt", content=b"b", headers=root)

    added = await client.put(f"{FILES}/allowed/new.txt", content=b"new", headers=kim)
    refused = await client.put(f"{FILES}/denied/new.txt", content=b"new", headers=kim)
    deleted = await client.delete(f"{FILES}/allowed/new.txt", headers=kim)
    kept = await client.delete(f"{FILES}/denied/b.txt", headers=kim)

    assert added.status_code == 201
    assert (refused.status_code, error_code(refused)) == (403, "forbidden")
    assert deleted.status_code == 204
    assert (kept.status_code, error_code(kept)) == (403, "forbidden")
    assert (await client.get(f"{FILES}/denied/b.txt", headers=root)).content == b"b"


async def test_through_a_group_a_selector_reads_the_paths_it_matches_only(client, kim):
    kim, root = kim
    await client.put(f"{FILES}/allowed/a.txt", content=b"a", headers=root)
    await client.put(f"{FILES}/denied/b.txt", content=b"b", headers=root)

    allowed = await client.get("/repository/files-group/allowed/a.txt", headers=kim)
    denied = await client.get("/repository/files-group/denied/b.txt", headers=kim)

    assert (allowed.status_code, allowed.content) == (200, b"a")
    assert denied.status_code == 403


async def test_a_components_attributes_change_where_its_file_may_be_edited(db, files, context_for):
    owner = await context_for(files, someone("*"))
    owner.format = Packaged()
    await store(owner, "acme/app/1.0/app.tgz", component_attributes={"n": 1})
    await store(owner, "other/tool/1.0/tool.tgz", component_attributes={"n": 1})
    acme = someone("selector:acme:raw:files:edit")
    editor = replace(acme, selectors={"acme": 'path =^ "/acme/"'})
    context = await context_for(files, editor)

    changed = await context.annotate("acme", "app", "1.0", {"n": 2}, path="acme/app/1.0/app.tgz")
    with pytest.raises(ApiError) as refused:
        await context.annotate("other", "tool", "1.0", {"n": 2}, path="other/tool/1.0/tool.tgz")

    assert changed is True
    assert refused.value.status_code == 403


async def test_a_path_written_another_way_is_not_served_past_a_selector(client, db, kim, make_user):
    _, root = kim
    db.add(ContentSelector(name="open", expression='not path =^ "/secret/"'))
    await roles.create_role(db, "open-files", "", ["selector:open:raw:files:read"], [])
    await db.commit()
    await make_user("nia", roles=["open-files"])
    nia = basic("nia", PASSWORD)
    await client.put(f"{FILES}/secret/x.txt", content=b"secret", headers=root)

    straight = await client.get(f"{FILES}/secret/x.txt", headers=nia)
    dotted = await client.get(f"{FILES}/%2E/secret/x.txt", headers=nia)
    doubled = await client.get(f"{FILES}/%2Fsecret/x.txt", headers=nia)

    assert straight.status_code == 403
    for other in (dotted, doubled):
        assert other.status_code != 200, other.text
        assert other.content != b"secret"


async def test_a_selector_changed_reaches_what_it_says_at_once(client, kim, make_user):
    kim, root = kim
    await client.put(f"{FILES}/allowed/a.txt", content=b"a", headers=root)
    before = await client.get(f"{FILES}/allowed/a.txt", headers=kim)

    changed = await client.put(
        "/api/v1/content-selectors/allowed",
        json={"description": "", "expression": 'path =^ "/elsewhere/"'},
        headers=root,
    )
    after = await client.get(f"{FILES}/allowed/a.txt", headers=kim)

    assert (before.status_code, changed.status_code, after.status_code) == (200, 200, 403)
```

Create `backend/tests/repositories/docker/test_selectors.py`:

```python
"""Images by selector permissions (spec 10): a pull is checked at the path of the
registry's request, and the catalog lists the images a selector reaches."""

from megooarti.security import roles
from megooarti.security.models import ContentSelector
from tests.accounts import PASSWORD, basic
from tests.repositories.docker.conftest import error_code, push_image


async def test_a_selector_pulls_the_images_it_matches_and_lists_only_them(
    client, images, root, make_user, db
):
    await push_image(client, root, "team/app", "1.0", "ours")
    await push_image(client, root, "secret/tool", "1.0", "theirs")
    db.add(ContentSelector(name="team", expression='path =^ "/team/"'))
    await roles.create_role(db, "team-pullers", "", ["selector:team:docker:images:read"], [])
    await db.commit()
    await make_user("puller", roles=["team-pullers"])
    puller = basic("puller", PASSWORD)

    allowed = await client.get("/v2/images/team/app/manifests/1.0", headers=puller)
    denied = await client.get("/v2/images/secret/tool/manifests/1.0", headers=puller)
    catalog = await client.get("/v2/_catalog", headers=puller)

    assert allowed.status_code == 200
    assert (denied.status_code, error_code(denied)) == (403, "DENIED")
    assert catalog.json() == {"repositories": ["images/team/app"]}
```

Change `backend/tests/repositories/test_content_components.py`:

```diff
@@ -116,11 +116,14 @@ async def test_components_lists_a_packages_versions_with_their_attributes(contex
     assert await context.components("acme", "nothing") == []
 
 
+APP = "acme/app/1.0/app.tgz"
+
+
 async def test_annotate_changes_a_components_attributes(context, db):
-    await store(context, "acme/app/1.0/app.tgz", component_attributes={"n": 1})
+    await store(context, APP, component_attributes={"n": 1})
 
-    changed = await context.annotate("acme", "app", "1.0", {"n": 1, "deprecated": "old"})
-    missing = await context.annotate("acme", "app", "9.9", {"n": 9})
+    changed = await context.annotate("acme", "app", "1.0", {"n": 1, "deprecated": "old"}, path=APP)
+    missing = await context.annotate("acme", "app", "9.9", {"n": 9}, path=APP)
 
     assert (changed, missing) == (True, False)
     assert (await context.components("acme", "app"))[0].attributes == {"n": 1, "deprecated": "old"}
@@ -135,8 +138,8 @@ async def test_annotate_needs_edit_and_a_repository_that_takes_changes(db, files
         db, files, online=True, hosted={"deployment_policy": "read_only"}, format_config={}
     )
 
-    forbidden = await error_of(adder.annotate("acme", "app", "1.0", {"n": 2}))
-    read_only = await error_of(writer.annotate("acme", "app", "1.0", {"n": 2}))
+    forbidden = await error_of(adder.annotate("acme", "app", "1.0", {"n": 2}, path=APP))
+    read_only = await error_of(writer.annotate("acme", "app", "1.0", {"n": 2}, path=APP))
 
     assert (forbidden.status_code, forbidden.code) == (403, "forbidden")
     assert (read_only.status_code, read_only.code) == (403, "repository_read_only")
```

Change `backend/tests/repositories/test_search_text.py`:

```diff
@@ -97,6 +97,9 @@ async def test_what_a_component_is_found_by_has_a_limit(client, root, db):
     assert len(text) == 4000 and text.startswith("tool 1.0.0 tool word word")
 
 
+TARBALL = "tool/-/tool-1.0.0.tgz"
+
+
 async def test_changing_what_is_said_about_a_component_changes_what_it_is_found_by(
     client, root, db, context_for
 ):
@@ -104,7 +107,9 @@ async def test_changing_what_is_said_about_a_component_changes_what_it_is_found_
     await publish(client, root, "tool", "1.0.0", description="first words")
     context = await context_for(repository, someone("repository:npm:npm"))
 
-    await context.annotate("", "tool", "1.0.0", {"npm": {"description": "Deprecated: use saw"}})
+    await context.annotate(
+        "", "tool", "1.0.0", {"npm": {"description": "Deprecated: use saw"}}, path=TARBALL
+    )
     await db.commit()
 
     assert await texts(db, None) == ["tool 1.0.0 tool deprecated: use saw"]
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `backend/`): `uv run pytest -q tests/repositories/test_selector_content.py tests/repositories/docker/test_selectors.py tests/repositories/test_content_components.py tests/repositories/test_search_text.py`
Expected: 9 failed, 23 passed: `annotate` takes no `path` yet, and what a selector allows is refused (`403`). `test_a_path_written_another_way_is_not_served_past_a_selector` passes already: it guards the change, and must still pass after it.

- [ ] **Step 3: Write the code**

Change `backend/src/megooarti/repositories/content.py`:

```diff
@@ -26,8 +26,8 @@ from megooarti.repositories import serving
 from megooarti.repositories.formats import ComponentKey, Format, get_format
 from megooarti.repositories.models import Asset, AssetReference, Component, Repository
 from megooarti.repositories.paths import normalise_path
-from megooarti.security import client_login
-from megooarti.security.authentication import Principal, authorize, unauthorized
+from megooarti.security import access, client_login
+from megooarti.security.authentication import Principal, unauthorized
 from megooarti.storage import blobs
 from megooarti.storage.backends import BlobBackend, StagedBlob
 from megooarti.storage.blob_stores import backend_for
@@ -196,9 +196,6 @@ class RepositoryContext:
         # Every staged blob recorded for this request, in case the request is rolled back.
         self.recorded: list[StagedBlob] = []
 
-    def permission(self, action: str) -> str:
-        return f"repository:{self.repository.format}:{self.repository.name}:{action}"
-
     def http(self) -> Any:
         """The application's outbound HTTP client, for fetching from a remote."""
         if self.outbound is None:
@@ -720,24 +717,25 @@ class RepositoryContext:
                 409, "redeploy_disabled", "This repository does not allow a path to be replaced."
             )
 
-    def _check_may_store(self, existing: Asset | None) -> None:
+    def _check_may_store(self, path: str, existing: Asset | None) -> None:
         action = "add" if existing is None else "edit"
-        authorize(self.principal, self.permission(action), scheme="Basic")
+        access.require(self.principal, self.repository, path, action)
         self._check_policy(replacing=existing is not None)
 
     def require_write(self) -> None:
         """Refuse a caller who may not change this repository's content at all.
 
         For an upload a format accepts without storing it as sent: it needs `add` or
-        `edit`, and the repository must not be read-only.
+        `edit` somewhere in the repository (each path it stores is checked as it is), and
+        the repository must not be read-only.
         """
         if self.repository.type != "hosted":
             # A programming error, like caching into a repository that is not a proxy.
             raise RuntimeError("only a hosted repository takes uploads")
         try:
-            authorize(self.principal, self.permission("add"), scheme="Basic")
+            access.require_somewhere(self.principal, self.repository, "add")
         except ApiError:
-            authorize(self.principal, self.permission("edit"), scheme="Basic")
+            access.require_somewhere(self.principal, self.repository, "edit")
         self._check_policy(replacing=False)
 
     async def _new_revision(self) -> None:
@@ -811,7 +809,7 @@ class RepositoryContext:
         path may have been written while the body arrived.
         """
         path = normalise_path(path)
-        self._check_may_store(await self.get(path))
+        self._check_may_store(path, await self.get(path))
         await self.db.commit()  # give the connection back while the body arrives
         staged = await self.stage(
             chunks, expected_size=expected_size, expected_hashes=expected_hashes
@@ -895,7 +893,7 @@ class RepositoryContext:
             await self._lock("path", path)
             existing = await self.get(path, fresh=True)
             if checked:
-                self._check_may_store(existing)
+                self._check_may_store(path, existing)
             await self._new_revision()
             blob = await blobs.record(self.db, self.backend, self.repository.blob_store_id, staged)
             self.recorded.append(staged)
@@ -1048,7 +1046,7 @@ class RepositoryContext:
         """
         path = normalise_path(path)
         if removing:
-            authorize(self.principal, self.permission("delete"), scheme="Basic")
+            access.require(self.principal, self.repository, path, "delete")
             self._check_policy(replacing=False)
         else:
             self.require_write()
@@ -1082,14 +1080,15 @@ class RepositoryContext:
         )
 
     async def annotate(
-        self, namespace: str, name: str, version: str, attributes: dict[str, Any]
+        self, namespace: str, name: str, version: str, attributes: dict[str, Any], *, path: str
     ) -> bool:
         """Replace a component's attributes. False if there is no such component.
 
-        Changing what is said about a published version needs `edit`. It is not a
-        redeploy, so `disable_redeploy` does not stop it; a read-only repository does.
+        Changing what is said about a published version needs `edit`, at `path`: the
+        file of the version it is said of. It is not a redeploy, so `disable_redeploy`
+        does not stop it; a read-only repository does.
         """
-        authorize(self.principal, self.permission("edit"), scheme="Basic")
+        access.require(self.principal, self.repository, path, "edit")
         self._check_policy(replacing=False)
         key = ComponentKey(namespace, name, version)
         await self._lock_component(key)
@@ -1112,7 +1111,7 @@ class RepositoryContext:
     async def delete(self, path: str) -> bool:
         """Remove what is at a path. False if there was nothing. The caller commits."""
         path = normalise_path(path)
-        authorize(self.principal, self.permission("delete"), scheme="Basic")
+        access.require(self.principal, self.repository, path, "delete")
         self._check_policy(replacing=False)
         return await self._remove(path)
 
```

Change `backend/src/megooarti/repositories/routes.py`:

```diff
@@ -15,9 +15,9 @@ from megooarti.errors import ApiError
 from megooarti.repositories import dispatch, remote, service
 from megooarti.repositories.content import build_context
 from megooarti.repositories.formats import get_format
+from megooarti.security import access
 from megooarti.security.authentication import (
     Credentials,
-    authorize,
     client_credentials,
     unauthorized,
 )
@@ -63,7 +63,8 @@ async def repository_content(
     )
 
     if reading:
-        authorize(principal, context.permission("read"), scheme="Basic")
+        # The path asked for, as it is asked: a path is never rewritten to be served.
+        access.require(principal, repository, path, "read")
     elif principal is None and not in_body:
         raise unauthorized(scheme="Basic")
     if not repository.online:
```

Change `backend/src/megooarti/repositories/npm/format.py`:

```diff
@@ -482,7 +482,9 @@ async def _update(
 
     for version, message in plan.deprecations.items():  # needs `edit`
         changed = documents.deprecated(held[version], message)
-        await context.annotate(scope, name, version, {_MANIFEST: changed})
+        await context.annotate(
+            scope, name, version, {_MANIFEST: changed}, path=paths.tarball_path(package, version)
+        )
     for version in plan.removals:  # needs `delete`
         await context.delete(paths.tarball_path(package, version))
     if tags is not None:
```

Change `backend/src/megooarti/repositories/docker/routes.py`:

```diff
@@ -24,11 +24,10 @@ from megooarti.repositories.content import build_context
 from megooarti.repositories.docker import errors, names
 from megooarti.repositories.docker.errors import RegistryError
 from megooarti.repositories.docker.format import FORMAT, images
-from megooarti.security import registry_tokens
+from megooarti.security import access, registry_tokens
 from megooarti.security.authentication import (
     Credentials,
     Principal,
-    authorize,
     issue_registry_token,
     registry_credentials,
 )
@@ -174,10 +173,15 @@ async def catalog(
         count, last = _paging(request)
         found: list[str] = []
         for repository in await service.repositories_of(db, FORMAT):
-            context = await build_context(db, request.app.state.settings, repository, principal)
-            if not repository.online or not principal.allows(context.permission("read")):
+            reached = access.reach(principal, repository, "read")
+            if not repository.online or not reached.anything:
                 continue
-            found.extend(f"{repository.name}/{image}" for image in await images(context))
+            context = await build_context(db, request.app.state.settings, repository, principal)
+            found.extend(
+                f"{repository.name}/{image}"
+                for image in await images(context)
+                if reached.folder(image)  # an image is what is under its name
+            )
         listed = sorted(name for name in found if name > last)
         page = listed[:count]
         headers = {}
@@ -222,7 +226,7 @@ async def repository_request(
             outbound=lambda: remote.client_of(request.app),
         )
         if request.method in ("GET", "HEAD"):
-            authorize(principal, context.permission("read"), scheme="Basic")
+            access.require(principal, repository, path, "read")
         if not repository.online:
             raise ApiError(503, "repository_offline", "This repository is offline.")
         response = await dispatch.serve(context, request, path)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest -q tests/repositories tests/storage`
Expected: 3319 passed.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat(repositories): what is read, stored and deleted is checked by may at its path: the content route, groups, the registry, uploads, deletes and a version's attributes"
```

---

### Task 5: Listings, search and MCP by `may`; the guides; what the plan settled

**Files:**
- Create: `backend/src/megooarti/repositories/reached.py`
- Modify:
  - `backend/src/megooarti/repositories/browse.py`, `backend/src/megooarti/repositories/search.py`, `backend/src/megooarti/repositories/search_api.py`, `backend/src/megooarti/repositories/content_api.py`, `backend/src/megooarti/mcp/repositories.py`.
  - `docs/administration.md` (the section on content selectors), `docs/repositories.md`, `docs/api.md`, `docs/superpowers/specs/2026-10-19-identity-audit-selectors-design.md`.
- Test: `backend/tests/repositories/test_selector_listings.py`, `backend/tests/mcp/test_selector_repositories.py`

**Interfaces:**
- Consumes: Task 3's `access.reach`, `may`, `may_somewhere`, `require_somewhere`, `Reached`; Task 4's content checks.
- Produces:
  - `reached.holding(reached_by_repository_id)` and `reached.unreached(db, reached_by_repository_id, conditions)`.
  - `browse.components(..., reached=None)` and `browse.component(..., reached=None)`.
  - `search.search(..., reached=None)`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/repositories/test_selector_listings.py`:

```python
"""What a selector permission lets a caller see (spec 10): the repositories it names, and
in them only the folders, files and components it reaches, in the content API, search
and MCP; and a folder deleted is deleted where it may be."""

import pytest

from megooarti.repositories import service
from megooarti.security import roles
from megooarti.security.models import ContentSelector
from tests.accounts import PASSWORD, basic
from tests.repositories.conftest import someone
from tests.repositories.test_content_components import Packaged, store

CONTENT = "/api/v1/content"
ALLOWED = ["acme/app/1.0/app.tgz", "acme/app/1.0/app.pom", "acme/lib/2.0/lib.tgz"]
DENIED = ["other/tool/1.0/tool.tgz", "acme-private/x/1.0/x.tgz"]


@pytest.fixture
async def kim(db, files, context_for, make_user) -> dict[str, str]:
    """Someone whose selectors reach /acme/ in `files` (browse and delete) and whose other
    one names `npm-only`, a repository of another format: with files there and beside."""
    owner = await context_for(files, someone("*"))
    owner.format = Packaged()
    for path in ALLOWED + DENIED:
        await store(owner, path)
    await db.commit()
    await service.create_repository(
        db,
        name="secret",
        format="raw",
        type="hosted",
        online=True,
        blob_store="default",
        hosted=None,
        format_config={},
    )
    db.add_all(
        [
            ContentSelector(name="acme", expression='path =^ "/acme/"'),
            ContentSelector(name="pattern", expression='path =~ "/acme/.*\\\\.tgz"'),
            ContentSelector(name="npm-only", expression='format == "npm"'),
        ]
    )
    await roles.create_role(
        db,
        "acme",
        "",
        [
            "selector:acme:raw:files:browse",
            "selector:acme:raw:files:delete",
            "selector:npm-only:raw:secret:browse",
        ],
        [],
    )
    await roles.create_role(db, "tgz", "", ["selector:pattern:raw:files:browse"], [])
    await db.commit()
    await make_user("kim", roles=["acme"])
    await make_user("tia", roles=["tgz"])
    return basic("kim", PASSWORD)


async def test_only_the_repositories_a_selector_reaches_are_listed(client, kim):
    listed = await client.get(CONTENT, headers=kim)
    secret = await client.get(f"{CONTENT}/secret", headers=kim)

    assert [found["name"] for found in listed.json()["items"]] == ["files"]
    assert secret.status_code == 403  # named, but by a selector of another format


async def test_a_folder_shows_what_is_reached_and_one_that_holds_nothing_is_not_there(client, kim):
    root = await client.get(f"{CONTENT}/files/tree", headers=kim)
    acme = await client.get(f"{CONTENT}/files/tree", params={"path": "acme/app/1.0"}, headers=kim)
    other = await client.get(f"{CONTENT}/files/tree", params={"path": "other"}, headers=kim)

    assert [entry["name"] for entry in root.json()["items"]] == ["acme"]
    assert [entry["name"] for entry in acme.json()["items"]] == ["app.pom", "app.tgz"]
    assert other.status_code == 404


async def test_a_file_reached_is_shown_and_one_beside_it_is_not_there(client, kim):
    shown = await client.get(
        f"{CONTENT}/files/asset", params={"path": "acme/app/1.0/app.tgz"}, headers=kim
    )
    hidden = await client.get(
        f"{CONTENT}/files/asset", params={"path": "other/tool/1.0/tool.tgz"}, headers=kim
    )

    assert shown.status_code == 200
    assert hidden.status_code == 404


async def test_components_are_those_with_a_file_reached(client, kim):
    listed = await client.get(f"{CONTENT}/files/components", headers=kim)

    assert [found["name"] for found in listed.json()["items"]] == ["app", "lib"]
    assert listed.json()["total"] == 2


async def test_through_a_pattern_components_are_those_a_file_of_matches(client, kim):
    tia = basic("tia", PASSWORD)

    listed = await client.get(f"{CONTENT}/files/components", headers=tia)
    app = next(found for found in listed.json()["items"] if found["name"] == "app")
    detail = await client.get(f"{CONTENT}/files/components/{app['id']}", headers=tia)

    assert [found["name"] for found in listed.json()["items"]] == ["app", "lib"]
    assert [entry["path"] for entry in detail.json()["files"]] == ["acme/app/1.0/app.tgz"]


async def test_a_component_with_no_file_reached_is_not_there(client, kim, make_user):
    await make_user("root", roles=["admin"])
    every = await client.get(f"{CONTENT}/files/components", headers=basic("root", PASSWORD))
    tool = next(found["id"] for found in every.json()["items"] if found["name"] == "tool")

    hidden = await client.get(f"{CONTENT}/files/components/{tool}", headers=kim)

    assert hidden.status_code == 404


async def test_search_finds_only_components_with_a_file_reached(client, kim):
    found = await client.get("/api/v1/search", headers=kim)
    by_pattern = await client.get("/api/v1/search", params={"q": "tool"}, headers=kim)

    assert sorted(item["name"] for item in found.json()["items"]) == ["app", "lib"]
    assert found.json()["total"] == 2
    assert by_pattern.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


async def test_a_folder_deleted_loses_what_may_be_deleted_and_keeps_the_rest(
    client, kim, make_user
):
    deleted = await client.request(
        "DELETE", f"{CONTENT}/files/tree", params={"path": "acme"}, headers=kim
    )
    everything = await client.request(
        "DELETE", f"{CONTENT}/files/tree", params={"path": "other"}, headers=kim
    )
    await make_user("root", roles=["admin"])
    kept = await client.get(
        f"{CONTENT}/files/asset",
        params={"path": "other/tool/1.0/tool.tgz"},
        headers=basic("root", PASSWORD),
    )

    assert deleted.json()["deleted"] == 3
    assert everything.json()["deleted"] == 0
    assert kept.status_code == 200
```

Create `backend/tests/mcp/test_selector_repositories.py`:

```python
"""MCP's repositories by selector permissions (spec 10): a repository a selector names is
listed to whoever holds it, through the route the tool calls."""

from megooarti.security import roles
from megooarti.security.models import ContentSelector
from tests.mcp.conftest import structured


async def test_an_agent_lists_the_repositories_its_selectors_reach(
    agent, files, make_user, make_token, db
):
    db.add(ContentSelector(name="acme", expression='path =^ "/acme/"'))
    await roles.create_role(db, "acme", "", ["selector:acme:raw:files:browse"], [])
    await db.commit()
    token = await make_token(await make_user("kim", roles=["acme"]))

    async with agent(token) as client:
        listed = structured(await client.call_tool("list_repositories", {}))

    assert [found["name"] for found in listed["items"]] == ["files"]
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `backend/`): `uv run pytest -q tests/repositories/test_selector_listings.py tests/mcp/test_selector_repositories.py`
Expected: 9 failed: the listings know nothing of selectors (a selector's repository is not listed, its components are refused `403`).

- [ ] **Step 3: Write the code, the guides and the spec's rows**

Create `backend/src/megooarti/repositories/reached.py`:

```python
"""Which components of repositories a caller reaches (spec 10): for listing and searching
them where a selector permission reaches some of a repository and not the whole.

A component is reached if one of its files is. The database is asked first for the
components with a file the reach's narrowing keeps; where that is not exact (a pattern
is in it), the files it kept are then checked one by one, and the components none of
whose files is reached are left out too. Who reaches every repository whole pays
nothing for this.
"""

import uuid
from collections.abc import Mapping

from sqlalchemy import ColumnElement, and_, exists, false, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from megooarti.repositories.models import Asset, Component
from megooarti.security.access import Reached


def _path(asset: type[Asset] = Asset) -> ColumnElement[str]:
    """An asset's path as an expression sees it: from `/`."""
    return literal("/").concat(asset.path)


def holding(reached: Mapping[uuid.UUID, Reached]) -> ColumnElement[bool]:
    """The components of these repositories (by their ids) with a file reached: exactly
    where a reach is the whole or exact, and a superset where it is not."""
    # A file of its own, so that a query that has assets already still has these.
    held = aliased(Asset)
    parts = []
    for repository_id, reach in reached.items():
        theirs = Component.repository_id == repository_id
        condition, _ = reach.narrowing(_path(held))
        if condition is None:
            parts.append(theirs)
        else:
            parts.append(and_(theirs, exists().where(held.component_id == Component.id, condition)))
    return or_(*parts) if parts else false()


async def unreached(
    db: AsyncSession, reached: Mapping[uuid.UUID, Reached], conditions: list
) -> list[uuid.UUID]:
    """The components `holding` keeps, of those the conditions give, none of whose files
    is reached after all: to be left out too. Only a reach through a pattern has any."""
    left: list[uuid.UUID] = []
    for repository_id, reach in reached.items():
        condition, exact = reach.narrowing(_path())
        if condition is None or exact:
            continue
        rows = await db.execute(
            select(Component.id, Asset.path)
            .join(Asset, Asset.component_id == Component.id)
            .where(*conditions, Component.repository_id == repository_id, condition)
        )
        seen: set[uuid.UUID] = set()
        kept: set[uuid.UUID] = set()
        for component_id, path in rows:
            seen.add(component_id)
            if component_id not in kept and reach.allows(path):
                kept.add(component_id)
        left.extend(seen - kept)
    return left
```

Change `backend/src/megooarti/repositories/browse.py`:

```diff
@@ -16,6 +16,8 @@ from sqlalchemy import func, select, text
 from sqlalchemy.ext.asyncio import AsyncSession
 
 from megooarti.repositories.models import Asset, Component, Repository
+from megooarti.repositories.reached import holding, unreached
+from megooarti.security.access import Reached
 from megooarti.storage.models import Blob, BlobStore
 
 # The character after "/" in byte order. Every path under `folder/` is below `folder0`.
@@ -236,17 +238,25 @@ async def components(
     name: str | None = None,
     limit: int,
     offset: int,
+    reached: Reached | None = None,
 ) -> tuple[list[ComponentSummary], int]:
     """A page of a repository's components, and how many there are.
 
     In the order of namespace and name, the newest first. `unlisted` are the
-    namespaces the repository's format keeps for itself.
+    namespaces the repository's format keeps for itself. With `reached`, only the
+    components with a file it reaches (spec 10).
     """
     conditions = _listed(repository, unlisted)
     if namespace is not None:
         conditions.append(Component.namespace == namespace)
     if name is not None:
         conditions.append(Component.name == name)
+    if reached is not None and not reached.whole:
+        by_id = {repository.id: reached}
+        conditions.append(holding(by_id))
+        hidden = await unreached(db, by_id, conditions)
+        if hidden:
+            conditions.append(Component.id.not_in(hidden))
     total = await db.scalar(select(func.count()).select_from(Component).where(*conditions))
     # The page is chosen first, and only its components' files are looked at: grouping
     # every component with its files to show fifty would read the whole repository.
@@ -290,9 +300,15 @@ def _summary(
 
 
 async def component(
-    db: AsyncSession, repository: Repository, component_id: uuid.UUID, *, unlisted: frozenset[str]
+    db: AsyncSession,
+    repository: Repository,
+    component_id: uuid.UUID,
+    *,
+    unlisted: frozenset[str],
+    reached: Reached | None = None,
 ) -> tuple[ComponentSummary, list[Child]] | None:
-    """One component and its files, in path order, or None if it is not one to show."""
+    """One component and its files, in path order, or None if it is not one to show.
+    With `reached`, only the files it reaches, and None if it reaches none (spec 10)."""
     found = (
         await db.execute(
             select(*_COLUMNS).where(Component.id == component_id, *_listed(repository, unlisted))
@@ -310,7 +326,10 @@ async def component(
     files = [
         Child(path.rpartition("/")[2], path, "file", size, modified, reference)
         for path, size, modified in rows
+        if reached is None or reached.allows(path)
     ]
+    if reached is not None and not files:
+        return None
     newest = max((child.modified for child in files), default=None)
     return _summary(*found, newest), files
 
```

Change `backend/src/megooarti/repositories/search.py`:

```diff
@@ -8,7 +8,7 @@ Queries and plain values only. Which repositories may be searched is the route's
 """
 
 import uuid
-from collections.abc import Sequence
+from collections.abc import Mapping, Sequence
 from dataclasses import dataclass
 from datetime import datetime
 
@@ -17,6 +17,8 @@ from sqlalchemy.ext.asyncio import AsyncSession
 
 from megooarti.repositories.formats import get_format
 from megooarti.repositories.models import Asset, Component, Repository
+from megooarti.repositories.reached import holding, unreached
+from megooarti.security.access import Reached
 from megooarti.storage.models import Blob
 
 # Lower-case hexadecimal digits of each checksum.
@@ -116,16 +118,25 @@ async def search(
     *,
     limit: int,
     offset: int,
+    reached: Mapping[uuid.UUID, Reached] | None = None,
 ) -> tuple[list[Found], int]:
     """A page of the components in these repositories that match, and how many there are.
 
-    In the order of name, namespace and repository, the newest first. Raises BadChecksum.
+    In the order of name, namespace and repository, the newest first. With `reached`
+    (each repository's, by its id), only the components with a file it reaches (spec
+    10). Raises BadChecksum.
     """
     conditions = _conditions(wanted)
     if not repositories:
         return [], 0
-    conditions.append(Component.repository_id.in_([repository.id for repository in repositories]))
     conditions += _unlisted(repositories)
+    if reached is None or all(reach.whole for reach in reached.values()):
+        conditions.append(Component.repository_id.in_([found.id for found in repositories]))
+    else:
+        conditions.append(holding(reached))
+        hidden = await unreached(db, reached, conditions)
+        if hidden:
+            conditions.append(Component.id.not_in(hidden))
     total = await db.scalar(select(func.count()).select_from(Component).where(*conditions))
     # By bytes, so that the order is the same whatever the database orders by.
     order = (
```

Change `backend/src/megooarti/repositories/search_api.py`:

```diff
@@ -12,6 +12,7 @@ from megooarti.db.session import get_session
 from megooarti.errors import ApiError
 from megooarti.pagination import Page, PageParams, page
 from megooarti.repositories import search, service
+from megooarti.security import access
 from megooarti.security.authentication import Principal, require_caller
 
 router = APIRouter(prefix="/search", tags=["content"])
@@ -59,18 +60,23 @@ async def search_components(
     components that have a file with exactly that checksum. `format` and `repository`
     narrow where to look. With nothing given, everything is listed.
     """
-    allowed = [
-        found
+    reached = {
+        found.id: (found, access.reach(caller, found, "browse"))
         for found in await service.all_repositories(db)
         if found.type != "group"  # a group holds nothing of its own
         and (not format or found.format == format)
         and (not repository or found.name == repository)
-        and caller.allows(f"repository:{found.format}:{found.name}:browse")
-    ]
+    }
+    allowed = {key: reach for key, (_, reach) in reached.items() if reach.anything}
     wanted = search.Wanted(q, namespace, name, version, md5, sha1, sha256, sha512)
     try:
         items, total = await search.search(
-            db, allowed, wanted, limit=params.limit, offset=params.offset
+            db,
+            [reached[key][0] for key in allowed],
+            wanted,
+            limit=params.limit,
+            offset=params.offset,
+            reached=allowed,
         )
     except search.BadChecksum as error:
         digits = search.CHECKSUMS[str(error)]
```

Change `backend/src/megooarti/repositories/content_api.py`:

```diff
@@ -27,9 +27,9 @@ from megooarti.repositories.content import RepositoryContext, build_context
 from megooarti.repositories.formats import ComponentKey, Format, get_format
 from megooarti.repositories.models import Repository
 from megooarti.repositories.paths import normalise_path
+from megooarti.security import access
 from megooarti.security.authentication import (
     Principal,
-    authorize,
     require_caller,
     unauthorized,
 )
@@ -110,10 +110,6 @@ class Uploaded(BaseModel):
     files: list[AssetView]
 
 
-def _permission(repository: Repository, action: str) -> str:
-    return f"repository:{repository.format}:{repository.name}:{action}"
-
-
 async def _base(request: Request, db: AsyncSession) -> str:
     """The public address of this server, without a slash at its end."""
     return (await get_setting(db, "base_url") or str(request.base_url)).rstrip("/")
@@ -145,7 +141,7 @@ async def _view(
         members = [
             member.name
             for member in await service.members(db, repository)
-            if caller.allows(_permission(member, "browse"))
+            if access.may_somewhere(caller, member, "browse")
         ]
     handler = get_format(repository.format)
     url = _address(repository, handler, base)
@@ -164,11 +160,11 @@ async def _view(
 async def _repository(
     db: AsyncSession, name: str, caller: Principal, action: str = "browse"
 ) -> Repository:
-    """The repository, if the caller may do this to it. Raises 404, 401 or 403."""
+    """The repository, if the caller may do this to some of it. Raises 404, 401 or 403."""
     repository = await service.get_repository(db, name)
     if repository is None:
         raise ApiError(404, "not_found", "No such repository.")
-    authorize(caller, _permission(repository, action))
+    access.require_somewhere(caller, repository, action, scheme="Bearer")
     return repository
 
 
@@ -203,7 +199,7 @@ async def list_repositories(
 ) -> dict:
     """The repositories the caller may browse."""
     every = await service.all_repositories(db)
-    allowed = [found for found in every if caller.allows(_permission(found, "browse"))]
+    allowed = [found for found in every if access.may_somewhere(caller, found, "browse")]
     base = await _base(request, db)
     shown = allowed[params.offset : params.offset + params.limit]
     views = [await _view(db, found, base, caller) for found in shown]
@@ -235,6 +231,7 @@ async def list_folder(
     A folder may hold millions of entries, so there is no total: `next` leads on.
     """
     found = await _holding(db, repository, caller)
+    reach = access.reach(caller, found, "browse")
     folder = path.strip("/")
     if folder:
         normalise_path(folder)
@@ -246,9 +243,15 @@ async def list_folder(
     except browse.BadCursor:
         details = [{"field": "after", "message": "Not something a listing returned."}]
         raise ApiError(422, "validation_error", "The request is not valid.", details) from None
-    if folder and not items and not after:
+    if folder and ((not items and not after) or not reach.folder(folder)):
         raise ApiError(404, "not_found", "No such folder.")
-    return Listing(items=[_entry(child) for child in items], next=following)
+    # What the caller may not see is left out: a page may be shorter, `next` leads on.
+    shown = [
+        child
+        for child in items
+        if (reach.folder(child.path) if child.kind == "folder" else reach.allows(child.path))
+    ]
+    return Listing(items=[_entry(child) for child in shown], next=following)
 
 
 @router.get("/{repository}/asset", response_model=AssetView)
@@ -261,10 +264,9 @@ async def get_asset(
 ) -> AssetView:
     found = await _holding(db, repository, caller)
     handler = _handler(found)
-    detail = await browse.asset(
-        db, found, normalise_path(path), unlisted=handler.unlisted_namespaces
-    )
-    if detail is None:
+    path = normalise_path(path)
+    detail = await browse.asset(db, found, path, unlisted=handler.unlisted_namespaces)
+    if detail is None or not access.may(caller, found, path, "browse"):
         raise ApiError(404, "not_found", "No such file.")
     return _asset_view(found, handler, detail, await _base(request, db))
 
@@ -288,6 +290,7 @@ async def list_components(
         name=name,
         limit=params.limit,
         offset=params.offset,
+        reached=access.reach(caller, found, "browse"),
     )
     return page(items, total, params)
 
@@ -302,7 +305,13 @@ async def get_component(
 ) -> ComponentDetail:
     found = await _holding(db, repository, caller)
     handler = _handler(found)
-    held = await browse.component(db, found, component_id, unlisted=handler.unlisted_namespaces)
+    held = await browse.component(
+        db,
+        found,
+        component_id,
+        unlisted=handler.unlisted_namespaces,
+        reached=access.reach(caller, found, "browse"),
+    )
     if held is None:
         raise ApiError(404, "not_found", "No such component.")
     summary, files = held
@@ -334,7 +343,7 @@ async def _deletable(
 ) -> RepositoryContext:
     """A context for deleting from a repository that holds files. Raises as `_holding` does."""
     repository = await _holding(db, name, caller)
-    authorize(caller, _permission(repository, "delete"))
+    access.require_somewhere(caller, repository, "delete", scheme="Bearer")
     return await build_context(db, request.app.state.settings, repository, caller)
 
 
@@ -384,8 +393,11 @@ async def delete_folder(
     found = await browse.paths_under(
         db, context.repository, folder, after=after, limit=_FOLDER_AT_ONCE
     )
+    deletable = access.reach(caller, context.repository, "delete")
     deleted = skipped = 0
     for held in found:
+        if not deletable.allows(held):
+            continue  # not theirs to delete: it stays, and is not said
         try:
             deleted += await _delete_file(context, held)  # 0 if it went with an earlier one
         except ApiError as error:
@@ -464,9 +476,9 @@ async def upload(
     if found is None:
         raise ApiError(404, "not_found", "No such repository.")
     try:
-        authorize(caller, _permission(found, "add"))
+        access.require_somewhere(caller, found, "add", scheme="Bearer")
     except ApiError:
-        authorize(caller, _permission(found, "edit"))
+        access.require_somewhere(caller, found, "edit", scheme="Bearer")
     handler = _handler(found)
     refusal = _NO_UPLOAD.get(found.type) or handler.no_upload
     if refusal is not None:
```

Change `backend/src/megooarti/mcp/repositories.py`:

```diff
@@ -13,6 +13,7 @@ from megooarti.mcp.results import Cursor, Limit, Page, offset_of, page_of
 from megooarti.mcp.tools import caller, database, tool
 from megooarti.repositories import api as repositories_api
 from megooarti.repositories import content_api, service
+from megooarti.security import access
 
 READ_SETTINGS = "admin:repositories:read"
 
@@ -52,7 +53,7 @@ async def list_repositories(
             for held in await service.all_repositories(db)
             if (not format or held.format == format)
             and (not type or held.type == type)
-            and principal.allows(f"repository:{held.format}:{held.name}:browse")
+            and access.may_somewhere(principal, held, "browse")
         ]
         summaries = []
         for held in allowed[offset : offset + limit]:
```

Change `docs/administration.md`:

````diff
@@ -235,6 +235,83 @@ Certificates, or at `/api/v1/certificates`, and is trusted by all of them at onc
 The full API is described at `/api/docs`. The page is served with its own script and
 stylesheet, and asks nothing of another host.
 
+### Content selectors
+
+A content selector names some of what repositories hold, by the repository's format and
+a file's path. A **selector permission** gives an action on what it names, where a
+repository permission gives it on all of a repository. Selectors are kept at
+`/api/v1/content-selectors`, with `admin:selectors:read` and `admin:selectors:write`.
+
+```bash
+curl -u admin -H 'Content-Type: application/json' -d '{
+  "name": "acme", "description": "Acme artifacts",
+  "expression": "format == \"maven\" and path =^ \"/com/acme/\""
+}' https://repo.example.com/api/v1/content-selectors
+```
+
+- **The expression.**
+  - Each comparison sets `format` or `path` against a string in double quotes:
+    - `==` means equal to;
+    - `=^` means starts with;
+    - `=~` means the whole value matches a regular expression (Python's, at most
+      1,000 characters).
+  - Combine comparisons with `and`, `or`, `not` and parentheses; `and` binds before
+    `or`.
+  - In a string, `\"` is a quote and `\\` a backslash. A pattern's own backslash is
+    written twice, so `\\.` stands for a literal dot.
+  - A path starts with `/`, and is the path after the repository's address:
+    - for Maven, `/com/acme/app/1.0/app-1.0.jar`;
+    - for Docker, the path after `/v2/<repository>/`, such as `/team/app/manifests/1.0`.
+  - An expression that does not parse is refused at `expression`, with the character
+    where it went wrong.
+- **The permission.**
+  - Its form is `selector:<selector>:<format>:<repository>:<action>`, with each part
+    `*` allowed and the same actions as a repository permission's. It gives that
+    action on the paths of those repositories that the selector matches.
+    `selector:acme:maven:*:read` reads Acme's artifacts in every Maven repository.
+  - A role can name only selectors that exist, and a selector a role names cannot be
+    deleted (`409 in_use`).
+  - Changing a selector changes, at once, what every permission naming it gives.
+- **Reading, writing, deleting.**
+  - A download is checked at the path asked for, whether by a package client, the
+    registry, or the API's file details.
+  - Each file stored or deleted is checked at its own path.
+  - An upload needs `add` or `edit` somewhere in the repository before its body is
+    read, and then at each path it stores.
+  - Changing what is said of a published version (npm's deprecate) needs `edit` at
+    the version's file.
+  - Through a group, the group's permission is checked at the path asked for; its
+    members are not checked again.
+- **What is listed.**
+  - A repository is listed to a caller holding a selector permission that names it,
+    with a selector that can match its format.
+  - Inside it are listed:
+    - the folders that may hold something reached. A pattern's folders cannot be
+      told, so all of them are listed.
+    - the files the selector reaches.
+    - the components that have a file it reaches, each with only those files.
+  - Search finds the same.
+  - Deleting a folder deletes what may be deleted, and keeps the rest.
+- **Tokens and anonymous access.**
+  - A token's scopes narrow a selector permission as they would the repository
+    permission it stands in for: a token that may only read reads through a selector
+    too.
+  - The `anonymous` user's selector permissions are everyone's, as its repository
+    permissions are.
+- **Preview.** `POST /api/v1/content-selectors/preview`, with `{"expression": ...,
+  "format": "maven", "paths": [...]}`, says which of up to 100 paths an expression
+  matches.
+- **What it costs.**
+  - Whoever holds no selector permission pays nothing for selectors, and an expression
+    is read once.
+  - Listing through a selector asks the database for what its prefixes allow. Where a
+    pattern is in it, each file kept is then checked: a listing a pattern decides is
+    slower in a large repository.
+  - A pattern is run against paths that anyone may send. Keep patterns simple: one
+    that nests repetitions, such as `(a+)+`, can take very long on a crafted path.
+  - Each change of a selector is recorded in the audit log (`selector.created`,
+    `selector.updated`, `selector.deleted`).
+
 ### Audit log
 
 Every change of configuration or security, and every sign-in, is recorded: under
````

Change `docs/repositories.md`:

```diff
@@ -35,7 +35,9 @@ In place of a password, use an API token as the password, or send it as
 - **Permissions** are `repository:<format>:<name>:<action>`, where the action is `browse`
   (see what is there), `read` (download), `add` (a new path), `edit` (replace a path) or
   `delete`. For example `repository:raw:files:read`, or `repository:raw` for everything
-  on every Raw repository.
+  on every Raw repository. A selector permission,
+  `selector:<selector>:<format>:<name>:<action>`, gives the same for the paths a content
+  selector matches: see [Content selectors](administration.md#content-selectors).
 - **Deployment policy** per hosted repository: `allow_redeploy`, `disable_redeploy`
   (a path can be written once) or `read_only`. A repository that is made without one
   allows redeploy, except a Maven repository for releases, which refuses it: a release
@@ -118,7 +120,8 @@ curl -u admin -H 'Content-Type: application/json' -d '{
 
 - Members are tried in order and the first that has the path answers. Offline members,
   and proxies whose remote is unavailable, are passed over.
-- Reading through a group needs `read` on the group only, not on its members.
+- Reading through a group needs `read` on the group only, not on its members: by a
+  repository permission, or by a selector permission on the group at the path asked.
 - A group may contain other groups. It cannot be written to, and a repository cannot be
   deleted while a group presents it.
 
```

Change `docs/api.md`:

````diff
@@ -105,7 +105,9 @@ curl -u alice -X DELETE 'https://repo.example.com/api/v1/content/maven-releases/
 - **Seeing needs `browse`** on the repository, and downloading needs `read`. Deleting
   through this API needs `browse` and `delete`, and nothing else: not the right to
   publish. The list leaves out what you may not browse, and a group names only the
-  members you may browse.
+  members you may browse. Through a content selector you see only what it reaches:
+  its folders, files and components (see
+  [Content selectors](administration.md#content-selectors)).
 - **A folder** (`tree`) lists what is directly in it, in the byte order of the names,
   each entry a `folder` or a `file`. It is read a page at a time: give the `next` of
   one answer as `after` in the following request. There is no total, because a
@@ -221,7 +223,8 @@ curl -u alice -F file=@greeter-1.0-py3-none-any.whl -F file=@greeter-1.0.tar.gz
 
 ## Search
 
-`/api/v1/search` finds components in every repository you may browse.
+`/api/v1/search` finds components in every repository you may browse, and, where a
+content selector lets you browse some of one, the components with a file it reaches.
 
 ```bash
 curl -u alice 'https://repo.example.com/api/v1/search?q=commons+lang'
````

Change `docs/superpowers/specs/2026-10-19-identity-audit-selectors-design.md`:

```diff
@@ -227,6 +227,21 @@ Settled here, by the designer:
 - REST: `GET/POST /api/v1/content-selectors`, `GET/PUT/DELETE /api/v1/content-selectors/{name}`, `POST /api/v1/content-selectors/preview` (an expression and paths: which match). Permissions `admin:selectors:read` and `write`. A selector a role names cannot be deleted.
 - The screens (15h): Content selectors, with a preview against paths; the role editor's rows offer selector permissions.
 
+### Settled while building plan 15g
+
+| # | What | Why |
+| --- | --- | --- |
+| G1 | Expressions are `security/selectors.py`'s: a parser of the grammar of D2 (keywords lower case; a string's only escapes `\"` and `\\`), at most 4,000 characters, 32 levels deep, a pattern at most 1,000; refused with `SelectorError`, the message and the character (from 1). `parse` is kept by the expression's text (1,024 at most), which is the selector's version: a changed selector is parsed anew. | D2; section 10; 14: compiled once. |
+| G2 | An expression says three things: `matches(format, path)`; `under(format, folder)`, whether no path, some or every path under a folder may match (a pattern: some), for listing folders; and `narrowing(format, path_column)`, a condition a database can test that every match meets, exact unless a pattern is in it, for listing only what may match before each is checked. | Section 10: listings and search leave out what a caller may not see, without reading every path where a prefix says it. |
+| G3 | Selectors are `content_selectors` (name unique, as a permission's segment; description; expression; times), at `/api/v1/content-selectors` with `admin:selectors:read` and `write`; the name does not change. A role names only selectors there are, or every one (`selector:*`); one a role names is not deleted (`409 in_use`). Each change is recorded (`selector.created`, `updated`, `deleted`). Preview takes an expression, a format and at most 100 paths, `/` put before a path without one. | Section 10; 15f's audit. |
+| G4 | A principal carries the selectors its patterns (and the public's) can name, each by its name with its expression, read with it; none, at no cost, for whoever holds no selector permission. `security/access.py` decides: `reach(principal, repository, action)` is the whole (by a repository permission) or the expressions of the selector permissions that name it; `may` is a path of it; `require` and `require_somewhere` answer 401 or 403 as `authorize` does. | E6; section 14: only a principal holding selector permissions evaluates them. |
+| G5 | A token's scopes grant a selector permission if they grant it, or the repository permission it narrows (`selector:s:maven:releases:read` as `repository:maven:releases:read`): a read-only token reads through a selector. The anonymous user's selector permissions are public, as its repository permissions are. | Section 10 is silent: a token that may only read must not lose what a selector gives its user to read. |
+| G6 | The content route and the registry check `read` at the path asked, with a `/` before it; a path is never rewritten to be served, and one that is not canonical is refused before it is (`invalid_path`). Each file stored is checked at its path (`add` or `edit`), each deleted at its own (`delete`); an upload whose paths are known only as it is read needs `add` or `edit` somewhere first. A version's attributes (npm's deprecate) need `edit` at its file. A document a format keeps beside what was uploaded (Maven's metadata, npm's package document) is written as part of that upload, not checked again. | Section 10: reads, writes and deletes. |
+| G7 | Through a group, the group's permission is checked at the path asked, and its members are not checked again (as `group.py` has it for repository permissions): each member is asked for that path, which is the member's path. | Section 10: "through groups (each member's path checked)". |
+| G8 | A repository is listed, and its page and members shown, to a caller whose reach of it for `browse` is something: the whole, or a selector that can match its format. In it: folders that may hold something reached (`under`), files reached, components with a file reached (each with only those files), counted exactly; search likewise. A file or component not reached is `404`, as one that is not there. Deleting a folder deletes what may be deleted, and keeps the rest unsaid. | Section 10: listings, search, `browse some of it`. |
+| G9 | Listing through a reach that is not the whole asks the database for the components with a file the narrowing keeps (`repositories/reached.py`), and, where a pattern makes it inexact, checks those files one by one and leaves out the components none of whose files is reached; totals stay exact and paging stays in the database. | Section 14: selectors must not slow every read. |
+| G10 | Docker's catalog lists, of the images of a repository reached, those under whose name (`<image>/`) something may be reached. | Section 10: Docker, at the path of the registry's request. |
+
 ## 11. Errors and limits
 
 - Sign-in through an external source answers as a local one does: `401 Invalid credentials.`, throttled alike (SEC-19); what went wrong is logged and audited, not said.
```

- [ ] **Step 4: Run the tests to verify they pass, and every test**

Run (in `backend/`): `uv run pytest -q tests/repositories/test_selector_listings.py tests/mcp tests/repositories/test_content_api.py tests/repositories/test_browse.py tests/repositories/test_search.py tests/repositories/test_search_text.py tests/repositories/test_content_delete.py tests/test_documents.py`
Expected: 431 passed.

Then every test: (in `backend/`) `uv run ruff format --check . && uv run ruff check . && uv run pytest -q`; (in `frontend/`) `pnpm vitest run`
Expected: Ruff: `474 files already formatted`, `All checks passed!`; pytest: 4446 passed, 2 skipped, 117 deselected (the `docker` tests); Vitest: 928 passed.

- [ ] **Step 5: Commit**

```bash
git add backend docs
git commit -m "feat(repositories): listings, search and MCP show what may lets a caller browse, narrowed in the database; docs: content selectors, and what plan 15g settled"
```
