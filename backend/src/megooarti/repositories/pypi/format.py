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

A group answers for a project from its hosted members if one of them holds it, and only
otherwise from its proxies: a public project must never add files to a private name.
That holds for the page and for the files alike.
"""

import asyncio
import hashlib
from collections.abc import AsyncIterator, Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from types import MappingProxyType
from typing import Any

from packaging.version import InvalidVersion, Version
from starlette.requests import Request
from starlette.responses import Response

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories import group, proxy
from megooarti.repositories.content import PackageFile, RepositoryContext, Stored
from megooarti.repositories.formats import (
    ComponentKey,
    Format,
    Serve,
    Usage,
    invalid_upload,
    only_fields,
    plain,
    register,
)
from megooarti.repositories.forms import UploadForm
from megooarti.repositories.pypi import names, pages, upload
from megooarti.repositories.versions import natural_key
from megooarti.storage.backends import StagedBlob

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


def _offline() -> ApiError:
    return ApiError(503, "repository_offline", "A repository that holds this project is offline.")


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


def _links(files: Sequence[PackageFile]) -> list[pages.Link]:
    """What a page says of the files a hosted repository holds."""
    return [
        pages.Link(
            filename=held.path.rpartition("/")[2],
            version=held.version,
            digest=f"sha256={held.sha256}",
            requires_python=(held.attributes.get(_DECLARED) or {}).get("requires_python"),
        )
        for held in files
    ]


async def _project_page(context: RepositoryContext, request: Request, project: str) -> Response:
    """A hosted project's page, from the files stored. `project` is in its normal form."""
    files = await context.package_files("", project)
    if not files:
        raise _not_found("No such project.")
    await context.release()  # writing the page needs no connection
    return _page(context, request, pages.project_page(project, _links(files)))


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
    await _keep(context, sent, staged)
    return Response(status_code=200, headers=_PROTECTIVE)


async def _keep(
    context: RepositoryContext,
    sent: upload.Declared,
    staged: StagedBlob,
    *,
    standing: dict[str, Any] | None = None,
) -> str:
    """Store a file with what was said about it. Returns where it is.

    `standing` is what the release already declares, for an upload that may say nothing:
    what it does not say then stays as it was.
    """
    release = {"name": sent.name, "version": sent.version, "summary": sent.summary}
    if sent.keywords:
        release["keywords"] = sent.keywords
    if standing:
        said = {key: release[key] for key in ("summary", "keywords") if release.get(key)}
        release = {**release, **standing, **said}
    # The path has the version in the file's name, not the one declared: a file name
    # then has one address in its project, and declaring another version cannot put a
    # second file of that name beside the first.
    path = names.file_path(sent.project, sent.file_version, sent.filename)
    # The facade checks `add` or `edit` and the deployment policy, under the path's lock.
    await context.store(
        path,
        staged,
        content_type=_FILE,
        # A page says what each file requires, so that is kept with the file.
        attributes={_DECLARED: {"requires_python": sent.requires_python}},
        component_attributes={_DECLARED: release},
    )
    return path


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
    etag = hashlib.sha256(f"pypi page 2\n{project}\n{made_from}".encode()).hexdigest()
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

    A file on an index does not change once published, so one that is cached is not
    asked about again, until the cache is invalidated. Then it is checked against
    the page once more: fetched again if the page describes another file, and kept
    if the remote no longer lists it or cannot be asked.
    """
    held = await context.stat(path)
    if held is None or held.verified is None:
        try:
            link = await _link_to(context, parsed)
        except ApiError as error:
            if held is None or error.status_code not in group.TRY_NEXT:
                raise
            link = None  # the remote cannot say: what is held is served
        if link is not None and parsed.kind == "metadata" and link.metadata is None:
            link = None
        if link is None and held is None:
            raise _not_found("No such file.")
        if link is not None:
            if parsed.kind == "metadata":
                address, described = pages.metadata_address(link.url), link.metadata
            else:
                address, described = link.url, link.digest
            checked = pages.digest_of(described)
            source = proxy.Source(address, {} if checked is None else dict([checked]))
            try:
                await proxy.ensure_cached(context, path, source=source)
            except ApiError as error:
                if held is None or error.status_code not in group.TRY_NEXT:
                    raise  # with nothing held there is nothing to fall back on
    return await context.respond(path, request)


# --- What a group serves -------------------------------------------------------------


async def _group_page(context: RepositoryContext, request: Request, project: str) -> Response:
    """A project's page from the repositories behind a group that answer for it."""
    leaves = await group.leaves(context)
    owners, offline = await group.owners(leaves, "", project)
    if owners:
        links: dict[str, pages.Link] = {}
        for owner in owners:
            for link in _links(await owner.package_files("", project)):
                links.setdefault(link.filename, link)  # the earlier repository's
        if not links:
            raise _not_found("No such project.")  # its last file went between the two questions
        await context.release()  # writing the page needs no connection
        return _page(context, request, pages.project_page(project, links.values()))
    if offline:
        raise _offline()

    page = names.page_path(project)
    sources = []
    for member in group.proxies(leaves):
        try:
            await proxy.ensure_cached(member, page)
        except ApiError as error:
            # A proxy that cannot answer is left out: the group answers from the others.
            if error.status_code not in group.TRY_NEXT:
                raise
            continue
        stored = await member.stat(page)
        if stored is not None:
            sources.append((member, stored))
    if not sources:
        raise _not_found("No such project.")
    return await _written(context, request, project, sources)


async def _group_file(
    context: RepositoryContext, request: Request, parsed: names.PypiPath, path: str, serve: Serve
) -> Response:
    """A file, from the same repositories that answer for its project's page."""
    leaves = await group.leaves(context)
    owners, offline = await group.owners(leaves, "", parsed.project)
    if not owners and offline:
        raise _offline()
    for member in owners or group.proxies(leaves):
        try:
            return await serve(member, request, path)
        except ApiError as error:
            if error.status_code not in group.TRY_NEXT:
                raise
    raise _not_found("No such file.")


def _pep440_key(text: str) -> tuple:
    """A version's place as pip orders them; text that is not a version before them all."""
    try:
        return (1, Version(text), text)
    except InvalidVersion:
        return (0, natural_key(text), text)


class PypiFormat(Format):
    name = "pypi"
    public_remotes = MappingProxyType({"": "https://pypi.org"})

    def search_text(self, key: ComponentKey, attributes: dict[str, Any]) -> str:
        """Its name and version, and the summary and keywords its upload declared."""
        declared = attributes.get(_DECLARED)
        declared = declared if isinstance(declared, dict) else {}
        said = [declared.get("summary"), declared.get("keywords")]
        words = [super().search_text(key, attributes)]
        return " ".join(words + [text for text in said if isinstance(text, str)])

    async def upload(self, context: RepositoryContext, form: UploadForm) -> list[str]:
        """Store wheels and source distributions as an upload by twine would.

        twine says which project and version a file is of. Here the file's name does,
        and what the form says besides is said of every file in it.
        """
        only_fields(form, ("summary", "requires_python", "keywords"))
        if not form.files:
            raise invalid_upload("file", "At least one wheel or source distribution is needed.")
        declared: list[upload.Declared] = []
        standing: list[dict[str, Any] | None] = []
        for file in form.files:
            if file.field != "file":
                raise invalid_upload(file.field, "A file is sent as `file`.")
            named = names.named(file.filename)
            if named is None:
                raise _invalid(
                    f"the name {file.filename} is not a wheel's or a source distribution's"
                )
            said = {**form.fields, ":action": "file_upload", "name": named[0], "version": named[1]}
            try:
                sent = upload.declared(said, file.filename, 1)
            except upload.InvalidUpload as error:
                raise _invalid(f"{file.filename}: {error}") from None
            if any(sent.filename == other.filename for other in declared):
                raise invalid_upload("file", f"Two files are named {file.filename}.")
            declared.append(sent)
            # twine repeats the summary and the keywords with every file. A form
            # mostly says neither, and must not erase them for a release that exists.
            held = await context.component("", sent.project, sent.file_version)
            known = None if held is None else held.attributes.get(_DECLARED)
            standing.append(known if isinstance(known, dict) else None)
        return [
            await _keep(context, sent, file.staged, standing=known)
            for sent, file, known in zip(declared, form.files, standing, strict=True)
        ]

    def ordered_versions(self, texts: Sequence[str]) -> list[str] | None:
        return sorted(set(texts), key=_pep440_key)

    def is_prerelease(self, version: str) -> bool:
        try:
            return Version(version).is_prerelease
        except InvalidVersion:
            return False

    def usage(self, address: str, key: ComponentKey, files: Sequence[str]) -> list[Usage]:
        if not plain(key.name, key.version):
            return []
        command = f"pip install --index-url {address}simple/ {key.name}=={key.version}"
        return [Usage("pip", "shell", command)]

    def describe_component(
        self, path: str, attributes: dict[str, Any] | None = None
    ) -> ComponentKey | None:
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

    async def handle_group(
        self, context: RepositoryContext, request: Request, path: str, serve: Serve
    ) -> Response:
        parsed = names.classify(path)
        if not _is_read(request):
            raise _not_allowed("GET, HEAD")
        if parsed.kind in ("index", "page"):
            moved = _canonical(parsed)
            if moved is not None:
                return moved
            if parsed.kind == "page":
                return await _group_page(context, request, parsed.project)
            online = [leaf.context for leaf in await group.leaves(context) if leaf.online]
            return await _root_index(context, request, online)
        if parsed.kind in ("file", "metadata"):
            return await _group_file(context, request, parsed, path, serve)
        raise _not_found()


register(PypiFormat())
