"""What a path of a YUM repository is.

Packages are where their uploaders put them. A hosted repository's `repodata_depth`
says where the `repodata/` directories are: at depth 0, one at the root for every
package; at depth 2, one in each directory two levels down (`el9/x86_64/repodata/`),
for the packages under it. Beside them is `public.key`, the key a hosted repository
signs with.
"""

import re
from dataclasses import dataclass

from megooarti.repositories.yum import versions

PUBLIC_KEY = "public.key"
REPOMD = "repomd.xml"
SIGNATURE = "repomd.xml.asc"
DEPTH_MOST = 5
# A `repodata/` file named by its hash, which never changes.
HASHED = re.compile(r"[0-9a-f]{32,128}-[^/]+")


@dataclass(frozen=True)
class YumPath:
    kind: str  # key, repodata, package, other
    directory: str = ""  # of a package: the directory its repodata is in; of repodata, its own
    filename: str = ""


def repodata_of(path: str) -> tuple[str, str] | None:
    """The directory and the file's name of a path in a `repodata/`, or None."""
    directory, _, rest = ("/" + path).rpartition("/repodata/")
    if not rest or "/" in rest:
        return None
    return directory.removeprefix("/"), rest


def directory_of(path: str, depth: int) -> str | None:
    """The directory whose `repodata/` lists a package, or None if it is not that deep."""
    parts = path.split("/")[:-1]
    if len(parts) < depth:
        return None
    return "/".join(parts[:depth])


def classify(path: str, depth: int = 0) -> YumPath:
    if path == PUBLIC_KEY:
        return YumPath("key")
    found = repodata_of(path)
    if found is not None:
        return YumPath("repodata", found[0], found[1])
    if path.endswith(".rpm") and "/repodata/" not in f"/{path}":
        directory = directory_of(path, depth)
        return YumPath("package", directory or "", path.rpartition("/")[2])
    return YumPath("other")


def deep_enough(path: str, depth: int) -> bool:
    return directory_of(path, depth) is not None


def at_depth(directory: str, depth: int) -> bool:
    """Whether a directory is one that has a `repodata/` at this depth."""
    return len(directory.split("/")) == depth if directory else depth == 0


def in_repodata(directory: str, filename: str) -> str:
    """A `repodata/` file's path."""
    return f"{directory}/repodata/{filename}" if directory else f"repodata/{filename}"


def named(path: str) -> tuple[str, str, str] | None:
    """The name, `version-release` and architecture an RPM's file name says, or None.

    `name-version-release.arch.rpm`: the version and release are the last two parts
    before the architecture, as rpm itself names its files. A name says no epoch.
    """
    filename = path.rpartition("/")[2]
    if not filename.endswith(".rpm"):
        return None
    stem, _, arch = filename.removesuffix(".rpm").rpartition(".")
    name, _, rest = stem.rpartition("-")
    name, _, version = name.rpartition("-")
    if not (name and version and rest and arch) or versions.NAME.fullmatch(name) is None:
        return None
    return name, f"{version}-{rest}", arch


def hashed(filename: str) -> bool:
    return HASHED.fullmatch(filename) is not None
