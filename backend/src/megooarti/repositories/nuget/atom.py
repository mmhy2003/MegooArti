"""The documents of NuGet's V2 protocol: OData's Atom feeds of versions, written from
what packages said of themselves.

Pure functions. `base` is the repository's address as a client is given it, ending in
a slash; every address in a document is under it. A version is an entry with the
properties NuGet's clients read, as nuget.org's V2 feed has them.
"""

import base64
import html
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from xml.sax.saxutils import escape, quoteattr

from megooarti.repositories.nuget import odata, versions
from megooarti.repositories.nuget.documents import Published

ATOM = "application/atom+xml;type=feed;charset=utf-8"
ATOM_ENTRY = "application/atom+xml;type=entry;charset=utf-8"
XML = "application/xml;charset=utf-8"
_DECLARATION = '<?xml version="1.0" encoding="utf-8"?>\n'
_NAMESPACES = (
    'xmlns="http://www.w3.org/2005/Atom" '
    'xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices" '
    'xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"'
)
_SCHEME = "http://schemas.microsoft.com/ado/2007/08/dataservices/scheme"
_TYPE = "NuGetGallery.OData.V2FeedPackage"
# An entry of a feed, as text; the address of the version it is of, by its id.
ENTRIES = re.compile(r"<entry\b.*?</entry>", re.DOTALL)
_ENTRY_ID = re.compile(r"<id>[^<]*/(Packages\([^<]*\))</id>")

# Of each id: the normalized versions, in lower case, of its newest stable version and
# of its newest version, prereleases too ("" for none).
Latest = tuple[str, str]


def latest(held: Sequence[Published]) -> Latest:
    """An id's newest stable version, and its newest version, from all it has."""
    ordered = versions.ordered([one.nuspec.version for one in held])
    stable = [one for one in ordered if not versions.parse(one).is_prerelease]  # type: ignore[union-attr]
    return (stable[-1].lower() if stable else "", ordered[-1].lower() if ordered else "")


def _time(when: datetime) -> str:
    """An `Edm.DateTime`, in UTC, as nuget.org writes one."""
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]


def _atom_time(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _quoted(text: str) -> str:
    return text.replace("'", "''")


def entry_address(base: str, package_id: str, version: str) -> str:
    return f"{base}Packages(Id='{_quoted(package_id)}',Version='{_quoted(version)}')"


def download_address(base: str, package_id: str, version: str) -> str:
    """V2's address of a package: `package/<id>/<version>`."""
    return f"{base}package/{package_id}/{version}"


def dependencies(held: Published) -> str:
    """The `Dependencies` property: `id:range:framework`, `|` between them, and a
    framework without dependencies as `::framework`."""
    written = []
    for group in held.nuspec.dependency_groups:
        if not group.dependencies:
            written.append(f"::{group.target_framework}")
        written += [
            f"{dependency.id}:{dependency.range}:{group.target_framework}"
            for dependency in group.dependencies
        ]
    return "|".join(written)


def _text(name: str, value: str) -> str:
    return f"<d:{name}>{escape(value)}</d:{name}>" if value else f'<d:{name} m:null="true"/>'


def _flag(name: str, value: bool) -> str:
    return f'<d:{name} m:type="Edm.Boolean">{"true" if value else "false"}</d:{name}>'


def _number(name: str, value: int) -> str:
    return f'<d:{name} m:type="Edm.Int64">{value}</d:{name}>'


def _date(name: str, value: datetime) -> str:
    return f'<d:{name} m:type="Edm.DateTime">{_time(value)}</d:{name}>'


def _hash(held: Published) -> str:
    return base64.b64encode(bytes.fromhex(held.sha512)).decode() if held.sha512 else ""


def _properties(held: Published, newest: Latest) -> str:
    nuspec = held.nuspec
    version = nuspec.version.lower()
    stable, absolute = newest
    return "".join(
        [
            _text("Id", nuspec.id),
            _text("Version", nuspec.original_version or nuspec.version),
            _text("NormalizedVersion", nuspec.version),
            _text("Authors", nuspec.authors),
            _text("Copyright", nuspec.copyright),
            _date("Created", held.published),
            _text("Dependencies", dependencies(held)),
            _text("Description", nuspec.description),
            _number("DownloadCount", 0),
            _text("IconUrl", nuspec.icon_url),
            _flag("IsLatestVersion", version == stable),
            _flag("IsAbsoluteLatestVersion", version == absolute),
            _flag("IsPrerelease", nuspec.is_prerelease),
            _text("Language", nuspec.language),
            _date("LastUpdated", held.published),
            _date("Published", held.published),
            _text("PackageHash", _hash(held)),
            _text("PackageHashAlgorithm", "SHA512" if held.sha512 else ""),
            _number("PackageSize", held.size),
            _text("ProjectUrl", nuspec.project_url),
            _text("ReleaseNotes", nuspec.release_notes),
            _flag("RequireLicenseAcceptance", nuspec.require_license_acceptance),
            _text("Summary", nuspec.summary),
            _text("Tags", nuspec.tags),
            _text("Title", nuspec.title),
            _number("VersionDownloadCount", 0),
            _text("MinClientVersion", nuspec.min_client_version),
            _text("LicenseUrl", nuspec.license_url),
            _text("LicenseNames", nuspec.license_expression),
        ]
    )


def _entry(base: str, held: Published, newest: Latest, *, alone: bool = False) -> str:
    nuspec = held.nuspec
    address = entry_address(base, nuspec.id, nuspec.version)
    opening = f"<entry xml:base={quoteattr(base)} {_NAMESPACES}>" if alone else "<entry>"
    return (
        f"{opening}<id>{escape(address)}</id>"
        f'<category term="{_TYPE}" scheme="{_SCHEME}"/>'
        f'<link rel="edit" title="V2FeedPackage" href={quoteattr(address)}/>'
        f'<link rel="edit-media" title="V2FeedPackage" href={quoteattr(address + "/$value")}/>'
        f'<title type="text">{escape(nuspec.id)}</title>'
        f'<summary type="text">{escape(nuspec.summary)}</summary>'
        f"<updated>{_atom_time(held.published)}</updated>"
        f"<author><name>{escape(nuspec.authors)}</name></author>"
        '<content type="application/zip" '
        f"src={quoteattr(download_address(base, nuspec.id, nuspec.version))}/>"
        f"<m:properties>{_properties(held, newest)}</m:properties></entry>"
    )


def rendered(base: str, held: Published, newest: Latest) -> str:
    """A version as an entry of a feed, as text."""
    return _entry(base, held, newest)


def named(entry: str) -> tuple[str, str] | None:
    """The id and the version an entry's id names, as written; None if it names none."""
    found = _ENTRY_ID.search(entry)
    return None if found is None else odata.entry_of(html.unescape(found[1]))


def key_of(entry: str) -> str | None:
    """What an entry is of, an id and a version as NuGet matches them: in lower case, the
    version normalized. None for an entry of what is not one."""
    found = named(entry)
    version = None if found is None else versions.normalize(found[1])
    return None if version is None else f"{found[0].lower()}/{version.lower()}"  # type: ignore[index]


def entry(base: str, held: Published, newest: Latest) -> bytes:
    """`Packages(Id='…',Version='…')`: one version, as an entry of its own."""
    return (_DECLARATION + _entry(base, held, newest, alone=True)).encode()


def feed(
    base: str,
    title: str,
    found: Sequence[tuple[Published, Latest]],
    *,
    updated: datetime,
    count: int | None = None,
    next_address: str = "",
) -> bytes:
    """A page of versions: each with what is newest of its id. `count` is written for
    `$inlinecount=allpages`; `next_address` leads to the next page, if there is one."""
    entries = [_entry(base, held, newest) for held, newest in found]
    return feed_of(base, title, entries, updated=updated, count=count, next_address=next_address)


def feed_of(
    base: str,
    title: str,
    entries: Sequence[str],
    *,
    updated: datetime,
    count: int | None = None,
    next_address: str = "",
) -> bytes:
    """A page of entries, each as text written with `base`, as `feed` writes them."""
    parts = [
        f"{_DECLARATION}<feed xml:base={quoteattr(base)} {_NAMESPACES}>",
        f"<m:count>{count}</m:count>" if count is not None else "",
        f"<id>{escape(base + title)}</id>",
        f'<title type="text">{escape(title)}</title>',
        f"<updated>{_atom_time(updated)}</updated>",
        f'<link rel="self" title="{escape(title)}" href="{escape(title)}"/>',
        *entries,
        f'<link rel="next" href={quoteattr(next_address)}/>' if next_address else "",
        "</feed>",
    ]
    return "".join(parts).encode()


def service_document(base: str) -> bytes:
    """The root of V2's feed: the one collection it has."""
    return (
        f"{_DECLARATION}<service xml:base={quoteattr(base)} "
        'xmlns="http://www.w3.org/2007/app" xmlns:atom="http://www.w3.org/2005/Atom">'
        "<workspace><atom:title>Default</atom:title>"
        '<collection href="Packages"><atom:title>Packages</atom:title></collection>'
        "</workspace></service>"
    ).encode()


_PROPERTIES = [
    ("Id", "Edm.String", False),
    ("Version", "Edm.String", False),
    ("NormalizedVersion", "Edm.String", True),
    ("Authors", "Edm.String", True),
    ("Copyright", "Edm.String", True),
    ("Created", "Edm.DateTime", False),
    ("Dependencies", "Edm.String", True),
    ("Description", "Edm.String", True),
    ("DownloadCount", "Edm.Int64", False),
    ("IconUrl", "Edm.String", True),
    ("IsLatestVersion", "Edm.Boolean", False),
    ("IsAbsoluteLatestVersion", "Edm.Boolean", False),
    ("IsPrerelease", "Edm.Boolean", False),
    ("Language", "Edm.String", True),
    ("LastUpdated", "Edm.DateTime", False),
    ("Published", "Edm.DateTime", False),
    ("PackageHash", "Edm.String", True),
    ("PackageHashAlgorithm", "Edm.String", True),
    ("PackageSize", "Edm.Int64", False),
    ("ProjectUrl", "Edm.String", True),
    ("ReleaseNotes", "Edm.String", True),
    ("RequireLicenseAcceptance", "Edm.Boolean", False),
    ("Summary", "Edm.String", True),
    ("Tags", "Edm.String", True),
    ("Title", "Edm.String", True),
    ("VersionDownloadCount", "Edm.Int64", False),
    ("MinClientVersion", "Edm.String", True),
    ("LicenseUrl", "Edm.String", True),
    ("LicenseNames", "Edm.String", True),
]


def _metadata() -> bytes:
    properties = "".join(
        f'<Property Name="{name}" Type="{kind}" Nullable="{"true" if nullable else "false"}"/>'
        for name, kind, nullable in _PROPERTIES
    )
    string = '<Parameter Name="{}" Type="Edm.String" FixedLength="false" Unicode="false"/>'
    return (
        f"{_DECLARATION}"
        '<edmx:Edmx Version="1.0" xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx">'
        '<edmx:DataServices xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"'
        ' m:DataServiceVersion="2.0" m:MaxDataServiceVersion="2.0">'
        '<Schema Namespace="NuGetGallery.OData" xmlns="http://schemas.microsoft.com/ado/2006/04/edm">'
        '<EntityType Name="V2FeedPackage" m:HasStream="true">'
        '<Key><PropertyRef Name="Id"/><PropertyRef Name="Version"/></Key>'
        f"{properties}</EntityType></Schema>"
        '<Schema Namespace="NuGetGallery" xmlns="http://schemas.microsoft.com/ado/2006/04/edm">'
        '<EntityContainer Name="V2FeedContext" m:IsDefaultEntityContainer="true">'
        '<EntitySet Name="Packages" EntityType="NuGetGallery.OData.V2FeedPackage"/>'
        '<FunctionImport Name="Search" ReturnType="Collection(NuGetGallery.OData.V2FeedPackage)"'
        ' EntitySet="Packages">'
        f"{string.format('searchTerm')}{string.format('targetFramework')}"
        '<Parameter Name="includePrerelease" Type="Edm.Boolean" Nullable="false"/>'
        "</FunctionImport>"
        '<FunctionImport Name="FindPackagesById"'
        ' ReturnType="Collection(NuGetGallery.OData.V2FeedPackage)" EntitySet="Packages">'
        f"{string.format('id')}</FunctionImport>"
        "</EntityContainer></Schema></edmx:DataServices></edmx:Edmx>"
    ).encode()


METADATA = _metadata()
