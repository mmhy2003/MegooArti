"""The formats this server has: what the web form, and an agent, make repositories of."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from megooarti.pagination import Page, PageParams, page
from megooarti.repositories.formats import format_names, get_format
from megooarti.security.authentication import Principal, require_caller

router = APIRouter(prefix="/formats", tags=["repositories"])


class FormatOut(BaseModel):
    name: str
    types: list[str]  # of "hosted", "proxy" and "group"
    # The public repository a new proxy is given where no remote is said, by the
    # protocol of its settings ("" for a format without one): none, where there is no one.
    public_remotes: dict[str, str]


@router.get("", response_model=Page[FormatOut])
async def list_formats(
    params: PageParams = Depends(), _: Principal = Depends(require_caller)
) -> dict:
    """Every format, in name order."""
    every = []
    for name in sorted(format_names()):
        handler = get_format(name)
        if handler is not None:
            every.append(
                FormatOut(
                    name=name,
                    types=sorted(handler.types),
                    public_remotes=dict(handler.public_remotes),
                )
            )
    return page(every[params.offset : params.offset + params.limit], len(every), params)
