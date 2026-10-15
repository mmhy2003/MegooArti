"""What a path of a NuGet repository is (section 4.2 of the spec).

Ids and versions are lower case in every path, as NuGet's clients ask for them; a
version in a path is normalized.
"""

from dataclasses import dataclass

from megooarti.repositories.nuget import versions

SERVICE_INDEX = "index.json"
PACKAGES = "v3/package/"
REGISTRATION = "v3/registration/"
SEARCH = "v3/search"
AUTOCOMPLETE = "v3/autocomplete"
PUBLISH = "api/v2/package"
SYMBOL_PUBLISH = "api/v2/symbolpackage"


@dataclass(frozen=True)
class NuGetPath:
    # service-index, versions, package, nuspec, symbols, registration, leaf, search,
    # autocomplete, publish, symbol-publish, delete, other
    kind: str
    id: str = ""  # lower case
    version: str = ""  # normalized, lower case


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


def classify(path: str) -> NuGetPath:
    if path == SERVICE_INDEX:
        return NuGetPath("service-index")
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
    return NuGetPath("other")
