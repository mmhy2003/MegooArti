"""What a path of an apk repository is.

As Alpine's mirrors have them: packages at `<any path>/<architecture>/<name>-<version>.apk`
and an `APKINDEX.tar.gz` in each architecture's directory. A client lists the path
above the architectures (`.../v3.24/main`), and apk adds `/<architecture>/...` itself.
Beside them, at the root, is the key a hosted repository signs with, under the name a
client saves it as: `megooarti-<repository>.rsa.pub`.
"""

from dataclasses import dataclass

from megooarti.repositories.apk import versions
from megooarti.repositories.apk.index import INDEX


@dataclass(frozen=True)
class ApkPath:
    kind: str  # key, index, package, other
    directory: str = ""  # an index's or a package's
    filename: str = ""

    @property
    def architecture(self) -> str:
        """The directory's last part: the architecture its packages are for."""
        return self.directory.rpartition("/")[2]


def key_name(repository: str) -> str:
    """The file a client saves a repository's key as, and finds it by."""
    return f"megooarti-{repository}.rsa.pub"


def classify(path: str, repository: str) -> ApkPath:
    directory, _, filename = path.rpartition("/")
    if path == key_name(repository):
        return ApkPath("key", filename=filename)
    if filename == INDEX:
        return ApkPath("index", directory, filename)
    if filename.endswith(".apk") and directory:
        return ApkPath("package", directory, filename)
    return ApkPath("other", directory, filename)


def in_directory(directory: str, filename: str) -> str:
    return f"{directory}/{filename}" if directory else filename


def named(path: str) -> tuple[str, str] | None:
    """The name and version a package's file name says, or None.

    `<name>-<version>-r<release>.apk`: the version is the last two parts, as apk names
    its files.
    """
    filename = path.rpartition("/")[2]
    if not filename.endswith(".apk"):
        return None
    stem = filename.removesuffix(".apk")
    rest, _, release = stem.rpartition("-")
    name, _, version = rest.rpartition("-")
    if not (name and version and release.startswith("r")):
        return None
    if versions.NAME.fullmatch(name) is None:
        return None
    return name, f"{version}-{release}"
