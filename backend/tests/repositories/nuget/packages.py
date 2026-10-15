"""NuGet packages made in memory, as `dotnet pack` lays them out, for the tests."""

import io
import zipfile
from xml.sax.saxutils import escape

_DATE = (2026, 1, 1, 0, 0, 0)
NUSPEC_2013 = "http://schemas.microsoft.com/packaging/2013/05/nuspec.xsd"


def nuspec(
    package_id: str = "MegooArti.Hello",
    version: str = "1.0.0",
    *,
    namespace: str = NUSPEC_2013,
    description: str = "Says hello.",
    authors: str = "MegooArti",
    tags: str = "hello greeting",
    dependencies: str = "",
    package_types: str = "",
    more: str = "",
) -> bytes:
    """A `.nuspec`: `dependencies` and `package_types` are their elements' inner XML."""
    parts = [
        f"<id>{escape(package_id)}</id>",
        f"<version>{escape(version)}</version>",
        f"<authors>{escape(authors)}</authors>",
        f"<description>{escape(description)}</description>",
        f"<tags>{escape(tags)}</tags>" if tags else "",
        f"<dependencies>{dependencies}</dependencies>" if dependencies else "",
        f"<packageTypes>{package_types}</packageTypes>" if package_types else "",
        more,
    ]
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<package xmlns="{namespace}"><metadata>{"".join(parts)}</metadata></package>\n'
    ).encode()


def nupkg(
    package_id: str = "MegooArti.Hello",
    version: str = "1.0.0",
    *,
    spec: bytes | None = None,
    files: dict[str, bytes] | None = None,
    method: int = zipfile.ZIP_DEFLATED,
    **fields: str,
) -> bytes:
    """A package: its `.nuspec` at the top, a library, and what NuGet's packer adds."""
    written = io.BytesIO()
    with zipfile.ZipFile(written, "w", compression=method) as archive:

        def add(name: str, data: bytes) -> None:
            # A fixed date, so that the same arguments always give the same bytes.
            archive.writestr(zipfile.ZipInfo(name, date_time=_DATE), data, compress_type=method)

        add("_rels/.rels", b"<Relationships/>")
        add(
            f"{package_id}.nuspec",
            spec if spec is not None else nuspec(package_id, version, **fields),
        )
        add("lib/net8.0/Hello.dll", b"MZ" + b"\0" * 64)
        add("[Content_Types].xml", b"<Types/>")
        for name, data in (files or {}).items():
            add(name, data)
    return written.getvalue()


def snupkg(package_id: str = "MegooArti.Hello", version: str = "1.0.0") -> bytes:
    """A symbol package of a package: its `.nuspec` says `SymbolsPackage`."""
    spec = nuspec(package_id, version, package_types='<packageType name="SymbolsPackage"/>')
    return nupkg(package_id, version, spec=spec, files={"lib/net8.0/Hello.pdb": b"BSJB"})


def reader(data: bytes):
    """What `packages.read` asks for its bytes by, from bytes in memory."""

    async def read(start: int, length: int) -> bytes:
        return data[start : start + length]

    return read
