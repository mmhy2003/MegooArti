"""What V3's search and autocomplete ask for, and which ids answer it, in which order.

Pure functions. A query is read as nuget.org reads one: words that each must be in an
id, a title, a description, the tags or the authors; `packageid:<id>` for one id
exactly, and `id:<text>` for ids that contain it. The repository finds and orders the
ids (an exact id first, then ids that begin with what was typed, then the rest, each
by id); what is here is the reading of a query and the choice of versions to show.
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


def shown(
    query: Query, names: Sequence[str], held: Mapping[str, Sequence[Published]]
) -> list[list[Published]]:
    """The versions of each of a page's ids that may be shown, in the page's order.

    A prerelease is shown only if the query asks for them.
    """
    return [
        [one for one in held.get(name, ()) if query.prerelease or not one.nuspec.is_prerelease]
        for name in names
    ]
