"""What is read of a NuGet package: its zip's directory and its `.nuspec`, to their bounds."""

import os
import struct
import zipfile

import pytest

from megooarti.repositories.nuget import packages
from tests.repositories.nuget.packages import NUSPEC_2013, nupkg, nuspec, reader, snupkg


async def read(data: bytes) -> packages.Nuspec:
    return (await packages.read(reader(data), len(data))).nuspec


def forged_central(data: bytes, name: bytes, at_field: int, value: int) -> bytes:
    """`data` with one field of the central directory entry called `name` replaced."""
    at = data.find(b"PK\x01\x02")
    while data[at + 46 : at + 46 + len(name)] != name:
        at = data.find(b"PK\x01\x02", at + 1)
    return data[: at + at_field] + struct.pack("<I", value) + data[at + at_field + 4 :]


async def test_the_nuspec_itself_is_kept_as_the_package_has_it():
    spec = nuspec(description="Kept as it is.")

    assert (await packages.read(reader(nupkg(spec=spec)), len(nupkg(spec=spec)))).spec == spec


async def test_a_package_says_its_id_version_and_what_its_feed_publishes():
    dependencies = (
        '<group targetFramework="net8.0">'
        '<dependency id="Newtonsoft.Json" version="13.0.1"/>'
        '<dependency id="Serilog" version="[3.0, 4.0)"/>'
        "</group>"
        '<group targetFramework="netstandard2.0"/>'
    )
    more = (
        "<title>Hello</title><projectUrl>https://example.com/hello</projectUrl>"
        '<license type="expression">MIT</license>'
        "<requireLicenseAcceptance>true</requireLicenseAcceptance>"
    )
    said = await read(
        nupkg("MegooArti.Hello", "01.2.0-Beta.1", dependencies=dependencies, more=more)
    )

    assert (said.id, said.version, said.original_version) == (
        "MegooArti.Hello",
        "1.2.0-Beta.1",
        "01.2.0-Beta.1",
    )
    assert (said.title, said.description, said.tags) == ("Hello", "Says hello.", "hello greeting")
    assert (said.license_expression, said.require_license_acceptance) == ("MIT", True)
    assert said.project_url == "https://example.com/hello"
    assert said.dependency_groups == (
        packages.DependencyGroup(
            "net8.0",
            (
                packages.Dependency("Newtonsoft.Json", "[13.0.1, )"),
                packages.Dependency("Serilog", "[3.0, 4.0)"),
            ),
        ),
        packages.DependencyGroup("netstandard2.0"),
    )
    assert said.is_prerelease and not said.is_symbols
    assert packages.Nuspec.from_json(said.as_json()) == said


@pytest.mark.parametrize(
    "namespace",
    [
        "http://schemas.microsoft.com/packaging/2010/07/nuspec.xsd",
        "http://schemas.microsoft.com/packaging/2011/08/nuspec.xsd",
        "",
    ],
)
async def test_every_schema_of_the_nuspec_is_read_alike(namespace):
    spec = (
        nuspec(namespace=namespace)
        if namespace
        else nuspec().replace(f' xmlns="{NUSPEC_2013}"'.encode(), b"")
    )
    assert (b"xmlns" in spec) == bool(namespace)
    said = await read(nupkg(spec=spec))

    assert (said.id, said.version) == ("MegooArti.Hello", "1.0.0")


async def test_dependencies_without_groups_are_for_every_framework():
    said = await read(nupkg(dependencies='<dependency id="Serilog" version="3.0.0"/>'))

    assert said.dependency_groups == (
        packages.DependencyGroup("", (packages.Dependency("Serilog", "[3.0.0, )"),)),
    )


async def test_a_symbol_package_says_so_and_a_stored_zip_is_read_too():
    assert (await read(snupkg())).is_symbols
    assert (await read(nupkg(method=zipfile.ZIP_STORED))).id == "MegooArti.Hello"


@pytest.mark.parametrize(
    ("data", "said"),
    [
        (b"not a zip at all", "it is not a zip file"),
        (nupkg(spec=nuspec(package_id="Hel lo")), "its id is not one NuGet takes"),
        (nupkg(spec=nuspec(version="one")), "its version is not one NuGet takes"),
        (nupkg(spec=b"<package/>"), "its .nuspec has no <package><metadata>"),
        (nupkg(spec=b"<package><metadata>"), "its .nuspec is not well-formed XML"),
        (
            nupkg(spec=b'<!DOCTYPE p [<!ENTITY a "a">]><package/>'),
            "its .nuspec has a DOCTYPE, which is not allowed",
        ),
        (nupkg(files={"Other.nuspec": nuspec()}), "it does not have exactly one .nuspec"),
        (
            nupkg(spec=nuspec(description="x" * (packages.NUSPEC_MOST + 1))),
            ".nuspec is larger than",
        ),
    ],
    ids=["no-zip", "id", "version", "no-metadata", "broken", "doctype", "two", "too-large"],
)
async def test_what_is_not_a_package_that_can_be_accepted_is_refused_and_says_why(data, said):
    with pytest.raises(packages.InvalidPackage, match=said):
        await read(data)


async def test_a_zip_with_too_many_files_is_refused_before_its_directory_is_read():
    data = nupkg()
    end = data.rfind(b"PK\x05\x06")
    count = packages.ENTRIES_MOST + 1
    forged = data[: end + 8] + struct.pack("<HH", count, count) + data[end + 12 :]

    with pytest.raises(packages.InvalidPackage, match="more than 10000 files"):
        await read(forged)


async def test_a_zip64_file_is_refused_with_a_message_that_says_so():
    data = nupkg()
    end = data.rfind(b"PK\x05\x06")
    forged = data[: end + 16] + b"\xff\xff\xff\xff" + data[end + 20 :]

    with pytest.raises(packages.InvalidPackage, match="ZIP64"):
        await read(forged)


async def test_only_what_is_needed_is_read_of_a_package():
    data = nupkg(files={"content/large.bin": os.urandom(5_000_000)})
    asked = []

    async def counted(start: int, length: int) -> bytes:
        asked.append(length)
        return data[start : start + length]

    assert len(data) > 5_000_000  # incompressible, so the whole package is not in the tail
    await packages.read(counted, len(data))

    assert sum(asked) < 70_000 + 20_000  # the tail, the directory and the .nuspec


@pytest.mark.parametrize("method", [zipfile.ZIP_DEFLATED, zipfile.ZIP_STORED])
async def test_a_forged_compressed_size_is_refused_before_anything_large_is_read(method):
    data = forged_central(nupkg(method=method), b"MegooArti.Hello.nuspec", 20, 0xFFFF_FFF0)
    asked = []

    async def counted(start: int, length: int) -> bytes:
        asked.append(length)
        return data[start : start + length]

    with pytest.raises(packages.InvalidPackage, match="compressed size"):
        await packages.read(counted, len(data))

    assert max(asked) < 100_000
