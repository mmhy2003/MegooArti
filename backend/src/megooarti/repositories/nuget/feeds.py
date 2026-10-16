"""What a NuGet repository has, as data a group merges: of a hosted repository, of a
proxy, and of a group, which merges its own members'.

Each function is given the address its documents are to name (`base`): a group asks
its members for theirs with its own, so that what it merges names only the group. A
member that does not have something, or cannot be asked, gives nothing to the group
(as the generic group engine passes over it); anything else it raises is raised.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any
from urllib.parse import urlencode

from starlette.requests import Request

from megooarti.errors import ApiError
from megooarti.repositories import group
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.nuget import documents, paths, proxied, queries, records, versions


async def _members[T](
    context: RepositoryContext, request: Request, ask: Callable[[RepositoryContext], Awaitable[T]]
) -> list[T]:
    """What each online member gives, in order; nothing of one that has nothing."""
    given = []
    for member in await group.member_contexts(context, request):
        try:
            given.append(await ask(member))
        except ApiError as error:
            if error.status_code not in group.TRY_NEXT:
                raise
    return given


# --- An id's versions -----------------------------------------------------------------


async def versions_of(context: RepositoryContext, request: Request, package_id: str) -> list[str]:
    """An id's versions, normalized in lower case, the oldest first. None, an empty list."""
    kind = context.repository.type
    if kind == "hosted":
        spelling = await context.spelling("", package_id)
        listed = [] if spelling is None else list(await context.versions("", spelling))
    elif kind == "proxy":
        listed = await proxied.versions_of(context, package_id)
    else:
        given = await _members(context, request, lambda one: versions_of(one, request, package_id))
        listed = [version for found in given for version in found]
    normalized = {
        version.lower() for one in listed if (version := versions.normalize(one)) is not None
    }
    return versions.ordered(list(normalized))


# --- An id's registration ---------------------------------------------------------------


async def items_of(
    context: RepositoryContext, request: Request, package_id: str, base: str
) -> list[dict[str, Any]]:
    """Every version's item of an id's registration, with addresses under `base`, the
    oldest first; of a group, the first member's for a version several have."""
    kind = context.repository.type
    if kind == "hosted":
        spelling = await context.spelling("", package_id)
        held = [] if spelling is None else records.published(await context.components("", spelling))
        return documents.merged_items([[documents.item(base, one) for one in held]])
    if kind == "proxy":
        found = await proxied.items_of(context, package_id, base)
        return documents.merged_items([[one for one in found if isinstance(one, dict)]])
    given = await _members(context, request, lambda one: items_of(one, request, package_id, base))
    return documents.merged_items(given)


# --- Search -----------------------------------------------------------------------------


async def _leading[T](
    ask: Callable[[dict[str, str]], Awaitable[tuple[list[T], int]]],
    arguments: Mapping[str, str],
    query: queries.Query,
) -> tuple[list[T], int]:
    """A member's first `skip + take` results, and how many it has: asked for at most
    `TAKE_MOST` at a time, as a member takes them (nuget.org too)."""
    wanted = query.skip + query.take
    found: list[T] = []
    start = 0
    while True:
        take = min(queries.TAKE_MOST, wanted - start)
        listed, total = await ask({**arguments, "skip": str(start), "take": str(take)})
        found += listed
        start += take
        if start >= wanted or len(listed) < take:
            return found, total


def _merged[T](
    given: Sequence[tuple[list[T], int]], key: Callable[[T], str], query: queries.Query
) -> tuple[list[T], int]:
    """Members' results in their order, each key's first, and the page asked for cut
    from them; how many there are is the members' counts less the results dropped."""
    merged: dict[str, T] = {}
    total = dropped = 0
    for found, counted in given:
        total += counted
        for one in found:
            if key(one) in merged:
                dropped += 1
            else:
                merged[key(one)] = one
    listed = list(merged.values())
    return listed[query.skip : query.skip + query.take], max(total - dropped, len(listed))


async def search(
    context: RepositoryContext, request: Request, arguments: Mapping[str, str], base: str
) -> tuple[list[dict[str, Any]], int]:
    """The ids a search finds, as V3's search lists them, and how many there are.

    A group asks each member for its first `skip + take` results, keeps an id's first,
    and cuts the page asked for from them; of the total, it takes off the ids it dropped.
    """
    query = queries.parse(arguments)
    kind = context.repository.type
    if kind == "hosted":
        return await hosted_search(context, query, base)
    if kind == "proxy":
        answer = await proxied.passed_on(context, paths.SEARCH, urlencode(dict(arguments)), base)
        data = answer.get("data") if isinstance(answer, dict) else None
        total = answer.get("totalHits") if isinstance(answer, dict) else None
        found = [one for one in data if isinstance(one, dict)] if isinstance(data, list) else []
        return found, total if isinstance(total, int) else len(found)
    given = await _members(
        context,
        request,
        lambda one: _leading(lambda page: search(one, request, page, base), arguments, query),
    )
    return _merged(given, lambda one: str(one.get("id", "")).lower(), query)


async def hosted_search(
    context: RepositoryContext, query: queries.Query, base: str
) -> tuple[list[dict[str, Any]], int]:
    """A hosted repository's search: its page of ids chosen in the database (W1)."""
    names, total = await context.package_page(
        "",
        query.words,
        exact=query.exact_id,
        containing=query.id_contains,
        ranked_by=" ".join(query.words),
        stable_only=not query.prerelease,
        limit=query.take,
        offset=query.skip,
    )
    held = await context.components_of("", names)
    found = queries.shown(
        query, names, {name: records.published(infos) for name, infos in held.items()}
    )
    return documents.search_result(base, found, total)["data"], total


# --- Autocomplete -------------------------------------------------------------------------


async def completed_ids(
    context: RepositoryContext, request: Request, arguments: Mapping[str, str]
) -> tuple[list[str], int]:
    """The ids that contain what was typed (`q`), as autocomplete lists them, and how
    many there are; of a group, each id once, in its members' order."""
    query = queries.parse({**arguments, "q": ""})
    typed = arguments.get("q", "").strip().lower()
    prerelease = arguments.get("prerelease", "").lower() == "true"
    kind = context.repository.type
    if kind == "hosted":
        return await context.package_page(
            "",
            [],
            containing=typed,
            ranked_by=typed,
            stable_only=not prerelease,
            limit=query.take,
            offset=query.skip,
        )
    if kind == "proxy":
        answer = await proxied.passed_on(
            context, paths.AUTOCOMPLETE, urlencode(dict(arguments)), ""
        )
        data = answer.get("data") if isinstance(answer, dict) else None
        total = answer.get("totalHits") if isinstance(answer, dict) else None
        found = [one for one in data if isinstance(one, str)] if isinstance(data, list) else []
        return found, total if isinstance(total, int) else len(found)
    given = await _members(
        context,
        request,
        lambda one: _leading(lambda page: completed_ids(one, request, page), arguments, query),
    )
    return _merged(given, str.lower, query)


async def completed_versions(
    context: RepositoryContext, request: Request, package_id: str, prerelease: bool
) -> list[str]:
    """An id's versions, as autocomplete lists them given an `id`: a prerelease only if
    asked for, each once, the oldest first."""
    kind = context.repository.type
    if kind == "hosted":
        spelling = await context.spelling("", package_id)
        held = [] if spelling is None else records.published(await context.components("", spelling))
        listed = [one.nuspec.version for one in held]
    elif kind == "proxy":
        arguments = {"id": package_id, "prerelease": "true" if prerelease else "false"}
        answer = await proxied.passed_on(context, paths.AUTOCOMPLETE, urlencode(arguments), "")
        data = answer.get("data") if isinstance(answer, dict) else None
        listed = [one for one in data if isinstance(one, str)] if isinstance(data, list) else []
    else:
        given = await _members(
            context, request, lambda one: completed_versions(one, request, package_id, prerelease)
        )
        listed = [version for found in given for version in found]
    shown: dict[str, str] = {}
    for one in listed:
        parsed = versions.parse(one)
        if parsed is not None and (prerelease or not parsed.is_prerelease):
            shown.setdefault(parsed.normalized.lower(), parsed.normalized)
    return [shown[key] for key in versions.ordered(list(shown))]


# --- NuGet Audit's data -----------------------------------------------------------------


async def vulnerability_index(
    context: RepositoryContext, request: Request, base: str
) -> list[dict[str, Any]] | None:
    """NuGet Audit's index, its files under `base`; of a group, its first member's that
    has one. None where there is none."""
    kind = context.repository.type
    if kind == "hosted":
        return None
    if kind == "proxy":
        try:
            return await proxied.vulnerability_index(context, base)
        except ApiError as error:
            if error.status_code not in group.TRY_NEXT:
                raise
            return None
    for found in await _members(
        context, request, lambda one: vulnerability_index(one, request, base)
    ):
        if found is not None:
            return found
    return None
