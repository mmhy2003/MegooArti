"""A proxy of a V3 feed: nuget.org, or any feed that serves NuGet's V3 protocol.

The remote's service index says where it serves each resource, often on other hosts
(nuget.org searches elsewhere). It is kept as metadata, under a path no client asks
for. The proxy serves a service index of its own, with its own addresses.

A package and its `.nuspec` are cached files, kept as every proxy keeps its files; an
id's versions and its registration are metadata, kept and asked about again after the
proxy's metadata age; search and autocomplete are passed on every time. What the proxy
passes on of a registration or a search has the remote's addresses made its own, as it
is sent: what is kept is what the remote sent.
"""

import json
import re
from typing import Any
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories import proxy
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.nuget import documents, paths, remotes, responses, versions
from megooarti.repositories.proxy import Absent, Answer, Source

# Where the remote's service index is kept: a path no client asks for.
REMOTE_INDEX = ".remote/index.json"
# What is read of the remote's documents, at the most.
INDEX_MOST = 1024 * 1024
REGISTRATION_MOST = 32 * 1024 * 1024
SEARCH_MOST = 8 * 1024 * 1024
# NuGet Audit's files: nuget.org's base file is some megabytes once inflated.
VULNERABILITIES_MOST = 64 * 1024 * 1024


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "Nothing is served at this address.")


async def resources(context: RepositoryContext) -> remotes.Resources:
    """Where the remote serves what the proxy passes on. Raises 502 for an index that
    cannot be used, as for a remote that cannot be reached."""
    remote_url = context.repository.config["proxy"]["remote_url"]
    data = await proxy.document(
        context, REMOTE_INDEX, Source(remote_url), limit=INDEX_MOST, content_type=responses.JSON
    )
    try:
        return remotes.read_index(data)
    except remotes.InvalidIndex as error:
        raise await proxy.refuse(context, REMOTE_INDEX, str(error)) from None


def _replacements(found: remotes.Resources, base: str) -> list[tuple[str, str]]:
    """The remote's addresses and the proxy's for them, the longest first."""
    pairs = [(registration, f"{base}{paths.REGISTRATION}") for registration in found.registrations]
    pairs.append((found.packages, f"{base}{paths.PACKAGES}"))
    return sorted(pairs, key=lambda pair: len(pair[0]), reverse=True)


# A part of a feed's path past an id: a version, a file, a page's bound.
_PART = re.compile(r"[A-Za-z0-9._+-]+")


def _id_first(parts: list[str]) -> bool:
    return parts[0] == parts[0].lower() and versions.is_id(parts[0])


def _a_package_path(relative: str) -> bool:
    """`<id>/index.json`, or `<id>/<version>/<file>`: what a feed's package address
    serves (a package, its `.nuspec`, its icon)."""
    parts = relative.split("/")
    if not _id_first(parts):
        return False
    if parts[1:] == ["index.json"]:
        return True
    if len(parts) != 3:
        return False
    version = versions.normalize(parts[1])
    return version is not None and version.lower() == parts[1] and bool(_PART.fullmatch(parts[2]))


def _a_registration_path(relative: str) -> bool:
    """`<id>/index.json`, `<id>/<version>.json` or `<id>/page/<lower>/<upper>.json`."""
    parts = relative.split("/")
    if not _id_first(parts) or not parts[-1].endswith(".json"):
        return False
    if len(parts) == 2:
        return bool(_PART.fullmatch(parts[1]))
    return (
        len(parts) == 4 and parts[1] == "page" and all(_PART.fullmatch(part) for part in parts[2:])
    )


def _relative(path: str, prefix: str, shaped) -> str | None:
    """What follows a resource's address in a path, escaped as an address is, if it is
    what the feed serves there; else None. The feed is asked for nothing else: what is
    asked of it goes with its credential."""
    rest = path[len(prefix) :] if path.startswith(prefix) else ""
    if not rest or ".." in rest.split("/") or not shaped(rest):
        return None
    return quote(rest, safe="/")


async def _parsed(context: RepositoryContext, path: str, data: bytes) -> Any:
    try:
        return json.loads(data)
    except ValueError:
        raise await proxy.refuse(context, path, "it sent a document that is not JSON") from None


async def registration_document(
    context: RepositoryContext, path: str, relative: str, base: str
) -> Any:
    """A registration's document as the feed sent it, kept, with its addresses made those
    under `base`: the proxy's, or a group's in front of it."""
    found = await resources(context)
    data = await proxy.document(
        context,
        path,
        Source(f"{found.registration}{relative}", gzipped=True),
        limit=REGISTRATION_MOST,
        content_type=responses.JSON,
    )
    return remotes.rewrite(await _parsed(context, path, data), _replacements(found, base))


def _items(document: Any) -> list[Any]:
    items = document.get("items") if isinstance(document, dict) else None
    return items if isinstance(items, list) else []


async def items_of(context: RepositoryContext, package_id: str, base: str) -> list[Any]:
    """Every version's item of an id's registration on the feed, its pages fetched where
    the feed lists them by their addresses, with the addresses under `base`. Raises 404
    or 502 as the feed's registration does."""
    relative = f"{package_id}/index.json"
    if not _a_registration_path(relative):
        raise _not_found()
    index = await registration_document(
        context, f"{paths.REGISTRATION}{relative}", quote(relative, safe="/"), base
    )
    found: list[Any] = []
    prefix = f"{base}{paths.REGISTRATION}"
    for page in _items(index):
        if not isinstance(page, dict):
            continue
        if "items" in page:
            found += _items(page)
            continue
        address = page.get("@id")
        if not isinstance(address, str) or not address.startswith(prefix):
            continue  # a page elsewhere than the feed's registration: not asked for
        page_relative = address[len(prefix) :]
        if not _a_registration_path(page_relative):
            continue
        document = await registration_document(
            context,
            f"{paths.REGISTRATION}{page_relative}",
            quote(page_relative, safe="/"),
            base,
        )
        found += _items(document)
    return found


async def versions_of(context: RepositoryContext, package_id: str) -> list[str]:
    """An id's versions on the feed, kept as metadata. Raises 404 or 502 as the feed does."""
    relative = f"{package_id}/index.json"
    if not _a_package_path(relative):
        raise _not_found()
    path = f"{paths.PACKAGES}{relative}"
    found = await resources(context)
    escaped = quote(relative, safe="/")
    await proxy.ensure_cached(context, path, source=Source(f"{found.packages}{escaped}"))
    data = await context.read(path, limit=REGISTRATION_MOST)
    document = await _parsed(context, path, data or b"{}")
    listed = document.get("versions") if isinstance(document, dict) else None
    return [one for one in listed if isinstance(one, str)] if isinstance(listed, list) else []


async def passed_on(context: RepositoryContext, path: str, query: str, base: str) -> Any:
    """A search or an autocomplete, passed on with `query`, its answer not kept, with its
    addresses under `base`. Raises 404 where the feed has no such service, 502 where it
    cannot be asked."""
    found = await resources(context)
    address = found.search if path == paths.SEARCH else found.autocomplete
    if not address:
        raise _not_found()
    source = Source(
        f"{address}?{query}" if query else address, remember_missing=False, blocks=False
    )
    answer = await proxy.ask(context, path, source, limit=SEARCH_MOST)
    if isinstance(answer, Absent):
        raise _not_found()
    if not isinstance(answer, Answer):
        raise answer.error
    return remotes.rewrite(await _parsed(context, path, answer.body), _replacements(found, base))


# --- NuGet Audit's data -------------------------------------------------------------


async def _vulnerability_entries(context: RepositoryContext) -> list[dict[str, Any]]:
    """The feed's index of its vulnerability files, kept: each with its `@name` and its
    address on the feed. Raises 404 where the feed has none."""
    found = await resources(context)
    if not found.vulnerabilities:
        raise _not_found()
    data = await proxy.document(
        context,
        paths.VULNERABILITY_INDEX,
        Source(found.vulnerabilities, gzipped=True),
        limit=INDEX_MOST,
        content_type=responses.JSON,
    )
    listed = await _parsed(context, paths.VULNERABILITY_INDEX, data)
    return [
        entry
        for entry in (listed if isinstance(listed, list) else [])
        if isinstance(entry, dict)
        and isinstance(entry.get("@name"), str)
        and _PART.fullmatch(entry["@name"])
        and isinstance(entry.get("@id"), str)
    ]


async def vulnerability_index(context: RepositoryContext, base: str) -> list[dict[str, Any]]:
    """NuGet Audit's index, each file at `<base>v3/vulnerabilities/<name>.json`."""
    return [
        {**entry, "@id": f"{base}{paths.VULNERABILITIES}{entry['@name']}.json"}
        for entry in await _vulnerability_entries(context)
    ]


async def _vulnerability_file(context: RepositoryContext, path: str, name: str) -> bytes:
    """One of NuGet Audit's files, by its name in the feed's index, kept as metadata."""
    entries = await _vulnerability_entries(context)
    entry = next((one for one in entries if one["@name"] == name), None)
    if entry is None:
        raise _not_found()
    return await proxy.document(
        context,
        path,
        Source(entry["@id"], gzipped=True),
        limit=VULNERABILITIES_MOST,
        content_type=responses.JSON,
    )


def vulnerability_name(path: str) -> str | None:
    """The name of one of NuGet Audit's files a path is of, or None."""
    name = path.removeprefix(paths.VULNERABILITIES).removesuffix(".json")
    shaped = path.startswith(paths.VULNERABILITIES) and path.endswith(".json")
    return name if shaped and name != "index" and _PART.fullmatch(name) else None


async def handle_proxy(context: RepositoryContext, request: Request, path: str) -> Response:
    """Answer a request to a V3 proxy. The route has checked `read`."""
    if request.method not in ("GET", "HEAD"):
        raise ApiError(
            405,
            "method_not_allowed",
            "A proxy repository accepts GET and HEAD.",
            headers={"Allow": "GET, HEAD"},
        )
    base = await responses.base(context, request)
    if path == paths.SERVICE_INDEX:
        found = await resources(context)
        index = documents.service_index(
            base,
            publish=False,
            search=bool(found.search),
            autocomplete=bool(found.autocomplete),
            vulnerabilities=bool(found.vulnerabilities),
        )
        return await responses.respond_json(context, request, index)
    if (relative := _relative(path, paths.PACKAGES, _a_package_path)) is not None:
        found = await resources(context)
        await proxy.ensure_cached(context, path, source=Source(f"{found.packages}{relative}"))
        return await context.respond(path, request)
    if (relative := _relative(path, paths.REGISTRATION, _a_registration_path)) is not None:
        document = await registration_document(context, path, relative, base)
        return await responses.respond_json(context, request, document)
    if path in (paths.SEARCH, paths.AUTOCOMPLETE):
        document = await passed_on(context, path, request.url.query, base)
        return await responses.respond_json(context, request, document)
    if path == paths.VULNERABILITY_INDEX:
        listed = await vulnerability_index(context, base)
        return await responses.respond_json(context, request, listed)
    if (name := vulnerability_name(path)) is not None:
        data = await _vulnerability_file(context, path, name)
        return await responses.respond_data(context, request, data)
    raise _not_found()
