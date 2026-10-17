"""What is kept of a NuGet package's `.nuspec`, and the versions it describes."""

from collections.abc import Sequence
from typing import Any

from megooarti.repositories.content import ComponentInfo
from megooarti.repositories.nuget import packages
from megooarti.repositories.nuget.documents import Published

# Where what a package said of itself is kept, among a file's attributes and among its
# version's component's.
DECLARED = "nuget"
# Where a version's package's size and SHA-512 are kept, among its component's attributes.
PACKAGE = "nuget_package"


def nuspec_of(attributes: dict[str, Any] | None) -> packages.Nuspec | None:
    said = (attributes or {}).get(DECLARED)
    return packages.Nuspec.from_json(said) if isinstance(said, dict) else None


def published(held: Sequence[ComponentInfo]) -> list[Published]:
    """The versions held that a package's `.nuspec` describes, with when each was pushed
    and what is known of its package."""
    found = []
    for one in held:
        nuspec = nuspec_of(one.attributes)
        if nuspec is None:
            continue
        package = (one.attributes or {}).get(PACKAGE)
        package = package if isinstance(package, dict) else {}
        size, sha512 = package.get("size"), package.get("sha512")
        found.append(
            Published(
                nuspec,
                one.created,
                size if isinstance(size, int) else 0,
                sha512 if isinstance(sha512, str) else "",
            )
        )
    return found
