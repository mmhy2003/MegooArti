"""The npm format: a registry that npm, pnpm and Yarn publish to and install from.

This is the only npm module that touches the repository context. What a path means,
whether a publish is acceptable and what a package document says come from the pure
functions beside it.

A package document is generated on each request from the versions stored, so it is
right after an unpublish and after two publishes at once. Reading a publish and
building a document are CPU-bound work whose size a client decides, so they run on two
worker threads of their own.
"""

import asyncio
import weakref
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories.content import RepositoryContext, TooLarge
from megooarti.repositories.formats import ComponentKey, Format, register
from megooarti.repositories.npm import documents, paths, semver
from megooarti.repositories.paths import normalise_path
from megooarti.security.authentication import unauthorized

# The most that is read into memory besides a publish: a sign-in or a tag, and the tags
# kept for a package.
SMALL_LIMIT = 16 * 1024
TAGS_LIMIT = 1024 * 1024
_JSON = "application/json"
_TARBALL = "application/octet-stream"
# Where a version's manifest is kept among its component's attributes.
_MANIFEST = "npm"
_MAX_SEARCH_RESULTS = 250
# Not the default executor: that one also reads and writes blobs and checks passwords.
_workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="npm-documents")

# How many publishes may be in memory at once. Each can be as large as the limit, and
# stays that large from the first byte read until its tarballs are stored.
_PUBLISHES_AT_ONCE = 2
_gates: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
    weakref.WeakKeyDictionary()
)

# Given the tags stored and the versions that exist, the tags to keep.
TagChange = Callable[[dict[str, str], set[str]], dict[str, str]]


async def off_loop[T](function: Callable[..., T], *arguments: Any) -> T:
    """Run document work in a worker thread, at most two at a time."""
    return await asyncio.get_running_loop().run_in_executor(_workers, function, *arguments)


def publishing() -> asyncio.Semaphore:
    """The turn a publish takes: `async with publishing():` around reading and storing it.

    One for each event loop, since a semaphore belongs to the loop that first waits on it.
    """
    loop = asyncio.get_running_loop()
    gate = _gates.get(loop)
    if gate is None:
        gate = _gates[loop] = asyncio.Semaphore(_PUBLISHES_AT_ONCE)
    return gate


def _answer(value: Any, status: int = 200) -> Response:
    """A small JSON answer. Like all content here, it is never to be rendered."""
    headers = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"}
    return Response(
        content=documents.dumps(value), status_code=status, media_type=_JSON, headers=headers
    )


def _not_found(message: str = "No such package.") -> ApiError:
    return ApiError(404, "not_found", message)


def _not_allowed(allowed: str) -> ApiError:
    return ApiError(
        405,
        "method_not_allowed",
        f"This address accepts {allowed}.",
        headers={"Allow": allowed},
    )


def _invalid(reason: object) -> ApiError:
    return ApiError(400, "invalid_package", f"The request cannot be accepted: {reason}.")


def _mismatch(check: object) -> ApiError:
    return ApiError(
        400, "checksum_mismatch", f"The tarball is not the one its manifest describes ({check})."
    )


async def _json_body(context: RepositoryContext, request: Request, limit: int) -> Any:
    """A small JSON body, read into memory."""
    raw = await context.receive(request.stream(), limit=limit)
    if raw is None:
        raise ApiError(413, "payload_too_large", "The request is larger than this address takes.")
    try:
        return documents.loads(raw)
    except documents.InvalidPackage as error:
        raise _invalid(error) from None


def _is_read(request: Request) -> bool:
    return request.method in ("GET", "HEAD")


# --- Signing in, and the registry's small endpoints ---------------------------------


async def _sign_in(context: RepositoryContext, request: Request, parsed: paths.NpmPath) -> Response:
    """`npm login`: a user name and a password in, a token out.

    This is the one request that may arrive without credentials, because it carries
    them in its body. It must not use `context.principal`.
    """
    if request.method != "PUT":
        raise _not_allowed("PUT")
    body = await _json_body(context, request, SMALL_LIMIT)
    name = body.get("name") if isinstance(body, dict) else None
    password = body.get("password") if isinstance(body, dict) else None
    if not isinstance(name, str) or not isinstance(password, str) or name != parsed.username:
        raise _invalid("it must carry the user name in the address, and a password")
    token = await context.issue_token(request, name, password, label="npm login")
    return _answer({"ok": True, "id": f"org.couchdb.user:{name}", "token": token}, 201)


async def _sign_out(
    context: RepositoryContext, request: Request, parsed: paths.NpmPath
) -> Response:
    if request.method != "DELETE":
        raise _not_allowed("DELETE")
    await context.revoke_token(parsed.token)
    return _answer({"ok": True})


def _who(context: RepositoryContext, request: Request) -> Response:
    if not _is_read(request):
        raise _not_allowed("GET, HEAD")
    if context.principal is None or context.principal.is_anonymous:
        raise unauthorized(scheme="Basic")
    return _answer({"username": context.principal.user.username})


async def registry_endpoint(
    context: RepositoryContext, request: Request, parsed: paths.NpmPath
) -> Response | None:
    """Answer for an endpoint every repository type has, or None if `parsed` is not one."""
    if parsed.kind == "login":
        return await _sign_in(context, request, parsed)
    if parsed.kind == "logout":
        return await _sign_out(context, request, parsed)
    if parsed.kind == "whoami":
        return _who(context, request)
    if parsed.kind == "ping":
        if not _is_read(request):
            raise _not_allowed("GET, HEAD")
        return _answer({})
    return None


# --- What a hosted repository holds --------------------------------------------------


def _coordinates(package: str) -> tuple[str, str]:
    """A package's namespace and name, as its components are keyed."""
    return paths.scope_of(package), paths.unscoped(package)


async def _versions(context: RepositoryContext, package: str) -> list[documents.Version]:
    """The versions of a package that are stored, each with its manifest."""
    held = await context.components(*_coordinates(package))
    return [
        documents.Version(
            version=info.version,
            manifest=info.attributes.get(_MANIFEST) or {"name": package, "version": info.version},
            created=info.created,
            modified=info.modified,
        )
        for info in held
    ]


def _read_tags(raw: bytes | None) -> dict[str, str]:
    """The dist-tags in a stored document. Anything unreadable counts as none."""
    if raw is None:
        return {}
    try:
        stored = documents.loads(raw)
    except documents.InvalidPackage:
        return {}
    if not isinstance(stored, dict):
        return {}
    return {tag: version for tag, version in stored.items() if isinstance(version, str)}


async def _stored_tags(context: RepositoryContext, package: str) -> dict[str, str]:
    try:
        return _read_tags(await context.read(paths.dist_tags_path(package), limit=TAGS_LIMIT))
    except TooLarge:
        return {}


async def _change_tags(context: RepositoryContext, package: str, change: TagChange) -> None:
    """Change a package's dist-tags under their lock.

    The versions are read inside the lock, so a tag is judged against what exists once
    every earlier change has been committed.
    """

    async def update(current: bytes | None) -> bytes | None:
        held = await context.versions(*_coordinates(package))
        kept = change(_read_tags(current), set(held))
        if len(kept) > documents.MAX_TAGS:
            raise _invalid(f"a package has at most {documents.MAX_TAGS} dist-tags")
        return documents.dumps(kept) if kept else None

    await context.maintain(
        paths.dist_tags_path(package), update, content_type=_JSON, limit=TAGS_LIMIT
    )


async def built(
    context: RepositoryContext, request: Request, package: str
) -> tuple[list[documents.Version], dict[str, str], str] | None:
    """What a hosted package's document is made of, or None if it has no version."""
    versions = await _versions(context, package)
    if not versions:
        return None
    tags = await _stored_tags(context, package)
    base = await context.public_url(request)
    await context.release()  # the work that follows needs no connection
    return versions, tags, base


# --- Reading -------------------------------------------------------------------------


async def _document(
    context: RepositoryContext, request: Request, parsed: paths.NpmPath
) -> Response:
    found = await built(context, request, parsed.package)
    if found is None:
        raise _not_found()
    rendered = await off_loop(documents.render, parsed.package, *found)
    return context.respond_with(
        rendered.data,
        request,
        filename=f"{parsed.name}.json",
        content_type=_JSON,
        last_modified=rendered.modified,
        etag=rendered.etag,
    )


async def _manifest(
    context: RepositoryContext, request: Request, parsed: paths.NpmPath
) -> Response:
    found = await built(context, request, parsed.package)
    if found is None:
        raise _not_found()
    document = await off_loop(documents.document, parsed.package, *found)
    manifest = documents.manifest_of(document, parsed.version)
    if manifest is None:
        raise _not_found("No such version.")
    return _answer(manifest)


async def _search(context: RepositoryContext, request: Request) -> Response:
    """Packages this repository holds whose name or scope contains the text."""

    def number(name: str, default: int, most: int) -> int:
        value = request.query_params.get(name, "")
        plain = value.isascii() and value.isdigit() and len(value) <= 9
        return min(int(value), most) if plain else default

    text = request.query_params.get("text", "").strip()[: paths.MAX_NAME_LENGTH]
    size = number("size", 20, _MAX_SEARCH_RESULTS)
    names, total = await context.package_names(text, limit=size, offset=number("from", 0, 10**9))
    found = []
    for scope, name in names:
        held = await context.versions(scope, name)
        if not held:
            continue  # its last file was removed between the two questions
        newest = max(held, key=semver.sort_key)
        # Only the newest version's manifest is read: a package can have thousands.
        info = await context.component(scope, name, newest)
        manifest = (info.attributes.get(_MANIFEST) if info is not None else None) or {}
        description = manifest.get("description")
        found.append(
            documents.Found(
                name=f"@{scope}/{name}" if scope else name,
                version=newest,
                description=description if isinstance(description, str) else "",
                date=held[newest],
            )
        )
    return _answer(documents.search_results(found, total, utcnow()))


# --- Changing ------------------------------------------------------------------------


async def _publish(context: RepositoryContext, package: str, upload: documents.Upload) -> Response:
    """Store the versions a publish carries: every tarball first, then the records."""
    staged = []
    try:
        for release in upload.releases:
            blob = await context.stage_bytes(release.data)
            staged.append((release, blob))
            documents.verify(
                release.manifest, sha1=blob.sha1, sha256=blob.sha256, sha512=blob.sha512
            )
        held = await context.versions(*_coordinates(package))
        if not held and package != package.lower():
            raise _invalid("the name of a new package must be in lower case")
    except BaseException as error:
        for _, blob in staged:
            await context.discard(blob)
        if isinstance(error, documents.ChecksumMismatch):
            raise _mismatch(error) from None
        raise

    for position, (release, blob) in enumerate(staged):
        manifest = documents.stored_manifest(release.manifest, sha1=blob.sha1, sha512=blob.sha512)
        try:
            # The facade checks `add` or `edit` and the deployment policy for each file.
            await context.store(
                paths.tarball_path(package, release.version),
                blob,
                content_type=_TARBALL,
                component_attributes={_MANIFEST: manifest},
            )
        except BaseException:
            for _, later in staged[position + 1 :]:
                await context.discard(later)
            raise

    published = {release.version for release in upload.releases}
    await _change_tags(
        context,
        package,
        lambda stored, versions: documents.merge_tags(
            stored, upload.tags, versions - published, versions
        ),
    )
    return _answer({"ok": True, "id": package, "rev": "1-0"}, 201)


async def _update(
    context: RepositoryContext, request: Request, package: str, upload: documents.Upload
) -> Response:
    """Apply a document sent back without attachments: `npm deprecate` and `npm unpublish`.

    The client read the document, changed it and sent all of it back. Acting on it is
    only right if nothing changed in between: otherwise a version published meanwhile
    is missing from what was sent, and would be removed.
    """
    scope, name = _coordinates(package)
    found = await built(context, request, package)
    if found is None:
        raise _not_found()
    versions, stored_tags, base = found
    held = {version.version: version.manifest for version in versions}
    try:
        plan = documents.update_plan(held, upload.document)
    except documents.InvalidPackage as error:
        raise _invalid(error) from None
    tags = upload.tags
    answer = _answer({"ok": True, "id": package, "rev": "1-0"})
    if not plan.deprecations and not plan.removals and tags is None:
        return answer

    current = await off_loop(documents.document, package, versions, stored_tags, base)
    if upload.document.get("_rev") != current["_rev"]:
        raise ApiError(
            409,
            "conflict",
            "The package has changed since it was read. Read it again and repeat the change.",
        )

    for version, message in plan.deprecations.items():  # needs `edit`
        changed = documents.deprecated(held[version], message)
        await context.annotate(scope, name, version, {_MANIFEST: changed})
    for version in plan.removals:  # needs `delete`
        await context.delete(paths.tarball_path(package, version))
    if tags is not None:
        await _change_tags(
            context, package, lambda _, existing: documents.effective_tags(tags, existing)
        )
    elif plan.removals:
        await _change_tags(context, package, documents.effective_tags)
    return answer


async def _write_document(
    context: RepositoryContext, request: Request, parsed: paths.NpmPath
) -> Response:
    """A document sent to a package's address: a publish, or an update."""
    # Refused before the body is read; the facade checks each operation again.
    context.require_write()
    limit = context.settings.npm_max_publish_bytes
    too_large = ApiError(413, "payload_too_large", "The package is larger than this server takes.")
    declared = request.headers.get("Content-Length", "")
    if declared.isascii() and declared.isdigit() and (len(declared) > 18 or int(declared) > limit):
        raise too_large
    await context.release()  # waiting for a turn needs no connection
    async with publishing():
        raw = await context.receive(request.stream(), limit=limit)
        if raw is None:
            raise too_large
        try:
            upload = await off_loop(documents.read_upload, parsed.package, raw)
        except documents.InvalidPackage as error:
            raise _invalid(error) from None
        except documents.ChecksumMismatch as error:
            raise _mismatch(error) from None
        del raw  # what is needed from it has been decoded
        if upload.releases:
            return await _publish(context, parsed.package, upload)
        return await _update(context, request, parsed.package, upload)


async def _unpublish(context: RepositoryContext, parsed: paths.NpmPath) -> Response:
    """Remove every version of a package, and its dist-tags."""
    package = parsed.package
    await context.delete(paths.dist_tags_path(package))  # checks `delete` before anything
    held = await context.components(*_coordinates(package))
    if not held:
        raise _not_found()
    for info in held:
        await context.delete(paths.tarball_path(package, info.version))
    return _answer({"ok": True})


async def _tarball(context: RepositoryContext, request: Request, parsed: paths.NpmPath) -> Response:
    path = paths.tarball_path(parsed.package, parsed.version)
    if _is_read(request):
        return await context.respond(path, request)
    if request.method != "DELETE":
        # A tarball arrives inside a publish, with its manifest, never on its own.
        raise _not_allowed("GET, HEAD, DELETE")
    # npm removes the version from the document first and then deletes the tarball, so
    # by now it may be gone. That is still what was asked for.
    await context.delete(path)
    return _answer({"ok": True})


async def _dist_tags(
    context: RepositoryContext, request: Request, parsed: paths.NpmPath
) -> Response:
    package, tag = parsed.package, parsed.tag
    if _is_read(request) and not tag:
        versions = set(await context.versions(*_coordinates(package)))
        if not versions:
            raise _not_found()
        return _answer(documents.effective_tags(await _stored_tags(context, package), versions))
    if request.method == "PUT" and tag:
        context.require_write()
        version = await _json_body(context, request, SMALL_LIMIT)
        if not isinstance(version, str) or not documents.is_valid_tag(tag):
            raise _invalid("a dist-tag is set by sending a version as a JSON string")
        if version not in await context.versions(*_coordinates(package)):
            raise _not_found("No such version.")
        await _change_tags(
            context,
            package,
            lambda stored, held: documents.merge_tags(stored, {tag: version}, held, held),
        )
        return _answer({"ok": True})
    if request.method == "DELETE" and tag:
        if tag == "latest":
            raise _invalid("the latest tag cannot be removed, only moved")
        await _change_tags(
            context,
            package,
            lambda stored, held: documents.effective_tags(
                {name: version for name, version in stored.items() if name != tag}, held
            ),
        )
        return _answer({"ok": True})
    raise _not_allowed("GET, HEAD" if not tag else "PUT, DELETE")


class NpmFormat(Format):
    name = "npm"
    # Proxy and group repositories need npm's own handling of package documents.
    types = frozenset({"hosted"})

    def describe_component(self, path: str) -> ComponentKey | None:
        """A tarball belongs to its package and version. Nothing else is part of one."""
        parsed = paths.classify(path)
        if parsed.kind != "tarball":
            return None
        return ComponentKey(parsed.scope, parsed.name, parsed.version)

    def content_type(self, path: str, declared: str | None) -> str | None:
        return _TARBALL if paths.classify(path).kind == "tarball" else declared

    def takes_body_credentials(self, method: str, path: str) -> bool:
        """`npm login` sends the user name and password in its body, with no header."""
        return method == "PUT" and paths.classify(path).kind == "login"

    async def handle_hosted(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        parsed = paths.classify(normalise_path(path))
        answered = await registry_endpoint(context, request, parsed)
        if answered is not None:
            return answered
        if parsed.kind == "document":
            if _is_read(request):
                return await _document(context, request, parsed)
            if request.method == "PUT":
                return await _write_document(context, request, parsed)
            if request.method == "DELETE":
                return await _unpublish(context, parsed)
            raise _not_allowed("GET, HEAD, PUT, DELETE")
        if parsed.kind == "version":
            if not _is_read(request):
                raise _not_allowed("GET, HEAD")
            return await _manifest(context, request, parsed)
        if parsed.kind == "tarball":
            return await _tarball(context, request, parsed)
        if parsed.kind == "dist_tags":
            return await _dist_tags(context, request, parsed)
        if parsed.kind == "search":
            if not _is_read(request):
                raise _not_allowed("GET, HEAD")
            return await _search(context, request)
        raise _not_found("Nothing is served at this address.")


register(NpmFormat())
