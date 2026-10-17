"""What a path of a NuGet repository is (section 4.2 of the spec).

Ids and versions are lower case in every path, as NuGet's clients ask for them; a
version in a path is normalized.
"""

from dataclasses import dataclass

from megooarti.repositories.nuget import odata, symbols, versions

SERVICE_INDEX = "index.json"
PACKAGES = "v3/package/"
REGISTRATION = "v3/registration/"
SEARCH = "v3/search"
AUTOCOMPLETE = "v3/autocomplete"
# NuGet Audit's data: an index of files, each by its name, as nuget.org serves it.
VULNERABILITIES = "v3/vulnerabilities/"
VULNERABILITY_INDEX = f"{VULNERABILITIES}index.json"
PUBLISH = "api/v2/package"
SYMBOL_PUBLISH = "api/v2/symbolpackage"


@dataclass(frozen=True)
class NuGetPath:
    # service-index, versions, package, nuspec, symbols, registration, leaf, search,
    # autocomplete, publish, symbol-publish, delete, page, v2 (V2's feed), download (V2's
    # address of a package), symbol (a portable PDB at its key), other
    kind: str
    id: str = ""  # lower case
    version: str = ""  # normalized, lower case
    lower: str = ""  # a registration page's first version, normalized, lower case
    upper: str = ""  # and its last


def _version(text: str) -> str | None:
    """A version in a path: normalized, lower case. None if it is not one."""
    normalized = versions.normalize(text)
    return None if normalized is None else normalized.lower()


def package_path(package_id: str, version: str) -> str:
    """Where a package is kept, and fetched from."""
    lower, at = package_id.lower(), version.lower()
    return f"{PACKAGES}{lower}/{at}/{lower}.{at}.nupkg"


def nuspec_path(package_id: str, version: str) -> str:
    lower = package_id.lower()
    return f"{PACKAGES}{lower}/{version.lower()}/{lower}.nuspec"


def symbols_path(package_id: str, version: str) -> str:
    """Where a package's symbol package is kept, beside it."""
    lower, at = package_id.lower(), version.lower()
    return f"{PACKAGES}{lower}/{at}/{lower}.{at}.snupkg"


def page_path(package_id: str, lower: str, upper: str) -> str:
    """Where a registration page of an id with many versions is served."""
    return f"{REGISTRATION}{package_id.lower()}/page/{lower.lower()}/{upper.lower()}.json"


def classify(path: str) -> NuGetPath:
    if path == SERVICE_INDEX:
        return NuGetPath("service-index")
    if odata.is_v2(path):
        return NuGetPath("v2")
    if symbols.is_path(path):
        return NuGetPath("symbol")
    parts = path.split("/")
    if len(parts) == 3 and parts[0] == "package":
        version = _version(parts[2])
        if versions.is_id(parts[1]) and version is not None:
            return NuGetPath("download", parts[1].lower(), version)
        return NuGetPath("other")
    if path in (SEARCH, AUTOCOMPLETE):
        return NuGetPath("search" if path == SEARCH else "autocomplete")
    # dotnet pushes to the address the service index gives, with a slash after it.
    if path.rstrip("/") in (PUBLISH, SYMBOL_PUBLISH):
        return NuGetPath("publish" if path.rstrip("/") == PUBLISH else "symbol-publish")
    parts = path.split("/")
    if path.startswith(PUBLISH + "/") and len(parts) == 5:
        version = _version(parts[4])
        if versions.is_id(parts[3]) and version is not None:
            return NuGetPath("delete", parts[3].lower(), version)
    if path.startswith(PACKAGES) and len(parts) in (4, 5):
        package_id = parts[2]
        if package_id != package_id.lower() or not versions.is_id(package_id):
            return NuGetPath("other")
        if len(parts) == 4:
            return NuGetPath("versions" if parts[3] == "index.json" else "other", package_id)
        version = _version(parts[3])
        if version is None or version != parts[3]:
            return NuGetPath("other")
        filename = parts[4]
        if filename == f"{package_id}.{version}.nupkg":
            return NuGetPath("package", package_id, version)
        if filename == f"{package_id}.nuspec":
            return NuGetPath("nuspec", package_id, version)
        if filename == f"{package_id}.{version}.snupkg":
            return NuGetPath("symbols", package_id, version)
        return NuGetPath("other")
    if path.startswith(REGISTRATION) and len(parts) == 4:
        package_id = parts[2]
        if package_id != package_id.lower() or not versions.is_id(package_id):
            return NuGetPath("other")
        if parts[3] == "index.json":
            return NuGetPath("registration", package_id)
        version = _version(parts[3].removesuffix(".json"))
        if parts[3].endswith(".json") and version == parts[3].removesuffix(".json"):
            return NuGetPath("leaf", package_id, version)
    if path.startswith(REGISTRATION) and len(parts) == 6 and parts[3] == "page":
        package_id = parts[2]
        lower, upper = _version(parts[4]), _version(parts[5].removesuffix(".json"))
        if (
            versions.is_id(package_id)
            and package_id == package_id.lower()
            and parts[5].endswith(".json")
            and lower == parts[4]
            and upper == parts[5].removesuffix(".json")
        ):
            return NuGetPath("page", package_id, lower=lower, upper=upper)
    return NuGetPath("other")


def v2_delete(path: str) -> tuple[str, str] | None:
    """`<id>/<version>`: where a V2 client deletes a version, under the address it is
    given, with the version normalized. None for a path that is not one."""
    parts = path.split("/")
    if len(parts) != 2 or not versions.is_id(parts[0]):
        return None
    version = _version(parts[1])
    return None if version is None else (parts[0].lower(), version)


def v2_path(path: str) -> str:
    """A path of V2's feed without the slashes a client put before it: PSResourceGet
    adds one to an address that ends in one. Any other path as it is."""
    stripped = path.lstrip("/")
    if stripped != path and classify(stripped).kind in ("v2", "download"):
        return stripped
    return path
