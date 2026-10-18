"""Who an agent acts as, and how the server is (spec 6.1: `whoami`, `system_status`)."""

import json
from datetime import datetime

from pydantic import BaseModel

from megooarti import __version__
from megooarti.mcp.tools import caller, database, tool
from megooarti.pagination import PageParams
from megooarti.security import users
from megooarti.security.models import ApiToken
from megooarti.storage import api as blob_stores_api
from megooarti.system import information_api, status


class TokenView(BaseModel):
    kind: str  # "api_token": made under Account, Tokens
    name: str
    prefix: str  # its first characters, as the web UI shows them
    scopes: list[str] | None  # what it narrows its owner's permissions to; null: none
    expires_at: datetime | None


class Whoami(BaseModel):
    username: str
    display_name: str
    email: str | None
    roles: list[str]
    permissions: list[str]  # the user's, before the token narrows them
    token: TokenView | None


@tool()
async def whoami() -> Whoami:
    """Who you act as here: the user, their roles and permissions, and the API token you
    signed in with, whose scopes (if any) narrow those permissions, and when it expires.
    Call it first to learn what you may do."""
    principal = caller().principal
    async with database() as db:
        view = await users.describe(db, principal.user)
        token = None if principal.token_id is None else await db.get(ApiToken, principal.token_id)
    return Whoami(
        username=view.username,
        display_name=view.display_name,
        email=view.email,
        roles=view.roles,
        permissions=sorted(principal.patterns),
        token=None
        if token is None
        else TokenView(
            kind="api_token",
            name=token.name,
            prefix=token.display_prefix,
            scopes=token.scopes,
            expires_at=token.expires_at,
        ),
    )


class Runtime(BaseModel):
    python: str
    platform: str
    started_at: datetime
    database: str  # the database server's version


class BlobStoreUsage(BaseModel):
    name: str
    type: str
    blob_count: int
    total_bytes: int
    available_bytes: int | None


class SystemStatus(BaseModel):
    version: str
    ready: bool  # whether the database answers and its schema is this version's
    database: str  # "ok" or "unreachable"
    database_schema: str  # "ok", "out_of_date" or "unknown"
    runtime: Runtime | None  # to those who may read the settings; null to others
    blob_stores: list[BlobStoreUsage] | None  # to those who may read blob stores


@tool()
async def system_status() -> SystemStatus:
    """The server's version and whether it is ready; to an administrator also what it
    runs on, and each blob store's usage (how many files, how many bytes, how many free)."""
    principal, request = caller().principal, caller().request
    checks = json.loads((await status.ready(request)).body)["checks"]
    runtime = stores = None
    async with database() as db:
        if principal.allows("admin:settings:read"):
            information = await information_api.information(request, principal, db)
            runtime = Runtime(
                python=information.runtime.python,
                platform=information.runtime.platform,
                started_at=information.runtime.started_at,
                database=information.database.version,
            )
        if principal.allows("admin:blobstores:read"):
            listed = await blob_stores_api.list_blob_stores(
                request, PageParams(limit=200, offset=0), principal, db
            )
            stores = [
                BlobStoreUsage.model_validate(store, from_attributes=True)
                for store in listed["items"]
            ]
    return SystemStatus(
        version=__version__,
        ready=checks == {"database": "ok", "schema": "ok"},
        database=checks["database"],
        database_schema=checks["schema"],
        runtime=runtime,
        blob_stores=stores,
    )
