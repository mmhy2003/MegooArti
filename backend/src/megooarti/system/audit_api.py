"""The audit log's records, read a page at a time and exported (spec 9). No route changes
or deletes a record: only how many days they are kept is changed here."""

import csv
import io
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.clock import utcnow
from megooarti.db.session import get_session
from megooarti.pagination import Page, PageParams, page
from megooarti.security.authentication import Principal, require
from megooarti.system import audit
from megooarti.system.models import AuditRecord
from megooarti.system.settings_store import get_setting

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/audit", tags=["audit"])

_COLUMNS = (
    "at",
    "actor",
    "method",
    "address",
    "event",
    "target_kind",
    "target_name",
    "changes",
    "request_id",
    "id",
)
# A spreadsheet takes a cell that starts so for a formula: a name someone typed is not one.
_FORMULA = ("=", "+", "-", "@", "\t", "\r")


class AuditRecordOut(BaseModel):
    id: uuid.UUID
    at: datetime
    actor: str | None
    method: str | None
    address: str | None
    event: str
    target_kind: str | None
    target_name: str | None
    changes: dict[str, Any] | None
    request_id: str | None


class Retention(BaseModel):
    audit_retention_days: int = Field(ge=1, le=36500)


def _utc(moment: datetime | None) -> datetime | None:
    return moment.replace(tzinfo=UTC) if moment and moment.tzinfo is None else moment


class Filters:
    """Which records: from and until a time, by whom, of which event (`user.created`, or
    every event of a kind, `user`), and about what (its name, and its kind)."""

    def __init__(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        actor: Annotated[str | None, Query(max_length=128)] = None,
        event: Annotated[str | None, Query(max_length=64)] = None,
        target: Annotated[str | None, Query(max_length=255)] = None,
        target_kind: Annotated[str | None, Query(max_length=32)] = None,
    ) -> None:
        # A time without its zone is UTC's, as a date alone is that day's start there.
        self.since, self.until = _utc(since), _utc(until)
        self.actor, self.event = actor, event
        self.target, self.target_kind = target, target_kind

    def where(self) -> list[ColumnElement[bool]]:
        found: list[ColumnElement[bool]] = []
        if self.since is not None:
            found.append(AuditRecord.at >= self.since)
        if self.until is not None:
            found.append(AuditRecord.at < self.until)
        if self.actor:
            found.append(AuditRecord.actor == self.actor.strip().lower())
        if self.event:
            event = self.event.strip()
            found.append(or_(AuditRecord.event == event, AuditRecord.event.startswith(f"{event}.")))
        if self.target:
            found.append(AuditRecord.target_name == self.target.strip())
        if self.target_kind:
            found.append(AuditRecord.target_kind == self.target_kind.strip())
        return found

    def select(self) -> Select[tuple[AuditRecord]]:
        return (
            select(AuditRecord)
            .where(*self.where())
            .order_by(AuditRecord.at.desc(), AuditRecord.id.desc())
        )


def _out(entry: AuditRecord) -> AuditRecordOut:
    return AuditRecordOut.model_validate(entry, from_attributes=True)


@router.get("", response_model=Page[AuditRecordOut])
async def list_records(
    filters: Filters = Depends(),
    params: PageParams = Depends(),
    _: Principal = Depends(require("admin:audit:read")),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """The records, newest first, a page at a time."""
    total = await db.scalar(select(func.count()).select_from(AuditRecord).where(*filters.where()))
    found = await db.scalars(filters.select().limit(params.limit).offset(params.offset))
    return page([_out(entry) for entry in found], total or 0, params)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    text = json.dumps(value, sort_keys=True) if isinstance(value, dict) else str(value)
    return f"'{text}" if text.startswith(_FORMULA) else text


def _line(entry: AuditRecordOut, format: str) -> str:
    plain = entry.model_dump(mode="json")
    if format == "jsonl":
        return json.dumps(plain, sort_keys=True) + "\n"
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerow([_cell(plain[name]) for name in _COLUMNS])
    return out.getvalue()


@router.get("/export")
async def export_records(
    request: Request,
    format: Literal["jsonl", "csv"] = "jsonl",
    filters: Filters = Depends(),
    _: Principal = Depends(require("admin:audit:read")),
) -> StreamingResponse:
    """Every record the filters give, newest first, as JSON Lines or CSV: streamed, a
    record a line, however many there are."""

    async def lines() -> AsyncIterator[str]:
        if format == "csv":
            yield ",".join(_COLUMNS) + "\n"
        # Its own session: the request's is closed before the body is sent.
        async with request.app.state.sessionmaker() as db:
            found = await db.stream_scalars(filters.select().execution_options(yield_per=500))
            async for entry in found:
                yield _line(_out(entry), format)

    named = f"audit-{utcnow():%Y%m%d-%H%M%S}.{format}"
    return StreamingResponse(
        lines(),
        media_type="text/csv" if format == "csv" else "application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{named}"'},
    )


@router.get("/retention", response_model=Retention)
async def read_retention(
    _: Principal = Depends(require("admin:audit:read")),
    db: AsyncSession = Depends(get_session),
) -> Retention:
    return Retention(audit_retention_days=await get_setting(db, "audit_retention_days"))


@router.put("/retention", response_model=Retention)
async def set_retention(
    body: Retention,
    principal: Principal = Depends(require("admin:audit:write")),
    db: AsyncSession = Depends(get_session),
) -> Retention:
    """How many days a record is kept: the hourly job removes older ones."""
    await audit.set_setting(db, "audit_retention_days", body.audit_retention_days)
    await db.commit()
    log.info(
        "setting_changed",
        setting="audit_retention_days",
        days=body.audit_retention_days,
        by=principal.user.username,
    )
    return body
