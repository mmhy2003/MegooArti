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

import xml.sax.saxutils
from collections.abc import Sequence
from contextlib import aclosing
from dataclasses import replace
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories import forms, service
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.formats import (
    ComponentKey,
    Format,
    Serve,
    Usage,
    invalid_upload,
    managed_by_format,
    only_fields,
    plain,
    register,
)
from megooarti.repositories.models import Repository
from megooarti.repositories.nuget import (
    documents,
    feeds,
    grouped,
    packages,
    paths,
    proxied,
    proxied_v2,
    queries,
    records,
    responses,
    symbol_server,
    v2,
    versions,
)
from megooarti.repositories.nuget.documents import Published
from megooarti.storage.backends import StagedBlob

_PACKAGE = "application/octet-stream"
_NUSPEC = "application/xml"
_PLAIN_HTTP = (
    "# Over plain HTTP: --allow-insecure-connections is the .NET SDK 9's and later's;"
    " with .NET 8, leave it out."
)


def _invalid(reason: object) -> ApiError:
    return ApiError(400, "invalid_package", f"The package cannot be accepted: {reason}.")


def _not_found(message: str = "Nothing is served at this address.") -> ApiError:
    return ApiError(404, "not_found", message)


def _not_allowed(allowed: str) -> ApiError:
    return ApiError(
        405, "method_not_allowed", f"This address accepts {allowed}.", headers={"Allow": allowed}
    )


# --- Pushing ------------------------------------------------------------------------


def _ranges(context: RepositoryContext, staged: StagedBlob) -> packages.Read:
    """A staged package's bytes by position: it is read from its start each time.

    A package is read four times at the most (its end, its directory, a local header and
    its `.nuspec`'s data), and only those bytes are kept. Each reading closes the file at
    once: a file that is still open cannot be moved into the store, or removed, on every
    system.
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
    await context.lock(f"id:{nuspec.id.lower()}")
    spelling = await context.spelling("", nuspec.id)
    return nuspec if spelling is None or spelling == nuspec.id else replace(nuspec, id=spelling)


async def _keep_package(
    context: RepositoryContext, staged: StagedBlob, package: packages.Package
) -> bool:
    """A package and its `.nuspec`, each at its path. Returns whether the version is new."""
    nuspec = await _spelled(context, package.nuspec)
    said = {records.DECLARED: nuspec.as_json()}
    known = {**said, records.PACKAGE: {"size": staged.size, "sha512": staged.sha512}}
    _, created = await context.store(
        paths.package_path(nuspec.id, nuspec.version),
        staged,
        content_type=_PACKAGE,
        attributes=said,
        component_attributes=known,
    )
    spec = await context.stage_bytes(package.spec)
    await context.store(
        paths.nuspec_path(nuspec.id, nuspec.version), spec, content_type=_NUSPEC, attributes=said
    )
    return created


async def _keep_symbols(
    context: RepositoryContext, staged: StagedBlob, package: packages.Package
) -> bool:
    """A symbol package, beside the package it is of: that must be here. Each of its
    portable PDBs is kept at its key, as a file of the version (section 8)."""
    nuspec = await _spelled(context, package.nuspec)
    if await context.stat(paths.package_path(nuspec.id, nuspec.version)) is None:
        await context.discard(staged)
        raise _not_found(
            f"This repository has no {nuspec.id} {nuspec.version}: push the package first."
        )
    try:
        pdbs = await symbol_server.staged_pdbs(context, _ranges(context, staged), staged.size)
    except packages.InvalidPackage as error:
        await context.discard(staged)
        raise _invalid(error) from None
    try:
        _, created = await context.store(
            paths.symbols_path(nuspec.id, nuspec.version),
            staged,
            content_type=_PACKAGE,
            attributes={records.DECLARED: nuspec.as_json()},
        )
        await symbol_server.keep(context, nuspec, pdbs)
    except BaseException:
        for _, blob in pdbs:
            await context.discard(blob)
        raise
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


async def _held(context: RepositoryContext, package_id: str) -> list[Published]:
    """Every version of an id this repository holds. Raises 404 for none."""
    spelling = await context.spelling("", package_id)
    held = [] if spelling is None else records.published(await context.components("", spelling))
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
    base = await responses.base(context, request)
    if len(listed) > documents.INLINED_MOST:
        return await responses.respond_json(
            context, request, documents.registration_pages(base, package_id, listed)
        )
    held = records.published(await context.components("", spelling))
    if not held:
        # Its last version went between the two reads.
        raise _not_found(f"This repository has no package {package_id}.")
    return await responses.respond_json(context, request, documents.registration(base, held))


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
        for one in records.published(await context.components("", spelling))
        if one.nuspec.version.lower() in set(wanted)
    ]
    base = await responses.base(context, request)
    page = documents.registration_page(base, parsed.id, held, parsed.lower, parsed.upper)
    return await responses.respond_json(context, request, page)


async def _search(context: RepositoryContext, request: Request) -> Response:
    base = await responses.base(context, request)
    found, total = await feeds.hosted_search(context, queries.parse(request.query_params), base)
    return await responses.respond_json(context, request, {"totalHits": total, "data": found})


async def _autocomplete(context: RepositoryContext, request: Request) -> Response:
    """Ids that contain what was typed; or, given an `id`, its versions."""
    arguments = request.query_params
    prerelease = arguments.get("prerelease", "").lower() == "true"
    if "id" in arguments:
        spelling = await context.spelling("", arguments["id"])
        held = [] if spelling is None else records.published(await context.components("", spelling))
        shown = versions.ordered(
            [one.nuspec.version for one in held if prerelease or not one.nuspec.is_prerelease]
        )
        return await responses.respond_json(
            context, request, documents.autocomplete(shown, len(shown))
        )
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
    return await responses.respond_json(context, request, documents.autocomplete(ids, total))


async def _read_request(
    context: RepositoryContext, request: Request, path: str, parsed: paths.NuGetPath
) -> Response:
    if parsed.kind == "service-index":
        return await responses.respond_json(
            context, request, documents.service_index(await responses.base(context, request))
        )
    if parsed.kind in ("package", "nuspec", "symbols"):
        return await context.respond(path, request)
    if parsed.kind == "versions":
        # Written from the versions alone: what each said of itself is not read.
        spelling = await context.spelling("", parsed.id)
        listed = [] if spelling is None else list(await context.versions("", spelling))
        if not listed:
            raise _not_found(f"This repository has no package {parsed.id}.")
        return await responses.respond_json(context, request, documents.version_list(listed))
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
        return await responses.respond_json(
            context, request, documents.leaf(await responses.base(context, request), held[0])
        )
    if parsed.kind == "search":
        return await _search(context, request)
    if parsed.kind == "autocomplete":
        return await _autocomplete(context, request)
    if parsed.kind == "v2":
        return await v2.answer(context, request, path)
    if parsed.kind == "download":
        return await v2.download(context, request, parsed)
    if parsed.kind == "symbol":
        return await symbol_server.serve(context, request, path)
    raise _not_found()


# --- Setting a machine up -----------------------------------------------------------


def _element(name: str) -> str:
    """A source's name as an element of `nuget.config`, as NuGet encodes one."""
    first = name[0]
    if first.isalpha() or first == "_":
        return name
    return f"_x{ord(first):04X}_{name[1:]}"


def setup_of(address: str, name: str, *, v3: bool = True) -> list[Usage]:
    """The repository as a source of `dotnet`, by its command and in `nuget.config`; of
    Chocolatey; and of PowerShell's PSResourceGet. `v3` is false for a proxy of a V2
    feed, which serves V2 alone: its sources are then its V2 address."""
    source = f"{address}index.json" if v3 else address
    command = (
        f'dotnet nuget add source "{source}" --name {name} \\\n'
        '  --username "$MEGOOARTI_USER" --password "$MEGOOARTI_TOKEN" '
        "--store-password-in-clear-text"
    )
    plain_http = source.startswith("http://")
    if plain_http:
        # NuGet refuses a plain-HTTP source that is not marked so (NU1302).
        command = f"{_PLAIN_HTTP}\n{command} \\\n  --allow-insecure-connections"
    insecure = ' allowInsecureConnections="true"' if plain_http else ""
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
    # Chocolatey is given V2's address, to which a push goes straight.
    chocolatey = (
        f'choco source add --name="{name}" --source="{address}" \\\n'
        '  --user="$MEGOOARTI_USER" --password="$MEGOOARTI_TOKEN"'
    )
    # PSResourceGet knows V3 by its index.json, and is told V2; it adds a slash itself.
    uri = f'"{source}"' if v3 else f'"{address.rstrip("/")}" -ApiVersion v2'
    powershell = (
        f"Register-PSResourceRepository -Name {name} -Uri {uri} -Trusted\n"
        "# Your user name, and an API token as the password, with each command:\n"
        "$credential = Get-Credential -UserName $env:MEGOOARTI_USER\n"
        f"Find-PSResource -Repository {name} -Credential $credential"
    )
    return [
        Usage("dotnet", "shell", command),
        Usage("nuget.config", "xml", config),
        Usage("Chocolatey", "shell", chocolatey),
        Usage("PowerShell", "powershell", powershell),
        Usage("Symbols", "shell", symbols_of(address)),
    ]


def symbols_of(address: str) -> str:
    """The repository as a symbol server: of Visual Studio, and of `dotnet-symbol`."""
    server = f"{address}symbols/"
    return (
        f"# Visual Studio: Tools > Options > Debugging > Symbols, add {server}\n"
        f'dotnet-symbol --authenticated-server-path "$MEGOOARTI_TOKEN" {server} \\\n'
        "  --symbols MyApp.dll"
    )


# The protocols a proxy may speak to its remote, and serve: chosen once (D2).
PROTOCOLS = ("v3", "v2")


def _invalid_setting(field: str, message: str) -> ApiError:
    details = [{"field": field, "message": message}]
    return ApiError(422, "validation_error", "The request is not valid.", details)


def proxy_settings(config: dict[str, Any], current: dict[str, Any] | None) -> dict[str, Any]:
    """A proxy's protocol, fixed once it is made, and the symbol server it may proxy."""
    unknown = sorted(set(config) - {"protocol", "symbol_url"})
    if unknown:
        raise _invalid_setting(f"format_config.{unknown[0]}", "This is not a setting of NuGet.")
    stored = "v3" if current is None else current.get("protocol", "v3")
    protocol = config.get("protocol", stored)
    if protocol not in PROTOCOLS:
        raise _invalid_setting(
            "format_config.protocol", "A NuGet proxy speaks v3 or v2 to its remote."
        )
    if current is not None and protocol != stored:
        raise _invalid_setting(
            "format_config.protocol", "The protocol cannot change once the proxy is made."
        )
    settings: dict[str, Any] = {"protocol": protocol}
    symbol_url = config.get("symbol_url")
    if symbol_url:
        if not isinstance(symbol_url, str) or service.remote_origin(symbol_url.strip()) is None:
            raise _invalid_setting(
                "format_config.symbol_url",
                "Give an http or https address with a host, and without credentials, a "
                "query or a fragment.",
            )
        settings["symbol_url"] = symbol_url.strip().rstrip("/")
    return settings


async def describe_fetched(
    context: RepositoryContext, path: str, staged: StagedBlob
) -> dict[str, Any]:
    """A package or a `.nuspec` a proxy fetched, read as a pushed one is: what its
    `.nuspec` says. Nothing for what cannot be read: it is the remote's."""
    kind = paths.classify(path).kind
    try:
        if kind == "symbol":
            return await symbol_server.checksum_of(context, path, staged)
        if kind == "package":
            nuspec = (await packages.read(_ranges(context, staged), staged.size)).nuspec
        elif kind == "nuspec":
            spec = await context.read_staged(staged, limit=packages.NUSPEC_MOST)
            if spec is None:
                return {}
            nuspec = packages.parse_nuspec(spec)
        else:
            return {}
    except packages.InvalidPackage:
        return {}
    return {records.DECLARED: nuspec.as_json()}


class NuGetFormat(Format):
    name = "nuget"
    types = frozenset({"hosted", "proxy", "group"})
    derives_indexes = True

    def validate_config(
        self, repository_type: str, config: dict[str, Any], current: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """A proxy's settings; a hosted repository has none."""
        if repository_type == "proxy":
            return proxy_settings(config, current)
        return super().validate_config(repository_type, config, current)

    async def describe_fetched(
        self, context: RepositoryContext, path: str, staged: StagedBlob
    ) -> dict[str, Any]:
        return await describe_fetched(context, path, staged)

    def is_metadata(self, path: str) -> bool:
        """An id's versions, its registration, NuGet Audit's data, a V2 feed's answers and
        what the remote says of itself change as packages are published; packages and their
        `.nuspec` do not."""
        if path.startswith(proxied_v2.KEPT) or path.startswith(paths.REGISTRATION):
            return True
        if path.startswith(paths.VULNERABILITIES):
            return True
        return path.startswith(paths.PACKAGES) and path.endswith("/index.json")

    async def handle_proxy(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        path = paths.v2_path(path)
        if paths.classify(path).kind == "symbol":
            return await symbol_server.serve_proxy(context, request, path)
        if context.repository.config.get("format_config", {}).get("protocol") == "v2":
            return await proxied_v2.handle_proxy(context, request, path)
        return await proxied.handle_proxy(context, request, path)

    async def handle_group(
        self, context: RepositoryContext, request: Request, path: str, serve: Serve
    ) -> Response:
        return await grouped.handle_group(context, request, paths.v2_path(path), serve)

    def default_deployment_policy(self, config: dict[str, Any]) -> str:
        """A version is pushed once, as nuget.org takes it: a second push is `409`."""
        return "disable_redeploy"

    def describe_component(
        self, path: str, attributes: dict[str, Any] | None = None
    ) -> ComponentKey | None:
        """A package's files belong to its id and version: as its `.nuspec` said, or its path."""
        nuspec = records.nuspec_of(attributes)
        if nuspec is not None:
            return ComponentKey("", nuspec.id, nuspec.version.lower())
        parsed = paths.classify(path)
        if parsed.kind in ("package", "nuspec", "symbols"):
            return ComponentKey("", parsed.id, parsed.version)
        return None

    def search_text(self, key: ComponentKey, attributes: dict[str, Any]) -> str:
        """Its id and version, and the words of its `.nuspec` that NuGet's search reads."""
        nuspec = records.nuspec_of(attributes)
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
        """A package goes with its version's every file; its `.nuspec` goes with it, and
        a symbol package's PDBs with it."""
        parsed = paths.classify(path)
        if parsed.kind == "package":
            return await _delete_version(context, parsed.id, parsed.version)
        if parsed.kind == "symbols":
            spelling = await context.spelling("", parsed.id)
            held = [] if spelling is None else await context.files("", spelling, parsed.version)
            for one in held:
                if paths.classify(one.path).kind == "symbol":
                    await context.delete(one.path)
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
            Usage("Chocolatey", "shell", f"choco install {key.name} --version {key.version}"),
            Usage(
                "PowerShell",
                "powershell",
                f"Install-PSResource {key.name} -Version {key.version}",
            ),
        ]

    def setup(self, address: str, repository: Repository) -> list[Usage]:
        protocol = repository.config.get("format_config", {}).get("protocol", "v3")
        v3 = repository.type != "proxy" or protocol == "v3"
        return setup_of(address, repository.name, v3=v3)

    def content_type(self, path: str, declared: str | None) -> str | None:
        kind = paths.classify(path).kind
        if kind in ("package", "symbols", "symbol"):
            return _PACKAGE
        if kind == "nuspec":
            return _NUSPEC
        return declared

    async def handle_hosted(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        path = paths.v2_path(path)
        parsed = paths.classify(path)
        if request.method in ("GET", "HEAD"):
            if parsed.kind in ("publish", "symbol-publish", "delete"):
                raise _not_allowed("PUT" if parsed.kind != "delete" else "DELETE")
            return await _read_request(context, request, path, parsed)
        if request.method == "PUT" and parsed.kind in ("publish", "symbol-publish"):
            return await _push(context, request, symbols=parsed.kind == "symbol-publish")
        if request.method == "PUT" and path == "":
            # A V2 client pushes to the address it is given: the repository's own.
            return await _push(context, request, symbols=False)
        deleted = paths.v2_delete(path) if request.method == "DELETE" else None
        if request.method == "DELETE" and (parsed.kind == "delete" or deleted is not None):
            package_id, version = (parsed.id, parsed.version) if deleted is None else deleted
            if not await _delete_version(context, package_id, version):
                raise _not_found(f"This repository has no {package_id} {version}.")
            return Response(status_code=204)
        if parsed.kind in ("publish", "symbol-publish"):
            raise _not_allowed("PUT")
        if parsed.kind == "delete":
            raise _not_allowed("DELETE")
        raise _not_allowed("GET, HEAD")


register(NuGetFormat())
