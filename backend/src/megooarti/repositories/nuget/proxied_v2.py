"""A proxy of a V2 feed: the Chocolatey community feed, the PowerShell Gallery, or any
feed that serves NuGet's V2 protocol (section 6 of the spec).

A client's query is passed on as it came, its path and its query string, and what the
feed answers has the feed's addresses made the proxy's as it is sent: each entry's,
its package's, and the next page's. A query's answer is metadata, kept by the whole
query and asked about again after the proxy's metadata age; a search is passed on every
time and not kept. A package is a cached file, kept where a pushed one would be, and
read as a pushed one is. The feed's `$metadata` is passed on as it is; the root, which
names the one collection, is the proxy's own.
"""

import hashlib
import re
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories import proxy
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.nuget import atom, paths, responses
from megooarti.repositories.proxy import Absent, Answer, Source

# Where what the feed answered is kept: paths no client asks for.
KEPT = ".remote/"
METADATA = f"{KEPT}$metadata"
ANSWERS = f"{KEPT}v2/"
SEARCHES = f"{KEPT}v2/search"
# What is read of the feed's answers, at the most.
FEED_MOST = 16 * 1024 * 1024
METADATA_MOST = 1024 * 1024
# What of a function's path is sent as it is: its parentheses, quotes, `=` and commas.
_SAFE = "()'=,$/"
_ADDRESS = re.compile(r'(xml:base|href|src)="([^"]*)"')
_ID = re.compile(r"<id>([^<]*)</id>")


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "Nothing is served at this address.")


def root(context: RepositoryContext) -> str:
    """The feed's root, ending in a slash."""
    return context.repository.config["proxy"]["remote_url"].rstrip("/") + "/"


def kept_path(path: str, query: str) -> str:
    """Where the answer to a query is kept: by the whole query, path and string."""
    return f"{ANSWERS}{hashlib.sha256(f'{path}?{query}'.encode()).hexdigest()}.xml"


def rewrite(data: bytes, feed: str, base: str) -> bytes:
    """An answer of the feed with its addresses made the proxy's: those under the feed's
    root as the proxy is given it, and under the root the answer names (`xml:base`)."""
    text = data.decode("utf-8")
    declared = re.search(r'xml:base="([^"]*)"', text)
    prefixes = {feed.rstrip("/")} | ({declared[1].rstrip("/")} if declared else set())
    ordered = sorted((prefix for prefix in prefixes if prefix), key=len, reverse=True)
    target = base.rstrip("/")

    def swap(value: str) -> str:
        for prefix in ordered:
            if value == prefix or value.startswith(prefix + "/"):
                return target + value[len(prefix) :]
        return value

    text = _ADDRESS.sub(lambda found: f'{found[1]}="{swap(found[2])}"', text)
    text = _ID.sub(lambda found: f"<id>{swap(found[1])}</id>", text)
    return text.encode("utf-8")


def _content_type(path: str) -> str:
    if path.endswith("/$count"):
        return "text/plain"
    if path.startswith("Packages(") and path.endswith(")"):
        return atom.ATOM_ENTRY
    return atom.ATOM


async def _answer(context: RepositoryContext, request: Request, path: str) -> bytes:
    """What the feed answers a query: kept, or for a search, asked each time."""
    query = request.url.query
    address = f"{root(context)}{quote(path, safe=_SAFE)}" + (f"?{query}" if query else "")
    if path.split("/")[0].removesuffix("()") != "Search":
        return await proxy.document(
            context,
            kept_path(path, query),
            Source(address),
            limit=FEED_MOST,
            content_type=_content_type(path),
        )
    answer = await proxy.ask(
        context, SEARCHES, Source(address, remember_missing=False, blocks=False), limit=FEED_MOST
    )
    if isinstance(answer, Absent):
        raise _not_found()
    if not isinstance(answer, Answer):
        raise answer.error
    return answer.body


async def handle_proxy(context: RepositoryContext, request: Request, path: str) -> Response:
    """Answer a request to a V2 proxy. The route has checked `read`."""
    if request.method not in ("GET", "HEAD"):
        raise ApiError(
            405,
            "method_not_allowed",
            "A proxy repository accepts GET and HEAD.",
            headers={"Allow": "GET, HEAD"},
        )
    base = await responses.base(context, request)
    if path == "":
        document = atom.service_document(base)
        return await responses.respond(context, request, document, atom.XML, "feed.xml")
    if path == "$metadata":
        data = await proxy.document(
            context,
            METADATA,
            Source(f"{root(context)}$metadata"),
            limit=METADATA_MOST,
            content_type=atom.XML,
        )
        return await responses.respond(context, request, data, atom.XML, "metadata.xml")
    parsed = paths.classify(path)
    if parsed.kind == "v2":
        data = await _answer(context, request, path)
        content_type = _content_type(path)
        if content_type != "text/plain":
            try:
                data = rewrite(data, root(context), base)
            except UnicodeDecodeError:
                raise await proxy.refuse(
                    context, path, "it sent an answer that is not UTF-8"
                ) from None
        return await responses.respond(context, request, data, content_type, "feed.xml")
    if parsed.kind == "download":
        package_id, version = path.split("/")[1:]
        kept = paths.package_path(parsed.id, parsed.version)
        address = f"{root(context)}package/{quote(package_id, safe='')}/{quote(version, safe='')}"
        await proxy.ensure_cached(context, kept, source=Source(address))
        return await context.respond(kept, request)
    raise _not_found()
