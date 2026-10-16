"""The NuGet format: hosted repositories that .NET's clients push to and restore from.

This is the only NuGet module that touches the repository context. What a path means,
what a package says of itself, what a document says and which packages a search finds
come from the pure modules beside it.

A package's `.nuspec` is read once, as it is pushed, and kept with its version: with
its file and as its component's attributes. The documents of V3 (an id's versions, its
registration, search) are written from those on each request, as npm's package
documents are, so they are right after every push and delete: each is of one id, or of
what a search found, and asks the database for nothing else.

An id is matched without regard to case, as NuGet's clients match it. The first push
of an id spells it; later ones are kept under that spelling. A version is kept
normalized and in lower case, as it is in every address; what its package wrote is in
its `.nuspec`.
"""

import json
import xml.sax.saxutils
from collections.abc import Sequence
from contextlib import aclosing
from dataclasses import replace
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories import forms
from megooarti.repositories.content import ComponentInfo, RepositoryContext
from megooarti.repositories.formats import (
    ComponentKey,
    Format,
    Usage,
    invalid_upload,
    managed_by_format,
    only_fields,
    plain,
    register,
)
from megooarti.repositories.models import Repository
from megooarti.repositories.nuget import documents, packages, paths, queries, versions
from megooarti.repositories.nuget.documents import Published
from megooarti.storage.backends import StagedBlob

# Where what a package said of itself is kept, among a file's attributes and among its
# version's component's.
_DECLARED = "nuget"
_PACKAGE = "application/octet-stream"
_NUSPEC = "application/xml"
_JSON = "application/json"


def _invalid(reason: object) -> ApiError:
    return ApiError(400, "invalid_package", f"The package cannot be accepted: {reason}.")


def _not_found(message: str = "Nothing is served at this address.") -> ApiError:
    return ApiError(404, "not_found", message)


def _not_allowed(allowed: str) -> ApiError:
    return ApiError(
        405, "method_not_allowed", f"This address accepts {allowed}.", headers={"Allow": allowed}
    )


def _nuspec_of(attributes: dict[str, Any] | None) -> packages.Nuspec | None:
    said = (attributes or {}).get(_DECLARED)
    return packages.Nuspec.from_json(said) if isinstance(said, dict) else None


def _published(held: Sequence[ComponentInfo]) -> list[Published]:
    """The versions held that a package's `.nuspec` describes, with when each was pushed."""
    return [
        Published(nuspec, one.created)
        for one in held
        if (nuspec := _nuspec_of(one.attributes)) is not None
    ]


# --- Pushing ------------------------------------------------------------------------


def _ranges(context: RepositoryContext, staged: StagedBlob) -> packages.Read:
    """A staged package's bytes by position: it is read from its start each time.

    A package is read three times at the most (its end, its directory, its `.nuspec`),
    and only those bytes are kept. Each reading closes the file at once: a file that is
    still open cannot be moved into the store, or removed, on every system.
    """

    async def read(start: int, length: int) -> bytes:
        kept, position = bytearray(), 0
        async with aclosing(context.open_staged(staged)) as chunks:
            async for chunk in chunks:
                end = position + len(chunk)
                if end > start and position < start + length:
                    kept += chunk[max(0, start - position) : start + length - position]
                position = end
                if position >= start + length:
                    break
        return bytes(kept)

    return read


async def _read(context: RepositoryContext, staged: StagedBlob) -> packages.Package:
    try:
        return await packages.read(_ranges(context, staged), staged.size)
    except packages.InvalidPackage as error:
        raise _invalid(error) from None


async def _received(context: RepositoryContext, request: Request) -> StagedBlob:
    """The one package a push sends, staged: as `multipart/form-data`, as every client sends it."""
    context.require_write()  # refused before the body is read
    await context.release()  # the body needs no connection
    try:
        form = await forms.read(
            request.stream(),
            request.headers.get("Content-Type", ""),
            stage=context.stage,
            discard=context.discard,
        )
    except forms.InvalidForm as error:
        raise _invalid(f"the push cannot be read: {error}") from None
    if len(form.files) != 1:
        for file in form.files:
            await context.discard(file.staged)
        raise _invalid("a push sends one package")
    return form.files[0].staged


async def _spelled(context: RepositoryContext, nuspec: packages.Nuspec) -> packages.Nuspec:
    """The `.nuspec`'s id as the repository already spells it, if it has the id."""
    spelling = await context.spelling("", nuspec.id)
    return nuspec if spelling is None or spelling == nuspec.id else replace(nuspec, id=spelling)


async def _keep_package(
    context: RepositoryContext, staged: StagedBlob, package: packages.Package
) -> bool:
    """A package and its `.nuspec`, each at its path. Returns whether the version is new."""
    nuspec = await _spelled(context, package.nuspec)
    said = {_DECLARED: nuspec.as_json()}
    _, created = await context.store(
        paths.package_path(nuspec.id, nuspec.version),
        staged,
        content_type=_PACKAGE,
        attributes=said,
        component_attributes=said,
    )
    spec = await context.stage_bytes(package.spec)
    await context.store(
        paths.nuspec_path(nuspec.id, nuspec.version), spec, content_type=_NUSPEC, attributes=said
    )
    return created


async def _keep_symbols(
    context: RepositoryContext, staged: StagedBlob, package: packages.Package
) -> bool:
    """A symbol package, beside the package it is of: that must be here."""
    nuspec = await _spelled(context, package.nuspec)
    if await context.stat(paths.package_path(nuspec.id, nuspec.version)) is None:
        await context.discard(staged)
        raise _not_found(
            f"This repository has no {nuspec.id} {nuspec.version}: push the package first."
        )
    _, created = await context.store(
        paths.symbols_path(nuspec.id, nuspec.version),
        staged,
        content_type=_PACKAGE,
        attributes={_DECLARED: nuspec.as_json()},
    )
    return created


async def _push(context: RepositoryContext, request: Request, *, symbols: bool) -> Response:
    """`PUT api/v2/package` and `api/v2/symbolpackage`. A symbol package may come to
    the first, as older clients send it."""
    staged = await _received(context, request)
    try:
        package = await _read(context, staged)
        if symbols and not package.nuspec.is_symbols:
            raise _invalid("a package is pushed to api/v2/package, not as symbols")
    except ApiError:
        await context.discard(staged)
        raise
    keep = _keep_symbols if package.nuspec.is_symbols else _keep_package
    created = await keep(context, staged, package)
    return Response(status_code=201 if created else 200)


# --- Deleting -----------------------------------------------------------------------


async def _delete_version(context: RepositoryContext, package_id: str, version: str) -> bool:
    """Every file of a version: its package, `.nuspec` and symbols. False if it has none."""
    spelling = await context.spelling("", package_id)
    if spelling is None:
        return False
    deleted = False
    for held in await context.files("", spelling, version):
        deleted = await context.delete(held.path) or deleted
    return deleted


# --- Reading ------------------------------------------------------------------------


async def _base(context: RepositoryContext, request: Request) -> str:
    return f"{await context.public_url(request)}/"


async def _respond(context: RepositoryContext, request: Request, document: Any) -> Response:
    """A document written for this request, as JSON."""
    data = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode()
    _, changed = await context.revision()
    return context.respond_with(
        data,
        request,
        filename="index.json",
        content_type=_JSON,
        last_modified=changed,
        # Two changes can be made within one second: only the bytes say which a client has.
        dated=False,
    )


async def _held(context: RepositoryContext, package_id: str) -> list[Published]:
    """Every version of an id this repository holds. Raises 404 for none."""
    spelling = await context.spelling("", package_id)
    held = [] if spelling is None else _published(await context.components("", spelling))
    if not held:
        raise _not_found(f"This repository has no package {package_id}.")
    return held


async def _registration(context: RepositoryContext, request: Request, package_id: str) -> Response:
    """An id's registration: its versions inlined if there are few, else its pages by
    their bounds, written from the version strings alone."""
    spelling = await context.spelling("", package_id)
    listed = [] if spelling is None else list(await context.versions("", spelling))
    if not listed:
        raise _not_found(f"This repository has no package {package_id}.")
    base = await _base(context, request)
    if len(listed) > documents.INLINED_MOST:
        return await _respond(
            context, request, documents.registration_pages(base, package_id, listed)
        )
    held = _published(await context.components("", spelling))
    return await _respond(context, request, documents.registration(base, held))


async def _registration_page(
    context: RepositoryContext, request: Request, parsed: paths.NuGetPath
) -> Response:
    """One page of an id's registration; only its versions' attributes are used."""
    spelling = await context.spelling("", parsed.id)
    listed = [] if spelling is None else list(await context.versions("", spelling))
    wanted = documents.page_of(listed, parsed.lower, parsed.upper)
    if wanted is None or len(listed) <= documents.INLINED_MOST:
        raise _not_found(f"This repository has no such page of {parsed.id}.")
    held = [
        one
        for one in _published(await context.components("", spelling))
        if one.nuspec.version.lower() in set(wanted)
    ]
    base = await _base(context, request)
    page = documents.registration_page(base, parsed.id, held, parsed.lower, parsed.upper)
    return await _respond(context, request, page)


async def _search(context: RepositoryContext, request: Request) -> Response:
    query = queries.parse(request.query_params)
    names, total = await context.package_page(
        "",
        query.words,
        exact=query.exact_id,
        containing=query.id_contains,
        ranked_by=" ".join(query.words),
        stable_only=not query.prerelease,
        limit=query.take,
        offset=query.skip,
    )
    held = await context.components_of("", names)
    found = queries.shown(query, names, {name: _published(infos) for name, infos in held.items()})
    return await _respond(
        context, request, documents.search_result(await _base(context, request), found, total)
    )


async def _autocomplete(context: RepositoryContext, request: Request) -> Response:
    """Ids that contain what was typed; or, given an `id`, its versions."""
    arguments = request.query_params
    prerelease = arguments.get("prerelease", "").lower() == "true"
    if "id" in arguments:
        spelling = await context.spelling("", arguments["id"])
        held = [] if spelling is None else _published(await context.components("", spelling))
        shown = versions.ordered(
            [one.nuspec.version for one in held if prerelease or not one.nuspec.is_prerelease]
        )
        return await _respond(context, request, documents.autocomplete(shown, len(shown)))
    query = queries.parse({**arguments, "q": ""})
    typed = arguments.get("q", "").strip().lower()
    ids, total = await context.package_page(
        "",
        [],
        containing=typed,
        ranked_by=typed,
        stable_only=not prerelease,
        limit=query.take,
        offset=query.skip,
    )
    return await _respond(context, request, documents.autocomplete(ids, total))


async def _read_request(
    context: RepositoryContext, request: Request, path: str, parsed: paths.NuGetPath
) -> Response:
    if parsed.kind == "service-index":
        return await _respond(
            context, request, documents.service_index(await _base(context, request))
        )
    if parsed.kind in ("package", "nuspec", "symbols"):
        return await context.respond(path, request)
    if parsed.kind == "versions":
        # Written from the versions alone: what each said of itself is not read.
        spelling = await context.spelling("", parsed.id)
        listed = [] if spelling is None else list(await context.versions("", spelling))
        if not listed:
            raise _not_found(f"This repository has no package {parsed.id}.")
        return await _respond(context, request, documents.version_list(listed))
    if parsed.kind == "registration":
        return await _registration(context, request, parsed.id)
    if parsed.kind == "page":
        return await _registration_page(context, request, parsed)
    if parsed.kind == "leaf":
        held = [
            one
            for one in await _held(context, parsed.id)
            if one.nuspec.version.lower() == parsed.version
        ]
        if not held:
            raise _not_found(f"This repository has no {parsed.id} {parsed.version}.")
        return await _respond(
            context, request, documents.leaf(await _base(context, request), held[0])
        )
    if parsed.kind == "search":
        return await _search(context, request)
    if parsed.kind == "autocomplete":
        return await _autocomplete(context, request)
    raise _not_found()


# --- Setting a machine up -----------------------------------------------------------


def _element(name: str) -> str:
    """A source's name as an element of `nuget.config`, as NuGet encodes one."""
    first = name[0]
    if first.isalpha() or first == "_":
        return name
    return f"_x{ord(first):04X}_{name[1:]}"


def setup_of(address: str, name: str) -> list[Usage]:
    """The repository as a source of `dotnet`, by its command and in `nuget.config`."""
    source = f"{address}index.json"
    command = (
        f'dotnet nuget add source "{source}" --name {name} \\\n'
        '  --username "$MEGOOARTI_USER" --password "$MEGOOARTI_TOKEN" '
        "--store-password-in-clear-text"
    )
    insecure = ' allowInsecureConnections="true"' if source.startswith("http://") else ""
    escaped = xml.sax.saxutils.quoteattr(source)
    element = _element(name)
    config = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<configuration>\n"
        "  <packageSources>\n"
        f'    <add key="{name}" value={escaped}{insecure} />\n'
        "  </packageSources>\n"
        "  <packageSourceCredentials>\n"
        f"    <{element}>\n"
        '      <add key="Username" value="%MEGOOARTI_USER%" />\n'
        '      <add key="ClearTextPassword" value="%MEGOOARTI_TOKEN%" />\n'
        f"    </{element}>\n"
        "  </packageSourceCredentials>\n"
        "</configuration>"
    )
    return [Usage("dotnet", "shell", command), Usage("nuget.config", "xml", config)]


class NuGetFormat(Format):
    name = "nuget"
    types = frozenset({"hosted"})
    derives_indexes = True

    def default_deployment_policy(self, config: dict[str, Any]) -> str:
        """A version is pushed once, as nuget.org takes it: a second push is `409`."""
        return "disable_redeploy"

    def describe_component(
        self, path: str, attributes: dict[str, Any] | None = None
    ) -> ComponentKey | None:
        """A package's files belong to its id and version: as its `.nuspec` said, or its path."""
        nuspec = _nuspec_of(attributes)
        if nuspec is not None:
            return ComponentKey("", nuspec.id, nuspec.version.lower())
        parsed = paths.classify(path)
        if parsed.kind in ("package", "nuspec", "symbols"):
            return ComponentKey("", parsed.id, parsed.version)
        return None

    def search_text(self, key: ComponentKey, attributes: dict[str, Any]) -> str:
        """Its id and version, and the words of its `.nuspec` that NuGet's search reads."""
        nuspec = _nuspec_of(attributes)
        words = [super().search_text(key, attributes)]
        if nuspec is not None:
            words += [nuspec.title, nuspec.description, nuspec.summary, nuspec.tags, nuspec.authors]
        return " ".join(word for word in words if word)

    async def upload(self, context: RepositoryContext, form: forms.UploadForm) -> list[str]:
        """Store packages and symbol packages as pushes would: each where its `.nuspec` says."""
        only_fields(form, ())
        if not form.files:
            raise invalid_upload("file", "At least one NuGet package is needed.")
        read = []
        for file in form.files:
            if file.field != "file":
                raise invalid_upload(file.field, "A package is sent as `file`.")
            read.append((file.staged, await _read(context, file.staged)))
        # Packages first: a symbol package goes beside its package.
        read.sort(key=lambda pair: pair[1].nuspec.is_symbols)
        stored = []
        for staged, package in read:
            nuspec = package.nuspec
            if nuspec.is_symbols:
                await _keep_symbols(context, staged, package)
                stored.append(paths.symbols_path(nuspec.id, nuspec.version))
            else:
                await _keep_package(context, staged, package)
                stored.append(paths.package_path(nuspec.id, nuspec.version))
        return stored

    async def delete_asset(self, context: RepositoryContext, path: str) -> bool:
        """A package goes with its version's every file; its `.nuspec` goes with it."""
        parsed = paths.classify(path)
        if parsed.kind == "package":
            return await _delete_version(context, parsed.id, parsed.version)
        if parsed.kind == "nuspec":
            package = paths.package_path(parsed.id, parsed.version)
            if await context.stat(path) is not None and await context.stat(package) is not None:
                raise managed_by_format(
                    "A package's .nuspec goes with it: delete the package, or its version."
                )
        return await context.delete(path)

    def usage(self, address: str, key: ComponentKey, files: Sequence[str]) -> list[Usage]:
        if not plain(key.name, key.version) or not versions.is_id(key.name):
            return []
        return [
            Usage("dotnet", "shell", f"dotnet add package {key.name} --version {key.version}"),
            Usage(
                "PackageReference",
                "xml",
                f'<PackageReference Include="{key.name}" Version="{key.version}" />',
            ),
            Usage(
                "Package Manager",
                "shell",
                f"Install-Package {key.name} -Version {key.version}",
            ),
        ]

    def setup(self, address: str, repository: Repository) -> list[Usage]:
        return setup_of(address, repository.name)

    def content_type(self, path: str, declared: str | None) -> str | None:
        kind = paths.classify(path).kind
        if kind in ("package", "symbols"):
            return _PACKAGE
        if kind == "nuspec":
            return _NUSPEC
        return declared

    async def handle_hosted(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        parsed = paths.classify(path)
        if request.method in ("GET", "HEAD"):
            if parsed.kind in ("publish", "symbol-publish", "delete"):
                raise _not_allowed("PUT" if parsed.kind != "delete" else "DELETE")
            return await _read_request(context, request, path, parsed)
        if request.method == "PUT" and parsed.kind in ("publish", "symbol-publish"):
            return await _push(context, request, symbols=parsed.kind == "symbol-publish")
        if request.method == "DELETE" and parsed.kind == "delete":
            if not await _delete_version(context, parsed.id, parsed.version):
                raise _not_found(f"This repository has no {parsed.id} {parsed.version}.")
            return Response(status_code=204)
        if parsed.kind in ("publish", "symbol-publish"):
            raise _not_allowed("PUT")
        if parsed.kind == "delete":
            raise _not_allowed("DELETE")
        raise _not_allowed("GET, HEAD")


register(NuGetFormat())
