"""What is kept of a NuGet package's `.nuspec`, and the versions it describes."""

from collections.abc import Sequence
from typing import Any

from megooarti.repositories.content import ComponentInfo
from megooarti.repositories.nuget import packages
from megooarti.repositories.nuget.documents import Published

# Where what a package said of itself is kept, among a file's attributes and among its
# version's component's.
DECLARED = "nuget"


def nuspec_of(attributes: dict[str, Any] | None) -> packages.Nuspec | None:
    said = (attributes or {}).get(DECLARED)
    return packages.Nuspec.from_json(said) if isinstance(said, dict) else None


def published(held: Sequence[ComponentInfo]) -> list[Published]:
    """The versions held that a package's `.nuspec` describes, with when each was pushed."""
    return [
        Published(nuspec, one.created)
        for one in held
        if (nuspec := nuspec_of(one.attributes)) is not None
    ]
