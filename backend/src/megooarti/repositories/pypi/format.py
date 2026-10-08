"""The PyPI format: an index that twine uploads to and pip, uv and Poetry install from.

This is the only PyPI module that touches the repository context. What a path means,
whether an upload is acceptable and what a page says come from the pure functions
beside it.

A project's page is generated on each request from the files stored, so it is right
after a delete and after two uploads at once. An upload goes to the blob store as it
arrives: it is never held in memory.
"""

import hashlib
from collections.abc import AsyncIterator

from starlette.requests import Request
from starlette.responses import Response

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.formats import ComponentKey, Format, register
from megooarti.repositories.pypi import names, pages, upload

_FILE = "application/octet-stream"
# Where what an upload declares is kept among its component's attributes.
_DECLARED = "pypi"
# The most projects a root index lists. Installers never ask for it.
ROOT_LIMIT = 100_000
_PROTECTIVE = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"}


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


async def _root_index(context: RepositoryContext, request: Request) -> Response:
    found, _ = await context.package_names("", limit=ROOT_LIMIT, offset=0)
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


class PypiFormat(Format):
    name = "pypi"
    # Proxy and group repositories need PyPI's own handling of index pages.
    types = frozenset({"hosted"})

    def describe_component(self, path: str) -> ComponentKey | None:
        """A file belongs to its project and version. Nothing else is part of one."""
        parsed = names.classify(path)
        if parsed.kind != "file":
            return None
        return ComponentKey("", parsed.project, parsed.version)

    def content_type(self, path: str, declared: str | None) -> str | None:
        return _FILE if names.classify(path).kind == "file" else declared

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


register(PypiFormat())
