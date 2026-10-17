"""The symbol server of a NuGet repository (section 8 of the spec).

A hosted repository keeps each portable PDB of a symbol package it is given at the
PDB's key, as a file of the package's version, with the PDB's checksum; it serves it to
a debugger that asks for it by that key, and names no other checksum. A proxy with a
symbol server (`format_config.symbol_url`) asks that server for what it does not keep,
with the debugger's checksum, and keeps what it is given. A group asks its members in
order, as the group engine does for any file.
"""

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories import proxy
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.nuget import packages, records, symbols
from megooarti.repositories.nuget.packages import Nuspec
from megooarti.repositories.proxy import Source
from megooarti.storage.backends import StagedBlob

# Where a file's attributes keep a PDB's checksum.
CHECKSUM = "symbol_checksum"
_PDB = "application/octet-stream"
_HEADER = "SymbolChecksum"


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "This repository has no such symbol file.")


async def staged_pdbs(
    context: RepositoryContext, read: packages.Read, size: int
) -> list[tuple[symbols.Pdb, StagedBlob]]:
    """Each portable PDB of a symbol package, read and staged one at a time. Raises
    InvalidPackage, with nothing left staged, for one that is not a portable PDB."""
    found = await symbols.entries(read, size)
    staged: list[tuple[symbols.Pdb, StagedBlob]] = []
    try:
        for entry in found:
            data = await packages.extract(read, entry, symbols.PDB_MOST)
            pdb = symbols.read(entry.name, data)
            if all(pdb.path != kept.path for kept, _ in staged):
                staged.append((pdb, await context.stage_bytes(data)))
    except BaseException:
        for _, blob in staged:
            await context.discard(blob)
        raise
    return staged


async def keep(
    context: RepositoryContext, nuspec: Nuspec, staged: list[tuple[symbols.Pdb, StagedBlob]]
) -> None:
    """A version's PDBs, each at its key, in place of those it had."""
    said = nuspec.as_json()
    paths = {pdb.path for pdb, _ in staged}
    for held in await context.files("", nuspec.id, nuspec.version.lower()):
        if symbols.is_path(held.path) and held.path not in paths:
            await context.delete(held.path)
    for pdb, blob in staged:
        await context.store(
            pdb.path,
            blob,
            content_type=_PDB,
            attributes={records.DECLARED: said, CHECKSUM: pdb.checksum},
        )


async def _respond(context: RepositoryContext, request: Request, path: str) -> Response:
    """A PDB this repository keeps, if the checksums the debugger names include its own."""
    asset = await context.get(path)
    if asset is None:
        raise _not_found()
    wanted = symbols.asked(request.headers.get(_HEADER))
    if wanted is not None and (asset.attributes or {}).get(CHECKSUM) not in wanted:
        raise _not_found()
    return await context.respond(path, request)


async def serve(context: RepositoryContext, request: Request, path: str) -> Response:
    """`symbols/<name>/<key>/<name>` of a hosted repository."""
    return await _respond(context, request, path)


async def serve_proxy(context: RepositoryContext, request: Request, path: str) -> Response:
    """`symbols/<name>/<key>/<name>` of a proxy: asked of its symbol server, with the
    debugger's checksum, and kept. A proxy without a symbol server has none."""
    server = context.repository.config.get("format_config", {}).get("symbol_url")
    if not server:
        raise _not_found()
    header = request.headers.get(_HEADER)
    source = Source(
        f"{server}/{path.removeprefix(symbols.PREFIX)}",
        headers={_HEADER: header} if header else {},
        # A server that has no file for one checksum may have it for another.
        remember_missing=False,
    )
    await proxy.ensure_cached(context, path, source=source)
    return await _respond(context, request, path)


async def checksum_of(context: RepositoryContext, path: str, staged: StagedBlob) -> dict:
    """What a proxy keeps of a PDB it fetched: its checksum, if it is a portable PDB."""
    data = await context.read_staged(staged, limit=symbols.PDB_MOST)
    if data is None:
        return {}
    try:
        return {CHECKSUM: symbols.read(path.rsplit("/", 1)[-1], data).checksum}
    except packages.InvalidPackage:
        return {}
