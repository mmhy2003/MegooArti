"""What a group that signs what it serves checks of its members, whatever their format.

A client of such a group trusts the group's key and nothing else, so the group checks
what a proxy member's remote signed with the keys the remote was given (`remote_keys`).
A member that fails a check is left out: the reason is logged, and kept as the proxy's
last error until it next reaches its remote.
"""

import uuid
from collections.abc import Callable, Sequence
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories import proxy_state, signing
from megooarti.repositories.content import RepositoryContext, build_context
from megooarti.repositories.models import Repository

log = structlog.get_logger(__name__)


class LeftOut(Exception):
    """A member that a check found wanting, and why."""


def remote_keys(member: RepositoryContext) -> str:
    """A proxy's remote's public keys, armoured, or nothing."""
    return member.repository.config.get("format_config", {}).get("remote_keys") or ""


def remote_keys_setting(
    config: dict[str, Any],
    format_label: str,
    read: Callable[[str], object] = signing.read_public_keys,
) -> dict[str, Any]:
    """A proxy's settings: its remote's public keys, which a group checks it with.

    `read` is what reads the format's kind of key: OpenPGP's unless said.
    """

    def invalid(field: str, message: str) -> ApiError:
        details = [{"field": field, "message": message}]
        return ApiError(422, "validation_error", "The request is not valid.", details)

    unknown = sorted(set(config) - {"remote_keys"})
    if unknown:
        raise invalid(f"format_config.{unknown[0]}", f"This is not a setting of {format_label}.")
    keys = config.get("remote_keys") or ""
    if not isinstance(keys, str):
        raise invalid("format_config.remote_keys", "The keys are text.")
    if not keys.strip():
        return {}
    try:
        read(keys)
    except signing.KeysUnusable as error:
        raise invalid("format_config.remote_keys", str(error)) from None
    return {"remote_keys": keys}


async def leave_out(context: RepositoryContext, member: RepositoryContext, reason: str) -> None:
    """Say that a group left a member out, and why, at once.

    Committed here: what is said holds the proxy's row, which every request through
    the proxy waits for, and a group may go on merging for a minute after.
    """
    log.warning(
        "group_member_unverified",
        group=context.repository.name,
        member=member.repository.name,
        reason=reason,
    )
    if member.repository.type == "proxy":
        said = f"Left out of the group {context.repository.name}: {reason}"
        await proxy_state.record_failure(
            member.db, member.repository, utcnow(), said, blockable=False
        )
        await member.db.commit()


async def members_in(
    db: AsyncSession, context: RepositoryContext, ids: Sequence[uuid.UUID]
) -> list[RepositoryContext]:
    """A group's members, by their ids, as contexts on a session of the caller's."""
    return [
        await build_context(
            db,
            context.settings,
            await db.get(Repository, member_id),
            context.principal,
            outbound=context.outbound,
        )
        for member_id in ids
    ]
