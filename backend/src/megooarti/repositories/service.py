"""Repositories: creating, changing, finding and deleting them."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories.formats import Format, format_names, get_format
from megooarti.repositories.models import (
    Asset,
    NegativeCacheEntry,
    ProxyState,
    Repository,
    RepositoryMember,
)
from megooarti.secrets_box import Sealed
from megooarti.storage import blobs
from megooarti.storage.blob_stores import DEFAULT_BLOB_STORE, get_blob_store
from megooarti.storage.models import BlobStore

DEPLOYMENT_POLICIES = ("allow_redeploy", "disable_redeploy", "read_only")
REMOTE_AUTH_TYPES = ("none", "basic", "bearer")


@dataclass(frozen=True)
class RepositoryView:
    name: str
    format: str
    type: str
    online: bool
    blob_store: str | None
    url_path: str
    hosted: dict[str, Any] | None
    format_config: dict[str, Any]
    proxy: dict[str, Any] | None = None
    group: dict[str, Any] | None = None
    status: dict[str, Any] | None = None


def _invalid(field: str, message: str) -> ApiError:
    details = [{"field": field, "message": message}]
    return ApiError(422, "validation_error", "The request is not valid.", details)


# What is enforced for a repository whose stored settings name no policy.
NO_POLICY = "allow_redeploy"


def _hosted_settings(hosted: dict[str, Any] | None, default: str) -> dict[str, Any]:
    """`default` is the policy of a repository when none is sent."""
    policy = (hosted or {}).get("deployment_policy") or default
    if policy not in DEPLOYMENT_POLICIES:
        choices = ", ".join(DEPLOYMENT_POLICIES)
        raise _invalid("hosted.deployment_policy", f"Must be one of: {choices}.")
    return {"deployment_policy": policy}


def _whole_number(value: Any, field: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise _invalid(field, f"Must be a whole number, {minimum} or more.")
    return value


def _remote_auth(
    sent: dict[str, Any] | None, current: dict[str, Any] | None, *, same_remote: bool
) -> dict[str, Any]:
    """The credential to store.

    A secret that is not sent is kept only if the kind of credential and the remote it
    is sent to are both unchanged. Otherwise someone allowed to edit the repository
    could point it at their own server and be sent a secret they were never shown.
    """
    if not same_remote:
        current = None
    sent = sent or {}
    kind = sent.get("type", "none")
    if kind not in REMOTE_AUTH_TYPES:
        choices = ", ".join(REMOTE_AUTH_TYPES)
        raise _invalid("proxy.remote_auth.type", f"Must be one of: {choices}.")
    if kind == "none":
        return {"type": "none"}
    username = (sent.get("username") or "").strip()
    if kind == "basic" and not username:
        raise _invalid("proxy.remote_auth.username", "A username is required.")
    secret = sent.get("secret")
    if secret is None and current is not None and current.get("type") == kind:
        secret = current.get("secret")
    elif secret is not None and not isinstance(secret, Sealed):
        # A caller's bug, not bad input: secrets are sealed before they get here.
        raise TypeError("remote_auth.secret must be sealed with secrets_box.seal")
    if not secret:
        raise _invalid("proxy.remote_auth.secret", "A secret is required.")
    return {"type": kind, "username": username if kind == "basic" else "", "secret": str(secret)}


def _remote_origin(url: str) -> tuple[str, str, int] | None:
    """Scheme, host and port of an acceptable remote URL, or None if it is not one."""
    try:
        parts = urlsplit(url)
        port = parts.port  # raises for a port that is not a number
        httpx.URL(url)  # the client must be able to request it
    except (ValueError, httpx.InvalidURL):
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    if parts.username is not None or parts.password is not None:
        return None
    if parts.query or parts.fragment:
        return None
    return parts.scheme, parts.hostname.lower(), port or (443 if parts.scheme == "https" else 80)


def _proxy_settings(proxy: dict[str, Any] | None, current: dict[str, Any] | None) -> dict[str, Any]:
    proxy = proxy or {}
    url = str(proxy.get("remote_url") or "").strip()
    origin = _remote_origin(url)
    if origin is None:
        # The message never repeats the URL: it may be the one with a password in it.
        raise _invalid(
            "proxy.remote_url",
            "Must be an http or https URL with a host and without credentials, a query or "
            "a fragment. Credentials belong in remote_auth.",
        )
    previous = (current or {}).get("remote_url")
    same_remote = previous is not None and _remote_origin(previous) == origin
    negative = proxy.get("negative_cache") or {}
    return {
        "remote_url": url.rstrip("/"),
        "content_max_age_minutes": _whole_number(
            proxy.get("content_max_age_minutes", 1440), "proxy.content_max_age_minutes", -1
        ),
        "metadata_max_age_minutes": _whole_number(
            proxy.get("metadata_max_age_minutes", 1440), "proxy.metadata_max_age_minutes", -1
        ),
        "negative_cache": {
            "enabled": bool(negative.get("enabled", True)),
            "ttl_minutes": _whole_number(
                negative.get("ttl_minutes", 1440), "proxy.negative_cache.ttl_minutes", 1
            ),
        },
        "remote_auth": _remote_auth(
            proxy.get("remote_auth"),
            (current or {}).get("remote_auth"),
            same_remote=same_remote,
        ),
        "blocked": bool(proxy.get("blocked", False)),
        "auto_block": bool(proxy.get("auto_block", True)),
    }


async def get_repository(db: AsyncSession, name: str) -> Repository | None:
    return await db.scalar(select(Repository).where(Repository.name == name))


async def all_repositories(db: AsyncSession) -> list[Repository]:
    """Every repository, in name order."""
    return list(await db.scalars(select(Repository).order_by(Repository.name_key)))


async def repositories_of(db: AsyncSession, format: str) -> list[Repository]:
    """Every repository of a format, in name order."""
    rows = await db.scalars(
        select(Repository).where(Repository.format == format).order_by(Repository.name_key)
    )
    return list(rows)


async def members(db: AsyncSession, group: Repository) -> list[Repository]:
    """A group's members, in the order they are tried."""
    rows = await db.scalars(
        select(Repository)
        .join(RepositoryMember, RepositoryMember.member_id == Repository.id)
        .where(RepositoryMember.group_id == group.id)
        .order_by(RepositoryMember.position)
    )
    return list(rows)


async def member_names(db: AsyncSession, group: Repository) -> list[str]:
    return [member.name for member in await members(db, group)]


async def _reachable(db: AsyncSession, repository_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """These repositories plus everything they present, directly or indirectly."""
    start = list(repository_ids)
    if not start:
        return set()
    reachable = (
        select(Repository.id).where(Repository.id.in_(start)).cte("reachable", recursive=True)
    )
    reachable = reachable.union(
        select(RepositoryMember.member_id).join(
            reachable, RepositoryMember.group_id == reachable.c.id
        )
    )
    return set(await db.scalars(select(reachable.c.id)))


async def _set_members(db: AsyncSession, group: Repository, names: list[str]) -> None:
    if len(set(names)) != len(names):
        raise _invalid("group.members", "A repository is listed more than once.")
    chosen = []
    for name in names:
        member = await get_repository(db, name)
        if member is None:
            raise _invalid("group.members", f"Unknown repository: {name}.")
        if member.format != group.format:
            raise _invalid("group.members", f"{name} is not a {group.format} repository.")
        get_format(group.format).validate_member(member)
        chosen.append(member)
    if group.id in await _reachable(db, [member.id for member in chosen]):
        raise ApiError(
            409, "repository_cycle", "A group cannot contain itself, directly or indirectly."
        )
    await db.execute(delete(RepositoryMember).where(RepositoryMember.group_id == group.id))
    if chosen:
        await db.execute(
            insert(RepositoryMember),
            [
                {"group_id": group.id, "member_id": member.id, "position": position}
                for position, member in enumerate(chosen)
            ],
        )


def _shown_proxy(proxy: dict[str, Any]) -> dict[str, Any]:
    auth = proxy["remote_auth"]
    shown = {
        "type": auth["type"],
        "username": auth.get("username", ""),
        "has_secret": bool(auth.get("secret")),
    }
    return {**proxy, "remote_auth": shown}


async def describe(db: AsyncSession, repository: Repository) -> RepositoryView:
    store = None
    if repository.blob_store_id is not None:
        store = await db.scalar(
            select(BlobStore.name).where(BlobStore.id == repository.blob_store_id)
        )
    proxy = repository.config.get("proxy")
    status = None
    if proxy is not None:
        state = await db.get(ProxyState, repository.id)
        until = None if state is None else state.blocked_until
        status = {
            "blocked": proxy["blocked"],
            "auto_blocked_until": until if until is not None and until > utcnow() else None,
            "failures": 0 if state is None else state.failures,
            "last_error": None if state is None else state.last_error,
        }
    group = None
    if repository.type == "group":
        group = {"members": await member_names(db, repository)}
    return RepositoryView(
        name=repository.name,
        format=repository.format,
        type=repository.type,
        online=repository.online,
        blob_store=store,
        url_path=f"/repository/{repository.name}/",
        hosted=repository.config.get("hosted"),
        format_config=repository.config.get("format_config", {}),
        proxy=None if proxy is None else _shown_proxy(proxy),
        group=group,
        status=status,
    )


async def list_repositories(
    db: AsyncSession, limit: int, offset: int
) -> tuple[list[RepositoryView], int]:
    total = await db.scalar(select(func.count()).select_from(Repository))
    page = list(
        await db.scalars(
            select(Repository).order_by(Repository.name_key).limit(limit).offset(offset)
        )
    )
    return [await describe(db, repository) for repository in page], total or 0


def _settings(
    handler: Format,
    type: str,
    hosted: dict[str, Any] | None,
    proxy: dict[str, Any] | None,
    format_config: dict[str, Any] | None,
    current: dict[str, Any] | None,
) -> dict[str, Any]:
    """What a repository's `config` holds: its type's settings and its format's."""
    config = handler.validate_config(
        type, format_config or {}, (current or {}).get("format_config")
    )
    settings: dict[str, Any] = {}
    if type == "hosted":
        if current is None:
            # A repository that is made is given its format's own policy.
            default = handler.default_deployment_policy(config)
        else:
            # One that is replaced keeps the policy it has: leaving it out, to take a
            # repository offline, is not a word about what may be deployed to it.
            default = (current.get("hosted") or {}).get("deployment_policy") or NO_POLICY
        settings["hosted"] = _hosted_settings(hosted, default)
    if type == "proxy":
        settings["proxy"] = _proxy_settings(proxy, (current or {}).get("proxy"))
    return {**settings, "format_config": config}


async def create_repository(
    db: AsyncSession,
    *,
    name: str,
    format: str,
    type: str,
    online: bool,
    blob_store: str | None,
    hosted: dict[str, Any] | None = None,
    proxy: dict[str, Any] | None = None,
    group: dict[str, Any] | None = None,
    format_config: dict[str, Any] | None = None,
) -> Repository:
    handler = get_format(format)
    if handler is None:
        known = ", ".join(format_names())
        raise _invalid("format", f"Unknown format. Known formats: {known}.")
    if type not in handler.types:
        raise _invalid("type", f"{type} repositories are not available for this format.")
    handler.validate_name(name)
    settings = _settings(handler, type, hosted, proxy, format_config, None)
    store_id = None
    if type != "group":  # a group stores nothing of its own
        store = await get_blob_store(db, blob_store or DEFAULT_BLOB_STORE)
        if store is None:
            raise _invalid("blob_store", f"Unknown blob store: {blob_store}.")
        store_id = store.id
    taken = await db.scalar(select(Repository.id).where(Repository.name_key == name.lower()))
    if taken is not None:
        raise ApiError(409, "conflict", f"A repository named {name} already exists.")
    repository = Repository(
        name=name,
        name_key=name.lower(),
        format=format,
        type=type,
        online=online,
        blob_store_id=store_id,
        config=settings,
    )
    db.add(repository)
    await db.flush()
    if type == "group":
        await _set_members(db, repository, list((group or {}).get("members", [])))
    return repository


async def update_repository(
    db: AsyncSession,
    repository: Repository,
    *,
    online: bool,
    hosted: dict[str, Any] | None = None,
    proxy: dict[str, Any] | None = None,
    group: dict[str, Any] | None = None,
    format_config: dict[str, Any] | None = None,
) -> None:
    """Replace what can change. Name, format, type and blob store never do."""
    handler = get_format(repository.format)
    if repository.type == "group" and group is None:
        # Leaving the members out must not quietly empty the group.
        raise _invalid("group", "A group's members must be given.")
    before = repository.config.get("proxy")
    repository.config = _settings(
        handler, repository.type, hosted, proxy, format_config, repository.config
    )
    repository.online = online
    await db.flush()
    if repository.type == "group":
        await _set_members(db, repository, list(group.get("members", [])))
    if repository.type == "proxy":
        # Saving a proxy is how an administrator says "try again": lift any block.
        await db.execute(delete(ProxyState).where(ProxyState.repository_id == repository.id))
        after = repository.config["proxy"]
        if (before["remote_url"], before["remote_auth"]) != (
            after["remote_url"],
            after["remote_auth"],
        ):
            # A different remote, or different access to it: nothing learned still holds.
            await invalidate_cache(db, repository)


async def delete_repository(db: AsyncSession, repository: Repository, now: datetime) -> None:
    """Delete a repository and everything in it. Its blobs become unreferenced."""
    presenting = await db.scalar(
        select(Repository.name)
        .join(RepositoryMember, RepositoryMember.group_id == Repository.id)
        .where(RepositoryMember.member_id == repository.id)
        .limit(1)
    )
    if presenting is not None:
        raise ApiError(409, "in_use", f"The group {presenting} presents this repository.")
    await db.delete(repository)  # the database removes its components and assets
    await db.flush()
    # One set-based statement, however many assets there were.
    await blobs.mark_unreferenced(db, now)


async def invalidate_cache(db: AsyncSession, repository: Repository) -> None:
    """Make a proxy ask its remote again for everything it has cached or ruled out."""
    if repository.type != "proxy":
        raise ApiError(409, "not_a_proxy", "Only a proxy repository has a cache to invalidate.")
    await db.execute(
        update(Asset).where(Asset.repository_id == repository.id).values(last_verified_at=None)
    )
    await db.execute(
        delete(NegativeCacheEntry).where(NegativeCacheEntry.repository_id == repository.id)
    )
