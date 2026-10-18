"""NuGet's V2 protocol of a group: one feed of the members that serve V2, its hosted
members, its V2 proxies and its groups (E3, 7.3 of the spec).

A query is asked of each member for its first `skip + top` entries, with the group's own
address, so that what each gives names the group alone; the answers are merged in the
members' order, the first entry of an id and a version kept, and the page asked for cut
from them, with the group's own link to the next (E5). An entry is the first member's
that has it. A package at V2's address is the first member's that has it, as the group
engine answers; the root and `$metadata` are the group's own. A query of one id, an
entry and a package of an id a hosted member holds are asked of its holders alone (H1).
"""

from dataclasses import replace
from datetime import UTC, datetime

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories import group
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.nuget import (
    atom,
    feeds,
    odata,
    proxied_v2,
    responses,
    v2,
    versions,
)

# An entry as text, and its key: its id and its version as NuGet matches them.
Keyed = tuple[str, str]


def _not_found(message: str = "No member of this group has it.") -> ApiError:
    return ApiError(404, "not_found", message)


async def _members(
    context: RepositoryContext, request: Request, query: odata.Query
) -> list[RepositoryContext]:
    """The members a query of a group is asked of: of one id a hosted repository holds,
    its owners alone; else every member that serves V2."""
    package_id = query.id if query.function in (odata.FIND, odata.ENTRY) else query.filter.id
    held = await feeds.owners(context, package_id) if package_id else []
    if held:
        return held
    return [
        member
        for member in await group.member_contexts(context, request)
        if feeds.speaks(member, "v2")
    ]


async def _listing(
    member: RepositoryContext,
    request: Request,
    path: str,
    query: odata.Query,
    base: str,
    wanted: int,
    counted: bool,
) -> tuple[list[Keyed], int]:
    """A member's first `wanted` entries of a query, and how many it has: its count if
    `counted`, else as many as it gave."""
    kind = member.repository.type
    if kind == "hosted":
        asked = replace(query, skip=0, top=wanted, inline_count=counted, count=False)
        page, _, total = await v2.found_of(member, asked)
        listed = []
        for held, newest in page:
            written = atom.rendered(base, held, newest)
            listed.append((atom.key_of(written) or "", written))
        return listed, total if total is not None else len(listed)
    if kind == "proxy":
        # A count is asked of the feed as its query, counted.
        function = path.removesuffix("/$count")
        arguments = request.query_params.multi_items()
        return await proxied_v2.listing(member, function, arguments, base, wanted, counted=counted)
    return await merged(member, request, path, query, base, wanted, counted)


async def merged(
    context: RepositoryContext,
    request: Request,
    path: str,
    query: odata.Query,
    base: str,
    wanted: int,
    counted: bool,
) -> tuple[list[Keyed], int]:
    """The first `wanted` entries of a query of a group's members that serve V2, in their
    order, an id's version once, and how many there are: the members' counts less the
    entries dropped. A member that is offline or cannot be asked gives nothing."""
    given = []
    for member in await _members(context, request, query):
        try:
            given.append(await _listing(member, request, path, query, base, wanted, counted))
        except ApiError as error:
            if error.status_code not in group.TRY_NEXT:
                raise
    entries: list[Keyed] = []
    seen: set[str] = set()
    total = dropped = 0
    for listed, counted_total in given:
        total += counted_total
        for key, written in listed:
            if key in seen:
                dropped += 1
                continue
            seen.add(key)
            entries.append((key, written))
    if query.filter.latest or query.filter.absolute_latest:
        newest = _newest(entries)
        dropped += len(entries) - len(newest)
        entries = newest
    return entries[:wanted], max(total - dropped, len(entries))


def _newest(entries: list[Keyed]) -> list[Keyed]:
    """Of each id, its newest entry alone, where the id's first was: what each member
    says is newest is newest of what it has, and the group's is the newest of those."""
    best: dict[str, Keyed] = {}
    for key, written in entries:
        package_id, version = key.split("/", 1)
        kept = best.get(package_id)
        if kept is None or _later(version, kept[0].split("/", 1)[1]):
            best[package_id] = (key, written)
    placed: list[Keyed] = []
    for key, _ in entries:
        package_id = key.split("/", 1)[0]
        if package_id in best:
            placed.append(best.pop(package_id))
    return placed


def _later(version: str, than: str) -> bool:
    mine, theirs = versions.parse(version), versions.parse(than)
    return mine is not None and theirs is not None and mine.sort_key() > theirs.sort_key()


async def _entry_of(
    context: RepositoryContext, request: Request, path: str, query: odata.Query, base: str
) -> bytes | None:
    """An entry of a group's: the first member's that has it, with the group's address."""
    for member in await _members(context, request, query):
        try:
            if member.repository.type == "hosted":
                found = await v2.entry_of(member, query.id, query.version, base)
            elif member.repository.type == "proxy":
                found = await proxied_v2.entry_document(member, path, base)
            else:
                found = await _entry_of(member, request, path, query, base)
        except ApiError as error:
            if error.status_code not in group.TRY_NEXT:
                raise
            continue
        if found is not None:
            return found
    return None


async def answer(context: RepositoryContext, request: Request, path: str, base: str) -> Response:
    """A request of a group's V2 feed: its root, `$metadata`, an entry, or a query."""
    if path == "":
        document = atom.service_document(base)
        return await responses.respond(context, request, document, atom.XML, "feed.xml")
    if path == "$metadata":
        return await responses.respond(context, request, atom.METADATA, atom.XML, "metadata.xml")
    try:
        query = odata.parse(path, request.query_params)
    except odata.UnsupportedQuery as error:
        raise v2.unsupported(error) from None
    if query.function == odata.ENTRY:
        found = await _entry_of(context, request, path, query, base)
        if found is None:
            raise _not_found()
        return await responses.respond(context, request, found, atom.ATOM_ENTRY, "feed.xml")
    counted = query.count or query.inline_count
    end = query.skip + query.top
    # One more than the page asked for: whether there is a next page.
    entries, total = await merged(context, request, path, query, base, end + 1, counted)
    if query.count:
        return await responses.respond(context, request, str(total).encode(), "text/plain", "count")
    page = [written for _, written in entries[query.skip : end]]
    more = len(entries) > end
    document = atom.feed_of(
        base,
        path.removesuffix("()"),
        page,
        updated=datetime.now(UTC),
        count=total if query.inline_count else None,
        next_address=v2.next_address(base, path, request, query) if more else "",
    )
    return await responses.respond(context, request, document, atom.ATOM, "feed.xml")
