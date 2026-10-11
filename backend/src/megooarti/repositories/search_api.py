"""The search route: components across every repository the caller may browse."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.pagination import Page, PageParams, page
from megooarti.repositories import search, service
from megooarti.security.authentication import Principal, require_caller

router = APIRouter(prefix="/search", tags=["content"])

Text = Annotated[str, Query(max_length=1024)]


class Result(BaseModel):
    id: uuid.UUID
    repository: str
    format: str
    namespace: str
    name: str
    version: str
    created: datetime
    modified: datetime


@router.get("", response_model=Page[Result])
async def search_components(
    q: Annotated[str, Query(max_length=1024, description="Words the component contains.")] = "",
    format: Text = "",
    repository: Text = "",
    namespace: Text = "",
    name: Text = "",
    version: Text = "",
    md5: Text = "",
    sha1: Text = "",
    sha256: Text = "",
    sha512: Text = "",
    params: PageParams = Depends(),
    caller: Principal = Depends(require_caller),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Find components in the repositories the caller may browse.

    Each word of `q` must be contained in the component's group, name, version or the
    words its format adds, whatever the case; `*` stands for anything. `namespace`,
    `name` and `version` match a whole value, also with `*`. A checksum finds the
    components that have a file with exactly that checksum. `format` and `repository`
    narrow where to look. With nothing given, everything is listed.
    """
    allowed = [
        found
        for found in await service.all_repositories(db)
        if found.type != "group"  # a group holds nothing of its own
        and (not format or found.format == format)
        and (not repository or found.name == repository)
        and caller.allows(f"repository:{found.format}:{found.name}:browse")
    ]
    wanted = search.Wanted(q, namespace, name, version, md5, sha1, sha256, sha512)
    try:
        items, total = await search.search(
            db, allowed, wanted, limit=params.limit, offset=params.offset
        )
    except search.BadChecksum as error:
        digits = search.CHECKSUMS[str(error)]
        message = f"Must be {digits} hexadecimal digits in lower case."
        details = [{"field": str(error), "message": message}]
        raise ApiError(422, "validation_error", "The request is not valid.", details) from None
    return page(items, total, params)
