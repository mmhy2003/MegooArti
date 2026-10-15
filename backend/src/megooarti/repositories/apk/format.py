"""The apk format: hosted repositories that apk installs from, and proxies of mirrors.

This is the only apk module that touches the repository context. What a path means,
what a package says of itself and what an index says come from the pure modules beside
it.

A package is uploaded to its architecture's directory, under the name apk asks for it
by (`<name>-<version>.apk`). Its `.PKGINFO` is read once, as it is stored, and kept
with it. Each directory's `APKINDEX.tar.gz` is written from what was kept: once for each
revision of the repository, in a worker thread, signed with the repository's RSA key.
Until the next change it is served from memory.

A proxy is the generic engine: its remote's indexes are metadata, checked again after
the proxy's metadata age, and passed on as the remote signed them.
"""

import asyncio
import hashlib
from collections import defaultdict
from collections.abc import Sequence
from contextlib import aclosing
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories import checks, derived, signing
from megooarti.repositories.apk import index, packages, paths, versions
from megooarti.repositories.content import RepositoryContext, Snapshot
from megooarti.repositories.formats import (
    ComponentKey,
    Format,
    Serve,
    Usage,
    declared_hashes,
    declared_size,
    invalid_upload,
    only_fields,
    register,
)
from megooarti.repositories.forms import UploadForm
from megooarti.repositories.models import Repository
from megooarti.repositories.paths import normalise_path
from megooarti.storage.backends import StagedBlob

# Where what a package said of itself is kept among its file's attributes, and what is
# said of the version among its component's.
_DECLARED = "apk"
_PACKED = "application/gzip"
_KEY = "application/x-pem-file"
# Where, among the index files of a revision, the index of a directory that holds no
# package is: one that no path can be.
_EMPTY = "/"


def _invalid(reason: object) -> ApiError:
    return ApiError(400, "invalid_package", f"The package cannot be accepted: {reason}.")


def _invalid_path(reason: str) -> ApiError:
    return ApiError(400, "invalid_path", f"The path is not valid: {reason}.")


def _not_found(message: str = "Nothing is served at this address.") -> ApiError:
    return ApiError(404, "not_found", message)


def _not_allowed(allowed: str) -> ApiError:
    return ApiError(
        405,
        "method_not_allowed",
        f"This address accepts {allowed}.",
        headers={"Allow": allowed},
    )


def _is_read(request: Request) -> bool:
    return request.method in ("GET", "HEAD")


def _declared(attributes: dict[str, Any] | None) -> dict[str, Any]:
    declared = (attributes or {}).get(_DECLARED)
    return declared if isinstance(declared, dict) else {}


def _apk_of(attributes: dict[str, Any] | None) -> packages.Apk | None:
    """What a stored package said of itself, as it was kept."""
    said = _declared(attributes).get("apk")
    return packages.Apk.from_json(said) if isinstance(said, dict) else None


def description_of(context: RepositoryContext) -> str:
    """What `apk update` shows of the repository's indexes."""
    return f"MegooArti {context.repository.name}"


# --- Uploading -----------------------------------------------------------------------


def _check_place(directory: str, apk: packages.Apk) -> str:
    """Where a package is kept in a directory, or the refusal of that directory."""
    architecture = directory.rpartition("/")[2]
    if not directory or (apk.arch != versions.NOARCH and architecture != apk.arch):
        raise _invalid_path(
            f"a package for {apk.arch} is kept in a directory of that name, as apk asks for it "
            f"there (`.../{apk.arch}/{apk.filename}`)"
        )
    return f"{directory}/{apk.filename}"


async def _read(context: RepositoryContext, staged: StagedBlob) -> packages.Apk:
    """What a staged package says of itself.

    Only its beginning is read, and the file is closed at once: a file that is still
    open cannot be moved into the store, or removed, on every system.
    """
    try:
        async with aclosing(context.open_staged(staged)) as chunks:
            return await packages.read(chunks)
    except packages.InvalidPackage as error:
        raise _invalid(error) from None


async def _keep(
    context: RepositoryContext, path: str, staged: StagedBlob, apk: packages.Apk
) -> bool:
    """Store a package at its path. Returns whether it is new there."""
    held = await context.component("", apk.name, apk.version)
    said = await asyncio.to_thread(apk.as_json)
    known = _declared(held.attributes if held else None).get("architectures", [])
    _, created = await context.store(
        path,
        staged,
        content_type=_PACKED,
        attributes={_DECLARED: {"apk": said}},
        component_attributes={
            _DECLARED: {
                "description": apk.info.get("pkgdesc", ""),
                "architectures": sorted({*known, path.split("/")[-2]}),
            }
        },
    )
    return created


async def _put(context: RepositoryContext, request: Request, parsed: paths.ApkPath) -> Response:
    """One package, as `curl --upload-file` sends it to its path."""
    # Refused before the body is read; the facade checks again when the file is stored.
    context.require_write()
    await context.release()  # the body needs no connection
    staged = await context.stage(
        request.stream(),
        expected_size=declared_size(request),
        expected_hashes=declared_hashes(request),
    )
    try:
        apk = await _read(context, staged)
        path = _check_place(parsed.directory, apk)
        if path != f"{parsed.directory}/{parsed.filename}":
            raise _invalid_path(f"apk asks for this package as {apk.filename}")
    except ApiError:
        await context.discard(staged)
        raise
    created = await _keep(context, path, staged, apk)
    return Response(status_code=201 if created else 204)


# --- The indexes ---------------------------------------------------------------------


def _listed(snapshot: Snapshot) -> dict[str, list[index.Listed]]:
    """The packages each directory's index lists, by the directory."""
    listed: dict[str, list[index.Listed]] = defaultdict(list)
    for held in snapshot.files:
        apk = _apk_of(held.attributes)
        directory = held.path.rpartition("/")[0]
        if apk is None or not directory:
            continue  # nothing a hosted repository holds, but it belongs to no index
        listed[directory].append(index.Listed(held.size, apk))
    return listed


def _written(
    snapshot: Snapshot, description: str, key_name: str, signer: signing.RsaSigner
) -> derived.Written:
    """Every directory's `APKINDEX.tar.gz` of a revision, by its path; and an empty one."""
    moment = int(snapshot.changed.timestamp())
    files = {}
    for directory, listed in [*_listed(snapshot).items(), (_EMPTY, [])]:
        architecture = directory.rpartition("/")[2]
        files[paths.in_directory(directory, index.INDEX)] = index.index_file(
            listed, architecture, description, key_name, signer, moment
        )
    return derived.Written(snapshot.revision, snapshot.changed, files)


async def hosted_indexes(context: RepositoryContext) -> derived.Written:
    """The indexes of this repository's revision: kept, or written now, once."""
    revision, _ = await context.revision()

    async def write() -> derived.Written:
        snapshot = await context.snapshot()
        key = await signing.key_of(context.db, context.settings, context.repository)
        signer = signing.signer(context.settings, key)
        await context.release()  # writing them needs no connection
        return await asyncio.to_thread(
            _written,
            snapshot,
            description_of(context),
            paths.key_name(context.repository.name),
            signer,
        )

    return await derived.written(context.repository.id, revision, write)


def holds_packages(written: derived.Written, directory: str) -> bool:
    """Whether a directory of a revision has packages in its index."""
    return paths.in_directory(directory, index.INDEX) in written.files


def index_file(written: derived.Written, directory: str) -> bytes:
    """A directory's index, from what was written of a revision: an empty one if it has none."""
    found = written.files.get(paths.in_directory(directory, index.INDEX))
    return found if found is not None else written.files[paths.in_directory(_EMPTY, index.INDEX)]


async def _index(context: RepositoryContext, request: Request, parsed: paths.ApkPath) -> Response:
    written = await hosted_indexes(context)
    data = index_file(written, parsed.directory)
    return context.respond_with(
        data,
        request,
        filename=index.INDEX,
        content_type=_PACKED,
        last_modified=written.changed,
        etag=hashlib.sha256(data).hexdigest(),
        # Two revisions can be made within one second: only the bytes say which one a
        # client has.
        dated=False,
    )


async def _public_key(context: RepositoryContext, request: Request) -> Response:
    key = await signing.key_of(context.db, context.settings, context.repository)
    return context.respond_with(
        key.public_key.encode(),
        request,
        filename=paths.key_name(context.repository.name),
        content_type=_KEY,
        last_modified=key.created_at,
        etag=key.fingerprint.lower(),
    )


def _invalid_setting(field: str, message: str) -> ApiError:
    details = [{"field": field, "message": message}]
    return ApiError(422, "validation_error", "The request is not valid.", details)


class ApkFormat(Format):
    name = "apk"
    types = frozenset({"hosted", "proxy", "group"})
    derives_indexes = True
    signs = signing.RSA

    def validate_config(
        self, repository_type: str, config: dict[str, Any], current: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """A proxy's remote's keys, PEM, which a group checks it with; nothing else."""
        if repository_type == "proxy":
            return checks.remote_keys_setting(config, "apk", signing.read_rsa_public_keys)
        return super().validate_config(repository_type, config, current)

    def validate_member(self, member: Repository) -> None:
        """A proxy whose signatures a group cannot check is not one of its members."""
        if member.type == "proxy" and not member.config.get("format_config", {}).get("remote_keys"):
            raise _invalid_setting(
                "group.members",
                f"{member.name} is a proxy without its remote's keys "
                "(format_config.remote_keys): a group could not check what it signs.",
            )

    def describe_component(
        self, path: str, attributes: dict[str, Any] | None = None
    ) -> ComponentKey | None:
        """A package belongs to its name and version: what it said, or its file's name."""
        apk = _apk_of(attributes)
        if apk is not None:
            return ComponentKey("", apk.name, apk.version)
        named = paths.named(path)
        return None if named is None else ComponentKey("", named[0], named[1])

    def search_text(self, key: ComponentKey, attributes: dict[str, Any]) -> str:
        """Its name and version, its description, and its architectures."""
        declared = _declared(attributes)
        words = [super().search_text(key, attributes)]
        description = declared.get("description")
        if isinstance(description, str):
            words.append(description)
        architectures = declared.get("architectures")
        if isinstance(architectures, list):
            words.extend(str(architecture) for architecture in architectures)
        return " ".join(words)

    async def upload(self, context: RepositoryContext, form: UploadForm) -> list[str]:
        """Store packages in a `directory`, each under the name apk asks for it by."""
        only_fields(form, ("directory",))
        if not form.files:
            raise invalid_upload("file", "At least one apk package is needed.")
        directory = form.fields.get("directory", "").strip("/")
        if directory:
            normalise_path(directory)
        read = []
        for file in form.files:
            if file.field != "file":
                raise invalid_upload(file.field, "A package is sent as `file`.")
            apk = await _read(context, file.staged)
            path = _check_place(directory, apk)
            if any(path == other for other, _ in read):
                raise invalid_upload("file", f"Two files are the same package: {file.filename}.")
            read.append((path, apk))
        for (path, apk), file in zip(read, form.files, strict=True):
            await _keep(context, path, file.staged, apk)
        return [path for path, _ in read]

    def usage(self, address: str, key: ComponentKey, files: Sequence[str]) -> list[Usage]:
        if (
            versions.NAME.fullmatch(key.name) is None
            or versions.VERSION.fullmatch(key.version) is None
        ):
            return []
        return [Usage("apk", "shell", f"apk add {key.name}={key.version}")]

    def content_type(self, path: str, declared: str | None) -> str | None:
        if path.endswith((".apk", index.INDEX)):
            return _PACKED
        return declared

    def is_metadata(self, path: str) -> bool:
        """A directory's index changes as packages are published; packages do not."""
        return path.rpartition("/")[2] == index.INDEX

    async def handle_hosted(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        parsed = paths.classify(path, context.repository.name)
        if parsed.kind == "package":
            if _is_read(request):
                return await context.respond(path, request)
            if request.method == "PUT":
                return await _put(context, request, parsed)
            if request.method != "DELETE":
                raise _not_allowed("GET, HEAD, PUT, DELETE")
            if not await context.delete(path):
                raise _not_found("No such package.")
            return Response(status_code=204)
        if not _is_read(request):
            if request.method == "PUT" and parsed.kind == "other":
                raise _invalid_path(
                    "a package is kept at `<directory>/<architecture>/<name>-<version>.apk`"
                )
            raise _not_allowed("GET, HEAD")
        if parsed.kind == "key":
            return await _public_key(context, request)
        if parsed.kind == "index":
            return await _index(context, request, parsed)
        raise _not_found()

    async def handle_group(
        self, context: RepositoryContext, request: Request, path: str, serve: Serve
    ) -> Response:
        if paths.classify(path, context.repository.name).kind == "key" and _is_read(request):
            return await _public_key(context, request)
        # Imported here: it is written against this module.
        from megooarti.repositories.apk import groups

        return await groups.handle_group(context, request, path, serve)


register(ApkFormat())
