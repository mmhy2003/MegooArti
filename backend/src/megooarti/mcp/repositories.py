"""Repositories: which there are, how a client is set up to use one, and how a proxy is
doing (spec 6.1). What the content routes give anyone who may browse; a repository's
settings and a proxy's state only to those who may read repositories' settings, as the
administration routes do."""

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field

from megooarti.mcp.packages import RepositoryName, Usage
from megooarti.mcp.results import Cursor, Limit, Page, offset_of, page_of
from megooarti.mcp.tools import caller, database, tool
from megooarti.repositories import api as repositories_api
from megooarti.repositories import content_api, service

READ_SETTINGS = "admin:repositories:read"


class Remote(BaseModel):
    url: str
    # Whether it is not asked now: blocked by an administrator, or for a while after
    # failing again and again.
    blocked: bool


class RepositorySummary(BaseModel):
    name: str  # what the other tools take as `repository`
    format: str
    type: str  # "hosted", "proxy" or "group"
    online: bool
    url: str  # what a client is given: an address, or for Docker a host and a name
    remote: Remote | None  # a proxy's, to those who may read settings; null otherwise


@tool()
async def list_repositories(
    format: Annotated[str, Field(max_length=32)] = "",
    type: Annotated[str, Field(max_length=16, description="hosted, proxy or group")] = "",
    limit: Limit = 50,
    cursor: Cursor = None,
) -> Page[RepositorySummary]:
    """The repositories you may browse, by name: each one's format, type (hosted, proxy
    or group), whether it is online, and the address a client is given for it. To those
    who may read repositories' settings, also a proxy's remote, and whether it is blocked.
    """
    principal, request = caller().principal, caller().request
    offset = offset_of(cursor)
    async with database() as db:
        allowed = [
            held
            for held in await service.all_repositories(db)
            if (not format or held.format == format)
            and (not type or held.type == type)
            and principal.allows(f"repository:{held.format}:{held.name}:browse")
        ]
        summaries = []
        for held in allowed[offset : offset + limit]:
            view = await content_api.get_repository(held.name, request, principal, db)
            remote = None
            if held.type == "proxy" and principal.allows(READ_SETTINGS):
                described = await service.describe(db, held)
                status = described.status or {}
                remote = Remote(
                    url=(described.proxy or {}).get("remote_url", ""),
                    blocked=bool(status.get("blocked") or status.get("auto_blocked_until")),
                )
            summaries.append(
                RepositorySummary(
                    name=view.name,
                    format=view.format,
                    type=view.type,
                    online=view.online,
                    url=view.url,
                    remote=remote,
                )
            )
    return page_of(summaries, len(allowed), offset, limit)


class ProxyStatus(BaseModel):
    blocked: bool  # by an administrator
    auto_blocked_until: datetime | None  # not asked until then, after failing
    failures: int  # how many times in a row the remote could not be reached
    last_error_untrusted: str | None  # what went wrong last; the remote's words in part


class RepositoryDetails(BaseModel):
    name: str
    format: str
    type: str
    online: bool
    url: str
    members: list[str] | None  # a group's, in the order they are asked; those you may browse
    # How a machine or a project is set up to use it: npm, pip, Maven, Gradle, NuGet,
    # Docker, APT, YUM or apk, as text to copy.
    setup: list[Usage]
    # Its settings as the REST API gives them (never a secret), and a proxy's state: to
    # those who may read repositories' settings; null to others.
    settings: dict[str, Any] | None
    status: ProxyStatus | None


@tool()
async def repository_details(name: RepositoryName) -> RepositoryDetails:
    """One repository: its address, a group's members, and how a client is set up to use
    it (the .npmrc, pip.conf, settings.xml, nuget.config, Docker login or sources line to
    write). To those who may read repositories' settings, also its settings, and a
    proxy's state: whether it is blocked, and the last error its remote gave."""
    principal, request = caller().principal, caller().request
    settings = status = None
    async with database() as db:
        view = await content_api.get_repository(name, request, principal, db)
        if principal.allows(READ_SETTINGS):
            described = repositories_api.RepositoryOut.model_validate(
                await repositories_api.get_repository(name, principal, db), from_attributes=True
            )
            settings = described.model_dump(mode="json", exclude={"status"})
            if described.status is not None:
                status = ProxyStatus(
                    blocked=described.status.blocked,
                    auto_blocked_until=described.status.auto_blocked_until,
                    failures=described.status.failures,
                    last_error_untrusted=described.status.last_error,
                )
    return RepositoryDetails(
        name=view.name,
        format=view.format,
        type=view.type,
        online=view.online,
        url=view.url,
        members=view.members,
        setup=[Usage.model_validate(one, from_attributes=True) for one in view.setup],
        settings=settings,
        status=status,
    )
