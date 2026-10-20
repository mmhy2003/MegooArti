"""The audit log (spec 9): who changed what, when, from where, and how they signed in.

A record is written by `record`, in the transaction of the change it records (E7): the
change and its record are kept together, or neither is. Who made it, how they signed in,
their address and the request's ID come from the request being served (`Context`, set by
`ContextMiddleware` and completed by `identified`); outside a request, it is the system's.
No record is ever changed; the hourly job removes those older than the days kept (D3).
"""

import uuid
from collections.abc import Iterable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import ASGIApp, Receive, Scope, Send

from megooarti.clock import utcnow
from megooarti.system import settings_store
from megooarti.system.models import AuditRecord
from megooarti.system.settings_store import get_setting

if TYPE_CHECKING:
    from megooarti.security.authentication import Principal

log = structlog.get_logger(__name__)

REDACTED = "[redacted]"
SYSTEM = "system"
PRUNE_SECONDS = 3600
# Arbitrary constant, distinct from the other advisory lock keys.
LOCK_KEY = 0x4D45474F53
# What a record never holds, wherever it is in what changed: secrets, by their names.
_SECRET_NAMES = frozenset(
    {
        "password",
        "current_password",
        "new_password",
        "bind_password",
        "secret",
        "client_secret",
        "private_key",
        "passphrase",
        "token",
    }
)
# What changes with every save, or is the record's own: not what anyone changed.
_UNTOLD = frozenset({"id", "created_at", "updated_at", "last_login_at", "last_used_at"})


@dataclass
class Context:
    """The request a record is written for. Who made it is known once they are identified."""

    request_id: str | None
    address: str | None
    actor: str | None = None
    method: str | None = None


_context: ContextVar[Context | None] = ContextVar("megooarti_audit", default=None)


class ContextMiddleware:
    """Each HTTP request's context, for the records written while it is served. Placed
    inside the middleware that sets the request's ID and its client's address."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        token = _context.set(
            Context(
                request_id=scope.get("state", {}).get("request_id"),
                address=client[0] if client else None,
            )
        )
        try:
            await self.app(scope, receive, send)
        finally:
            _context.reset(token)


def acting(actor: str | None, method: str | None) -> None:
    """Who the request being served is from, for its records, and how they signed in."""
    said = _context.get()
    if said is not None:
        said.actor, said.method = actor, method


def identified(principal: "Principal | None") -> None:
    """Who a principal is, for the records: the user's name (none when anonymous), and
    how they signed in (`oauth` for an application's token a person approved)."""
    if principal is None:
        return
    acting(
        None if principal.is_anonymous else principal.user.username,
        "oauth" if principal.grant_id is not None else principal.method,
    )


def _plain(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    plain = jsonable_encoder(value)
    return plain if isinstance(plain, dict) else {"value": plain}


def _hidden(value: Any) -> Any:
    """A secret's value, redacted: a change of one keeps its shape, each side redacted."""
    if isinstance(value, Mapping) and set(value) == {"before", "after"}:
        return {side: None if value[side] is None else REDACTED for side in ("before", "after")}
    return None if value is None else REDACTED


def _redacted(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _hidden(item) if key in _SECRET_NAMES else _redacted(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redacted(item) for item in value]
    return value


def diff(before: Any, after: Any, *, secrets: Iterable[str] = ()) -> dict[str, Any]:
    """What changed, a field at a time: `{field: {"before": ..., "after": ...}}`. Either
    side may be None (made, or deleted), a mapping, a model or a dataclass. A secret given
    anew is said by its name, its values redacted: they are never known to the record."""
    old, new = _plain(before), _plain(after)
    changed = {
        name: {"before": old.get(name), "after": new.get(name)}
        for name in sorted((old.keys() | new.keys()) - _UNTOLD)
        if old.get(name) != new.get(name)
    }
    for name in secrets:
        changed[name] = {"before": REDACTED, "after": REDACTED}
    return changed


def record(
    db: AsyncSession,
    event: str,
    target: tuple[str, str] | None = None,
    changes: Mapping[str, Any] | None = None,
) -> AuditRecord:
    """Write a record in the caller's transaction: kept when it commits, with the change.

    `event` is `<kind>.<what happened>` (`user.created`, `sign_in.failed`); `target` is
    what it happened to, by its kind and its name."""
    said = _context.get()
    entry = AuditRecord(
        id=uuid.uuid4(),
        at=utcnow(),
        actor=None if said is None else said.actor,
        method=SYSTEM if said is None else said.method,
        address=None if said is None else said.address,
        event=event,
        target_kind=None if target is None else target[0],
        target_name=None if target is None else target[1][:255],
        changes=_redacted(jsonable_encoder(dict(changes))) if changes else None,
        request_id=None if said is None else said.request_id,
    )
    db.add(entry)
    return entry


async def record_once(
    db: AsyncSession,
    event: str,
    target: tuple[str, str] | None = None,
    changes: Mapping[str, Any] | None = None,
    *,
    within_seconds: int = 60,
) -> bool:
    """Write a record unless one of this event came from the same address lately: for
    what anyone may send without signing in, which would otherwise be a row a request.
    Whether it was written."""
    said = _context.get()
    if said is not None and said.address is not None:
        lately = await db.scalar(
            select(
                exists().where(
                    AuditRecord.event == event,
                    AuditRecord.address == said.address,
                    AuditRecord.at > utcnow() - timedelta(seconds=within_seconds),
                )
            )
        )
        if lately:
            return False
    record(db, event, target, changes)
    return True


async def set_setting(db: AsyncSession, key: str, value: Any) -> None:
    """Keep a setting's value, with a record of the change when it is one."""
    before = await get_setting(db, key)
    await settings_store.set_setting(db, key, value)
    after = await get_setting(db, key)
    if after != before:
        record(db, "setting.changed", ("setting", key), diff({key: before}, {key: after}))


async def prune(db: AsyncSession, now: datetime) -> int:
    """Remove the records older than the days kept; how many were removed."""
    days = await get_setting(db, "audit_retention_days")
    removed = await db.execute(
        delete(AuditRecord).where(AuditRecord.at < now - timedelta(days=days))
    )
    return removed.rowcount or 0


async def prune_now(app: Any) -> None:
    """The hourly job: run by one container at a time (`LOCK_KEY`)."""
    async with app.state.sessionmaker() as db:
        removed = await prune(db, utcnow())
        await db.commit()
    if removed:
        log.info("audit_pruned", removed=removed)
