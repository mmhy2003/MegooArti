"""Packages: finding them, their versions, a version's files and usage, and a
repository's folders (spec 6.1). Each answers as the REST route beside it does."""

import uuid
from datetime import datetime
from functools import partial
from typing import Annotated

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.errors import ApiError
from megooarti.mcp.results import Cursor, Limit, Page, most_that_fit, offset_of, page_of
from megooarti.mcp.tools import caller, database, tool
from megooarti.pagination import PageParams
from megooarti.repositories import content_api, search_api, service
from megooarti.repositories.formats import get_format

# No value is longer than what it is compared with can be, as the search route has it.
Text = Annotated[str, Field(max_length=256)]
Format = Annotated[str, Field(max_length=32, description="maven, npm, pypi, nuget, docker, …")]
RepositoryName = Annotated[str, Field(max_length=64)]
# A checksum's kind, by how many hexadecimal digits it has.
_CHECKSUMS = {32: "md5", 40: "sha1", 64: "sha256", 128: "sha512"}
# How many copies of one package `package_versions` reads, at most.
_COPIES_MOST = 2000
# How many of a version's files `package_details` describes, at most.
_FILES_MOST = 50


def _invalid(field: str, message: str) -> ApiError:
    details = [{"field": field, "message": message}]
    return ApiError(422, "validation_error", "The request is not valid.", details)


async def _members_of(db: AsyncSession, repository: str) -> list[str] | None:
    """The members the caller may browse of a group named `repository`; None where it is
    not a group. Raises as the content route does for one there is not, or not theirs."""
    if not repository:
        return None
    view = await content_api.get_repository(repository, caller().request, caller().principal, db)
    return view.members if view.type == "group" else None


def _not_browsable(members: list[str], doing: str) -> ApiError:
    return ApiError(
        409,
        "not_browsable",
        f"A group holds nothing of its own. {doing} its members: {', '.join(members)}.",
    )


def _one_package(copies: list["Package"], name: str, namespace: str | None) -> list["Package"]:
    """The copies of the one package that `name` (and `namespace`) name, as it is spelled
    where several are spelled alike. Raises 422 where it is not one."""
    if namespace is not None:
        copies = [copy for copy in copies if copy.namespace == namespace]
    namespaces = sorted({copy.namespace for copy in copies})
    if len(namespaces) > 1:
        said = ", ".join(one or '""' for one in namespaces[:10])
        raise _invalid(
            "namespace",
            f"There are packages named {name} in more than one namespace: {said}. "
            'Give `namespace` ("" for none).',
        )
    spellings = sorted({copy.name for copy in copies})
    if len(spellings) > 1:
        if name not in spellings:
            said = ", ".join(spellings[:10])
            raise _invalid(
                "name", f"There are packages named {name} spelled more than one way: {said}."
            )
        copies = [copy for copy in copies if copy.name == name]
    return copies


class Package(BaseModel):
    id: uuid.UUID  # what `package_details` takes as `component_id`
    repository: str
    format: str
    namespace: str  # a Maven groupId, an npm scope; empty where the format has none
    name: str
    version: str
    created: datetime
    modified: datetime


async def _search(
    db: AsyncSession,
    *,
    words: str = "",
    format: str = "",
    repository: str = "",
    namespace: str = "",
    name: str = "",
    version: str = "",
    sums: dict[str, str] | None = None,
    limit: int,
    offset: int,
) -> tuple[list[Package], int]:
    """A page of what the search route finds for the caller, and how many there are."""
    found = await search_api.search_components(
        q=words,
        format=format,
        repository=repository,
        namespace=namespace,
        name=name,
        version=version,
        **(sums or dict.fromkeys(_CHECKSUMS.values(), "")),
        params=PageParams(limit=limit, offset=offset),
        caller=caller().principal,
        db=db,
    )
    items = [Package.model_validate(item, from_attributes=True) for item in found["items"]]
    return items, found["total"]


@tool()
async def search_packages(
    words: Text = "",
    format: Format = "",
    repository: RepositoryName = "",
    namespace: Text = "",
    name: Text = "",
    version: Text = "",
    checksum: Annotated[str, Field(max_length=128)] = "",
    limit: Limit = 50,
    cursor: Cursor = None,
) -> Page[Package]:
    """Find packages (components) in the repositories you may browse.

    `words`: each must be in the package's namespace, name or version, whatever the case;
    `*` stands for anything. `namespace`, `name` and `version` match a whole value, also
    with `*`. `checksum` (MD5, SHA-1, SHA-256 or SHA-512, in hexadecimal) finds the package
    a file belongs to. `format` and `repository` narrow where to look. A group holds
    nothing of its own: name one of its members, or none.
    """
    sums = dict.fromkeys(_CHECKSUMS.values(), "")
    if checksum:
        kind = _CHECKSUMS.get(len(checksum))
        if kind is None:
            raise _invalid("checksum", "A checksum is 32, 40, 64 or 128 hexadecimal digits.")
        sums[kind] = checksum
    offset = offset_of(cursor)
    async with database() as db:
        members = await _members_of(db, repository)
        if members is not None:
            raise _not_browsable(members, "Search")
        items, total = await _search(
            db,
            words=words,
            format=format,
            repository=repository,
            namespace=namespace,
            name=name,
            version=version,
            sums=sums,
            limit=limit,
            offset=offset,
        )
    return page_of(items, total, offset, limit)


class Holder(BaseModel):
    repository: str
    type: str  # "hosted": pushed there; "proxy": fetched from its remote, and kept


class Version(BaseModel):
    version: str
    prerelease: bool  # one a client takes only when it is asked for
    repositories: list[Holder]


class Versions(BaseModel):
    format: str
    namespace: str
    name: str
    # The newest first, as the format's clients order versions. Docker's tags, which
    # have no order, from the one pushed or fetched last.
    versions: Page[Version]
    newest_release: str | None  # the newest that is not a prerelease
    # Whether there were more than 2,000 copies, of which only those were read.
    incomplete: bool


@tool()
async def package_versions(
    format: Format,
    name: Text,
    namespace: Annotated[str | None, Field(max_length=256)] = None,
    repository: RepositoryName = "",
    limit: Limit = 50,
    cursor: Cursor = None,
) -> Versions:
    """Every version of one package in the repositories you may browse, the newest first,
    with the repositories that have each: hosted ones, where it was pushed, and proxies,
    which keep what they have fetched so far (not all their remote has); and the newest
    release. Give `namespace` where the format has them (a Maven groupId, an npm scope
    without `@`), and "" for a package in none. `repository` narrows where to look; a
    group's are its members'.
    """
    handler = get_format(format)
    if handler is None:
        raise _invalid("format", "No such format.")
    if "*" in name:
        raise _invalid("name", "Give one package's whole name, without `*`.")
    copies: list[Package] = []
    async with database() as db:
        members = await _members_of(db, repository)
        types = {held.name: held.type for held in await service.all_repositories(db)}
        total = None
        while len(copies) < _COPIES_MOST and (total is None or len(copies) < total):
            items, total = await _search(
                db,
                format=format,
                repository="" if members is not None else repository,
                namespace=namespace or "",
                name=name,
                limit=200,
                offset=len(copies),
            )
            if not items:
                break
            copies += items
    if members is not None:
        copies = [copy for copy in copies if copy.repository in members]
    copies = _one_package(copies, name, namespace)
    namespaces = sorted({copy.namespace for copy in copies})
    holders: dict[str, list[Holder]] = {}
    last: dict[str, datetime] = {}
    for copy in copies:
        holder = Holder(repository=copy.repository, type=types.get(copy.repository, "hosted"))
        holders.setdefault(copy.version, []).append(holder)
        last[copy.version] = max(last.get(copy.version, copy.modified), copy.modified)
    ordered = handler.ordered_versions(list(holders))
    if ordered is None:
        newest_first = sorted(holders, key=lambda version: last[version], reverse=True)
    else:
        newest_first = list(reversed(ordered))
    every = [
        Version(
            version=version,
            prerelease=handler.is_prerelease(version),
            repositories=sorted(holders[version], key=lambda holder: holder.repository),
        )
        for version in newest_first
    ]
    releases = (one.version for one in every if not one.prerelease)
    newest_release = None if ordered is None else next(releases, None)
    offset = offset_of(cursor)

    def versions_with(page: Page[Version]) -> Versions:
        return Versions(
            format=format,
            namespace=namespaces[0] if namespaces else namespace or "",
            name=copies[0].name if copies else name,
            versions=page,
            newest_release=newest_release,
            incomplete=len(copies) >= _COPIES_MOST,
        )

    shown = page_of(every[offset : offset + limit], len(every), offset, limit, versions_with)
    return versions_with(shown)


class File(BaseModel):
    path: str
    size: int
    md5: str
    sha1: str
    sha256: str
    sha512: str
    download: str | None  # where a client fetches it, if it has an address of its own


class Usage(BaseModel):
    label: str  # what it is for: Maven, Gradle, npm, pip, dotnet, Docker, …
    language: str  # what `text` is written in: xml, kotlin, groovy, shell, …
    text: str  # to copy into a project, or to run


class PackageDetails(BaseModel):
    id: uuid.UUID
    repository: str
    format: str
    namespace: str
    name: str
    version: str
    created: datetime
    modified: datetime
    files: list[File]
    usage: list[Usage]  # how a project uses this version from this repository
    # Whether files were left out: past the first 50, or to keep within 64 KiB.
    truncated: bool


async def component_named(
    db: AsyncSession, repository: str, namespace: str | None, name: str, version: str
) -> uuid.UUID:
    """The id of the one version of one package that these name in a repository: found
    by the search, among any number. Raises 422 where they name none or several, 404."""
    if not name or not version or "*" in name + version:
        raise _invalid(
            "component_id", "Give `component_id`, or `name` and `version` (without `*`)."
        )
    found, _ = await _search(
        db,
        repository=repository,
        namespace=namespace or "",
        name=name,
        version=version,
        limit=200,
        offset=0,
    )
    matching = _one_package([one for one in found if one.version == version], name, namespace)
    if not matching:
        raise ApiError(404, "not_found", "No such component.")
    return matching[0].id


@tool()
async def package_details(
    repository: RepositoryName,
    component_id: uuid.UUID | None = None,
    namespace: Annotated[str | None, Field(max_length=256)] = None,
    name: Text = "",
    version: Text = "",
) -> PackageDetails:
    """One version of a package in one repository: its files with their sizes, checksums
    and download addresses, and how a project uses it from there (the dependency to add
    to a pom.xml, a package.json, a requirements.txt or a .csproj; the command to run).
    Give `component_id` as `search_packages` gave it, or `name` and `version`, and
    `namespace` where the format has them ("" for a package in none).
    """
    principal, request = caller().principal, caller().request
    async with database() as db:
        members = await _members_of(db, repository)
        if members is not None:
            raise _not_browsable(members, "Look in")
        if component_id is None:
            component_id = await component_named(db, repository, namespace, name, version)
        detail = await content_api.get_component(repository, component_id, request, principal, db)
        held = await service.get_repository(db, repository)
        paths = [entry.path for entry in detail.files if entry.kind == "file"]
        files = [
            File.model_validate(
                await content_api.get_asset(repository, path, request, principal, db),
                from_attributes=True,
            )
            for path in paths[:_FILES_MOST]
        ]
    usage = [Usage.model_validate(one, from_attributes=True) for one in detail.usage]

    def details(kept: int) -> PackageDetails:
        return PackageDetails(
            id=detail.id,
            repository=repository,
            format="" if held is None else held.format,
            namespace=detail.namespace,
            name=detail.name,
            version=detail.version,
            created=detail.created,
            modified=detail.modified,
            files=files[:kept],
            usage=usage,
            truncated=kept < len(paths),
        )

    return details(most_that_fit(len(files), details))


class Ref(BaseModel):
    id: uuid.UUID  # what `package_details` takes as `component_id`
    namespace: str
    name: str
    version: str


class Entry(BaseModel):
    name: str
    path: str  # what `browse` takes as `path`, for a folder
    kind: str  # "folder" or "file"
    size: int | None = None
    modified: datetime | None = None
    component: Ref | None = None  # the package a file belongs to


class Folder(BaseModel):
    repository: str
    path: str
    items: list[Entry]
    next_cursor: str | None  # give it as `cursor` for what follows; null at the end
    # Whether fewer items were given than asked for, to keep within 64 KiB.
    truncated: bool


# A folder's cursor names the entry it follows, and a path may be 1,024 characters long.
FolderCursor = Annotated[
    str | None, Field(max_length=1100, description="`next_cursor` of the page before; none first.")
]


@tool()
async def browse(
    repository: RepositoryName,
    path: Annotated[str, Field(max_length=1024)] = "",
    limit: Limit = 50,
    cursor: FolderCursor = None,
) -> Folder:
    """What is directly in a folder of a repository, as its files are stored; an empty
    `path` is the repository's root. A file that belongs to a package says which. A group
    holds nothing of its own: browse its members."""
    principal = caller().principal
    cut = False
    async with database() as db:
        while True:
            listing = await content_api.list_folder(
                repository, path, after=cursor or "", limit=limit, caller=principal, db=db
            )
            found = Folder(
                repository=repository,
                path=path.strip("/"),
                items=[Entry.model_validate(item, from_attributes=True) for item in listing.items],
                next_cursor=listing.next,
                truncated=cut,
            )
            kept = most_that_fit(len(found.items), partial(_first, found))
            if kept == len(found.items):
                return found
            # Fewer, asked for again, so that the listing's own cursor leads on from them.
            limit, cut = kept, True


def _first(folder: Folder, count: int) -> Folder:
    """A folder's listing with only its first `count` items."""
    return folder.model_copy(update={"items": folder.items[:count]})
