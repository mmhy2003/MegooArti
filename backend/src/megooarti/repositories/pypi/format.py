"""The PyPI format: an index that twine uploads to and pip, uv and Poetry install from.

This is the only PyPI module that touches the repository context. What a path means,
whether an upload is acceptable and what a page says come from the pure functions
beside it.

A project's page is generated on each request from the files stored, so it is right
after a delete and after two uploads at once. An upload goes to the blob store as it
arrives: it is never held in memory.

A proxy keeps the remote's page for a project and never serves it. The links are read
out of it as it streams, and the page sent is written from them, pointing here. A file
is fetched from the address the remote's page gives for it, which is often on another
host, and must match the hash on that page. Reading a page is CPU-bound work whose size
a remote decides, so it runs on two worker threads of its own.
"""

import asyncio
import hashlib
from collections.abc import AsyncIterator, Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories import proxy
from megooarti.repositories.content import RepositoryContext, Stored
from megooarti.repositories.formats import ComponentKey, Format, register
from megooarti.repositories.pypi import names, pages, upload

_FILE = "application/octet-stream"
_METADATA = "text/plain; charset=utf-8"
# Not the default executor: that one also reads and writes blobs and checks passwords.
_workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pypi-pages")
# Where what an upload declares is kept among its component's attributes.
_DECLARED = "pypi"
# The most projects a root index lists. Installers never ask for it.
ROOT_LIMIT = 100_000
_PROTECTIVE = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"}


async def off_loop[T](function: Callable[..., T], *arguments: Any) -> T:
    """Run page work in a worker thread, at most two at a time."""
    return await asyncio.get_running_loop().run_in_executor(_workers, function, *arguments)


def _not_found(message: str = "Nothing is served at this address.") -> ApiError:
    return ApiError(404, "not_found", message)


def _not_allowed(allowed: str) -> ApiError:
    return ApiError(
        405,
        "method_not_allowed",
        f"This address accepts {allowed}.",
        headers={"Allow": allowed},
    )


def _invalid(reason: object) -> ApiError:
    return ApiError(400, "invalid_package", f"The upload cannot be accepted: {reason}.")


def _is_read(request: Request) -> bool:
    return request.method in ("GET", "HEAD")


def _redirect(location: str) -> Response:
    """Send the client to the one address a page has. `location` is relative."""
    return Response(status_code=301, headers={"Location": location, **_PROTECTIVE})


def _page(context: RepositoryContext, request: Request, data: bytes) -> Response:
    """The answer to a request for an index page that was built for it."""
    return context.respond_with(
        data,
        request,
        filename="index.html",
        content_type=pages.CONTENT_TYPE,
        last_modified=utcnow(),
        etag=hashlib.sha256(data).hexdigest(),
    )


# --- Reading -------------------------------------------------------------------------


async def _root_index(
    context: RepositoryContext,
    request: Request,
    within: Sequence[RepositoryContext] | None = None,
) -> Response:
    """The projects held: by this repository, or by those behind a group."""
    found, _ = await context.package_names("", limit=ROOT_LIMIT, offset=0, within=within)
    await context.release()  # writing the page needs no connection
    return _page(context, request, pages.root_page(name for _, name in found))


async def _project_page(context: RepositoryContext, request: Request, project: str) -> Response:
    """A hosted project's page, from the files stored. `project` is in its normal form."""
    files = await context.package_files("", project)
    if not files:
        raise _not_found("No such project.")
    await context.release()  # writing the page needs no connection
    links = [
        pages.Link(
            filename=held.path.rpartition("/")[2],
            version=held.version,
            digest=f"sha256={held.sha256}",
            requires_python=(held.attributes.get(_DECLARED) or {}).get("requires_python"),
        )
        for held in files
    ]
    return _page(context, request, pages.project_page(project, links))


# --- Uploading -----------------------------------------------------------------------


async def _upload(context: RepositoryContext, request: Request) -> Response:
    """Take one file and what the client says about it, as twine sends them."""
    # Refused before the body is read; the facade checks again when the file is stored.
    context.require_write()
    try:
        form = upload.Form(request.headers.get("Content-Type", ""))
    except upload.InvalidUpload as error:
        raise _invalid(error) from None
    await context.release()  # the body needs no connection

    async def file_bytes() -> AsyncIterator[bytes]:
        async for chunk in request.stream():
            for piece in form.feed(chunk):
                yield piece
        form.finish()

    try:
        staged = await context.stage(file_bytes())
    except upload.InvalidUpload as error:
        raise _invalid(error) from None
    try:
        sent = upload.declared(form.fields, form.filename, form.files)
    except upload.InvalidUpload as error:
        await context.discard(staged)
        raise _invalid(error) from None
    wrong = [name for name, digest in sent.digests.items() if getattr(staged, name) != digest]
    if wrong:
        await context.discard(staged)
        raise ApiError(400, "checksum_mismatch", f"The {wrong[0]} digest does not match the file.")

    release = {"name": sent.name, "version": sent.version, "summary": sent.summary}
    # The facade checks `add` or `edit` and the deployment policy, under the path's lock.
    # The path has the version in the file's name, not the one declared: a file name
    # then has one address in its project, and declaring another version cannot put a
    # second file of that name beside the first.
    await context.store(
        names.file_path(sent.project, sent.file_version, sent.filename),
        staged,
        content_type=_FILE,
        # A page says what each file requires, so that is kept with the file.
        attributes={_DECLARED: {"requires_python": sent.requires_python}},
        component_attributes={_DECLARED: release},
    )
    return Response(status_code=200, headers=_PROTECTIVE)


async def _file(context: RepositoryContext, request: Request, path: str) -> Response:
    if _is_read(request):
        return await context.respond(path, request)
    if request.method != "DELETE":
        # A file arrives in an upload form, with what it declares, never on its own.
        raise _not_allowed("GET, HEAD, DELETE")
    if not await context.delete(path):
        raise _not_found("No such file.")
    return Response(status_code=204)


def _canonical(parsed: names.PypiPath) -> Response | None:
    """The redirect to an index page's one address, or None if this is it.

    Links in a page are relative, so a page served at another spelling of its
    address would point nowhere.
    """
    if parsed.kind == "index":
        return None if parsed.slash else _redirect("simple/")
    project = names.normalise(parsed.project)
    if parsed.slash:
        return None if parsed.project == project else _redirect(f"../{project}/")
    return _redirect(f"{project}/")


# --- What a proxy serves -------------------------------------------------------------


def _page_address(member: RepositoryContext, project: str) -> str:
    """Where a proxy's cached page came from. Its links are resolved against this."""
    remote_url = member.repository.config["proxy"]["remote_url"]
    return member.format.remote_url(remote_url, names.page_path(project))


def _lines(reader: pages.Reader, chunk: bytes, project: str, written: set[str]) -> bytes:
    """The lines for the links in one piece of a remote's page that are not written yet."""
    lines = []
    for link in reader.feed(chunk):
        if link.filename not in written:
            written.add(link.filename)
            lines.append(pages.link_line(project, link))
    return b"".join(lines)


async def _written(
    context: RepositoryContext,
    request: Request,
    project: str,
    sources: Sequence[tuple[RepositoryContext, Stored]],
) -> Response:
    """A project's page written from proxies' cached pages, as it is sent.

    `sources` are the proxies that have the remote's page, in the order they are
    tried, each with what `stat` said of it. A file name two of them list is written
    once, from the earlier one. The pages are never held in memory.
    """
    made_from = "\n".join(stored.sha256 for _, stored in sources)
    etag = hashlib.sha256(f"pypi page 1\n{project}\n{made_from}".encode()).hexdigest()
    read_from = [(member, stored, _page_address(member, project)) for member, stored in sources]

    async def body() -> AsyncIterator[bytes]:
        written: set[str] = set()
        yield pages.head(f"Links for {project}")
        for member, stored, address in read_from:
            reader = pages.Reader(project, address)
            async for chunk in member.open(stored):
                lines = await off_loop(_lines, reader, chunk, project, written)
                if lines:
                    yield lines
        yield pages.foot()

    return await context.respond_stream(
        request,
        body,
        etag=etag,
        content_type=pages.CONTENT_TYPE,
        filename="index.html",
        last_modified=max(stored.modified for _, stored in sources),
    )


async def _proxied_page(context: RepositoryContext, request: Request, project: str) -> Response:
    page = names.page_path(project)
    await proxy.ensure_cached(context, page)
    stored = await context.stat(page)
    if stored is None:
        raise _not_found("No such project.")
    return await _written(context, request, project, [(context, stored)])


def _find(reader: pages.Reader, chunk: bytes, filename: str) -> pages.Link | None:
    return next((link for link in reader.feed(chunk) if link.filename == filename), None)


async def _link_to(context: RepositoryContext, parsed: names.PypiPath) -> pages.Link | None:
    """The link a proxy's remote has for a file, from its page, fetched if need be."""
    page = names.page_path(parsed.project)
    await proxy.ensure_cached(context, page)
    stored = await context.stat(page)
    if stored is None:
        return None
    await context.release()  # reading the page needs no connection
    reader = pages.Reader(parsed.project, _page_address(context, parsed.project))
    async for chunk in context.open(stored):
        link = await off_loop(_find, reader, chunk, parsed.filename)
        if link is not None:
            # A file has one address here: under the version in its name.
            return link if link.version == parsed.version else None
    return None


async def _proxied_file(
    context: RepositoryContext, request: Request, parsed: names.PypiPath, path: str
) -> Response:
    """A file, or the metadata file beside it, from the cache or from where the remote keeps it.

    A file on an index never changes once published, so one that is cached is never
    asked about again.
    """
    if await context.stat(path) is None:
        link = await _link_to(context, parsed)
        if link is None or (parsed.kind == "metadata" and link.metadata is None):
            raise _not_found("No such file.")
        if parsed.kind == "metadata":
            address, described = pages.metadata_address(link.url), link.metadata
        else:
            address, described = link.url, link.digest
        checked = pages.digest_of(described)
        source = proxy.Source(address, {} if checked is None else dict([checked]))
        await proxy.ensure_cached(context, path, source=source)
    return await context.respond(path, request)


class PypiFormat(Format):
    name = "pypi"
    # A group needs PyPI's own handling of index pages.
    types = frozenset({"hosted", "proxy"})

    def describe_component(self, path: str) -> ComponentKey | None:
        """A file belongs to its project and version. Nothing else is part of one."""
        parsed = names.classify(path)
        if parsed.kind != "file":
            return None
        return ComponentKey("", parsed.project, parsed.version)

    def content_type(self, path: str, declared: str | None) -> str | None:
        kind = names.classify(path).kind
        if kind == "file":
            return _FILE
        if kind == "metadata":
            return _METADATA
        return pages.CONTENT_TYPE if kind == "page" else declared

    def remote_url(self, base: str, path: str) -> str:
        """Where a proxy finds a project's page on its remote.

        The remote is an index's root, or the index itself if its address ends in
        `/simple` (or devpi's `/+simple`). Nothing but a page is found by its path: a
        file is fetched from the address its page gives.
        """
        base = base.rstrip("/")
        index = base if base.rpartition("/")[2] in ("simple", "+simple") else f"{base}/simple"
        parsed = names.classify(path)
        if parsed.kind == "page":
            return f"{index}/{parsed.project}/"
        return super().remote_url(base, path)

    def is_metadata(self, path: str) -> bool:
        """A project's page changes with every release. A file never changes."""
        return names.classify(path).kind == "page"

    async def handle_hosted(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        parsed = names.classify(path)
        if parsed.kind == "repository":
            if request.method != "POST":
                raise _not_allowed("POST")
            return await _upload(context, request)
        if parsed.kind in ("index", "page"):
            if not _is_read(request):
                raise _not_allowed("GET, HEAD")
            moved = _canonical(parsed)
            if moved is not None:
                return moved
            if parsed.kind == "index":
                return await _root_index(context, request)
            return await _project_page(context, request, parsed.project)
        if parsed.kind == "file":
            return await _file(context, request, path)
        raise _not_found()

    async def handle_proxy(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        parsed = names.classify(path)
        if not _is_read(request):
            raise _not_allowed("GET, HEAD")
        if parsed.kind in ("index", "page"):
            moved = _canonical(parsed)
            if moved is not None:
                return moved
            if parsed.kind == "index":
                return await _root_index(context, request)
            return await _proxied_page(context, request, parsed.project)
        if parsed.kind in ("file", "metadata"):
            return await _proxied_file(context, request, parsed, path)
        raise _not_found()


register(PypiFormat())
