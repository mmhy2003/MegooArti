"""The APT format: hosted repositories that apt installs from, and proxies of mirrors.

This is the only APT module that touches the repository context. What a path means,
what a package says of itself and what an index says come from the pure functions
beside it.

A package is uploaded to a hosted repository's root, or through the upload form, and
kept where Debian keeps it, under `pool/`. Its control file is read once, as it is
stored, and kept with it. The indexes are written from what was kept: once for each
revision of the repository, in a worker thread, and signed with the repository's key.
Until the next change they are served from memory.

A proxy is the generic engine: its remote's indexes are metadata, checked again after
the proxy's metadata age, and passed on as the remote signed them.
"""

import asyncio
import hashlib
from collections.abc import Sequence
from contextlib import aclosing
from typing import Any
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories import checks, derived, signing
from megooarti.repositories.apt import control, debs, indexes, paths, versions
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
from megooarti.storage.backends import StagedBlob

# Where what a package said of itself is kept among its file's attributes, and what is
# said of the version among its component's.
_DECLARED = "apt"
_DEB = "application/vnd.debian.binary-package"
_TEXT = "text/plain; charset=utf-8"
_COMPRESSED = {".gz": "application/gzip", ".xz": "application/x-xz"}
_SIGNATURE = "application/pgp-signature"
_KEY = "application/pgp-keys"
DEFAULT_SUITE = "stable"


def _invalid(reason: object) -> ApiError:
    return ApiError(400, "invalid_package", f"The package cannot be accepted: {reason}.")


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


def _control_of(attributes: dict[str, Any] | None) -> control.Paragraph | None:
    """What a stored package said of itself, as it was kept."""
    declared = (attributes or {}).get(_DECLARED)
    said = declared.get("control") if isinstance(declared, dict) else None
    if not isinstance(said, list):
        return None
    return [(str(name), str(value)) for name, value in said]


def _invalid_setting(field: str, message: str) -> ApiError:
    details = [{"field": field, "message": message}]
    return ApiError(422, "validation_error", "The request is not valid.", details)


def suite_of(context: RepositoryContext) -> str:
    return context.repository.config.get("format_config", {}).get("suite", DEFAULT_SUITE)


# --- Uploading -----------------------------------------------------------------------


async def _read(context: RepositoryContext, staged: StagedBlob) -> debs.Deb:
    """What a staged package says of itself.

    Only its beginning is read, and the file is closed at once, read to the end or
    not: a file that is still open cannot be moved into the store, or removed, on
    every system.
    """
    try:
        async with aclosing(context.open_staged(staged)) as chunks:
            return await debs.read(chunks)
    except debs.InvalidPackage as error:
        raise _invalid(error) from None


async def _keep(context: RepositoryContext, staged: StagedBlob, deb: debs.Deb) -> tuple[str, bool]:
    """Store a package where Debian keeps it. Returns where, and whether it is new there."""
    path = paths.pool_path(deb.package, deb.version, deb.architecture)
    held = await context.component("", deb.package, deb.version)
    known = ((held.attributes if held else {}).get(_DECLARED) or {}).get("architectures", [])
    architectures = sorted({*known, deb.architecture})
    description = control.first_line(control.get(deb.control, "Description") or "")
    _, created = await context.store(
        path,
        staged,
        content_type=_DEB,
        attributes={_DECLARED: {"control": [list(field) for field in deb.control]}},
        component_attributes={
            _DECLARED: {"description": description, "architectures": architectures}
        },
    )
    return path, created


async def _upload(context: RepositoryContext, request: Request) -> Response:
    """One package, as `curl --upload-file` sends it to the repository's root."""
    # Refused before the body is read; the facade checks again when the file is stored.
    context.require_write()
    await context.release()  # the body needs no connection
    staged = await context.stage(
        request.stream(),
        expected_size=declared_size(request),
        expected_hashes=declared_hashes(request),
    )
    try:
        deb = await _read(context, staged)
    except ApiError:
        await context.discard(staged)
        raise
    path, created = await _keep(context, staged, deb)
    location = f"{await context.public_url(request)}/{path}"
    return Response(status_code=201 if created else 204, headers={"Location": location})


# --- The indexes ---------------------------------------------------------------------


def _listed(snapshot: Snapshot) -> list[indexes.Listed]:
    listed = []
    for held in snapshot.files:
        said = _control_of(held.attributes)
        if said is None:
            continue  # nothing a hosted repository holds, but it belongs to no index
        listed.append(
            indexes.Listed(
                path=held.path,
                size=held.size,
                md5=held.md5,
                sha1=held.sha1,
                sha256=held.sha256,
                control=said,
                package=control.get(said, "Package") or "",
                version=control.get(said, "Version") or "",
                architecture=control.get(said, "Architecture") or "",
            )
        )
    return listed


def _written(snapshot: Snapshot, suite: str, label: str, signer: signing.Signer) -> derived.Written:
    """Every index file of a suite, by its path under `dists/<suite>/`."""
    listed = _listed(snapshot)
    files = indexes.packages_files(listed)
    release = indexes.release(
        label=label,
        suite=suite,
        moment=snapshot.changed,
        architectures=indexes.architectures(listed),
        files=files,
    )
    signed = {
        "Release": release,
        "InRelease": signer.clear(release),
        "Release.gpg": signer.detached(release),
    }
    return derived.Written(snapshot.revision, snapshot.changed, {**files, **signed})


async def hosted_indexes(context: RepositoryContext) -> derived.Written:
    """The index files of this repository's revision: kept, or written now, once."""
    revision, _ = await context.revision()

    async def write() -> derived.Written:
        snapshot = await context.snapshot()
        key = await signing.key_of(context.db, context.settings, context.repository)
        signer = signing.signer(context.settings, key)
        await context.release()  # writing them needs no connection
        return await asyncio.to_thread(
            _written, snapshot, suite_of(context), context.repository.name, signer
        )

    return await derived.written(context.repository.id, revision, write)


def index_content_type(filename: str) -> str:
    if filename == "Release.gpg":
        return _SIGNATURE
    return _COMPRESSED.get(filename[filename.rfind(".") :], _TEXT) if "." in filename else _TEXT


async def _index(context: RepositoryContext, request: Request, parsed: paths.AptPath) -> Response:
    if parsed.suite != suite_of(context) or (
        parsed.component and parsed.component != paths.COMPONENT
    ):
        raise _not_found("This repository has no such suite or component.")
    if parsed.kind == "release":
        name = parsed.filename
    else:
        name = f"{parsed.component}/binary-{parsed.architecture}/{parsed.filename}"
    written = await hosted_indexes(context)
    data = written.files.get(name)
    if data is None:
        raise _not_found("This repository has no packages of that architecture.")
    return context.respond_with(
        data,
        request,
        filename=parsed.filename,
        content_type=index_content_type(parsed.filename),
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
    """The repository's key, its line in `sources.list.d`, and the account apt signs in with."""
    name = repository.name
    parts = urlsplit(address)
    # apt sends credentials over plain HTTP only to a line that says so (`machine http://`).
    machine = parts.netloc if parts.scheme == "https" else f"{parts.scheme}://{parts.netloc}"
    lines = []
    if repository.type == "proxy":
        keyring = "/usr/share/keyrings/<distribution>-archive-keyring.gpg"
        suite = "<suite>"
    else:
        keyring = f"/etc/apt/keyrings/{name}.asc"
        lines.append(
            f'sudo curl -fsS -u "$MEGOOARTI_USER:$MEGOOARTI_TOKEN" -o {keyring} {address}public.key'
        )
        format_config = repository.config.get("format_config", {})
        suite = (
            format_config.get("suite", DEFAULT_SUITE) if repository.type == "hosted" else "<suite>"
        )
    lines += [
        f'echo "deb [signed-by={keyring}] {address.rstrip("/")} {suite} main" \\',
        f"  | sudo tee /etc/apt/sources.list.d/{name}.list > /dev/null",
        f"printf 'machine {machine}\\nlogin %s\\npassword %s\\n' \\",
        '  "$MEGOOARTI_USER" "$MEGOOARTI_TOKEN" \\',
        f"  | sudo tee /etc/apt/auth.conf.d/{name}.conf > /dev/null",
        f"sudo chmod 600 /etc/apt/auth.conf.d/{name}.conf",
        "sudo apt-get update",
    ]
    return [Usage("apt", "shell", "\n".join(lines))]


class AptFormat(Format):
    name = "apt"
    types = frozenset({"hosted", "proxy", "group"})
    derives_indexes = True
    signs = signing.OPENPGP

    def validate_config(
        self, repository_type: str, config: dict[str, Any], current: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """A hosted repository's suite, which never changes; a proxy's remote's keys."""
        if repository_type == "proxy":
            return checks.remote_keys_setting(config, "APT")
        if repository_type != "hosted":
            return super().validate_config(repository_type, config, current)
        unknown = sorted(set(config) - {"suite"})
        if unknown:
            raise _invalid_setting(f"format_config.{unknown[0]}", "This is not a setting of APT.")
        suite = config.get("suite", DEFAULT_SUITE if current is None else current.get("suite"))
        if not isinstance(suite, str) or paths.SUITE.fullmatch(suite) is None:
            raise _invalid_setting(
                "format_config.suite",
                "A suite is 1 to 64 letters, digits, '.', '_' or '-', and begins with a "
                "letter or a digit.",
            )
        if current is not None and suite != current.get("suite", DEFAULT_SUITE):
            raise _invalid_setting(
                "format_config.suite", "The suite cannot change once the repository is made."
            )
        return {"suite": suite}

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
        said = _control_of(attributes)
        if said is not None:
            return ComponentKey("", control.get(said, "Package"), control.get(said, "Version"))
        named = paths.in_pool(path)
        return None if named is None else ComponentKey("", named[0], named[1])

    def search_text(self, key: ComponentKey, attributes: dict[str, Any]) -> str:
        """Its name and version, its description's first line, and its architectures."""
        declared = attributes.get(_DECLARED)
        declared = declared if isinstance(declared, dict) else {}
        words = [super().search_text(key, attributes)]
        description = declared.get("description")
        if isinstance(description, str):
            words.append(description)
        architectures = declared.get("architectures")
        if isinstance(architectures, list):
            words.extend(str(architecture) for architecture in architectures)
        return " ".join(words)

    async def upload(self, context: RepositoryContext, form: UploadForm) -> list[str]:
        """Store packages as an upload of each to the repository's root would."""
        only_fields(form, ())
        if not form.files:
            raise invalid_upload("file", "At least one Debian package is needed.")
        read = []
        for file in form.files:
            if file.field != "file":
                raise invalid_upload(file.field, "A package is sent as `file`.")
            deb = await _read(context, file.staged)
            path = paths.pool_path(deb.package, deb.version, deb.architecture)
            if any(path == other for other, _ in read):
                raise invalid_upload("file", f"Two files are the same package: {file.filename}.")
            read.append((path, deb))
        return [
            (await _keep(context, file.staged, deb))[0]
            for (_, deb), file in zip(read, form.files, strict=True)
        ]

    def usage(self, address: str, key: ComponentKey, files: Sequence[str]) -> list[Usage]:
        if versions.NAME.fullmatch(key.name) is None or versions.split(key.version) is None:
            return []
        return [Usage("apt", "shell", f"sudo apt install {key.name}={key.version}")]

    def setup(self, address: str, repository: Repository) -> list[Usage]:
        return setup_of(address, repository)

    def content_type(self, path: str, declared: str | None) -> str | None:
        parsed = paths.classify(path)
        if parsed.kind == "pool":
            return _DEB
        if parsed.kind in ("release", "packages"):
            return index_content_type(parsed.filename)
        return declared

    def is_metadata(self, path: str) -> bool:
        """A suite's indexes change as packages are published, except those named by a hash."""
        return path.startswith("dists/") and "/by-hash/" not in path

    async def handle_hosted(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        parsed = paths.classify(path)
        if parsed.kind == "upload":
            if request.method not in ("PUT", "POST"):
                raise _not_allowed("PUT, POST")
            return await _upload(context, request)
        if parsed.kind == "pool":
            if _is_read(request):
                return await context.respond(path, request)
            if request.method != "DELETE":
                raise _not_allowed("GET, HEAD, DELETE")
            if not await context.delete(path):
                raise _not_found("No such package.")
            return Response(status_code=204)
        if not _is_read(request):
            raise _not_allowed("GET, HEAD")
        if parsed.kind == "key":
            return await _public_key(context, request)
        if parsed.kind in ("release", "packages"):
            return await _index(context, request, parsed)
        raise _not_found()

    async def handle_group(
        self, context: RepositoryContext, request: Request, path: str, serve: Serve
    ) -> Response:
        if paths.classify(path).kind == "key" and _is_read(request):
            return await _public_key(context, request)
        # Imported here: it is written against this module.
        from megooarti.repositories.apt import groups

        return await groups.handle_group(context, request, path, serve)


register(AptFormat())
