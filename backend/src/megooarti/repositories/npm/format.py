"""The npm format: a registry that npm, pnpm and Yarn publish to and install from.

This is the only npm module that touches the repository context. What a path means,
whether a publish is acceptable and what a package document says come from the pure
functions beside it.

A package document is generated on each request from the versions stored, so it is
right after an unpublish and after two publishes at once. Reading a publish and
building a document are CPU-bound work whose size a client decides, so they run on two
worker threads of their own.

A proxy does not hold every version of a package, so it cannot write the document
itself. It serves the remote's, with the tarball links in it pointed here as it is sent.

A group answers for a package from its hosted members if one of them holds it, and
only otherwise from its proxies: a public package must never add versions to a private
name. That holds for the document and for the tarballs alike.
"""

import asyncio
import weakref
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import quote

import structlog
from starlette.requests import Request
from starlette.responses import Response

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories import group, proxy
from megooarti.repositories.content import RepositoryContext, TooLarge
from megooarti.repositories.formats import (
    ComponentKey,
    Format,
    Serve,
    managed_by_format,
    register,
)
from megooarti.repositories.npm import documents, paths, semver
from megooarti.repositories.npm.rewrite import TarballLinks
from megooarti.repositories.paths import normalise_path
from megooarti.security.authentication import unauthorized

log = structlog.get_logger(__name__)

# The most that is read into memory besides a publish: a sign-in or a tag, and the tags
# kept for a package.
SMALL_LIMIT = 16 * 1024
TAGS_LIMIT = 1024 * 1024
# The most that is parsed of proxies' documents, all together, to merge them.
MERGE_LIMIT = 16 * 1024 * 1024
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
# How many merges of proxies' documents may be in memory at once. Parsed, a document
# takes several times its size.
_MERGES_AT_ONCE = 2
_gates: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Semaphore]]" = (
    weakref.WeakKeyDictionary()
)

# Given the tags stored and the versions that exist, the tags to keep.
TagChange = Callable[[dict[str, str], set[str]], dict[str, str]]


async def off_loop[T](function: Callable[..., T], *arguments: Any) -> T:
    """Run document work in a worker thread, at most two at a time."""
    return await asyncio.get_running_loop().run_in_executor(_workers, function, *arguments)


def _gate(kind: str, most: int) -> asyncio.Semaphore:
    """One for each event loop, since a semaphore belongs to the loop that first waits on it."""
    gates = _gates.setdefault(asyncio.get_running_loop(), {})
    if kind not in gates:
        gates[kind] = asyncio.Semaphore(most)
    return gates[kind]


def publishing() -> asyncio.Semaphore:
    """The turn a publish takes: `async with publishing():` around reading and storing it."""
    return _gate("publish", _PUBLISHES_AT_ONCE)


def merging() -> asyncio.Semaphore:
    """The turn a merge takes: `async with merging():` around reading and merging."""
    return _gate("merge", _MERGES_AT_ONCE)


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


def _hosted_only() -> ApiError:
    """For what is answered from the versions stored, which only a hosted repository has."""
    return ApiError(
        405,
        "method_not_allowed",
        "Only a hosted repository answers at this address. Ask for the package itself.",
        headers={"Allow": ""},
    )


def _offline() -> ApiError:
    return ApiError(503, "repository_offline", "A repository that holds this package is offline.")


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


def _as_document(
    context: RepositoryContext, request: Request, package: str, rendered: documents.Rendered
) -> Response:
    """The answer to a request for a package document that was built for it."""
    return context.respond_with(
        rendered.data,
        request,
        filename=f"{paths.unscoped(package)}.json",
        content_type=_JSON,
        last_modified=rendered.modified,
        etag=rendered.etag,
    )


async def _document(
    context: RepositoryContext, request: Request, parsed: paths.NpmPath
) -> Response:
    found = await built(context, request, parsed.package)
    if found is None:
        raise _not_found()
    rendered = await off_loop(documents.render, parsed.package, *found)
    return _as_document(context, request, parsed.package, rendered)


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


async def _found(
    holders: Sequence[RepositoryContext], scope: str, name: str
) -> documents.Found | None:
    """What a search says about a package: what the first of `holders` to have it holds."""
    for holder in holders:
        held = await holder.versions(scope, name)
        if not held:
            continue
        newest = max(held, key=semver.sort_key)
        # Only the newest version's manifest is read: a package can have thousands.
        info = await holder.component(scope, name, newest)
        manifest = (info.attributes.get(_MANIFEST) if info is not None else None) or {}
        description = manifest.get("description")
        return documents.Found(
            name=f"@{scope}/{name}" if scope else name,
            version=newest,
            description=description if isinstance(description, str) else "",
            date=held[newest],
        )
    return None  # its last file was removed between the two questions


async def _search(
    context: RepositoryContext, request: Request, holders: Sequence[RepositoryContext]
) -> Response:
    """Packages that `holders` hold whose name or scope contains the text.

    `holders` is the repository itself, or for a group the repositories behind it.
    """

    def number(name: str, default: int, most: int) -> int:
        value = request.query_params.get(name, "")
        plain = value.isascii() and value.isdigit() and len(value) <= 9
        return min(int(value), most) if plain else default

    text = request.query_params.get("text", "").strip()[: paths.MAX_NAME_LENGTH]
    size = number("size", 20, _MAX_SEARCH_RESULTS)
    names, total = await context.package_names(
        text, limit=size, offset=number("from", 0, 10**9), within=holders
    )
    found = [await _found(holders, scope, name) for scope, name in names]
    listed = [entry for entry in found if entry is not None]
    return _answer(documents.search_results(listed, total, utcnow()))


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


# --- What a proxy serves -------------------------------------------------------------


async def _streamed(
    holder: RepositoryContext, request: Request, package: str, base: str
) -> Response:
    """A proxy's cached package document, its links pointed at `base` as it is sent.

    `base` is the public address of the repository that was asked. The document is
    never read into memory: such documents reach tens of megabytes.
    """
    return await holder.respond_transformed(
        package,
        request,
        TarballLinks(base, package),
        variant=f"tarball links to {base}",
        content_type=_JSON,
        filename=f"{paths.unscoped(package)}.json",
    )


# --- What a group serves -------------------------------------------------------------


async def _cached_by(members: Sequence[RepositoryContext], package: str) -> list[RepositoryContext]:
    """Those of `members` that have a package's document, fetching it where need be.

    A proxy that cannot answer is left out, never an error: the group answers from
    the others.
    """
    have = []
    for member in members:
        try:
            await proxy.ensure_cached(member, package)
        except ApiError as error:
            if error.status_code not in group.TRY_NEXT:
                raise
            continue
        have.append(member)
    return have


async def _several(
    context: RepositoryContext,
    request: Request,
    package: str,
    have: Sequence[RepositoryContext],
    base: str,
) -> Response:
    """Answer from the documents of several proxies, merged.

    This is the one place a remote's document is parsed, so they are read only up to
    a limit on their size together, and only two merges run at once. They are read in
    the members' order, and reading stops at the first that does not fit: a later
    member's document must not stand in for an earlier member's, whose tarballs are
    the ones served. One that is not a package document is left out. If fewer than two
    are left, one is served as it is.
    """
    await context.release()  # waiting for a turn needs no connection
    async with merging():
        read = []
        room = MERGE_LIMIT
        for member in have:
            stored = await member.stat(package)
            try:
                data = None if stored is None else await member.read(package, limit=room)
            except TooLarge:
                log.warning(
                    "document_too_large_to_merge",
                    repository=member.repository.name,
                    package=package,
                )
                break
            if data is not None:
                read.append((member, data, stored.modified))
                room -= len(data)
        await context.release()
        merged = await off_loop(
            documents.merge_remote, package, [data for _, data, _ in read], base
        )
    for position, (member, _, _) in enumerate(read):
        if position not in merged.used:
            log.warning("document_unreadable", repository=member.repository.name, package=package)
    used = [read[position] for position in merged.used]
    if merged.data is None:
        source = used[0][0] if used else have[0]
        return await _streamed(source, request, package, base)
    rendered = documents.Rendered(
        data=merged.data, etag=merged.etag, modified=max(modified for _, _, modified in used)
    )
    return _as_document(context, request, package, rendered)


async def _group_document(context: RepositoryContext, request: Request, package: str) -> Response:
    leaves = await group.leaves(context)
    owners, offline = await group.owners(leaves, *_coordinates(package))
    # The links name the group, so every download comes back through it.
    base = await context.public_url(request)
    if owners:
        held = [
            (await _versions(owner, package), await _stored_tags(owner, package))
            for owner in owners
        ]
        await context.release()  # the work that follows needs no connection
        rendered = await off_loop(documents.render, package, *documents.combine(held), base)
        if rendered is None:
            raise _not_found()  # its last version was removed between the two questions
        return _as_document(context, request, package, rendered)
    if offline:
        raise _offline()
    have = await _cached_by(group.proxies(leaves), package)
    if not have:
        raise _not_found()
    if len(have) == 1:
        return await _streamed(have[0], request, package, base)
    return await _several(context, request, package, have, base)


async def _group_tarball(
    context: RepositoryContext, request: Request, parsed: paths.NpmPath, serve: Serve
) -> Response:
    """A tarball, from the same members that answer for its package's document."""
    leaves = await group.leaves(context)
    owners, offline = await group.owners(leaves, *_coordinates(parsed.package))
    if not owners and offline:
        raise _offline()
    path = paths.tarball_path(parsed.package, parsed.version)
    for member in owners or group.proxies(leaves):
        try:
            return await serve(member, request, path)
        except ApiError as error:
            if error.status_code not in group.TRY_NEXT:
                raise
    raise _not_found("No such file.")


async def _group_search(context: RepositoryContext, request: Request) -> Response:
    members = [leaf.context for leaf in await group.leaves(context) if leaf.online]
    # A hosted member's word about a package comes first, as it does in its document.
    members.sort(key=lambda member: member.repository.type != "hosted")
    return await _search(context, request, members)


class NpmFormat(Format):
    name = "npm"

    async def delete_asset(self, context: RepositoryContext, path: str) -> bool:
        """A tarball goes as `npm unpublish <name>@<version>` removes it.

        Nothing else is deleted by itself.
        """
        parsed = paths.classify(path)
        if parsed.kind != "tarball":
            if await context.stat(path) is None:
                return False
            reason = "A package's dist-tags are the registry's. They go with its last version."
            raise managed_by_format(reason)
        if not await context.delete(path):
            return False
        # A tag that named the version moves to what is left, or goes with the last one.
        await _change_tags(context, parsed.package, documents.effective_tags)
        return True

    def describe_component(self, path: str) -> ComponentKey | None:
        """A tarball belongs to its package and version. Nothing else is part of one."""
        parsed = paths.classify(path)
        if parsed.kind != "tarball":
            return None
        return ComponentKey(parsed.scope, parsed.name, parsed.version)

    def content_type(self, path: str, declared: str | None) -> str | None:
        kind = paths.classify(path).kind
        if kind == "tarball":
            return _TARBALL
        return _JSON if kind == "document" else declared

    def remote_url(self, base: str, path: str) -> str:
        """Where a proxy finds a path on its remote.

        A scoped package's document is asked for as registries spell it, with the
        slash of its name encoded: `@scope%2Fname`.
        """
        parsed = paths.classify(path)
        if parsed.kind == "document" and parsed.scope:
            return f"{base.rstrip('/')}/@{parsed.scope}%2F{parsed.name}"
        return f"{base.rstrip('/')}/{quote(path, safe='/@')}"

    def is_metadata(self, path: str) -> bool:
        """A package document changes with every publish. A tarball never changes."""
        return paths.classify(path).kind == "document"

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
            return await _search(context, request, [context])
        raise _not_found("Nothing is served at this address.")

    async def handle_proxy(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        parsed = paths.classify(normalise_path(path))
        answered = await registry_endpoint(context, request, parsed)
        if answered is not None:
            return answered
        if not _is_read(request):
            raise _not_allowed("GET, HEAD")
        if parsed.kind == "document":
            await proxy.ensure_cached(context, parsed.package)
            base = await context.public_url(request)
            return await _streamed(context, request, parsed.package, base)
        if parsed.kind == "tarball":
            # Asked for under its one spelling, whatever revision the address carried.
            canonical = paths.tarball_path(parsed.package, parsed.version)
            return await proxy.handle_proxy(context, request, canonical)
        if parsed.kind == "search":
            return await _search(context, request, [context])
        if parsed.kind in ("version", "dist_tags"):
            raise _hosted_only()
        raise _not_found("Nothing is served at this address.")

    async def handle_group(
        self, context: RepositoryContext, request: Request, path: str, serve: Serve
    ) -> Response:
        parsed = paths.classify(normalise_path(path))
        answered = await registry_endpoint(context, request, parsed)
        if answered is not None:
            return answered
        if not _is_read(request):
            raise _not_allowed("GET, HEAD")
        if parsed.kind == "document":
            return await _group_document(context, request, parsed.package)
        if parsed.kind == "tarball":
            return await _group_tarball(context, request, parsed, serve)
        if parsed.kind == "search":
            return await _group_search(context, request)
        if parsed.kind in ("version", "dist_tags"):
            raise _hosted_only()
        raise _not_found("Nothing is served at this address.")


register(NpmFormat())
