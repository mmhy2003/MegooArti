"""The Docker format: a registry that Docker, Podman and containerd push to and pull from.

This is the only Docker module that touches the repository context. What a path means
and what a manifest refers to come from the pure functions beside it. Repositories of
this format are served by the registry API at `/v2/`, not under `/repository/`.

How an image is kept:

- A layer or an image configuration is a blob, stored once for the repository at
  `blobs/<digest>` and shared by every image in it.
- A manifest is stored at `manifests/<image>/<digest>`, with the blobs and manifests
  it refers to recorded beside it.
- A tag is a file at `tags/<image>/<tag>` that holds the manifest it names, so the
  stored file's own hash is the digest a client asks for, and the deployment policy
  applies to a tag as to any path.

Deleting a manifest removes what only it used. Pushing a manifest and deleting one take
the same lock, so a push never ends up referring to a blob a delete has just removed.

A proxy keeps what it fetches in the same layout. A manifest is read before it is kept,
so what is stored is a manifest, is the one that was asked for, and records what it
refers to. A tag is asked about again when it is old, and only asked about: the remote
says which manifest the tag names, and that is fetched only if it is another one.

A group answers for an image from the hosted repositories behind it if one of them has
the image, and only otherwise from its proxies: an image on a public registry must not
stand in for one that was pushed here, nor add tags to it. A repository has an image
while it holds a manifest of it, tagged or not; to make that one lookup, a manifest is
a component too, in a namespace apart from the tags.
"""

import json
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories import group, proxy, uploads
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.docker import manifests, names
from megooarti.repositories.docker.errors import RegistryError, unknown
from megooarti.repositories.formats import (
    ComponentKey,
    Format,
    Serve,
    managed_by_format,
    register,
)
from megooarti.storage.backends import StagedBlob

FORMAT = "docker"
_BLOB = "application/octet-stream"
# What serialises every change to which blobs a repository's manifests refer to.
_REFERENCES = "references"
# A blob no manifest refers to is removed once it has been here this long: a push that
# stopped half-way, or a layer of an image that never arrived.
UNUSED_BLOB_SECONDS = 86400
_SWEEP_AT_ONCE = 1000
_CATALOG_MOST = 10_000
_TAGS_DEFAULT = 1000


def _not_allowed(allowed: str) -> RegistryError:
    return RegistryError(
        405, "UNSUPPORTED", f"This address accepts {allowed}.", headers={"Allow": allowed}
    )


def _digest_invalid(message: str = "Only a lower-case SHA-256 digest is taken.") -> RegistryError:
    return RegistryError(400, "DIGEST_INVALID", message)


def _is_read(request: Request) -> bool:
    return request.method in ("GET", "HEAD")


def _address(context: RepositoryContext, image: str, rest: str) -> str:
    """An address under the registry API. Relative: a registry is always at a host's root."""
    return f"/v2/{context.repository.name}/{image}/{rest}"


# --- Blobs ---------------------------------------------------------------------------


async def _blob(context: RepositoryContext, request: Request, parsed: names.DockerPath) -> Response:
    if not _is_read(request):
        # Layers go with the images that use them, not one by one.
        raise _not_allowed("GET, HEAD")
    try:
        response = await context.respond(names.blob_path(parsed.reference), request)
    except ApiError as error:
        if error.status_code != 404:
            raise
        raise unknown("BLOB_UNKNOWN", "No such blob.") from None
    response.headers["Docker-Content-Digest"] = parsed.reference
    return response


async def _keep(context: RepositoryContext, digest: str, staged: StagedBlob) -> None:
    """Store staged content as the blob it claims to be, unless it is here already.

    Raises DIGEST_INVALID, having discarded the content, if it is not that blob.
    """
    if staged.sha256 != names.hex_of(digest):
        await context.discard(staged)
        raise _digest_invalid("The content is not what the digest says.")
    # Two pushes of one layer may finish together. The second finds it stored.
    await context.lock(f"blob {digest}")
    if await context.stat(names.blob_path(digest)) is not None:
        await context.discard(staged)
        return
    await context.store(names.blob_path(digest), staged, content_type=_BLOB)


def _created(context: RepositoryContext, image: str, digest: str) -> Response:
    headers = {
        "Location": _address(context, image, f"blobs/{digest}"),
        "Docker-Content-Digest": digest,
    }
    return Response(status_code=201, headers=headers)


def _progress(
    context: RepositoryContext, image: str, upload: str, size: int, status: int
) -> Response:
    """What a client is told about an upload: where it is, and how much has arrived."""
    headers = {
        "Location": _address(context, image, f"blobs/uploads/{upload}"),
        "Range": f"0-{max(size - 1, 0)}",
        "Docker-Upload-UUID": upload,
    }
    return Response(status_code=status, headers=headers)


def _wanted_digest(request: Request) -> str | None:
    digest = request.query_params.get("digest")
    if digest is not None and not names.is_digest(digest):
        raise _digest_invalid()
    return digest


async def _start_upload(
    context: RepositoryContext, request: Request, parsed: names.DockerPath
) -> Response:
    if request.method != "POST":
        raise _not_allowed("POST")
    context.require_write()
    mounted = request.query_params.get("mount")
    if mounted is not None and names.is_digest(mounted):
        # Every image of a repository shares its blobs, so one that is here is mounted.
        if await context.stat(names.blob_path(mounted)) is not None:
            return _created(context, parsed.image, mounted)
    digest = _wanted_digest(request)
    if digest is not None:
        # The whole blob in this one request.
        await context.release()  # the body needs no connection
        staged = await context.stage(request.stream())
        await _keep(context, digest, staged)
        return _created(context, parsed.image, digest)
    upload = await uploads.begin(context, parsed.image)
    return _progress(context, parsed.image, upload, 0, 202)


def _chunk_start(request: Request) -> int | None:
    """Where the client says its chunk starts, from `Content-Range: <start>-<end>`."""
    stated = request.headers.get("Content-Range")
    if stated is None:
        return None
    start = stated.removeprefix("bytes").strip().partition("-")[0]
    if not (start.isascii() and start.isdigit() and len(start) <= 18):
        raise RegistryError(400, "BLOB_UPLOAD_INVALID", "The Content-Range cannot be read.")
    return int(start)


async def _upload(
    context: RepositoryContext, request: Request, parsed: names.DockerPath
) -> Response:
    image, upload = parsed.image, parsed.reference
    try:
        if request.method == "GET":
            found = await uploads.progress(context, upload, image)
            return _progress(context, image, upload, found.size, 204)
        if request.method == "DELETE":
            await uploads.abandon(context, upload, image)
            return Response(status_code=204)
        if request.method == "PATCH":
            size = await uploads.append(
                context, upload, image, request.stream(), at=_chunk_start(request)
            )
            return _progress(context, image, upload, size, 202)
        if request.method == "PUT":
            digest = _wanted_digest(request)
            if digest is None:
                raise _digest_invalid("Completing an upload needs the digest of its content.")
            await uploads.append(context, upload, image, request.stream())  # often empty
            staged = await uploads.complete(context, upload, image)
            await _keep(context, digest, staged)
            return _created(context, image, digest)
    except uploads.UnknownUpload:
        raise unknown("BLOB_UPLOAD_UNKNOWN", "No such upload in progress.") from None
    except uploads.TooManyChunks:
        raise RegistryError(
            400, "BLOB_UPLOAD_INVALID", "The upload is in too many chunks. Send larger ones."
        ) from None
    except uploads.OutOfOrder as error:
        raise RegistryError(
            416,
            "BLOB_UPLOAD_INVALID",
            "The chunk does not start where the upload ends.",
            headers={"Range": f"0-{max(error.size - 1, 0)}"},
        ) from None
    raise _not_allowed("GET, PATCH, PUT, DELETE")


# --- Manifests -----------------------------------------------------------------------


def _stored_path(image: str, reference: str) -> str:
    if names.is_digest(reference):
        return names.manifest_path(image, reference)
    return names.tag_path(image, reference)


async def _read_manifest(
    context: RepositoryContext, request: Request, parsed: names.DockerPath
) -> Response:
    path = _stored_path(parsed.image, parsed.reference)
    stored = await context.stat(path)
    if stored is None:
        raise unknown("MANIFEST_UNKNOWN", "No such manifest.")
    response = await context.respond(path, request)
    response.headers["Docker-Content-Digest"] = f"sha256:{stored.sha256}"
    return response


async def _push_manifest(
    context: RepositoryContext, request: Request, parsed: names.DockerPath
) -> Response:
    image, reference = parsed.image, parsed.reference
    # Refused before the body is read; the facade checks each file again.
    context.require_write()
    raw = await context.receive(request.stream(), limit=manifests.MAX_BYTES)
    try:
        if raw is None:
            raise manifests.InvalidManifest("it is larger than 4 MiB")
        manifest = manifests.read(raw, request.headers.get("Content-Type"))
    except manifests.InvalidManifest as error:
        message = f"The manifest cannot be taken: {error}."
        raise RegistryError(400, "MANIFEST_INVALID", message) from None
    if names.is_digest(reference) and reference != manifest.digest:
        raise _digest_invalid("The manifest is not what the digest in its address says.")

    await context.lock(_REFERENCES)
    needed = [names.blob_path(digest) for digest in manifest.blobs]
    needed += [names.manifest_path(image, digest) for digest in manifest.manifests]
    missing = sorted(set(needed) - await context.present(needed))
    if missing:
        raise RegistryError(
            400,
            "MANIFEST_BLOB_UNKNOWN",
            "The manifest refers to something that has not been pushed.",
            detail=[path.rpartition("/")[2] for path in missing],
        )

    by_digest = names.manifest_path(image, manifest.digest)
    if await context.stat(by_digest) is None:
        staged = await context.stage_bytes(raw)
        await context.store(by_digest, staged, content_type=manifest.media_type, references=needed)
    if not names.is_digest(reference):
        tag = names.tag_path(image, reference)
        held = await context.stat(tag)
        # Pushing a tag again with what it already names changes nothing, whatever the
        # deployment policy and whatever the caller may do.
        if held is None or held.sha256 != names.hex_of(manifest.digest):
            staged = await context.stage_bytes(raw)
            try:
                await context.store(tag, staged, content_type=manifest.media_type)
            except ApiError as error:
                if error.code != "redeploy_disabled":
                    raise
                message = "The tag exists, and this repository does not let a tag be moved."
                raise RegistryError(409, "DENIED", message) from None
    headers = {
        "Location": _address(context, image, f"manifests/{manifest.digest}"),
        "Docker-Content-Digest": manifest.digest,
    }
    return Response(status_code=201, headers=headers)


async def _tags_naming(context: RepositoryContext, image: str, digest: str) -> list[str]:
    """The stored paths of the tags of an image that name a manifest."""
    wanted = names.hex_of(digest)
    held = await context.package_files("", image)
    return [file.path for file in held if file.sha256 == wanted]


async def _drop(context: RepositoryContext, image: str, digest: str) -> bool:
    """Remove a manifest, its tags, and what only it used. False if it was not there."""
    path = names.manifest_path(image, digest)
    referred = await context.references(path)
    if not await context.delete(path):  # the facade checks `delete`
        return False
    for tag in await _tags_naming(context, image, digest):
        await context.delete(tag)
    still_used = await context.referenced(referred)
    for target in referred:
        if target in still_used:
            continue
        if target.startswith("blobs/"):
            await context.delete(target)
            continue
        # A platform's manifest. It goes too, unless it has a tag of its own.
        platform = target.rpartition("/")[2]
        if not await _tags_naming(context, image, platform):
            await _drop(context, image, platform)
    return True


async def _delete_manifest(context: RepositoryContext, parsed: names.DockerPath) -> Response:
    image, reference = parsed.image, parsed.reference
    if names.is_digest(reference):
        await context.lock(_REFERENCES)
        removed = await _drop(context, image, reference)
    else:
        # A tag goes alone: what it named may be pinned by its digest.
        removed = await context.delete(names.tag_path(image, reference))
    if not removed:
        raise unknown("MANIFEST_UNKNOWN", "No such manifest.")
    return Response(status_code=202)


async def _manifest(
    context: RepositoryContext, request: Request, parsed: names.DockerPath
) -> Response:
    if _is_read(request):
        return await _read_manifest(context, request, parsed)
    if request.method == "PUT":
        return await _push_manifest(context, request, parsed)
    if request.method == "DELETE":
        return await _delete_manifest(context, parsed)
    raise _not_allowed("GET, HEAD, PUT, DELETE")


# --- Tags and the catalog ------------------------------------------------------------


def _page(request: Request, default: int, most: int) -> tuple[int, str]:
    asked = request.query_params.get("n", "")
    plain = asked.isascii() and asked.isdigit() and len(asked) <= 6
    return (min(int(asked), most) if plain else default), request.query_params.get("last", "")


async def _tags(context: RepositoryContext, request: Request, parsed: names.DockerPath) -> Response:
    if not _is_read(request):
        raise _not_allowed("GET, HEAD")
    held = sorted(await context.versions("", parsed.image))
    if not held:
        raise unknown("NAME_UNKNOWN", "No such image.")
    return _tag_page(context, request, parsed.image, held)


def _tag_page(
    context: RepositoryContext, request: Request, image: str, held: list[str]
) -> Response:
    """A page of an image's tags, which are in order, with where the next page is."""
    count, last = _page(request, _TAGS_DEFAULT, _CATALOG_MOST)
    after = [tag for tag in held if tag > last]
    page = after[:count]
    headers = {}
    if count and len(after) > count:
        more = _address(context, image, f"tags/list?n={count}&last={page[-1]}")
        headers["Link"] = f'<{more}>; rel="next"'
    name = f"{context.repository.name}/{image}"
    return JSONResponse({"name": name, "tags": page}, headers=headers)


async def images(context: RepositoryContext) -> list[str]:
    """The images of a repository that have a tag, in order.

    A group has those of the repositories behind it that are online, each once.
    """
    if context.repository.type == "group":
        behind: set[str] = set()
        for leaf in await group.leaves(context):
            if leaf.online:
                behind.update(await images(leaf.context))
        return sorted(behind)[:_CATALOG_MOST]
    found, _ = await context.package_names("", limit=_CATALOG_MOST, offset=0)
    return [name for namespace, name in found if namespace == ""]  # those with a tag


# --- A proxy: what its remote has, fetched when it is asked for -----------------------

# Every kind of manifest this registry keeps, so that the remote sends the one it has
# and does not convert it: a converted manifest has another digest.
_ACCEPT = ", ".join(
    (manifests.OCI_INDEX, manifests.DOCKER_LIST, manifests.OCI_MANIFEST, manifests.DOCKER_MANIFEST)
)
# Docker Hub keeps its official images under `library/`, and Docker leaves that out.
_HUB = "registry-1.docker.io"
_LIST_PAGE_BYTES = 4 * 1024 * 1024
_LIST_PAGES_MOST = 100
_LIST_TAGS_MOST = 100_000
_LIST_BYTES_MOST = 16 * 1024 * 1024
_NEXT = re.compile(r'<([^>]*)>\s*;\s*rel="?next"?')


def _remote_address(context: RepositoryContext, image: str, rest: str) -> str:
    """Where the remote has something of an image."""
    base = context.repository.config["proxy"]["remote_url"].rstrip("/")
    official = (urlsplit(base).hostname or "").lower() == _HUB and "/" not in image
    name = f"library/{image}" if official else image
    return f"{base}/v2/{quote(name, safe='/')}/{rest}"


def _unhelped(found: proxy.Unavailable, code: str) -> ApiError:
    """What to answer when the remote did not help and nothing is held."""
    if found.status in (401, 403):
        # A registry says this of an image it does not have as of one it will not show.
        message = "The remote has no such image, or does not let this proxy read it."
        return unknown(code, message)
    return found.error


async def _keep_manifest(
    context: RepositoryContext, image: str, raw: bytes, *, asked: str, expected: str | None
) -> manifests.Manifest:
    """Keep a manifest the remote sent, under its digest, with what it refers to.

    `asked` is the path it was fetched for, and `expected` the digest it must have if
    it was asked for by one. What is not a manifest, or not that one, is not kept.
    """
    try:
        manifest = manifests.read(raw, None)
    except manifests.InvalidManifest as error:
        reason = f"it sent a manifest that cannot be used: {error}"
        raise await proxy.refuse(context, asked, reason) from None
    if expected is not None and manifest.digest != expected:
        reason = "it sent a manifest that is not the one asked for"
        raise await proxy.refuse(context, asked, reason)
    needed = [names.blob_path(digest) for digest in manifest.blobs]
    needed += [names.manifest_path(image, digest) for digest in manifest.manifests]
    await context.cache(
        names.manifest_path(image, manifest.digest),
        await context.stage_bytes(raw),
        content_type=manifest.media_type,
        attributes={},
        now=utcnow(),
        references=needed,  # what they name is fetched when it is asked for
    )
    return manifest


async def _fetch_manifest(
    context: RepositoryContext, image: str, digest: str, *, remember_missing: bool = True
) -> tuple[bytes, manifests.Manifest]:
    """Fetch the manifest with this digest from the remote, and keep it."""
    path = names.manifest_path(image, digest)
    source = proxy.Source(
        _remote_address(context, image, f"manifests/{digest}"),
        accept=_ACCEPT,
        subject=image,
        remember_missing=remember_missing,
    )
    found = await proxy.ask(context, path, source, limit=manifests.MAX_BYTES)
    if isinstance(found, proxy.Absent):
        raise unknown("MANIFEST_UNKNOWN", "No such manifest.")
    if isinstance(found, proxy.Unavailable):
        raise _unhelped(found, "MANIFEST_UNKNOWN")
    kept = await _keep_manifest(context, image, found.body, asked=path, expected=digest)
    return found.body, kept


async def _refresh_tag(context: RepositoryContext, image: str, tag: str) -> None:
    """Make what is held for a tag what the remote has now, if the remote can be asked.

    Returning means there is a manifest to serve: a new one, the old one confirmed, or
    the old one kept because the remote could not be asked or has dropped the tag.
    """
    path = names.tag_path(image, tag)
    held = await context.stat(path)
    by_tag = proxy.Source(
        _remote_address(context, image, f"manifests/{tag}"), accept=_ACCEPT, subject=image
    )
    # Only asking is cheap, and a registry that counts pulls does not count it.
    found = await proxy.probe(context, path, by_tag)
    digest = ""
    if isinstance(found, proxy.Answer):
        digest = found.headers.get("Docker-Content-Digest", "")
    if isinstance(found, proxy.Answer) and not names.is_digest(digest):
        # The remote does not say which manifest the tag names until it is fetched.
        found = await proxy.ask(context, path, by_tag, limit=manifests.MAX_BYTES)
    if isinstance(found, proxy.Unavailable):
        if held is None:
            raise _unhelped(found, "MANIFEST_UNKNOWN")
        return
    if isinstance(found, proxy.Absent):
        if held is None:
            raise unknown("MANIFEST_UNKNOWN", "No such manifest.")
        # The remote dropped a tag we hold. An artifact manager keeps it.
        await proxy.still_current(context, path)
        return
    if held is not None and names.is_digest(digest) and held.sha256 == names.hex_of(digest):
        await proxy.still_current(context, path)
        return
    try:
        if names.is_digest(digest):
            by_digest = names.manifest_path(image, digest)
            raw = await context.read(by_digest, limit=manifests.MAX_BYTES)
            if raw is None:
                # The remote has just said that it has this manifest. If it then says
                # otherwise, that is not worth remembering: it would hide the tag.
                raw, manifest = await _fetch_manifest(
                    context, image, digest, remember_missing=False
                )
            else:
                manifest = manifests.read(raw, None)  # it was read when it was kept
        else:
            raw = found.body
            manifest = await _keep_manifest(context, image, raw, asked=path, expected=None)
    except ApiError:
        if held is None:
            raise
        # The tag names something else now, and the remote will not give it: where
        # pulls are counted, asking still works when fetching no longer does. What is
        # held is served, and the tag is asked about again the next time.
        return
    await context.cache(
        path,
        await context.stage_bytes(raw),
        content_type=manifest.media_type,
        attributes={},
        now=utcnow(),
    )


def _is_stale(context: RepositoryContext, asset: object, path: str) -> bool:
    settings = context.repository.config["proxy"]
    return asset is None or not proxy.is_fresh(settings, context.format, asset, path, utcnow())


async def _proxied_manifest(
    context: RepositoryContext, request: Request, parsed: names.DockerPath
) -> Response:
    image, reference = parsed.image, parsed.reference
    if names.is_digest(reference):
        # A digest names content: once held, it is never asked about again.
        if await context.stat(names.manifest_path(image, reference)) is None:
            await _fetch_manifest(context, image, reference)
    else:
        path = names.tag_path(image, reference)
        if _is_stale(context, await context.get(path), path):
            await _refresh_tag(context, image, reference)
    return await _read_manifest(context, request, parsed)


async def _proxied_blob(
    context: RepositoryContext, request: Request, parsed: names.DockerPath
) -> Response:
    digest = parsed.reference
    path = names.blob_path(digest)
    if await context.stat(path) is None:
        source = proxy.Source(
            _remote_address(context, parsed.image, f"blobs/{digest}"),
            digests={"sha256": names.hex_of(digest)},
            subject=parsed.image,
            # Another image of the remote may have the blob that this one has not.
            remember_missing=False,
        )
        if request.method == "HEAD":
            # Asking about a layer must not fetch it: it may be gigabytes.
            found = await proxy.probe(context, path, source)
            if isinstance(found, proxy.Absent):
                raise unknown("BLOB_UNKNOWN", "No such blob.")
            if isinstance(found, proxy.Unavailable):
                raise _unhelped(found, "BLOB_UNKNOWN")
            headers = {"Docker-Content-Digest": digest, "Content-Type": _BLOB}
            length = found.headers.get("Content-Length", "")
            if length.isascii() and length.isdigit():
                headers["Content-Length"] = length
            return Response(status_code=200, headers=headers)
        try:
            await proxy.ensure_cached(context, path, source=source)
        except ApiError as error:
            if error.status_code != 404:
                raise
            raise unknown("BLOB_UNKNOWN", "No such blob.") from None
    return await _blob(context, request, parsed)


def _next_page(link: str, current: str) -> str | None:
    """The address of the next page of a list, from the `Link` header of this one."""
    found = _NEXT.search(link)
    if found is None:
        return None
    try:
        return urljoin(current, found[1])
    except ValueError:
        return None


async def _refresh_list(context: RepositoryContext, image: str, *, held: bool) -> None:
    """Fetch every page of the remote's list of an image's tags, and keep it as one."""
    path = names.list_path(image)
    address = _remote_address(context, image, "tags/list?n=1000")
    tags: set[str] = set()
    for _ in range(_LIST_PAGES_MOST):
        # A page that is missing is the end of the list, not a thing to remember.
        source = proxy.Source(
            address, accept="application/json", subject=image, remember_missing=False
        )
        found = await proxy.ask(context, path, source, limit=_LIST_PAGE_BYTES)
        if isinstance(found, proxy.Unavailable):
            if not held:
                raise _unhelped(found, "NAME_UNKNOWN")
            return
        if isinstance(found, proxy.Absent):
            if tags:
                break
            if not held:
                raise unknown("NAME_UNKNOWN", "No such image.")
            await proxy.still_current(context, path)
            return
        try:
            listed = json.loads(found.body).get("tags") or []
        except (ValueError, AttributeError, RecursionError):
            listed = None
        if not isinstance(listed, list):
            raise await proxy.refuse(context, path, "it sent a list of tags that cannot be read")
        tags.update(tag for tag in listed if isinstance(tag, str) and names.is_tag(tag))
        following = _next_page(found.headers.get("Link", ""), address)
        if following is None or len(tags) >= _LIST_TAGS_MOST:
            break
        address = following
    document = json.dumps({"tags": sorted(tags)}).encode()
    await context.cache(
        path,
        await context.stage_bytes(document),
        content_type="application/json",
        attributes={},
        now=utcnow(),
    )


async def _remote_tags(context: RepositoryContext, image: str) -> list[str]:
    """The tags of an image as a proxy's remote lists them, renewed if the list is old."""
    path = names.list_path(image)
    asset = await context.get(path)
    if _is_stale(context, asset, path):
        await _refresh_list(context, image, held=asset is not None)
    raw = await context.read(path, limit=_LIST_BYTES_MOST)
    return json.loads(raw)["tags"] if raw is not None else []


async def _proxied_tags(
    context: RepositoryContext, request: Request, parsed: names.DockerPath
) -> Response:
    held = await _remote_tags(context, parsed.image)
    return _tag_page(context, request, parsed.image, held)


# --- A group: the repositories behind it, as one --------------------------------------


async def _answering(context: RepositoryContext, image: str) -> list[RepositoryContext]:
    """The repositories behind a group that answer for an image, in the order to try them.

    If a hosted repository has the image, hosted ones alone answer for it, whatever a
    proxy's remote has under the same name. A hosted repository has an image while it
    holds a manifest of it, with a tag or without: deleting a tag withdraws a release,
    and must not hand its name to whoever has the same name elsewhere. A layer is not
    an image's: holding one that a public image also uses decides nothing.

    If the only hosted repositories that have the image are offline, the answer is
    `503`: while they are away, nothing else may answer in their place.
    """
    leaves = await group.leaves(context)
    holders, away = await group.owners(leaves, names.MANIFESTS, image)
    if holders:
        return holders
    if away:
        message = "The repository that holds this image is offline."
        raise ApiError(503, "repository_offline", message)
    return group.proxies(leaves)


async def _grouped(
    context: RepositoryContext,
    request: Request,
    parsed: names.DockerPath,
    path: str,
    serve: Serve,
) -> Response:
    """A manifest or a blob, from the first repository that has it among those that answer."""
    unavailable = None
    for member in await _answering(context, parsed.image):
        try:
            return await serve(member, request, path)
        except ApiError as error:
            if error.status_code not in group.TRY_NEXT:
                raise
            if error.status_code != 404 and unavailable is None:
                unavailable = error
    if unavailable is not None:
        # Nobody had it, and somebody could not say. That is not "there is no such thing".
        raise unavailable
    if parsed.kind == "blob":
        raise unknown("BLOB_UNKNOWN", "No such blob.")
    raise unknown("MANIFEST_UNKNOWN", "No such manifest.")


async def _grouped_tags(
    context: RepositoryContext, request: Request, parsed: names.DockerPath
) -> Response:
    """The tags of an image in every repository that answers for it, each once."""
    image = parsed.image
    tags: set[str] = set()
    known, unavailable = False, None
    for member in await _answering(context, image):
        try:
            if member.repository.type == "hosted":
                held = await member.versions("", image)
                if not held:
                    continue  # it has the image, and no tag of it
                tags.update(held)
            else:
                tags.update(await _remote_tags(member, image))
        except ApiError as error:
            if error.status_code not in group.TRY_NEXT:
                raise
            if error.status_code != 404 and unavailable is None:
                unavailable = error
            continue
        known = True
    if not known:
        raise unavailable or unknown("NAME_UNKNOWN", "No such image.")
    return _tag_page(context, request, image, sorted(tags))


class DockerFormat(Format):
    name = FORMAT
    served_at = "registry"
    remote_signs_in = True
    unlisted_namespaces = frozenset({names.MANIFESTS})

    async def delete_asset(self, context: RepositoryContext, path: str) -> bool:
        """A tag goes alone. A manifest goes as by its digest in the registry API.

        A blob goes only if no manifest refers to it: otherwise it is part of an image.
        """
        held = names.manifest_of(path)
        if held is None and not path.startswith("blobs/"):
            return await context.delete(path)
        await context.lock(_REFERENCES)
        if held is not None:
            return await _drop(context, *held)
        if await context.referenced([path]):
            reason = "An image uses this layer. It goes when the images that use it are deleted."
            raise managed_by_format(reason)
        return await context.delete(path)

    def download_path(self, repository: str, path: str) -> str | None:
        """A tag and a manifest are fetched through the registry. A blob is an image's part."""
        named = names.tag_of(path) or names.manifest_of(path)
        if named is None:
            return None
        return f"/v2/{repository}/{named[0]}/manifests/{named[1]}"

    def content_type(self, path: str, declared: str | None) -> str | None:
        """What a proxy records for a file its engine fetched, which is only ever a blob."""
        return _BLOB if path.startswith("blobs/") else declared

    def is_metadata(self, path: str) -> bool:
        """A tag and a list of tags change at the remote. What a digest names does not."""
        return path.startswith(("tags/", "lists/"))

    def validate_name(self, name: str) -> None:
        """The repository is the first part of every image's name, so it is named like one."""
        if "/" in name or not names.is_valid_name(name):
            message = (
                "A Docker repository's name is the first part of its images' names: lower-case "
                "letters and digits, with single '.', '_', '__' or '-' between them."
            )
            details = [{"field": "name", "message": message}]
            raise ApiError(422, "validation_error", "The request is not valid.", details)

    def search_text(self, key: ComponentKey, attributes: dict[str, Any]) -> str:
        """A tag is found by its image and tag, also as `image:tag`."""
        words = super().search_text(key, attributes)
        return words if key.namespace else f"{words} {key.name}:{key.version}"

    def describe_component(self, path: str) -> ComponentKey | None:
        """A tag is a component: the image, and the tag as its version.

        A manifest is one as well, in a namespace of its own, with its digest as the
        version. It is what says that a repository has something of an image, tagged
        or not, which decides who answers for the image behind a group. Tag lists and
        the catalog are made of the tags alone.
        """
        named = names.tag_of(path)
        if named is not None:
            return ComponentKey("", *named)
        held = names.manifest_of(path)
        return None if held is None else ComponentKey(names.MANIFESTS, *held)

    async def maintain(self, context: RepositoryContext, now: datetime) -> None:
        """Remove blobs that no manifest has referred to for a day."""
        await context.lock(_REFERENCES)
        before = now - timedelta(seconds=UNUSED_BLOB_SECONDS)
        for path in await context.unreferenced("blobs/", before=before, limit=_SWEEP_AT_ONCE):
            await context.sweep(path)

    async def handle_hosted(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        parsed = names.classify(path)
        if parsed.kind == "blob":
            return await _blob(context, request, parsed)
        if parsed.kind == "upload_start":
            return await _start_upload(context, request, parsed)
        if parsed.kind == "upload":
            return await _upload(context, request, parsed)
        if parsed.kind == "manifest":
            return await _manifest(context, request, parsed)
        if parsed.kind == "tags":
            return await _tags(context, request, parsed)
        if parsed.kind == "referrers":
            raise RegistryError(404, "UNSUPPORTED", "The referrers API is not available.")
        raise RegistryError(404, "NAME_UNKNOWN", "Nothing is served at this address.")

    async def handle_proxy(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        if not _is_read(request):
            # Whatever the address: nothing can be pushed to a proxy, or deleted from it.
            raise _not_allowed("GET, HEAD")
        parsed = names.classify(path)
        if parsed.kind == "blob":
            return await _proxied_blob(context, request, parsed)
        if parsed.kind == "manifest":
            return await _proxied_manifest(context, request, parsed)
        if parsed.kind == "tags":
            return await _proxied_tags(context, request, parsed)
        if parsed.kind == "referrers":
            raise RegistryError(404, "UNSUPPORTED", "The referrers API is not available.")
        raise RegistryError(404, "NAME_UNKNOWN", "Nothing is served at this address.")

    async def handle_group(
        self, context: RepositoryContext, request: Request, path: str, serve: Serve
    ) -> Response:
        if not _is_read(request):
            raise _not_allowed("GET, HEAD")
        parsed = names.classify(path)
        if parsed.kind in ("blob", "manifest"):
            return await _grouped(context, request, parsed, path, serve)
        if parsed.kind == "tags":
            return await _grouped_tags(context, request, parsed)
        if parsed.kind == "referrers":
            raise RegistryError(404, "UNSUPPORTED", "The referrers API is not available.")
        raise RegistryError(404, "NAME_UNKNOWN", "Nothing is served at this address.")


register(DockerFormat())
