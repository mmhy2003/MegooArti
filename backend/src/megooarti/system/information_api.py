"""What is running here: the administrator's system page (SYS-4).

The health endpoints say yes or no to a load balancer. This says what: which version,
which schema, on what, since when. It says nothing of the configuration, which holds
the database's address and with it a password.
"""

import platform
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti import __version__
from megooarti.db.schema import current_revision
from megooarti.db.session import get_session
from megooarti.security.authentication import Principal, require

router = APIRouter(prefix="/system", tags=["system"])


class SchemaState(BaseModel):
    revision: str | None  # what the database says it is at; None if it was never migrated
    expected: str  # what this version was written for
    current: bool


class Runtime(BaseModel):
    python: str
    platform: str
    started_at: datetime


class Database(BaseModel):
    version: str


class Information(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: str
    # `schema` is a name pydantic has a use for itself.
    schema_state: SchemaState = Field(alias="schema")
    runtime: Runtime
    database: Database


@router.get("/information", response_model=Information)
async def information(
    request: Request,
    _: Principal = Depends(require("admin:settings:read")),
    db: AsyncSession = Depends(get_session),
) -> Information:
    revision = await current_revision(await db.connection())
    expected = request.app.state.head_revision
    server = await db.scalar(text("SELECT current_setting('server_version')"))
    return Information(
        version=__version__,
        schema_state=SchemaState(
            revision=revision, expected=expected, current=revision == expected
        ),
        runtime=Runtime(
            python=platform.python_version(),
            platform=platform.platform(),
            started_at=request.app.state.started_at,
        ),
        database=Database(version=f"PostgreSQL {server}"),
    )
