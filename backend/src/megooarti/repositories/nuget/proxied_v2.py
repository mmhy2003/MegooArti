"""A proxy of a V2 feed: the Chocolatey community feed, the PowerShell Gallery, or any
feed that serves NuGet's V2 protocol (section 6 of the spec).

A client's query is passed on as it came, its path and its query string, and what the
feed answers has the feed's addresses made the proxy's as it is sent: each entry's and
the next page's. A version's package is the proxy's `package/<id>/<version>`, fetched
from where the feed's entry of it says, wherever that is. A query's answer is metadata,
kept by the whole
query and asked about again after the proxy's metadata age; a search is passed on every
time and not kept. A package is a cached file, kept where a pushed one would be, and
read as a pushed one is. The feed's `$metadata` is passed on as it is; the root, which
names the one collection, is the proxy's own.
"""

import hashlib
import html
import re
from collections.abc import Sequence
from urllib.parse import quote, urlencode, urljoin

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories import proxy
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.nuget import atom, odata, paths, responses, versions
from megooarti.repositories.proxy import Absent, Answer, Source

# Where what the feed answered is kept: paths no client asks for.
KEPT = ".remote/"
METADATA = f"{KEPT}$metadata"
ANSWERS = f"{KEPT}v2/"
SEARCHES = f"{KEPT}v2/search"
# What is read of the feed's answers, at the most.
FEED_MOST = 16 * 1024 * 1024
# A search is not kept: the Gallery answers PSResourceGet's `$top=6000` with tens of MB.
SEARCH_MOST = 64 * 1024 * 1024
METADATA_MOST = 1024 * 1024
# What of a function's path is sent as it is: its parentheses, quotes, `=` and commas.
_SAFE = "()'=,$/"
_ADDRESS = re.compile(r'(xml:base|href|src)="([^"]*)"')
_ID = re.compile(r"<id>([^<]*)</id>")
_CONTENT = re.compile(r'(<content\b[^>]*\bsrc=")([^"]*)(")')
_BASE = re.compile(r'xml:base="([^"]*)"')
_NEXT = re.compile(
    r'<link\b[^>]*\brel="next"[^>]*\bhref="([^"]*)"|<link\b[^>]*\bhref="([^"]*)"[^>]*\brel="next"'
)
_COUNT = re.compile(r"<m:count>([0-9]+)</m:count>")
# The pages of a feed's answer a group follows, at the most, for the entries it asks for.
PAGES_MOST = 10


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
    return atom.ENTRIES.sub(lambda found: _packaged(found[0], target), text).encode("utf-8")


def _packaged(entry: str, target: str) -> str:
    """An entry whose package is at the proxy's `package/<id>/<version>`, as its id says,
    wherever the feed has it."""
    found = atom.named(entry)
    if found is None:
        return entry
    package_id, version = (quote(part, safe="") for part in found)
    address = f"{target}/package/{package_id}/{version}"
    return _CONTENT.sub(lambda content: f"{content[1]}{address}{content[3]}", entry, count=1)


def _a_feed_path(path: str) -> bool:
    """Whether a path of V2's is what the feed serves there: a function, or the entry of
    an id and a version NuGet takes. The feed is asked for nothing else: what is asked of
    it goes with its credential."""
    entry = odata.entry_of(path)
    if entry is None:
        return True
    package_id, version = entry
    return versions.is_id(package_id) and versions.normalize(version) is not None


def _content_type(path: str) -> str:
    if path.endswith("/$count"):
        return "text/plain"
    if path.startswith("Packages(") and path.endswith(")"):
        return atom.ATOM_ENTRY
    return atom.ATOM


async def answer_of(context: RepositoryContext, path: str, query: str) -> bytes:
    """What the feed answers a query, `path` a function's and `query` its string as the
    feed is to be sent it: kept, or for a search, asked each time."""
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
        context, SEARCHES, Source(address, remember_missing=False, blocks=False), limit=SEARCH_MOST
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
    if parsed.kind == "v2" and _a_feed_path(path):
        data = await answer_of(context, path, request.url.query)
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
        address = await _package_address(context, package_id, version)
        await proxy.ensure_cached(context, kept, source=Source(address))
        return await context.respond(kept, request)
    raise _not_found()


def _prefixes(context: RepositoryContext, text: str) -> list[str]:
    """The feed's roots, as the proxy is given it and as an answer names it."""
    declared = _BASE.search(text)
    found = {root(context).rstrip("/")} | ({declared[1].rstrip("/")} if declared else set())
    return sorted((prefix for prefix in found if prefix), key=len, reverse=True)


def _next_of(context: RepositoryContext, text: str) -> tuple[str, str] | None:
    """The path and the query of an answer's next page, if it has one under the feed's
    root and it is a path of V2's feed."""
    found = _NEXT.search(text)
    if found is None:
        return None
    address = html.unescape(found[1] or found[2])
    prefixes = _prefixes(context, text)
    if "://" not in address:
        address = f"{prefixes[0]}/{address}" if prefixes else address
    for prefix in prefixes:
        if address.startswith(prefix + "/"):
            path, _, query = address[len(prefix) + 1 :].partition("?")
            if paths.classify(path).kind == "v2" and path and _a_feed_path(path):
                return path, query
    return None


async def entry_document(context: RepositoryContext, path: str, base: str) -> bytes:
    """An entry the feed has, `path` its `Packages(Id='…',Version='…')`, kept, with the
    addresses under `base`. Raises 404 for one the feed does not have, or is not asked."""
    if not _a_feed_path(path):
        raise _not_found()
    return rewrite(await answer_of(context, path, ""), root(context), base)


async def listing(
    context: RepositoryContext,
    path: str,
    arguments: Sequence[tuple[str, str]],
    base: str,
    wanted: int,
    *,
    counted: bool,
) -> tuple[list[tuple[str, str]], int]:
    """The feed's first `wanted` entries of a query, each as its key and its text with
    the addresses under `base`, and how many there are: the feed's count if `counted`,
    else as many as were read. The feed's next pages are followed for them."""
    kept = [
        (name, value) for name, value in arguments if name not in ("$skip", "$top", "$inlinecount")
    ]
    kept += [("$skip", "0"), ("$top", str(wanted))]
    if counted:
        kept.append(("$inlinecount", "allpages"))
    asked: tuple[str, str] | None = (path, urlencode(kept, quote_via=quote, safe="'$(),"))
    entries: list[tuple[str, str]] = []
    total = None
    for _ in range(PAGES_MOST):
        if asked is None or len(entries) >= wanted:
            break
        raw = (await answer_of(context, *asked)).decode("utf-8", errors="replace")
        if total is None and (count := _COUNT.search(raw)) is not None:
            total = int(count[1])
        text = rewrite(raw.encode(), root(context), base).decode()
        for found in atom.ENTRIES.findall(text):
            if (key := atom.key_of(found)) is not None:
                entries.append((key, found))
        asked = _next_of(context, raw)
    entries = entries[:wanted]
    return entries, total if counted and total is not None else len(entries)


async def _package_address(context: RepositoryContext, package_id: str, version: str) -> str:
    """Where the feed has a version's package: as its entry says, the entry kept as any
    answer is. Raises 404 if the feed has no such entry, or one without a package."""
    entry = f"Packages(Id='{package_id}',Version='{version}')"
    data = await proxy.document(
        context,
        kept_path(entry, ""),
        Source(f"{root(context)}{quote(entry, safe=_SAFE)}"),
        limit=FEED_MOST,
        content_type=atom.ATOM_ENTRY,
    )
    text = data.decode("utf-8", errors="replace")
    content = _CONTENT.search(text)
    if content is None:
        raise _not_found()
    declared = _BASE.search(text)
    base = html.unescape(declared[1]) if declared else root(context)
    return urljoin(base.rstrip("/") + "/", html.unescape(content[2]))
