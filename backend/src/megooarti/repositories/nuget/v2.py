"""NuGet's V2 protocol of a hosted repository: OData's Atom feeds of its versions,
written from the same records as V3's documents (E1), on each request (W1).

A query of one id reads that id's versions. A query of many (a `Search()`, or
`Packages()` without an id) takes their ids from the database a page at a time, in the
order of V3's search, and reads each page's versions, until it has the page asked for.
Only a count, or an order across ids by something other than the id, reads them all.
"""

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from urllib.parse import quote, urlencode

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.nuget import atom, odata, paths, queries, records, responses, versions
from megooarti.repositories.nuget.documents import Published

# How many ids are read at a time, for a query of many.
_NAMES_AT_ONCE = 100
# A query of many reads at most this many ids' versions: past it, a client is asked to
# narrow its query.
NAMES_MOST = 10_000

Found = tuple[Published, atom.Latest]


def _unsupported(error: odata.UnsupportedQuery) -> ApiError:
    return ApiError(
        400, "unsupported_query", f"This feed does not answer that query: {error}.", None
    )


_COMPARED = {
    "eq": lambda order: order == 0,
    "ne": lambda order: order != 0,
    "gt": lambda order: order > 0,
    "ge": lambda order: order >= 0,
    "lt": lambda order: order < 0,
    "le": lambda order: order <= 0,
}


def _compare(version: versions.Version, other: str) -> int | None:
    """Where a version is against another: -1, 0 or 1; None if the other is none."""
    parsed = versions.parse(other)
    if parsed is None:
        return None
    mine, theirs = version.sort_key(), parsed.sort_key()
    return (mine > theirs) - (mine < theirs)


def _admits(wanted: odata.Filter, held: Published, newest: atom.Latest) -> bool:
    """Whether a version holds each condition of a query's `$filter`."""
    nuspec = held.nuspec
    lower, version = nuspec.id.lower(), nuspec.version.lower()
    parsed = versions.parse(nuspec.version)
    if parsed is None or (wanted.id and lower != wanted.id):
        return False
    if not lower.startswith(wanted.id_starts) or wanted.id_contains not in lower:
        return False
    tags = nuspec.tags.lower().split()
    if any(not any(tag in one for one in tags) for tag in wanted.tags):
        return False
    for operator, other in wanted.versions:
        order = _compare(parsed, other)
        if order is None or not _COMPARED[operator](order):
            return False
    if wanted.prerelease is not None and parsed.is_prerelease != wanted.prerelease:
        return False
    if wanted.latest and version != newest[0]:
        return False
    return not wanted.absolute_latest or version == newest[1]


def _chosen(held: Sequence[Published], query: odata.Query) -> list[Found]:
    """The versions of one id that a query asks for, the oldest first."""
    newest = atom.latest(held)
    found = [
        (one, newest)
        for one in held
        if (query.prerelease or not one.nuspec.is_prerelease) and _admits(query.filter, one, newest)
    ]
    return sorted(
        found,
        key=lambda pair: versions.parse(pair[0].nuspec.version).sort_key(),  # type: ignore[union-attr]
    )


async def _names(context: RepositoryContext, query: odata.Query) -> AsyncIterator[list[str]]:
    """The ids a query may be of, a page at a time, in the order of V3's search. Its
    `$filter` is held to each of their versions after."""
    wanted = query.filter
    package_id = query.id if query.function == odata.FIND else wanted.id
    if package_id:
        spelling = await context.spelling("", package_id)
        if spelling is not None:
            yield [spelling]
        return
    searched = queries.parse({"q": query.search_term})
    stable = not query.prerelease or wanted.prerelease is False or wanted.latest
    # Ordered by id, the ids are taken in that order; else as V3's search ranks them.
    by_id = _leading(query.order) == "id"
    ranked = " ".join(searched.words) or searched.exact_id or wanted.id_starts
    for offset in range(0, NAMES_MOST, _NAMES_AT_ONCE):
        names, _ = await context.package_page(
            "",
            [*searched.words, *wanted.tags],
            exact=searched.exact_id,
            containing=searched.id_contains or wanted.id_contains or wanted.id_starts,
            ranked_by="" if by_id else ranked,
            stable_only=stable,
            limit=_NAMES_AT_ONCE,
            offset=offset,
        )
        if names:
            yield names
        if len(names) < _NAMES_AT_ONCE:
            return
    raise ApiError(
        400,
        "unsupported_query",
        f"This query is of more than {NAMES_MOST} ids: narrow it with a search term or an id.",
        None,
    )


def _sort_key(order: tuple[str, bool]):
    what, _ = order

    def key(pair: Found):
        held = pair[0]
        if what == "id":
            return held.nuspec.id.lower()
        if what == "version":
            return versions.parse(held.nuspec.version).sort_key()  # type: ignore[union-attr]
        if what == "published":
            return held.published
        return 0  # downloads: MegooArti counts none, so the order stays as it is

    return key


def _ordered(found: list[Found], order: Sequence[tuple[str, bool]]) -> list[Found]:
    for one in reversed(order):  # the first is sorted by last, as a stable sort allows
        found = sorted(found, key=_sort_key(one), reverse=one[1])
    return found


def _leading(order: Sequence[tuple[str, bool]]) -> str:
    """What an order is by first, past the download counts: each is 0, and orders
    nothing. "" for an order by them alone, which keeps the order of V3's search."""
    return next((what for what, _ in order if what != "downloads"), "")


def _in_name_order(order: Sequence[tuple[str, bool]]) -> bool:
    """Whether an order keeps each id's versions together, in the ids' order."""
    return _leading(order) in ("", "id") and not any(
        descending for what, descending in order if what == "id"
    )


async def _found(
    context: RepositoryContext, query: odata.Query
) -> tuple[list[Found], bool, int | None]:
    """The page a query asks for, whether there is more, and how many there are if the
    query asks for that."""
    wanted = query.skip + query.top
    every = query.count or query.inline_count or not _in_name_order(query.order)
    found: list[Found] = []
    async for names in _names(context, query):
        held = await context.components_of("", names)
        for name in names:
            found += _chosen(records.published(held.get(name, [])), query)
        if not every and len(found) > wanted:
            break
    total = len(found) if every else None
    found = _ordered(found, query.order)
    return found[query.skip : wanted], len(found) > wanted, total


def _next(base: str, path: str, request: Request, query: odata.Query) -> str:
    """The address of the page after this one: the same query, `$skip` past it."""
    arguments = [
        (name, value) for name, value in request.query_params.multi_items() if name != "$skip"
    ]
    arguments.append(("$skip", str(query.skip + query.top)))
    return f"{base}{path}?{urlencode(arguments, quote_via=quote, safe=chr(39) + '$(),')}"


async def _respond(
    context: RepositoryContext, request: Request, data: bytes, content_type: str
) -> Response:
    return await responses.respond(context, request, data, content_type, "feed.xml")


async def _entry(context: RepositoryContext, request: Request, query: odata.Query) -> Response:
    spelling = await context.spelling("", query.id)
    held = [] if spelling is None else records.published(await context.components("", spelling))
    chosen = [one for one in held if one.nuspec.version.lower() == query.version]
    if not chosen:
        raise ApiError(404, "not_found", f"This repository has no {query.id} {query.version}.")
    base = await responses.base(context, request)
    document = atom.entry(base, chosen[0], atom.latest(held))
    return await _respond(context, request, document, atom.ATOM_ENTRY)


async def download(
    context: RepositoryContext, request: Request, parsed: paths.NuGetPath
) -> Response:
    """`package/<id>/<version>`: V2's address of a package."""
    spelling = await context.spelling("", parsed.id)
    if spelling is None:
        raise ApiError(404, "not_found", f"This repository has no package {parsed.id}.")
    return await context.respond(paths.package_path(spelling, parsed.version), request)


async def answer(context: RepositoryContext, request: Request, path: str) -> Response:
    """A request of V2's feed: its root, `$metadata`, or a query of its versions."""
    base = await responses.base(context, request)
    if path == "":
        return await _respond(context, request, atom.service_document(base), atom.XML)
    if path == "$metadata":
        return await _respond(context, request, atom.METADATA, atom.XML)
    try:
        query = odata.parse(path, request.query_params)
    except odata.UnsupportedQuery as error:
        raise _unsupported(error) from None
    if query.function == odata.ENTRY:
        return await _entry(context, request, query)
    page, more, total = await _found(context, query)
    if query.count:
        count = str(total).encode()
        return await responses.respond(context, request, count, "text/plain", "count")
    title = path.removesuffix("()")
    document = atom.feed(
        base,
        title,
        page,
        updated=datetime.now(UTC),
        count=total if query.inline_count else None,
        next_address=_next(base, path, request, query) if more else "",
    )
    return await _respond(context, request, document, atom.ATOM)
