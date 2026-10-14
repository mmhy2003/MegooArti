"""Debian packages made in memory, as dpkg-deb writes them, and the real ones it wrote."""

import gzip
import io
import lzma
import tarfile
from collections.abc import AsyncIterator
from pathlib import Path

import zstandard

DATA = Path(__file__).parent / "data"
# Four packages dpkg-deb 1.22 wrote, one for each way it compresses a control archive,
# and the index dpkg-scanpackages wrote of them. `data/make.sh` says how.
REAL = {
    "gzip": "megooarti-hello_1.0-1_all.deb",
    "xz": "megooarti-hello_2.0~rc1-1_amd64.deb",
    "zstd": "megooarti-tool_0.3_arm64.deb",
    "none": "megooarti-plain_1.0_amd64.deb",
}


def control_text(
    package: str = "megooarti-hello",
    version: str = "1.0-1",
    architecture: str = "all",
    description: str = "Says hello\n A package made for the tests.",
    extra: str = "",
) -> str:
    return (
        f"Package: {package}\nVersion: {version}\nArchitecture: {architecture}\n"
        "Maintainer: MegooArti Tests <tests@example.com>\nInstalled-Size: 1\n"
        f"{extra}Description: {description}\n"
    )


def ar(members: list[tuple[str, bytes]]) -> bytes:
    """An ar archive, as dpkg-deb writes one."""
    out = bytearray(b"!<arch>\n")
    for name, data in members:
        header = f"{name:<16}{0:<12}{0:<6}{0:<6}{100644:<8}{len(data):<10}`\n"
        out += header.encode("ascii") + data + (b"\n" if len(data) % 2 else b"")
    return bytes(out)


def tar_of(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for name, data in files.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            tar.addfile(entry, io.BytesIO(data))
    return buffer.getvalue()


def compressed(data: bytes, compression: str) -> tuple[str, bytes]:
    """The control archive's name and bytes for a way of compressing it."""
    if compression == "gz":
        return "control.tar.gz", gzip.compress(data, mtime=0)
    if compression == "xz":
        return "control.tar.xz", lzma.compress(data)
    if compression == "zst":
        return "control.tar.zst", zstandard.ZstdCompressor().compress(data)
    return "control.tar", data


def make_deb(
    control: str | None = None,
    *,
    compression: str = "gz",
    data: bytes = b"the files of the package",
    before_control: list[tuple[str, bytes]] | None = None,
) -> bytes:
    """A package whose control file is `control`, compressed as dpkg-deb can."""
    archive = tar_of({"./control": (control or control_text()).encode()})
    name, packed = compressed(archive, compression)
    return ar(
        [
            ("debian-binary", b"2.0\n"),
            *(before_control or []),
            (name, packed),
            ("data.tar.xz", lzma.compress(data)),
        ]
    )


async def pieces(data: bytes, size: int = 7) -> AsyncIterator[bytes]:
    """Bytes as they arrive: a few at a time."""
    for start in range(0, len(data), size):
        yield data[start : start + size]
