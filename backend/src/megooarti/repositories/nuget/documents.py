"""The documents of NuGet's V3 protocol, written from what packages said of themselves.

Pure functions. `base` is the repository's address as a client is given it, ending in
a slash; every address in a document is under it.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from megooarti.repositories.nuget import paths, versions
from megooarti.repositories.nuget.packages import Nuspec

# Versions in a page of a registration, as nuget.org's.
PAGE = 64
# An id with more versions than this has its pages listed by their bounds, each at an
# address of its own; with this many or fewer they are inlined, as nuget.org's are.
INLINED_MOST = 128


@dataclass(frozen=True)
class Published:
    """A version a repository has: what its package says, and when it was pushed."""

    nuspec: Nuspec
    published: datetime


def service_index(
    base: str, *, publish: bool = True, search: bool = True, autocomplete: bool = True
) -> dict[str, Any]:
    """`index.json`: where a client finds each of the protocol's resources.

    A proxy offers no place to push to, and searches only where its remote does.
    """
    resources = [
        (paths.PACKAGES, ["PackageBaseAddress/3.0.0"]),
        (paths.PUBLISH, ["PackagePublish/2.0.0"]),
        (paths.SYMBOL_PUBLISH, ["SymbolPackagePublish/4.9.0"]),
        (
            paths.REGISTRATION,
            [
                "RegistrationsBaseUrl",
                "RegistrationsBaseUrl/3.0.0-beta",
                "RegistrationsBaseUrl/3.0.0-rc",
                "RegistrationsBaseUrl/3.4.0",
                "RegistrationsBaseUrl/3.6.0",
                "RegistrationsBaseUrl/Versioned",
            ],
        ),
        (
            paths.SEARCH,
            [
                "SearchQueryService",
                "SearchQueryService/3.0.0-beta",
                "SearchQueryService/3.0.0-rc",
                "SearchQueryService/3.5.0",
            ],
        ),
        (
            paths.AUTOCOMPLETE,
            [
                "SearchAutocompleteService",
                "SearchAutocompleteService/3.0.0-beta",
                "SearchAutocompleteService/3.0.0-rc",
                "SearchAutocompleteService/3.5.0",
            ],
        ),
    ]
    left_out = {
        paths.PUBLISH: not publish,
        paths.SYMBOL_PUBLISH: not publish,
        paths.SEARCH: not search,
        paths.AUTOCOMPLETE: not autocomplete,
    }
    return {
        "version": "3.0.0",
        "resources": [
            {"@id": f"{base}{path}", "@type": kind}
            for path, kinds in resources
            if not left_out.get(path, False)
            for kind in kinds
        ],
    }


def version_list(held: Sequence[str]) -> dict[str, Any]:
    """`v3/package/<id>/index.json`: an id's versions, lower case, the oldest first."""
    return {"versions": [version.lower() for version in versions.ordered(list(held))]}


def _registration(base: str, package_id: str) -> str:
    return f"{base}{paths.REGISTRATION}{package_id.lower()}/index.json"


def _leaf(base: str, nuspec: Nuspec) -> str:
    return f"{base}{paths.REGISTRATION}{nuspec.id.lower()}/{nuspec.version.lower()}.json"


def _content(base: str, nuspec: Nuspec) -> str:
    return f"{base}{paths.package_path(nuspec.id, nuspec.version)}"


def _words(text: str, separator: str | None = None) -> list[str]:
    return [word.strip() for word in text.split(separator) if word.strip()]


def _catalog_entry(base: str, held: Published) -> dict[str, Any]:
    nuspec = held.nuspec
    leaf = _leaf(base, nuspec)
    entry: dict[str, Any] = {
        "@id": f"{leaf}#catalogEntry",
        "@type": "PackageDetails",
        "id": nuspec.id,
        "version": nuspec.version,
        "authors": nuspec.authors,
        "description": nuspec.description,
        "summary": nuspec.summary,
        "title": nuspec.title,
        "tags": _words(nuspec.tags),
        "projectUrl": nuspec.project_url,
        "licenseUrl": nuspec.license_url,
        "licenseExpression": nuspec.license_expression,
        "iconUrl": nuspec.icon_url,
        "language": nuspec.language,
        "requireLicenseAcceptance": nuspec.require_license_acceptance,
        "minClientVersion": nuspec.min_client_version,
        "listed": True,
        "published": held.published.isoformat(),
        "packageContent": _content(base, nuspec),
        "dependencyGroups": [],
    }
    for number, group in enumerate(nuspec.dependency_groups):
        written: dict[str, Any] = {
            "@id": f"{leaf}#dependencygroup/{number}",
            "@type": "PackageDependencyGroup",
            "dependencies": [
                {
                    "@id": f"{leaf}#dependencygroup/{number}/{dependency.id.lower()}",
                    "@type": "PackageDependency",
                    "id": dependency.id,
                    "range": dependency.range,
                    "registration": _registration(base, dependency.id),
                }
                for dependency in group.dependencies
            ],
        }
        if group.target_framework:
            written["targetFramework"] = group.target_framework
        entry["dependencyGroups"].append(written)
    return entry


def _item(base: str, held: Published) -> dict[str, Any]:
    return {
        "@id": _leaf(base, held.nuspec),
        "@type": "Package",
        "commitTimeStamp": held.published.isoformat(),
        "catalogEntry": _catalog_entry(base, held),
        "packageContent": _content(base, held.nuspec),
        "registration": _registration(base, held.nuspec.id),
    }


def _ordered(held: Sequence[Published]) -> list[Published]:
    return sorted(
        held,
        key=lambda one: versions.parse(one.nuspec.version).sort_key(),  # type: ignore[union-attr]
    )


def _bounds(listed: Sequence[str]) -> list[tuple[str, str, int]]:
    """The pages of an id's versions: each one's first, last and number of versions."""
    ordered = [version.lower() for version in versions.ordered(list(listed))]
    return [
        (page[0], page[-1], len(page))
        for start in range(0, len(ordered), PAGE)
        if (page := ordered[start : start + PAGE])
    ]


def _page(
    base: str, index: str, address: str, held: Sequence[Published], lower: str, upper: str
) -> dict[str, Any]:
    """A page, with its versions' items, `held` being exactly its versions."""
    return {
        "@id": address,
        "@type": "catalog:CatalogPage",
        "count": len(held),
        "items": [_item(base, one) for one in held],
        "lower": lower,
        "upper": upper,
        "parent": index,
    }


def _root(index: str, pages: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "@id": index,
        "@type": ["catalog:CatalogRoot", "PackageRegistration", "catalog:Permalink"],
        "count": len(pages),
        "items": pages,
    }


def registration(base: str, held: Sequence[Published]) -> dict[str, Any]:
    """`v3/registration/<id>/index.json` of an id with at most `INLINED_MOST` versions:
    its versions, inlined in pages of 64."""
    ordered = _ordered(held)
    index = _registration(base, ordered[0].nuspec.id)
    pages = []
    for start in range(0, len(ordered), PAGE):
        page = ordered[start : start + PAGE]
        lower, upper = page[0].nuspec.version.lower(), page[-1].nuspec.version.lower()
        pages.append(_page(base, index, f"{index}#page/{lower}/{upper}", page, lower, upper))
    return _root(index, pages)


def registration_pages(base: str, package_id: str, listed: Sequence[str]) -> dict[str, Any]:
    """`v3/registration/<id>/index.json` of an id with more: its pages by their bounds
    alone, each served at its own address. `listed` is its versions."""
    index = _registration(base, package_id)
    pages = [
        {
            "@id": f"{base}{paths.page_path(package_id, lower, upper)}",
            "@type": "catalog:CatalogPage",
            "count": count,
            "lower": lower,
            "upper": upper,
        }
        for lower, upper, count in _bounds(listed)
    ]
    return _root(index, pages)


def page_of(listed: Sequence[str], lower: str, upper: str) -> list[str] | None:
    """The versions of the page of an id's `listed` versions that has these bounds,
    or None if no page has them."""
    ordered = [version.lower() for version in versions.ordered(list(listed))]
    for start in range(0, len(ordered), PAGE):
        page = ordered[start : start + PAGE]
        if page[0] == lower and page[-1] == upper:
            return page
    return None


def registration_page(
    base: str, package_id: str, held: Sequence[Published], lower: str, upper: str
) -> dict[str, Any]:
    """`v3/registration/<id>/page/<lower>/<upper>.json`: one page, its versions inlined.
    `held` is exactly the page's versions."""
    index = _registration(base, package_id)
    address = f"{base}{paths.page_path(package_id, lower, upper)}"
    return _page(base, index, address, _ordered(held), lower, upper)


def leaf(base: str, held: Published) -> dict[str, Any]:
    """`v3/registration/<id>/<version>.json`: one version."""
    return {
        "@id": _leaf(base, held.nuspec),
        "@type": ["Package", "http://schema.nuget.org/catalog#Permalink"],
        "catalogEntry": _catalog_entry(base, held)["@id"],
        "listed": True,
        "packageContent": _content(base, held.nuspec),
        "published": held.published.isoformat(),
        "registration": _registration(base, held.nuspec.id),
    }


def search_result(base: str, found: Sequence[Sequence[Published]], total: int) -> dict[str, Any]:
    """`v3/search`: each id found, with its versions, the newest's details in front."""
    data = []
    for held in found:
        if not held:
            continue
        ordered = _ordered(held)
        newest = ordered[-1].nuspec
        index = _registration(base, newest.id)
        data.append(
            {
                "@id": index,
                "@type": "Package",
                "registration": index,
                "id": newest.id,
                "version": newest.version,
                "description": newest.description,
                "summary": newest.summary,
                "title": newest.title,
                "iconUrl": newest.icon_url,
                "licenseUrl": newest.license_url,
                "projectUrl": newest.project_url,
                "tags": _words(newest.tags),
                "authors": _words(newest.authors, ","),
                "owners": _words(newest.owners, ","),
                "totalDownloads": 0,
                "verified": False,
                "packageTypes": [
                    {"name": name} for name in (newest.package_types or ("Dependency",))
                ],
                "versions": [
                    {"version": one.nuspec.version, "downloads": 0, "@id": _leaf(base, one.nuspec)}
                    for one in ordered
                ],
            }
        )
    return {"totalHits": total, "data": data}


def autocomplete(found: Sequence[str], total: int) -> dict[str, Any]:
    """`v3/autocomplete`: ids, or an id's versions."""
    return {"totalHits": total, "data": list(found)}
