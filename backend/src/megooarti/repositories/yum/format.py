"""The YUM format: hosted repositories that dnf installs from, and proxies of mirrors.

This is the only YUM module that touches the repository context. What a path means,
what a package says of itself and what its metadata says come from the pure modules
beside it.

A package is uploaded to the path it is kept at. Its headers are read once, as it is
stored, and what they say is kept with it. Each `repodata/` is written from what was
kept: once for each revision of the repository, in a worker thread, with `repomd.xml`
signed by the repository's key. Until the next change it is served from memory, and
so are the hash-named files of the revision before, which a client that read the
older `repomd.xml` a moment ago is still fetching.

A proxy is the generic engine: its remote's `repomd.xml` is metadata, checked again
after the proxy's metadata age, and passed on as the remote wrote it; the files it
names carry their hash in their names, and never change.
"""

import asyncio
import hashlib
from collections import defaultdict
from collections.abc import Sequence
from contextlib import aclosing
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories import checks, derived, signing
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
from megooarti.repositories.yum import paths, repodata, rpms, versions
from megooarti.storage.backends import StagedBlob

# Where what a package said of itself is kept among its file's attributes, and what is
# said of the version among its component's.
_DECLARED = "yum"
_RPM = "application/x-rpm"
_XML = "application/xml"
_PACKED = {".gz": "application/gzip", ".xz": "application/x-xz", ".zst": "application/zstd"}
_SIGNATURE = "application/pgp-signature"
_KEY = "application/pgp-keys"
# Where, among the index files of a revision, the `repodata/` of a directory that holds
# no package is: one that no path can be.
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


def _invalid_setting(field: str, message: str) -> ApiError:
    details = [{"field": field, "message": message}]
    return ApiError(422, "validation_error", "The request is not valid.", details)


def _declared(attributes: dict[str, Any] | None) -> dict[str, Any]:
    declared = (attributes or {}).get(_DECLARED)
    return declared if isinstance(declared, dict) else {}


def _rpm_of(attributes: dict[str, Any] | None) -> rpms.Rpm | None:
    """What a stored package said of itself, as it was kept."""
    said = _declared(attributes).get("rpm")
    return rpms.Rpm.from_json(said) if isinstance(said, dict) else None


def depth_of(context: RepositoryContext) -> int:
    return context.repository.config.get("format_config", {}).get("repodata_depth", 0)


# --- Uploading -----------------------------------------------------------------------


def _check_path(path: str, depth: int) -> None:
    """Refuse a path a package cannot be kept at."""
    parsed = paths.classify(path, depth)
    if parsed.kind != "package":
        raise _invalid_path("a package's path ends in `.rpm`, outside `repodata/`")
    if not paths.deep_enough(path, depth):
        raise _invalid_path(
            f"this repository's metadata is {depth} directories down "
            f"(repodata_depth), so a package must be at least that deep"
        )


async def _read(context: RepositoryContext, staged: StagedBlob) -> rpms.Rpm:
    """What a staged package says of itself.

    Only its headers are read, and the file is closed at once: a file that is still
    open cannot be moved into the store, or removed, on every system.
    """
    try:
        async with aclosing(context.open_staged(staged)) as chunks:
            return await rpms.read(chunks)
    except rpms.InvalidPackage as error:
        raise _invalid(error) from None


async def _keep(context: RepositoryContext, path: str, staged: StagedBlob, rpm: rpms.Rpm) -> bool:
    """Store a package at its path. Returns whether it is new there."""
    held = await context.component("", rpm.name, rpm.evr)
    said = await asyncio.to_thread(rpm.as_json)  # a large package's is megabytes
    known = _declared(held.attributes if held else None).get("architectures", [])
    _, created = await context.store(
        path,
        staged,
        content_type=_RPM,
        attributes={_DECLARED: {"rpm": said, "stored": int(utcnow().timestamp())}},
        component_attributes={
            _DECLARED: {
                "summary": rpm.summary,
                "architectures": sorted({*known, rpm.arch}),
            }
        },
    )
    return created


async def _put(context: RepositoryContext, request: Request, path: str) -> Response:
    """One package, as `curl --upload-file` sends it to its path."""
    _check_path(path, depth_of(context))
    # Refused before the body is read; the facade checks again when the file is stored.
    context.require_write()
    await context.release()  # the body needs no connection
    staged = await context.stage(
        request.stream(),
        expected_size=declared_size(request),
        expected_hashes=declared_hashes(request),
    )
    try:
        rpm = await _read(context, staged)
    except ApiError:
        await context.discard(staged)
        raise
    created = await _keep(context, path, staged, rpm)
    return Response(status_code=201 if created else 204)


# --- The metadata --------------------------------------------------------------------


def _listed(snapshot: Snapshot, depth: int) -> dict[str, list[repodata.Listed]]:
    """The packages each directory's `repodata/` lists, by the directory."""
    listed: dict[str, list[repodata.Listed]] = defaultdict(list)
    for held in snapshot.files:
        rpm = _rpm_of(held.attributes)
        directory = paths.directory_of(held.path, depth)
        if rpm is None or directory is None:
            continue  # nothing a hosted repository holds, but it belongs to no metadata
        location = held.path[len(directory) + 1 :] if directory else held.path
        stored = _declared(held.attributes).get("stored", 0)
        listed[directory].append(
            repodata.Listed(location, held.size, held.sha256, int(stored), rpm)
        )
    return listed


def _signed(listed: Sequence[repodata.Listed], moment: int, signer: signing.Signer):
    files = repodata.repodata(listed, moment)
    files[paths.SIGNATURE] = signer.detached(files[paths.REPOMD])
    return files


def _carried(previous: derived.Written | None) -> dict[str, bytes]:
    """The hash-named files the last revision's `repomd.xml` named: a client may still want them."""
    if previous is None:
        return {}
    carried = {}
    for key, data in previous.files.items():
        found = paths.repodata_of(key)
        if found is None or not paths.hashed(found[1]):
            continue
        repomd = previous.files.get(paths.in_repodata(found[0], paths.REPOMD), b"")
        if f'href="repodata/{found[1]}"'.encode() in repomd:
            carried[key] = data
    return carried


def _written(
    snapshot: Snapshot, depth: int, signer: signing.Signer, previous: derived.Written | None
) -> derived.Written:
    """Every `repodata/` file of a revision, by its path; and the last revision's."""
    moment = int(snapshot.changed.timestamp())
    listed = _listed(snapshot, depth)
    # At depth 0 the root always has one; deeper, any directory without packages has
    # the same, empty one, kept as well beside the root's, to tell an empty one by.
    if depth == 0:
        listed.setdefault("", [])
    listed[_EMPTY] = []
    files = _carried(previous)
    for directory, packages in listed.items():
        for name, data in _signed(packages, moment, signer).items():
            files[paths.in_repodata(directory, name)] = data
    return derived.Written(snapshot.revision, snapshot.changed, files)


async def hosted_repodata(context: RepositoryContext) -> derived.Written:
    """The `repodata/` files of this repository's revision: kept, or written now, once."""
    revision, _ = await context.revision()

    async def write() -> derived.Written:
        snapshot = await context.snapshot()
        key = await signing.key_of(context.db, context.settings, context.repository)
        signer = signing.signer(context.settings, key)
        previous = derived.peek(context.repository.id)
        await context.release()  # writing them needs no connection
        return await asyncio.to_thread(_written, snapshot, depth_of(context), signer, previous)

    return await derived.written(context.repository.id, revision, write)


def repodata_file(written: derived.Written, directory: str, filename: str) -> bytes | None:
    """A file of a directory's `repodata/`, from what was written of a revision.

    The directory is one as deep as the repository's `repodata_depth`.
    """
    data = written.files.get(paths.in_repodata(directory, filename))
    own = paths.in_repodata(directory, paths.REPOMD) in written.files
    if data is None and (not own or paths.hashed(filename)):
        # A directory without packages has the empty one; a client that read its
        # `repomd.xml` before the first package came still finds what it named.
        data = written.files.get(paths.in_repodata(_EMPTY, filename))
    return data


def holds_packages(written: derived.Written, directory: str) -> bool:
    """Whether a directory of a revision has packages in its `repodata/`."""
    own = written.files.get(paths.in_repodata(directory, paths.REPOMD))
    return own is not None and own != written.files.get(paths.in_repodata(_EMPTY, paths.REPOMD))


def repodata_content_type(filename: str) -> str:
    if filename.endswith(".asc"):
        return _SIGNATURE
    if filename.endswith(".xml"):
        return _XML
    return _PACKED.get(filename[filename.rfind(".") :], "application/octet-stream")


async def _repodata(
    context: RepositoryContext, request: Request, parsed: paths.YumPath
) -> Response:
    depth = depth_of(context)
    if not paths.at_depth(parsed.directory, depth):
        raise _not_found(
            f"This repository's metadata is {depth} directories down (repodata_depth)."
        )
    written = await hosted_repodata(context)
    data = repodata_file(written, parsed.directory, parsed.filename)
    if data is None:
        raise _not_found("This repository's metadata has no such file.")
    return context.respond_with(
        data,
        request,
        filename=parsed.filename,
        content_type=repodata_content_type(parsed.filename),
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
        filename=paths.PUBLIC_KEY,
        content_type=_KEY,
        last_modified=key.created_at,
        etag=key.fingerprint.lower(),
    )


def setup_of(address: str, repository: Repository) -> list[Usage]:
    """The repository's key, and its `.repo` file with the account dnf signs in with."""
    name = repository.name
    depth = repository.config.get("format_config", {}).get("repodata_depth", 0)
    # A group has metadata wherever a member has, at any depth.
    deep = repository.type == "group" or (repository.type == "hosted" and depth)
    directory = "<directory>" if deep else ""
    lines = []
    if repository.type == "proxy":
        signed, checked, keys = "0", "1", "file:///etc/pki/rpm-gpg/<the distribution's key>"
    else:
        lines.append(
            'sudo curl -fsS -u "$MEGOOARTI_USER:$MEGOOARTI_TOKEN" '
            f"-o /etc/pki/rpm-gpg/{name}.asc {address}public.key"
        )
        signed, keys = "1", f"file:///etc/pki/rpm-gpg/{name}.asc"
        # A group may have a member it cannot check: then every package is (S8).
        checked = "1" if repository.type == "group" else "0"
        if repository.type == "group":
            keys += " file:///etc/pki/rpm-gpg/<the packages' keys>"
    lines += [
        f"sudo tee /etc/yum.repos.d/{name}.repo > /dev/null <<EOF",
        f"[{name}]",
        f"name={name}",
        f"baseurl={address}{directory}",
        "username=$MEGOOARTI_USER",
        "password=$MEGOOARTI_TOKEN",
        f"repo_gpgcheck={signed}",
        f"gpgcheck={checked}",
        f"gpgkey={keys}",
        "EOF",
        f"sudo chmod 600 /etc/yum.repos.d/{name}.repo",
    ]
    return [Usage("dnf", "shell", "\n".join(lines))]


class YumFormat(Format):
    name = "yum"
    types = frozenset({"hosted", "proxy", "group"})
    derives_indexes = True
    signs = signing.OPENPGP

    def validate_config(
        self, repository_type: str, config: dict[str, Any], current: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """A hosted repository's `repodata_depth`, which never changes; a proxy's remote's keys."""
        if repository_type == "proxy":
            return checks.remote_keys_setting(config, "YUM")
        if repository_type != "hosted":
            return super().validate_config(repository_type, config, current)
        unknown = sorted(set(config) - {"repodata_depth"})
        if unknown:
            raise _invalid_setting(f"format_config.{unknown[0]}", "This is not a setting of YUM.")
        stored = 0 if current is None else current.get("repodata_depth", 0)
        depth = config.get("repodata_depth", stored)
        if type(depth) is not int or not 0 <= depth <= paths.DEPTH_MOST:
            raise _invalid_setting(
                "format_config.repodata_depth",
                f"The depth of the metadata is a whole number from 0 to {paths.DEPTH_MOST}.",
            )
        if current is not None and depth != stored:
            raise _invalid_setting(
                "format_config.repodata_depth",
                "The depth of the metadata cannot change once the repository is made.",
            )
        return {"repodata_depth": depth}

    def describe_component(
        self, path: str, attributes: dict[str, Any] | None = None
    ) -> ComponentKey | None:
        """A package belongs to its name and version: what it said, or its file's name."""
        rpm = _rpm_of(attributes)
        if rpm is not None:
            return ComponentKey("", rpm.name, rpm.evr)
        named = paths.named(path) if paths.classify(path).kind == "package" else None
        return None if named is None else ComponentKey("", named[0], named[1])

    def search_text(self, key: ComponentKey, attributes: dict[str, Any]) -> str:
        """Its name and version, its summary, and its architectures."""
        declared = _declared(attributes)
        words = [super().search_text(key, attributes)]
        summary = declared.get("summary")
        if isinstance(summary, str):
            words.append(summary)
        architectures = declared.get("architectures")
        if isinstance(architectures, list):
            words.extend(str(architecture) for architecture in architectures)
        return " ".join(words)

    async def upload(self, context: RepositoryContext, form: UploadForm) -> list[str]:
        """Store packages in a `directory`, each by its file's name."""
        only_fields(form, ("directory",))
        if not form.files:
            raise invalid_upload("file", "At least one RPM is needed.")
        directory = form.fields.get("directory", "").strip("/")
        depth = depth_of(context)
        read = []
        for file in form.files:
            if file.field != "file":
                raise invalid_upload(file.field, "A package is sent as `file`.")
            if "/" in file.filename or "\\" in file.filename:
                raise invalid_upload("file", f"A file's name cannot hold a slash: {file.filename}")
            path = normalise_path(f"{directory}/{file.filename}" if directory else file.filename)
            _check_path(path, depth)
            if any(path == other for other, _ in read):
                raise invalid_upload("file", f"Two files are named {file.filename}.")
            read.append((path, await _read(context, file.staged)))
        for (path, rpm), file in zip(read, form.files, strict=True):
            await _keep(context, path, file.staged, rpm)
        return [path for path, _ in read]

    def usage(self, address: str, key: ComponentKey, files: Sequence[str]) -> list[Usage]:
        if versions.NAME.fullmatch(key.name) is None or versions.split(key.version) is None:
            return []
        return [Usage("dnf", "shell", f"sudo dnf install {key.name}-{key.version}")]

    def setup(self, address: str, repository: Repository) -> list[Usage]:
        return setup_of(address, repository)

    def content_type(self, path: str, declared: str | None) -> str | None:
        parsed = paths.classify(path)
        if parsed.kind == "package":
            return _RPM
        if parsed.kind == "repodata":
            return repodata_content_type(parsed.filename)
        return declared

    def is_metadata(self, path: str) -> bool:
        """`repomd.xml` changes as packages are published; what it names by hash does not."""
        parsed = paths.classify(path)
        return parsed.kind == "repodata" and not paths.hashed(parsed.filename)

    async def handle_hosted(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        parsed = paths.classify(path, depth_of(context))
        if parsed.kind == "package":
            if _is_read(request):
                return await context.respond(path, request)
            if request.method == "PUT":
                return await _put(context, request, path)
            if request.method != "DELETE":
                raise _not_allowed("GET, HEAD, PUT, DELETE")
            if not await context.delete(path):
                raise _not_found("No such package.")
            return Response(status_code=204)
        if not _is_read(request):
            if request.method == "PUT" and parsed.kind == "other":
                raise _invalid_path("a package's path ends in `.rpm`, outside `repodata/`")
            raise _not_allowed("GET, HEAD")
        if parsed.kind == "key":
            return await _public_key(context, request)
        if parsed.kind == "repodata":
            return await _repodata(context, request, parsed)
        raise _not_found()

    async def handle_group(
        self, context: RepositoryContext, request: Request, path: str, serve: Serve
    ) -> Response:
        if paths.classify(path).kind == "key" and _is_read(request):
            return await _public_key(context, request)
        # Imported here: it is written against this module.
        from megooarti.repositories.yum import groups

        return await groups.handle_group(context, request, path, serve)


register(YumFormat())
