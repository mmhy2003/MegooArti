"""What V3's search and autocomplete ask for, and which ids answer it, in which order.

Pure functions. A query is read as nuget.org reads one: words that each must be in an
id, a title, a description, the tags or the authors; `packageid:<id>` for one id
exactly, and `id:<text>` for ids that contain it. An exact id comes first, then ids
that begin with what was typed, then the rest, each by id.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from megooarti.errors import ApiError
from megooarti.repositories.nuget.documents import Published

# What one search may ask for (section 9 of the spec).
TAKE_MOST = 1000
SKIP_AND_TAKE_MOST = 3000
TAKE_DEFAULT = 20


@dataclass(frozen=True)
class Query:
    words: tuple[str, ...]  # lower case
    exact_id: str = ""  # lower case
    id_contains: str = ""  # lower case
    prerelease: bool = False
    skip: int = 0
    take: int = TAKE_DEFAULT

    @property
    def stored_words(self) -> tuple[str, ...]:
        """What a package's stored search text must hold: every word, and the id's."""
        return tuple(word for word in (*self.words, self.exact_id, self.id_contains) if word)


def _invalid(name: str, message: str) -> ApiError:
    details = [{"field": name, "message": message}]
    return ApiError(400, "invalid_query", message, details)


def _number(text: str | None, name: str, default: int) -> int:
    if text is None or text == "":
        return default
    if not (text.isascii() and text.isdigit() and len(text) <= 9):
        raise _invalid(name, f"{name} is a whole number, 0 or more.")
    return int(text)


def parse(arguments: Mapping[str, str]) -> Query:
    """A query from a request's arguments. Raises a 400 for one beyond the bounds."""
    skip = _number(arguments.get("skip"), "skip", 0)
    take = _number(arguments.get("take"), "take", TAKE_DEFAULT)
    if take > TAKE_MOST:
        raise _invalid("take", f"take is at most {TAKE_MOST}.")
    if skip + take > SKIP_AND_TAKE_MOST:
        raise _invalid("skip", f"skip and take together are at most {SKIP_AND_TAKE_MOST}.")
    words, exact, contains = [], "", ""
    for word in arguments.get("q", "").lower().split():
        field, colon, value = word.partition(":")
        if colon and field == "packageid" and value:
            exact = value
        elif colon and field == "id" and value:
            contains = value
        else:
            words.append(word)
    return Query(
        words=tuple(words),
        exact_id=exact,
        id_contains=contains,
        prerelease=arguments.get("prerelease", "").lower() == "true",
        skip=skip,
        take=take,
    )


def _text(held: Published) -> str:
    said = held.nuspec
    return " ".join(
        (said.id, said.title, said.description, said.tags, said.authors, said.summary)
    ).lower()


def _matches(query: Query, package_id: str, held: Sequence[Published]) -> bool:
    lower = package_id.lower()
    if query.exact_id and lower != query.exact_id:
        return False
    if query.id_contains and query.id_contains not in lower:
        return False
    return any(all(word in _text(one) for word in query.words) for one in held)


def _rank(query: Query, package_id: str) -> tuple:
    lower, typed = package_id.lower(), " ".join(query.words)
    return (lower != typed, not lower.startswith(typed), lower)


def select(
    query: Query, held: Mapping[str, Sequence[Published]]
) -> tuple[list[list[Published]], int]:
    """The page of ids that answer, each with the versions it may show, and how many answer.

    `held` is every version of each id that may answer, by id. A prerelease is shown
    only if the query asks for them; an id with nothing else is then not found.
    """
    answering = []
    for package_id, versions_held in held.items():
        shown = [one for one in versions_held if query.prerelease or not one.nuspec.is_prerelease]
        if shown and _matches(query, package_id, shown):
            answering.append((package_id, shown))
    answering.sort(key=lambda pair: _rank(query, pair[0]))
    page = answering[query.skip : query.skip + query.take]
    return [shown for _, shown in page], len(answering)
