"""What a path of an APT repository is, and where a package is kept.

The standard layout, as Debian's mirrors have it:

    dists/<suite>/InRelease, Release, Release.gpg
    dists/<suite>/main/binary-<arch>/Packages, Packages.gz, Packages.xz
    pool/main/<letter>/<package>/<package>_<version>_<arch>.deb

plus `public.key`, the key a hosted repository signs with. The root is where a
package is uploaded.
"""

import re
from dataclasses import dataclass

from megooarti.repositories.apt import versions

COMPONENT = "main"
SUITE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
RELEASE_FILES = ("InRelease", "Release", "Release.gpg")
PACKAGES_FILES = {"Packages": "", "Packages.gz": "gz", "Packages.xz": "xz"}
PUBLIC_KEY = "public.key"
_PACKAGES = re.compile(r"dists/([^/]+)/([^/]+)/binary-([^/]+)/(Packages(?:\.gz|\.xz)?)")
_RELEASE = re.compile(r"dists/([^/]+)/(InRelease|Release|Release\.gpg)")


@dataclass(frozen=True)
class AptPath:
    # upload (the root), key, release, packages, pool, dists (anything else there), other
    kind: str
    suite: str = ""
    filename: str = ""
    component: str = ""
    architecture: str = ""


def classify(path: str) -> AptPath:
    if path == "":
        return AptPath("upload")
    if path == PUBLIC_KEY:
        return AptPath("key")
    found = _RELEASE.fullmatch(path)
    if found is not None:
        return AptPath("release", suite=found[1], filename=found[2])
    found = _PACKAGES.fullmatch(path)
    if found is not None:
        return AptPath(
            "packages",
            suite=found[1],
            component=found[2],
            architecture=found[3],
            filename=found[4],
        )
    if path.startswith("dists/"):
        return AptPath("dists")
    if path.startswith("pool/") and path.endswith(".deb"):
        return AptPath("pool")
    return AptPath("other")


def letter(package: str) -> str:
    """The pool's directory for a package: its first letter, or four for a library."""
    return package[:4] if package.startswith("lib") and len(package) > 3 else package[0]


def pool_path(package: str, version: str, architecture: str) -> str:
    """Where a package is kept: Debian's file name, without the version's epoch."""
    filename = f"{package}_{versions.without_epoch(version)}_{architecture}.deb"
    return f"pool/{COMPONENT}/{letter(package)}/{package}/{filename}"


def in_pool(path: str) -> tuple[str, str, str] | None:
    """The package, version and architecture a package's file name says, or None.

    A mirror keeps a package under its source package's directory, which may have
    another name, so only the file's own name is read. Its version has no epoch.
    """
    if not path.startswith("pool/") or not path.endswith(".deb"):
        return None
    parts = path.rpartition("/")[2].removesuffix(".deb").split("_")
    if len(parts) != 3 or not all(parts):
        return None
    package, version, architecture = parts
    return package, version, architecture
