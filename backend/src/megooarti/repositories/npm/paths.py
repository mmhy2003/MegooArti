"""npm registry paths: what a request path means, and which package it names.

Pure functions. A package is `name` or `@scope/name`; everything under `-/` is the
registry's own API.
"""

import re
from dataclasses import dataclass

MAX_NAME_LENGTH = 214
_LOGIN_PREFIX = "org.couchdb.user:"
# One part of a name: URL-safe characters, not starting with a dot or an underscore.
_PART = re.compile(r"[A-Za-z0-9~-][A-Za-z0-9._~-]*")


@dataclass(frozen=True)
class NpmPath:
    """A path, classified. Fields that do not apply to its kind are left empty."""

    # document, version, tarball, dist_tags, login, logout, whoami, ping, search or other
    kind: str
    package: str = ""  # the full name: `name` or `@scope/name`
    version: str = ""  # version: the version or tag asked for; tarball: its version
    filename: str = ""  # tarball
    tag: str = ""  # dist_tags: the tag, if one is named
    username: str = ""  # login
    token: str = ""  # logout

    @property
    def scope(self) -> str:
        """The scope without its `@`, or "" for an unscoped package."""
        return scope_of(self.package)

    @property
    def name(self) -> str:
        """The name without its scope."""
        return unscoped(self.package)


_OTHER = NpmPath("other")


def scope_of(package: str) -> str:
    return package[1:].partition("/")[0] if package.startswith("@") else ""


def unscoped(package: str) -> str:
    return package.rpartition("/")[2]


def is_valid_name(package: str) -> bool:
    """Whether this can be a package name. Upper case is allowed: old packages have it."""
    if not package or len(package) > MAX_NAME_LENGTH:
        return False
    if package.startswith("@"):
        scope, slash, name = package[1:].partition("/")
        return bool(slash) and bool(_PART.fullmatch(scope)) and bool(_PART.fullmatch(name))
    return bool(_PART.fullmatch(package))


def tarball_filename(package: str, version: str) -> str:
    return f"{unscoped(package)}-{version}.tgz"


def tarball_path(package: str, version: str) -> str:
    """Where a version's tarball is stored, and requested."""
    return f"{package}/-/{tarball_filename(package, version)}"


def dist_tags_path(package: str) -> str:
    """Where a hosted repository keeps a package's dist-tags."""
    return f"-/package/{package}/dist-tags"


def _split_package(segments: list[str]) -> tuple[str, list[str]] | None:
    """The package a path starts with, and what follows it."""
    if not segments:
        return None
    count = 2 if segments[0].startswith("@") else 1
    package = "/".join(segments[:count])
    if len(segments) < count or not is_valid_name(package):
        return None
    return package, segments[count:]


def _without_revision(rest: list[str]) -> list[str]:
    """Drop a trailing `-rev/<rev>`: the revision is accepted and not used."""
    return rest[:-2] if len(rest) >= 2 and rest[-2] == "-rev" else rest


def _registry(segments: list[str]) -> NpmPath:
    if segments == ["ping"]:
        return NpmPath("ping")
    if segments == ["whoami"]:
        return NpmPath("whoami")
    if segments == ["v1", "search"]:
        return NpmPath("search")
    if segments[:1] == ["user"]:
        rest = _without_revision(segments[1:])
        if len(rest) == 1 and rest[0].startswith(_LOGIN_PREFIX):
            username = rest[0].removeprefix(_LOGIN_PREFIX)
            return NpmPath("login", username=username) if username else _OTHER
        if len(rest) == 2 and rest[0] == "token":
            return NpmPath("logout", token=rest[1])
        return _OTHER
    if segments[:1] == ["package"]:
        found = _split_package(segments[1:])
        if found is None:
            return _OTHER
        package, rest = found
        if rest == ["dist-tags"]:
            return NpmPath("dist_tags", package=package)
        if len(rest) == 2 and rest[0] == "dist-tags":
            return NpmPath("dist_tags", package=package, tag=rest[1])
    return _OTHER


def classify(path: str) -> NpmPath:
    """What a request path is."""
    segments = path.split("/")
    if segments[0] == "-":
        return _registry(segments[1:])
    found = _split_package(segments)
    if found is None:
        return _OTHER
    package, rest = found
    rest = _without_revision(rest)
    if not rest:
        return NpmPath("document", package=package)
    if rest[0] == "-":
        prefix = f"{unscoped(package)}-"
        if len(rest) != 2 or not rest[1].startswith(prefix) or not rest[1].endswith(".tgz"):
            return _OTHER
        version = rest[1][len(prefix) : -len(".tgz")]
        if not version:
            return _OTHER
        return NpmPath("tarball", package=package, version=version, filename=rest[1])
    if len(rest) == 1:
        return NpmPath("version", package=package, version=rest[0])
    return _OTHER
