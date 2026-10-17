"""What a request of NuGet's V2 protocol asks for: its function, its arguments and its
OData options, as the clients of the spec's D7 send them.

Pure functions. Only what those clients send is read (7.3 of the spec); anything else
is refused with a message that names it, rather than answered as if it were understood.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from megooarti.repositories.nuget import versions

# A page of a V2 feed, at most, as nuget.org's (section 9 of the spec).
TOP_MOST = 100

PACKAGES = "packages"
FIND = "find"
SEARCH = "search"
ENTRY = "entry"

_FUNCTIONS = {"Packages": PACKAGES, "FindPackagesById": FIND, "Search": SEARCH}
_ENTRY = re.compile(r"Packages\(Id='(?P<id>(?:[^']|'')*)',Version='(?P<version>(?:[^']|'')*)'\)")
_ORDERS = {
    "id": "id",
    "version": "version",
    "normalizedversion": "version",
    "downloadcount": "downloads",
    "published": "published",
    "lastupdated": "published",
    "created": "published",
}
# The options and arguments a client may send, by function.
_OPTIONS = {"$filter", "$orderby", "$skip", "$top", "$inlinecount", "semVerLevel"}
_ARGUMENTS = {
    PACKAGES: set(),
    FIND: {"id"},
    SEARCH: {"searchTerm", "targetFramework", "includePrerelease"},
    ENTRY: set(),
}


class UnsupportedQuery(Exception):
    """A request of V2 that this server does not answer. The message says what in it."""


@dataclass(frozen=True)
class Filter:
    """What `$filter` asks of a version: each condition given must hold. Text is in
    lower case; a version is normalized."""

    id: str = ""  # `Id eq '…'`
    id_starts: str = ""  # `startswith(Id, '…')`
    id_contains: str = ""  # `substringof('…', Id)`
    tags: tuple[str, ...] = ()  # `substringof('…', Tags)`: each is in its tags
    versions: tuple[tuple[str, str], ...] = ()  # `NormalizedVersion ge '…'`: (operator, version)
    latest: bool = False  # the newest stable version of its id
    absolute_latest: bool = False  # the newest of its id, prereleases too
    prerelease: bool | None = None  # `IsPrerelease eq …`


@dataclass(frozen=True)
class Query:
    function: str
    id: str = ""  # FindPackagesById's, or the entry's: as given
    version: str = ""  # the entry's: normalized, lower case
    search_term: str = ""
    prerelease: bool = True  # whether a prerelease may be shown
    filter: Filter = field(default_factory=Filter)
    order: tuple[tuple[str, bool], ...] = ()  # (what, descending)
    skip: int = 0
    top: int = TOP_MOST
    inline_count: bool = False
    count: bool = False  # `…/$count`: how many there are, as text


def _literal(text: str, name: str) -> str:
    """A string literal of OData: in single quotes, a quote in it doubled."""
    text = text.strip()
    if len(text) < 2 or text[0] != "'" or text[-1] != "'":
        raise UnsupportedQuery(f"{name} is a string in single quotes")
    inner = text[1:-1]
    if re.search(r"(?<!')'(?!')", inner.replace("''", "")):
        raise UnsupportedQuery(f"{name} has a quote that is not doubled")
    return inner.replace("''", "'")


def _number(text: str, name: str) -> int:
    if not (text.isascii() and text.isdigit() and len(text) <= 9):
        raise UnsupportedQuery(f"{name} is a whole number, 0 or more")
    return int(text)


_OPERATORS = ("eq", "ne", "gt", "ge", "lt", "le")
_STRING = r"('(?:[^']|'')*')"
_FLAG = re.compile(r"(IsLatestVersion|IsAbsoluteLatestVersion)(\s+eq\s+true)?")
_PRERELEASE = re.compile(r"IsPrerelease\s+eq\s+(true|false)")
_ID = re.compile(rf"(?:Id|tolower\(Id\))\s+eq\s+{_STRING}")
_VERSION = re.compile(rf"(?:Version|NormalizedVersion)\s+({'|'.join(_OPERATORS)})\s+{_STRING}")
_STARTS = re.compile(rf"startswith\((?:Id|tolower\(Id\)),\s*{_STRING}\)(\s+eq\s+true)?")
_CONTAINS = re.compile(rf"substringof\({_STRING},\s*(Id|tolower\(Id\)|Tags)\)(\s+eq\s+true)?")


def _unwrapped(text: str) -> str:
    """A condition without the parentheses around all of it."""
    text = text.strip()
    while text.startswith("(") and text.endswith(")"):
        depth = 0
        for at, character in enumerate(text):
            depth += {"(": 1, ")": -1}.get(character, 0)
            if depth == 0 and at < len(text) - 1:
                return text  # the first parenthesis closes before the end
        text = text[1:-1].strip()
    return text


def _condition(text: str, found: dict[str, object]) -> None:
    """One condition of `$filter`, read into what it asks for."""
    if (flag := _FLAG.fullmatch(text)) is not None:
        found["latest" if flag[1] == "IsLatestVersion" else "absolute_latest"] = True
    elif (prerelease := _PRERELEASE.fullmatch(text)) is not None:
        found["prerelease"] = prerelease[1] == "true"
    elif (compared := _ID.fullmatch(text)) is not None:
        found["id"] = _literal(compared[1], "Id").lower()
    elif (compared := _VERSION.fullmatch(text)) is not None:
        value = _literal(compared[2], "Version")
        # A version that is none matches nothing: no version has it.
        normalized = (versions.normalize(value) or f"none:{value}").lower()
        found["versions"] = (*found.get("versions", ()), (compared[1], normalized))  # type: ignore[misc]
    elif (starts := _STARTS.fullmatch(text)) is not None:
        found["id_starts"] = _literal(starts[1], "startswith").lower()
    elif (contains := _CONTAINS.fullmatch(text)) is not None:
        value = _literal(contains[1], "substringof").lower()
        if contains[2] == "Tags":
            found["tags"] = (*found.get("tags", ()), value)  # type: ignore[misc]
        else:
            found["id_contains"] = value
    else:
        raise UnsupportedQuery(f"$filter does not take {text!r} here")


def _filter(text: str) -> Filter:
    found: dict[str, object] = {}
    for part in re.split(r"\s+and\s+", _unwrapped(text)):
        _condition(_unwrapped(part), found)
    return Filter(**found)  # type: ignore[arg-type]


def _order(text: str) -> tuple[tuple[str, bool], ...]:
    order = []
    for part in text.split(","):
        words = part.split()
        what = _ORDERS.get(words[0].lower()) if words else None
        direction = words[1].lower() if len(words) == 2 else "asc"
        if what is None or len(words) > 2 or direction not in ("asc", "desc"):
            raise UnsupportedQuery(f"$orderby does not take {part.strip()!r}")
        order.append((what, direction == "desc"))
    return tuple(order)


def _function(path: str) -> tuple[str, str, str, bool]:
    """A path's function, the id and version of an entry, and whether it is `/$count`."""
    count = path.endswith("/$count")
    path = path.removesuffix("/$count")
    entry = _ENTRY.fullmatch(path)
    if entry is not None and not count:
        return ENTRY, entry["id"].replace("''", "'"), entry["version"].replace("''", "'"), False
    name = path.removesuffix("()")
    if name in _FUNCTIONS:
        return _FUNCTIONS[name], "", "", count
    raise UnsupportedQuery(f"{path!r} is not a function of this feed")


def is_v2(path: str) -> bool:
    """Whether a path is one of V2's: the root, `$metadata`, or a function of its feed."""
    if path in ("", "$metadata"):
        return True
    name = path.removesuffix("/$count")
    return _ENTRY.fullmatch(name) is not None or name.removesuffix("()") in _FUNCTIONS


def parse(path: str, arguments: Mapping[str, str]) -> Query:
    """A request of V2's feed. Raises UnsupportedQuery."""
    function, entry_id, entry_version, count = _function(path)
    unknown = sorted(set(arguments) - _OPTIONS - _ARGUMENTS[function])
    if unknown:
        raise UnsupportedQuery(f"{unknown[0]} is not taken by {path}")
    if function == ENTRY:
        normalized = versions.normalize(entry_version)
        return Query(ENTRY, id=entry_id, version=(normalized or entry_version).lower())
    inline = arguments.get("$inlinecount", "none")
    if inline not in ("allpages", "none"):
        raise UnsupportedQuery("$inlinecount is allpages or none")
    # More than a page is answered with a page, and the address of the next, as nuget.org does.
    top = min(_number(arguments["$top"], "$top"), TOP_MOST) if "$top" in arguments else TOP_MOST
    prerelease = True
    if function == SEARCH:
        flag = arguments.get("includePrerelease", "false").lower()
        if flag not in ("true", "false"):
            raise UnsupportedQuery("includePrerelease is true or false")
        prerelease = flag == "true"
    return Query(
        function,
        id=_literal(arguments["id"], "id") if function == FIND and "id" in arguments else "",
        search_term=_literal(arguments.get("searchTerm", "''"), "searchTerm"),
        prerelease=prerelease,
        filter=_filter(arguments["$filter"]) if arguments.get("$filter") else Filter(),
        order=_order(arguments["$orderby"]) if arguments.get("$orderby") else (),
        skip=_number(arguments.get("$skip", "0") or "0", "$skip"),
        top=top,
        inline_count=inline == "allpages",
        count=count,
    )
