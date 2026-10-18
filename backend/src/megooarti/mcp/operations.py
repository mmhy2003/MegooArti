"""Running repositories (spec 6.2): making, changing and deleting them, clearing a proxy's
cache, going through a repository's index again, and deleting what is in one. Each calls
the REST route beside it, with its permission: `admin:repositories:write`, or `delete` on
the repository whose content it deletes."""

import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from megooarti.errors import ApiError
from megooarti.mcp.packages import component_named
from megooarti.mcp.tools import (
    CHANGE,
    DESTRUCTIVE,
    WRITE,
    caller,
    database,
    holding,
    may_somewhere,
    tool,
)
from megooarti.repositories import api as repositories_api
from megooarti.repositories import content_api, service
from megooarti.repositories.api import (
    GroupSettings,
    HostedIn,
    IndexRebuilt,
    NegativeCache,
    ProxyIn,
    RemoteAuthIn,
    RepositoryCreate,
    RepositoryOut,
    RepositoryUpdate,
)
from megooarti.repositories.formats import get_format

WRITE_REPOSITORIES = "admin:repositories:write"
Name = Annotated[str, Field(max_length=64)]


class ProxySettings(BaseModel):
    """A proxy's settings, as the REST API takes them; its remote, where none is given, is
    its format's public repository."""

    remote_url: str | None = Field(default=None, min_length=1, max_length=2048)
    content_max_age_minutes: int = Field(default=1440, ge=-1)
    metadata_max_age_minutes: int = Field(default=1440, ge=-1)
    negative_cache: NegativeCache = NegativeCache()
    remote_auth: RemoteAuthIn = RemoteAuthIn()
    blocked: bool = False
    auto_block: bool = True


def _invalid(field: str, message: str) -> ApiError:
    details = [{"field": field, "message": message}]
    return ApiError(422, "validation_error", "The request is not valid.", details)


def _shown(view: Any) -> RepositoryOut:
    return RepositoryOut.model_validate(view, from_attributes=True)


@tool(annotations=WRITE, shown_to=holding(WRITE_REPOSITORIES))
async def create_repository(
    name: Name,
    format: Annotated[str, Field(max_length=32, description="maven, npm, pypi, nuget, …")],
    type: Literal["hosted", "proxy", "group"],
    online: bool = True,
    blob_store: Annotated[str | None, Field(max_length=64)] = None,
    hosted: HostedIn | None = None,
    proxy: ProxySettings | None = None,
    members: list[str] | None = None,
    format_config: dict[str, Any] | None = None,
) -> RepositoryOut:
    """Make a repository: hosted (packages are pushed to it), a proxy of a remote (which it
    fetches from, and keeps), or a group of others (`members`, in the order they are
    asked). A proxy whose `proxy.remote_url` is not given proxies its format's public
    repository (Maven Central, the npm registry, PyPI, Docker Hub, Debian, Alpine,
    nuget.org). `format_config` is the format's own: an APT repository's `suite`, a
    NuGet proxy's `protocol`. Gives its settings."""
    config = format_config or {}
    if type == "proxy":
        given = proxy or ProxySettings()
        remote = given.remote_url
        if remote is None:
            handler = get_format(format)
            remote = None if handler is None else handler.public_remote(config)
        if remote is None:
            raise _invalid(
                "proxy.remote_url", "This format has no public repository: give the remote's."
            )
        proxy_in: ProxyIn | None = ProxyIn(**{**given.model_dump(), "remote_url": remote})
    else:
        proxy_in = None
    body = RepositoryCreate(
        name=name,
        format=format,
        type=type,
        online=online,
        blob_store=blob_store,
        hosted=hosted,
        proxy=proxy_in,
        group=GroupSettings(members=members or []) if type == "group" else None,
        format_config=config,
    )
    principal, request = caller().principal, caller().request
    async with database() as db:
        made = await repositories_api.create_repository(body, request, principal, db)
    return _shown(made)


def _merged(held: dict[str, Any] | None, given: dict[str, Any] | None) -> dict[str, Any] | None:
    """Settings as they are, with what was given in their place, one level down too."""
    if given is None:
        return held
    merged = dict(held or {})
    for key, value in given.items():
        inner = merged.get(key)
        merged[key] = (
            {**inner, **value} if isinstance(inner, dict) and isinstance(value, dict) else value
        )
    return merged


@tool(annotations=CHANGE, shown_to=holding(WRITE_REPOSITORIES))
async def update_repository(
    name: Name,
    online: bool | None = None,
    members: list[str] | None = None,
    hosted: dict[str, Any] | None = None,
    proxy: dict[str, Any] | None = None,
    format_config: dict[str, Any] | None = None,
) -> RepositoryOut:
    """Change a repository: take it online or offline, give a group its `members` (all of
    them, in the order they are asked), or change some of its settings, given as
    `repository_details` shows them (`proxy: {"blocked": true}`, `hosted:
    {"deployment_policy": "disable_redeploy"}`): what is not given stays as it is. A
    proxy's stored secret is kept unless `proxy.remote_auth.secret` is given. Its name,
    format, type and blob store do not change. Gives its settings."""
    principal, request = caller().principal, caller().request
    async with database() as db:
        held = await service.get_repository(db, name)
        if held is None:
            raise ApiError(404, "not_found", "No such repository.")
        current = _shown(await service.describe(db, held))
        now = current.model_dump(mode="json")
        current_proxy = now["proxy"]
        if current_proxy is not None:
            # A secret is never shown: one that is not given is the one stored.
            auth = current_proxy["remote_auth"]
            current_proxy["remote_auth"] = {"type": auth["type"], "username": auth["username"]}
        body = RepositoryUpdate(
            online=current.online if online is None else online,
            hosted=_merged(now["hosted"], hosted),
            proxy=_merged(current_proxy, proxy),
            group=GroupSettings(members=members) if members is not None else current.group,
            format_config=_merged(now["format_config"], format_config) or {},
        )
        changed = await repositories_api.update_repository(name, body, request, principal, db)
    return _shown(changed)


class Done(BaseModel):
    repository: str
    done: str  # what was done


@tool(annotations=DESTRUCTIVE, shown_to=holding(WRITE_REPOSITORIES))
async def delete_repository(name: Name) -> Done:
    """Delete a repository and everything in it. It cannot be undone. A group that has it
    as a member must be changed first."""
    async with database() as db:
        await repositories_api.delete_repository(name, caller().principal, db)
    return Done(repository=name, done="deleted")


@tool(annotations=CHANGE, shown_to=holding(WRITE_REPOSITORIES))
async def invalidate_proxy_cache(name: Name) -> Done:
    """Make a proxy ask its remote again: what it keeps is not trusted until it is. Its
    files stay; it is not blocked any more for its failures."""
    async with database() as db:
        await repositories_api.invalidate_cache(name, caller().principal, db)
    return Done(repository=name, done="invalidated")


@tool(annotations=CHANGE, shown_to=holding(WRITE_REPOSITORIES))
async def rebuild_search_index(name: Name) -> IndexRebuilt:
    """Go through a repository again: every file to its package, every package the words it
    is found by. It repairs what search and browsing say of it; repeated, it changes
    nothing more."""
    principal, request = caller().principal, caller().request
    async with database() as db:
        return await repositories_api.rebuild_index(name, request, principal, db)


# --- Deleting content -----------------------------------------------------------------


class Deleted(BaseModel):
    repository: str
    deleted: int  # files
    skipped: int  # files the format keeps itself, which go with what they describe


@tool(annotations=DESTRUCTIVE, shown_to=may_somewhere("delete"))
async def delete_component(
    repository: Name,
    component_id: uuid.UUID | None = None,
    namespace: Annotated[str | None, Field(max_length=256)] = None,
    name: Annotated[str, Field(max_length=256)] = "",
    version: Annotated[str, Field(max_length=256)] = "",
) -> Deleted:
    """Delete one version of a package from a repository: every file of it, each as the
    format's own client would delete it. Give `component_id` as `search_packages` gave
    it, or `name` and `version` (and `namespace` where the format has them). It cannot be
    undone; a proxy fetches it again when it is next asked for."""
    principal, request = caller().principal, caller().request
    async with database() as db:
        if component_id is None:
            component_id = await component_named(db, repository, namespace, name, version)
        held = await content_api.get_component(repository, component_id, request, principal, db)
        files = [entry for entry in held.files if entry.kind == "file"]
        await content_api.delete_component(repository, component_id, request, principal, db)
    return Deleted(repository=repository, deleted=len(files), skipped=0)


@tool(annotations=DESTRUCTIVE, shown_to=may_somewhere("delete"))
async def delete_path(
    repository: Name, path: Annotated[str, Field(min_length=1, max_length=1024)]
) -> Deleted:
    """Delete a file, or a folder and everything under it, from a repository, each file as
    the format's own client would. Files the format keeps itself (an index, a checksum)
    are skipped: they go with what they describe. It cannot be undone."""
    path = path.strip("/")
    if not path:
        raise _invalid(
            "path", "Give a file or a folder. To delete everything, delete the repository."
        )
    principal, request = caller().principal, caller().request
    async with database() as db:
        try:
            await content_api.delete_asset(repository, path, request, principal, db)
            return Deleted(repository=repository, deleted=1, skipped=0)
        except ApiError as error:
            if error.code != "not_found" or error.message != "No such file.":
                raise
        deleted = skipped = 0
        after: str | None = ""
        while after is not None:
            done = await content_api.delete_folder(repository, path, request, after, principal, db)
            deleted, skipped, after = deleted + done.deleted, skipped + done.skipped, done.next
    if deleted == skipped == 0:
        raise ApiError(404, "not_found", "No such file or folder.")
    return Deleted(repository=repository, deleted=deleted, skipped=skipped)
