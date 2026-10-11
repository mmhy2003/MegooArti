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
"""

from datetime import datetime, timedelta

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from megooarti.errors import ApiError
from megooarti.repositories import uploads
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.docker import manifests, names
from megooarti.repositories.docker.errors import RegistryError, unknown
from megooarti.repositories.formats import ComponentKey, Format, register
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
    count, last = _page(request, _TAGS_DEFAULT, _CATALOG_MOST)
    after = [tag for tag in held if tag > last]
    page = after[:count]
    headers = {}
    if count and len(after) > count:
        more = _address(context, parsed.image, f"tags/list?n={count}&last={page[-1]}")
        headers["Link"] = f'<{more}>; rel="next"'
    name = f"{context.repository.name}/{parsed.image}"
    return JSONResponse({"name": name, "tags": page}, headers=headers)


async def images(context: RepositoryContext) -> list[str]:
    """The images of a repository that have a tag, in order."""
    found, _ = await context.package_names("", limit=_CATALOG_MOST, offset=0)
    return [name for _, name in found]


class DockerFormat(Format):
    name = FORMAT
    served_at = "registry"
    # Proxy and group repositories need the registry's own handling.
    types = frozenset({"hosted"})

    def validate_name(self, name: str) -> None:
        """The repository is the first part of every image's name, so it is named like one."""
        if "/" in name or not names.is_valid_name(name):
            message = (
                "A Docker repository's name is the first part of its images' names: lower-case "
                "letters and digits, with single '.', '_', '__' or '-' between them."
            )
            details = [{"field": "name", "message": message}]
            raise ApiError(422, "validation_error", "The request is not valid.", details)

    def describe_component(self, path: str) -> ComponentKey | None:
        """A tag is a component: the image, and the tag as its version. Nothing else is."""
        named = names.tag_of(path)
        return None if named is None else ComponentKey("", *named)

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


register(DockerFormat())
